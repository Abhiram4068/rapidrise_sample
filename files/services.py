from django.db.models import Q
from django.contrib.auth import get_user_model
from .models import User, File, FileShareLink, Collection, CollectionFile, ScheduledMail
from django.db.models import F
from django.db import transaction, IntegrityError
from rest_framework_simplejwt.tokens import RefreshToken
import hashlib
from typing import List
from django.http import FileResponse
from django.shortcuts import get_object_or_404
import secrets
from django.utils import timezone
from django.utils.timezone import localtime
from datetime import timedelta
import csv
from io import StringIO
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Sum, Count
from django.contrib.auth import update_session_auth_hash
from .exceptions import StorageLimitExceeded
import logging
logger = logging.getLogger(__name__)
import os
from datetime import datetime
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.tokens import default_token_generator
from .models import NodeActivity, NodeDependency, NodeFile, ProjectNode, ProjectThread



def create_user(validated_data):
    email=validated_data.get('email')
    if User.objects.filter(email=email).exists():
        raise ValueError("Email already exists")
    try:
        with transaction.atomic():
            return User.objects.create_user(**validated_data)
    except IntegrityError:
        raise ValueError("Unable to create user. Please try again")
    
class AuthenticationError(Exception):
    """
    Custom exception for authentication failures
    """
    pass
    
def authenticate_and_generate_token(email:str, password:str)->dict:
    try:
        user=User.objects.get(email=email)
    except User.DoesNotExist:
        raise AuthenticationError("User not found")
    if not user.check_password(password):
        raise AuthenticationError("Invalid credentials")
    if not user.is_active:
        raise AuthenticationError("Account is disabled")
    refresh=RefreshToken.for_user(user)
    return {
        'user':user,
        'tokens':{
            'access':str(refresh.access_token),
            'refresh':str(refresh)
        }
    }

def get_designation():
    return [
        {"value": key, "label": label}
        for key, label in User.DesignationChoices.choices
    ]

class AuthService:
    @staticmethod
    def change_password(data, user, request=None):
        new_password=data["new_password"]

        user.set_password(new_password)
        user.save()
        #to keep the user logged in     
        if request:
            update_session_auth_hash(request, user)
        return user
    @staticmethod
    def request_password_reset(email):
        """
        Looks up the user by email, generates a secure one-time token,
        and emails them a reset link. Always returns success to prevent
        user enumeration (don't reveal whether the email exists).
        """
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return  # silently do nothing

        uid   = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        reset_url = (
        f"{settings.FRONTEND_URL}"
        f"/auth/reset-password/confirm/"
        f"?uid={uid}&token={token}"
    )
    

        def _send_email():
            try:
                send_mail(
                    subject="Password Reset Request — HiveDrive",
                    message=(
                        f"Hi {user.first_name or user.email},\n\n"
                        f"Click the link below to reset your password. "
                        f"This link expires in 24 hours.\n\n"
                        f"{reset_url}\n\n"
                        f"If you didn't request this, ignore this email."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
            except Exception as e:
                logger.error(f"Failed to send password reset email: {e}")

        import threading
        threading.Thread(target=_send_email).start()
    @staticmethod
    def confirm_password_reset(uid, token, new_password):
        """
        Validates the uid + token pair, then sets the new password.
        Raises ValueError with a user-friendly message on any failure.
        """
        try:
            user_id = force_str(urlsafe_base64_decode(uid))
            user    = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError):
            raise ValueError("Invalid reset link.")

        if not default_token_generator.check_token(user, token):
            raise ValueError("This reset link has expired or has already been used.")

        user.set_password(new_password)
        user.save()
        return user


class UserProfileService:
    @staticmethod
    def get_profile(user: User):
        return (
            User.objects
            .filter(pk=user.pk)
            .annotate(total_files=Count(
                "files",
                filter=Q(files__is_deleted=False)
                ))  # related_name
            .only("id", "email", "first_name", "last_name", "designation", "date_of_birth")
            .first()
        )
    @staticmethod
    def update_profile(user: User, data: dict) -> User:
        updatable_fields = ["first_name", "last_name", "date_of_birth", "designation"]
        
        for field in updatable_fields:
            if field in data:
                setattr(user, field, data[field])
        
        user.save(update_fields=updatable_fields)
        return user

class StorageService:
    """
    service for handling storage for the auth user
    """
    @staticmethod
    def claim(user_id, file_size):
        with transaction.atomic():
            updated=(
                User.objects.filter(
                    id=user_id,
                    storage_used_bytes__lte=F("storage_limit_bytes")-file_size
                ).update(
                    storage_used_bytes=F("storage_used_bytes")+file_size
                )
            )
            if updated == 0:
                raise StorageLimitExceeded("Storage limit of 1GB exceeded")

    @staticmethod
    def release(user_id, file_size):
        with transaction.atomic():
            User.objects.filter(
                id=user_id
            ).update(
                storage_used_bytes=F("storage_used_bytes")-file_size
            )




class FileService:
    """
    Handles uploads with checksum-based deduplication,
    secure downloads with ownership validation,
    user-scoped listing, and soft deletion.
    """
    @staticmethod
    
    def upload_files(user, files: List, description=None, action=None):
        uploaded_files = []

        for file_obj in files:
            with transaction.atomic():
                StorageService.claim(user.id, file_obj.size)
                checksum = FileService._calculate_checksum(file_obj)
                existing_file = File.objects.filter(checksum=checksum, user=user, is_deleted=False).first()

                # Duplicate with no action → ask the frontend what to do
                if existing_file and not action:
                    raise ValidationError({
                        "duplicate": True,
                        "message": f"File '{file_obj.name}' already exists",
                        "existing_file_id": str(existing_file.id),
                        "file_name": file_obj.name,
                    })

                # Replace
                if existing_file and action == "replace":
                    old_path = existing_file.file.name
                    existing_file.file.delete(save=False)
                    existing_file.file = file_obj
                    existing_file.original_name = file_obj.name
                    existing_file.file_size = file_obj.size
                    existing_file.content_type = file_obj.content_type
                    existing_file.save()
                    logger.info(f"File replaced | user_id={user.id} | old={old_path} | new={file_obj.name}")
                    uploaded_files.append({
                        'id': str(existing_file.id),
                        'name': existing_file.original_name,
                        'size': existing_file.file_size,
                        'content_type': existing_file.content_type,
                        'checksum': existing_file.checksum,
                        'created_at': existing_file.created_at,
                    })
                    continue  # ← was `return`, this lets remaining files still process

                # Keep both
                if existing_file and action == "keep_both":
                    file_obj.name = FileService._rename_file(file_obj.name)
                    logger.info(f"Keeping both | user_id={user.id} | renamed to={file_obj.name}")

                # Fresh upload (or keep_both falls through to here)
                new_file = File.objects.create(
                    user=user,
                    file=file_obj,
                    original_name=file_obj.name,
                    file_size=file_obj.size,
                    content_type=file_obj.content_type,
                    checksum=checksum,
                )
                uploaded_files.append({
                    'id': str(new_file.id),
                    'name': new_file.original_name,
                    'size': new_file.file_size,
                    'content_type': new_file.content_type,
                    'checksum': new_file.checksum,
                    'created_at': new_file.created_at,
                })

        return uploaded_files

    


    @staticmethod
    def _rename_file(filename):
        from django.utils.text import slugify
        name, ext = os.path.splitext(filename)        # Clean filename
        safe_name = slugify(name)
        # Short unique identifier
        import uuid
        unique_suffix = uuid.uuid4().hex[:8]
        return f"{safe_name}_{unique_suffix}{ext.lower()}"

    @staticmethod
    def download_file(user, file_id):
        file_obj=get_object_or_404(File, id=file_id, user=user)

        return FileResponse(
            file_obj.file.open('rb'),
            as_attachment=True,
            filename=file_obj.original_name
        )

    @staticmethod
    def view_file_inline(user, file_id):
        """
        Serves the file for inline viewing in a new tab.
        """
        file_obj = get_object_or_404(File, id=file_id, user=user, is_deleted=False)
        response = FileResponse(
            file_obj.file.open('rb'),
            content_type=file_obj.content_type,
            as_attachment=False
        )
        return response

    @staticmethod
    def user_list_files(user):
        all_files=File.objects.filter(user=user, is_deleted=False, is_archive=False)
        return all_files
    
    @staticmethod
    def get_file_detail(user, file_id):
        file_obj=get_object_or_404(
            File, user=user, id=file_id, is_deleted=False, is_archive=False
        )
        file_obj.last_accessed = timezone.now()
        file_obj.save(update_fields=['last_accessed'])
        return file_obj
    @staticmethod
    def update_file_details(file_obj, data):
        file_obj.display_name = data.get("display_name", file_obj.display_name)
        file_obj.description = data.get("description", file_obj.description)
        file_obj.is_starred = data.get("is_starred", file_obj.is_starred)
        file_obj.save(update_fields=["display_name", "description", "updated_at","is_starred"])

        return file_obj
    
    @staticmethod
    def user_delete_file(user, file_id):
        file_obj=get_object_or_404(
            File, user=user, id=file_id, is_deleted=False
        )
        file_obj.is_deleted=True
        file_obj.deleted_at=timezone.now()
        file_obj.save(update_fields=['is_deleted', 'deleted_at'])

    @staticmethod
    def user_archive_file(user, file_id):
        file_obj=get_object_or_404(
            File, user=user, id=file_id, is_deleted=False, is_archive=False
        )
        file_obj.is_archive=True
        file_obj.archived_at=timezone.now()
        file_obj.save(update_fields=['is_archive', 'archived_at'])

    @staticmethod
    def user_unarchive_file(user, file_id):
        file_obj=get_object_or_404(
            File, user=user, id=file_id, is_deleted=False, is_archive=True
        )
        file_obj.is_archive=False
        file_obj.archived_at=None
        file_obj.save(update_fields=['is_archive', 'archived_at'])
        
    @staticmethod
    def get_user_starred_files(user):
        starred_files=File.objects.filter(user=user, is_starred=True, is_deleted=False)
        return starred_files.order_by('-created_at')

    @staticmethod
    def get_user_archived_files(user, search=None):
        archived_files=File.objects.filter(user=user, is_archive=True, is_deleted=False)
        if search:
            archived_files=archived_files.filter(
                Q(original_name__icontains=search) |
                Q(display_name__icontains=search) |
                Q(content_type__icontains=search)
        )
        return archived_files.order_by('-archived_at')

    @staticmethod
    def delete_archived_files(user, file_ids):
        if not file_ids or not isinstance(file_ids, list):
            raise ValueError("Provide a valid list of file_ids.")

        files = File.objects.filter(
            id__in=file_ids,
            user=user,
            is_archive=True
        )

        if not files.exists():
            raise ValueError("No matching archived files found.")

        return files.update(is_deleted=True, deleted_at=timezone.now())

    @staticmethod
    def get_user_deleted_files(user):
        all_deleted_files=File.objects.filter(user=user, is_deleted=True)
        return all_deleted_files.order_by('-deleted_at')

    @staticmethod
    def get_deleted_file_by_id(user, file_id):
        file_obj=get_object_or_404(
            File, user=user, id=file_id, is_deleted=True
        )
        return file_obj
    
    @staticmethod
    def user_restore_file(user, file_id):
        file_obj=File.objects.get(user= user, id=file_id)
        file_obj.is_deleted=False
        file_obj.save(update_fields=['is_deleted'])
        return file_obj

    @staticmethod
    def _calculate_checksum(file_obj):
        hash_md5 = hashlib.md5()
        file_obj.seek(0)
        for chunk in file_obj.chunks():
            hash_md5.update(chunk)
        file_obj.seek(0)
        return hash_md5.hexdigest()
    
    @staticmethod
    def get_recent_files(user):
        return File.objects.filter(user=user, is_deleted=False, is_archive=False).order_by('-last_accessed')[:9]


 
    @staticmethod
    def upload(node: ProjectNode, user, file) -> NodeFile:
        node_file = NodeFile.objects.create(
            node=node,
            file=file,
            original_name=file.name,
            uploaded_by=user,
        )
        # Inline impact propagation (no Celery — synchronous for now)
        FileService._propagate_impact(node, user)
 
        NodeActivity.objects.create(
            node=node,
            actor=user,
            event_type=NodeActivity.EventType.FILE_UPLOADED,
            message=f'"{file.name}" uploaded to "{node.title}".',
        )
        return node_file
 
    @staticmethod
    def _propagate_impact(source_node: ProjectNode, user):
        """
        Walk downstream and mark nodes that need review.
        Synchronous BFS — replace with Celery later.
        """
        source_node.status = ProjectNode.Status.NEEDS_REVIEW
        source_node.save(update_fields=["status"])

        NodeActivity.objects.create(
            node=source_node,
            actor=user,
            event_type=NodeActivity.EventType.STATUS_CHANGED,
            message=f'Marked as NEEDS_REVIEW because dependency structure changed.',
        )
        queue = list(
            NodeDependency.objects.filter(source_node=source_node).values_list("target_node_id", flat=True)
        )
        visited = set()
 
        while queue:
            node_id = queue.pop(0)
            if node_id in visited:
                continue
            visited.add(node_id)
 
            try:
                node = ProjectNode.objects.get(id=node_id, is_deleted=False)
            except ProjectNode.DoesNotExist:
                continue
 
            old_status = node.status
            node.status = ProjectNode.Status.NEEDS_REVIEW
            node.save(update_fields=["status"])
 
            NodeActivity.objects.create(
                node=node,
                actor=user,
                event_type=NodeActivity.EventType.STATUS_CHANGED,
                message=f'Marked as NEEDS_REVIEW because "{source_node.title}" was updated.',
            )
 
            # Go deeper
            next_ids = NodeDependency.objects.filter(source_node=node).values_list("target_node_id", flat=True)
            queue.extend(next_ids)
 
    @staticmethod
    def delete_file(node_file: NodeFile, user):
        name = node_file.original_name
        node = node_file.node
        node_file.file.delete(save=False)
        node_file.delete()
        FileService._propagate_impact(node, user)
        NodeActivity.objects.create(
            node=node,
            actor=user,
            event_type=NodeActivity.EventType.FILE_DELETED,
            message=f'"{name}" deleted from "{node.title}".',
        )
        
from django.db.models import Sum, Count
from django.core.exceptions import ValidationError, PermissionDenied
from .models import Collection, CollectionFile, File


class CollectionService:

    @staticmethod
    def get_user_collections(user):
        """Return all collections for a user with file count and size annotated."""
        return (
            Collection.objects.filter(user=user).order_by('-created_at')
            .annotate(
                total_files=Count("collection_files"),
                total_size=Sum("collection_files__file__file_size"),
            )
        )

    @staticmethod
    def get_single_collection(user, collection_id):
        """Return a single collection with annotations. Raises if not found or not owner."""
        try:
            return (
                Collection.objects.filter(user=user)
                .annotate(
                    total_files=Count("collection_files"),
                    total_size=Sum("collection_files__file__file_size"),
                )
                .get(id=collection_id)
            )
        except Collection.DoesNotExist:
            raise ValidationError("Collection not found.")

    @staticmethod
    def create_collection(user, validated_data):
        """Create a new collection for the user."""
        try:
            return Collection.objects.create(user=user, **validated_data)
        except IntegrityError:
            raise ValidationError("You already have a collection with this name. Please choose a different name.")

    @staticmethod
    def update_collection(user, collection_id, validated_data):
        """Update name or description of a collection."""
        try:
            collection = Collection.objects.get(id=collection_id, user=user)
        except Collection.DoesNotExist:
            raise ValidationError("Collection not found.")

        for attr, value in validated_data.items():
                setattr(collection, attr, value)
        try:
            collection.save()
        except IntegrityError:
            raise ValidationError("A collection with this name already exists.")
        return collection


    @staticmethod
    def delete_collection(user, collection_id):
        """Hard delete a collection. Cascades to CollectionFile rows."""
        try:
            collection = Collection.objects.get(id=collection_id, user=user)
        except Collection.DoesNotExist:
            raise ValidationError("Collection not found.")
        collection.delete()

    @staticmethod
    def add_file_to_collection(user, collection_id, file_id):
        """
        Add a file to a collection.
        - Validates the collection belongs to the user.
        - Validates the file belongs to the user.
        - Prevents duplicate entries via get_or_create.
        """
        try:
            collection = Collection.objects.get(id=collection_id, user=user)
        except Collection.DoesNotExist:
            raise ValidationError("Collection not found.")

        try:
            file = File.objects.get(id=file_id, user=user)
        except File.DoesNotExist:
            raise ValidationError("File not found.")

        collection_file, created = CollectionFile.objects.get_or_create(
            collection=collection,
            file=file,
            defaults={"added_by": user},
        )

        if not created:
            raise ValidationError("This file is already in the collection.")

        return collection_file
    
    
    @staticmethod
    def get_collection_files(user, collection_id):
        """Return all files inside a collection. Validates ownership."""
        try:
            collection = Collection.objects.get(id=collection_id, user=user)
        except Collection.DoesNotExist:
            raise ValidationError("Collection not found.")
        
        return CollectionFile.objects.filter(
            collection=collection,
            file__is_deleted=False
        ).select_related("file")
        
    @staticmethod
    def get_user_starred_collections(user):
        """Return the starred collection for the auth user"""
        starred_collections=Collection.objects.filter(user=user, is_starred=True)
        return starred_collections

    @staticmethod
    def remove_file_from_collection(user, collection_id, file_id):
        """Remove a file from a collection."""
        try:
            collection = Collection.objects.get(id=collection_id, user=user)
        except Collection.DoesNotExist:
            raise ValidationError("Collection not found.")

        deleted_count, _ = CollectionFile.objects.filter(
            collection=collection, file__id=file_id
        ).delete()

        if deleted_count == 0:
            raise ValidationError("File not found in this collection.")  
    
class FileShareService:
    """
    service handles the file sharing business logic
    """
    @staticmethod
    def generate_share_token():
        return secrets.token_urlsafe(32)
    @staticmethod
    def create_share_token(file_id, owner, recipient_email, expiration_hours, title, message, schedule_at=None):
        """
        for creating a file token and returns a fileshare link
        """
        try:
            file=File.objects.get(id=file_id, user=owner)
        except File.DoesNotExist:
            raise ValueError("File not found or you dont have the permission")
        share_token=FileShareService.generate_share_token()
        expiration_datetime = timezone.now() + timedelta(hours=expiration_hours)

        share=FileShareLink.objects.create(
            file=file,
            owner=owner,
            recipient_email=recipient_email.lower(),
            share_token=share_token,
            expiration_datetime=expiration_datetime
        )

        if schedule_at:
            scheduled_mail = ScheduledMail.objects.create(
                share=share,
                title=title,
                message=message,
                scheduled_for=schedule_at,
            )
            from .tasks import send_scheduled_share_email

            task_result = send_scheduled_share_email.apply_async(
                args=[str(scheduled_mail.id)],
                eta=schedule_at,
            )
            scheduled_mail.task_id = task_result.id
            scheduled_mail.save(update_fields=["task_id"])
        else:
            #used python threads for async email send
            import threading
            threading.Thread(
                target=FileShareService.send_share_email, 
                args=(share, message, title)
            ).start()
        return share
    
    @staticmethod
    def send_share_email(share, message, title=None):
        """
        send email
        """
        email_subject = f"{share.owner.email} shared '{share.file.original_name}' with you"
        share_url = f"{settings.BACKEND_BASE_URL}/api/files/public/{share.share_token}/"

        title_display = f"\n        Title: {title}" if title else ""
        message_display = f"\n        Message from sender: \"{message}\"" if message else ""

        email_body = f"""
        Hi,

        {share.owner.email} has shared a file with you.

        File: {share.file.original_name}
        Size: {share.file.file_size / (1024 * 1024):.2f} MB{title_display}{message_display}

        Click here to access the file:
        {share_url}

        This link will expire on {share.expiration_datetime.strftime('%B %d, %Y')}.

        IMPORTANT:
        - This link is personal and should not be shared with others.
        - You will need to verify your email address ({share.recipient_email}) to access the file.

        ---
        If you did not expect this file, please ignore this email.
                """
        try:
            send_mail(
                subject=email_subject,
                message=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[share.recipient_email],
                fail_silently=False
            )
            return True
        except Exception as e:
            logger.error("Error sending file share email | share_id=%s | error=%s", share.id, str(e))
            return False


    @staticmethod
    def get_user_shares(user):
        shares=FileShareLink.objects.filter(owner=user)
        return shares

    @staticmethod
    def revoke_share(file_share_id, owner):
        try:
            file_share=FileShareLink.objects.get(id=file_share_id, owner=owner, accessed=False)
        except FileShareLink.DoesNotExist:
            raise ValueError("You haven't made this share or you don't have the permission")
        file_share.revoked_at=timezone.now()
        file_share.is_active=False
        file_share.save(update_fields=["revoked_at", "is_active"])
        return True

    @staticmethod
    def revoke_scheduled_mail(user, mail_id):
        try:
            scheduled_mail = ScheduledMail.objects.get(id=mail_id, share__owner=user)
        except ScheduledMail.DoesNotExist:
            raise ValueError("Scheduled email not found or you don't have permission.")
            
        if scheduled_mail.status != ScheduledMail.Status.PENDING:
            raise ValueError("Only pending scheduled emails can be revoked.")
            
        if timezone.now() >= scheduled_mail.scheduled_for:
            raise ValueError("Time has already reached for this scheduled email.")
            
        scheduled_mail.status = ScheduledMail.Status.REVOKED
        scheduled_mail.save(update_fields=["status"])
        
        if scheduled_mail.task_id:
            from celery.result import AsyncResult
            AsyncResult(scheduled_mail.task_id).revoke()
            
        return scheduled_mail

    @staticmethod
    def get_scheduled_mails(user, status_filter=None):
        queryset = ScheduledMail.objects.filter(
            share__owner=user
        ).select_related('share', 'share__file', 'share__owner')
        
        return {
            "total": queryset.count(),           # unfiltered (for stat cards)
            "pending": queryset.filter(status=ScheduledMail.Status.PENDING).count(),
            "completed": queryset.filter(status=ScheduledMail.Status.SENT).count(),
            "filtered_total": queryset.filter(   # filtered count for pagination
                status=status_filter.lower()
            ).count() if status_filter and status_filter.lower() != 'all' else queryset.count(),
            "mails": queryset.filter(status=status_filter.lower()) 
                    if status_filter and status_filter.lower() != 'all' 
                    else queryset
        }

    @staticmethod
    def get_scheduled_mails_for_calendar(user, month, year, status_filter=None):
        queryset = ScheduledMail.objects.filter(
            share__owner=user,
            scheduled_for__month=month,
            scheduled_for__year=year,
        ).select_related('share', 'share__file', 'share__owner').order_by('scheduled_for')

        if status_filter and status_filter.lower() != 'all':
            queryset = queryset.filter(status=status_filter.lower())

        return queryset
            

class ViewFileShareService:
    @staticmethod
    def get_file_response(share):
        return share.file.file.open("rb"), share.file.original_name

    
    @staticmethod
    def mark_as_accessed(share):
        if not share.accessed:
            share.accessed=True
            share.accessed_at=timezone.now()
            share.save(update_fields=["accessed", "accessed_at"])
import csv
from io import StringIO
from django.utils.timezone import localtime
class ReportService:

    @staticmethod
    def get_queryset(owner, timeline=None, search=''):
        """
        Fetch:
        1. All shared files
        2. All SENT scheduled mails
        """

        shares = (
            FileShareLink.objects
            .filter(owner=owner)
            .select_related("file")
        )

        mails = (
            ScheduledMail.objects
            .filter(
                share__owner=owner,
                status=ScheduledMail.Status.SENT,
                sent_at__isnull=False
            )
            .select_related("share", "share__file")
        )

        if timeline == 'weekly':
            shares = shares.filter(created_at__gte=timezone.now() - timedelta(days=7))
            mails = mails.filter(sent_at__gte=timezone.now() - timedelta(days=7))
        elif timeline == 'monthly':
            shares = shares.filter(created_at__gte=timezone.now() - timedelta(days=31))
            mails = mails.filter(sent_at__gte=timezone.now() - timedelta(days=31))
        if search:
            shares = shares.filter(
            Q(file__original_name__icontains=search) |
            Q(recipient_email__icontains=search)
            )
            mails = mails.filter(
            Q(share__file__original_name__icontains=search) |
            Q(share__recipient_email__icontains=search)
            )

        return shares, mails
    @staticmethod
    def get_dashboard_metrics(owner):
        """
        Compute dashboard stats
        """

        # Total shares
        total_shares = FileShareLink.objects.filter(
            owner=owner
        ).count()

        # Active links (not expired)
        active_links = FileShareLink.objects.filter(
            owner=owner,
            accessed=False,
            expiration_datetime__gt=timezone.now()
        ).count()

        # Next scheduled mail
        next_schedule = ScheduledMail.objects.filter(
            share__owner=owner,
            status=ScheduledMail.Status.PENDING
        ).order_by("created_at").first()

        next_report_days = (
            (next_schedule.created_at - timezone.now()).days
            if next_schedule else None
        )

        return {
            "total_shares": total_shares,
            "active_links": active_links,
            "next_report_days": next_report_days
        }

    @staticmethod
    def build_response_data(shares, mails):
        """
                Normalize + merge data
                """
        data = []

        # 🔹 Shares
        for share in shares:
            data.append({
                "type": "SHARES",
                "id": str(share.id),
                "file_name": share.file.original_name,
                "recipient": share.recipient_email,
                "status": "shared",
                "sent_at": localtime(share.created_at),                
                "sort_time": share.created_at,  
                "accessed": share.accessed,
                "accessed_at":share.accessed_at or "N/A"
            })

        # 🔹 Mails
        for mail in mails:
            share = mail.share
            file = share.file

            data.append({
                "type": "SCHEDULES",
                "id": str(mail.id),
                "file_name": file.original_name,
                "recipient": share.recipient_email,
                "status": mail.status,
                "sent_at": localtime(mail.sent_at),
                "sort_time": mail.sent_at,
                "accessed": share.accessed,
                "accessed_at":share.accessed_at or "N/A"
            })

        # Sort (latest first)
        data.sort(key=lambda x: x["sort_time"], reverse=True)

        return data

    @staticmethod
    def generate_csv(data):
        """
        Generate CSV from unified data
        """

        buffer = StringIO()
        writer = csv.writer(buffer)

        writer.writerow([
            "Type",
            "ID",
            "File Name",
            "Recipient",
            "Status",
            "Sent At",
            "Accessed"
        ])

        for row in data:
            writer.writerow([
                row["type"],
                row["id"],
                row["file_name"],
                row["recipient"],
                row["status"],
                str(row["sent_at"]),
                row["accessed"],
            ])

        buffer.seek(0)
        return buffer


CONTENT_TYPE_GROUPS = {
    "images": [
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/svg+xml",
    ],
    "documents": [
        "application/pdf",
        "text/plain",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ],
    "spreadsheets": [
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/csv",
    ],
    "archives": [
        "application/zip",
        "application/x-rar-compressed",
        "application/x-tar",
        "application/gzip",
    ],
    "others": [
        "application/octet-stream",
        "application/json",
        "application/xml",
    ],
}

class StorageService:

    @staticmethod
    def format_size(size_bytes):
        """
        Convert bytes into human readable format
        """

        if size_bytes is None:
            return "0 Bytes"

        units = ["Bytes", "KB", "MB", "GB", "TB"]

        size = float(size_bytes)

        for unit in units:

            if size < 1024:
                return f"{size:.2f} {unit}"

            size /= 1024

        return f"{size:.2f} PB"

    @staticmethod
    def calculate_percentage(used, limit):
        """
        Calculate storage usage percentage
        """
        if limit == 0:
            return 0

        return round((used / limit) * 100, 2)

    @staticmethod
    def is_storage_critical(percentage):
        """
        Determine whether storage usage is critical
        """

        return percentage >= 90

    @staticmethod
    def get_storage_summary(user):
        """
        Get storage dashboard summary data
        """

        storage_limit = user.storage_limit_bytes or 0
        storage_used = user.storage_used_bytes or 0

        free_storage = max(storage_limit - storage_used, 0)

        percentage_used = StorageService.calculate_percentage(
            used=storage_used,
            limit=storage_limit
        )

        return {
            "storage_limit_bytes": storage_limit,
            "storage_used_bytes": storage_used,
            "free_storage_bytes": free_storage,

            "storage_limit_human":
                StorageService.format_size(storage_limit),

            "storage_used_human":
                StorageService.format_size(storage_used),

            "free_storage_human":
                StorageService.format_size(free_storage),

            "percentage_used": percentage_used,

            "is_storage_critical":
                StorageService.is_storage_critical(
                    percentage_used
                )
        }
    @staticmethod
    def get_storage_by_content_type(user):
        """
        Returns storage used grouped by content type category.
        Assumes a File model with fields: user, content_type, size
        """
        from django.db.models import Sum  # adjust import to your ORM

        result = {}

        for group_name, mime_types in CONTENT_TYPE_GROUPS.items():
            total = (
                File.objects                          # replace with your model
                    .filter(user=user, content_type__in=mime_types)
                    .aggregate(total=Sum("file_size"))     # replace "size" with your field name
                ["total"] or 0
            )
            result[group_name] = total

        return result

    @staticmethod
    def get_storage_summary(user):
        storage_limit = user.storage_limit_bytes or 0
        storage_used = user.storage_used_bytes or 0
        free_storage = max(storage_limit - storage_used, 0)

        percentage_used = StorageService.calculate_percentage(
            used=storage_used,
            limit=storage_limit
        )

        # --- new: per-category breakdown ---
        by_type_bytes = StorageService.get_storage_by_content_type(user)

        by_type = {
            group: {
                "bytes": bytes_used,
                "human": StorageService.format_size(bytes_used),
                "percentage": StorageService.calculate_percentage(bytes_used, storage_used)  # ← storage_used not storage_limit
            }
            for group, bytes_used in by_type_bytes.items()
        }
        # ------------------------------------

        return {
            "storage_limit_bytes": storage_limit,
            "storage_used_bytes": storage_used,
            "free_storage_bytes": free_storage,
            "storage_limit_human": StorageService.format_size(storage_limit),
            "storage_used_human": StorageService.format_size(storage_used),
            "free_storage_human": StorageService.format_size(free_storage),
            "percentage_used": percentage_used,
            "is_storage_critical": StorageService.is_storage_critical(percentage_used),
            "storage_by_type": by_type,   # <-- added
        }

  
    @staticmethod
    def claim(user_id, file_size):
        with transaction.atomic():
            updated=(
                User.objects.filter(
                    id=user_id,
                    storage_used_bytes__lte=F("storage_limit_bytes")-file_size
                ).update(
                    storage_used_bytes=F("storage_used_bytes")+file_size
                )
            )
            if updated == 0:
                raise StorageLimitExceeded("Storage limit of 1GB exceeded")

    @staticmethod
    def release(user_id, file_size):
        with transaction.atomic():
            User.objects.filter(
                id=user_id
            ).update(
                storage_used_bytes=F("storage_used_bytes")-file_size
            )


class DashboardClass:
    @staticmethod
    def get_dashboard_data(user):
        now = timezone.now()
        
        # Total Sent
        total_sent = FileShareLink.objects.filter(owner=user).count()
        
        # Shared Contacts
        shared_contacts = FileShareLink.objects.filter(owner=user).values('recipient_email').distinct().count()
        
        # Next Report In (using next scheduled mail)
        next_schedule = ScheduledMail.objects.filter(
            share__owner=user,
            status=ScheduledMail.Status.PENDING,
            scheduled_for__gt=now
        ).order_by("scheduled_for").first()
        
        next_report_days = (next_schedule.scheduled_for - now).days if next_schedule else None
        
        # Monthly Reach (Growth in shares)
        last_month = now - timedelta(days=30)
        two_months_ago = now - timedelta(days=60)
        
        shares_this_month = FileShareLink.objects.filter(owner=user, created_at__gte=last_month).count()
        shares_last_month = FileShareLink.objects.filter(owner=user, created_at__gte=two_months_ago, created_at__lt=last_month).count()
        
        if shares_last_month == 0:
            monthly_reach = f"+{shares_this_month * 100}%" if shares_this_month > 0 else "0%"
        else:
            growth = ((shares_this_month - shares_last_month) / shares_last_month) * 100
            monthly_reach = f"+{int(growth)}%" if growth > 0 else f"{int(growth)}%"
            
        # Total Files
        total_files = File.objects.filter(user=user, is_deleted=False).count()
            
        # Active Shared Links (top 3)
        active_links = FileShareLink.objects.filter(
            owner=user,
            accessed=False,
            expiration_datetime__gt=now
        ).select_related('file').order_by('-created_at')[:3]
        
        # Recent Activities (combining recently uploaded files and shares)
        # For simplicity, we just fetch latest files and latest shares
        recent_files = File.objects.filter(user=user, is_deleted=False).order_by('-created_at')[:5]
        
        activities = []
        for f in recent_files:
            activities.append({
                "type": "file",
                "id": str(f.id),
                "title": f.original_name,
                "icon": "fa-file",
                "sub": f"{f.content_type} • Uploaded",
                "time": f.created_at,
                "is_active": True
            })
            
        recent_shares = FileShareLink.objects.filter(owner=user).select_related('file').order_by('-created_at')[:5]
        for s in recent_shares:
            activities.append({
                "type": "share",
                "id": str(s.id),
                "title": s.file.original_name,
                "icon": "fa-share-nodes",
                "sub": f"Shared with {s.recipient_email}",
                "time": s.created_at,
                "is_active": True
            })
            
        activities.sort(key=lambda x: x["time"], reverse=True)
        recent_activities = activities[:4] # Take top 4
        
        storage_summary = StorageService.get_storage_summary(user)
        
        return {
            "kpi": {
                "total_sent": total_sent,
                "shared_contacts": shared_contacts,
                "next_report_days": next_report_days,
                "monthly_reach": monthly_reach,
                "total_files": total_files
            },
            "active_links": active_links,
            "recent_activities": recent_activities,
            "storage_summary": storage_summary
        }

class StorageManagementService:
    @staticmethod
    def get_files_by_category(user, category, search="", sort_by="-file_size"):
        files = File.objects.filter(user=user, is_deleted=False)
        if search:
            files = files.filter(Q(original_name__icontains=search) | Q(description__icontains=search))
            
        if category and category.lower() != "all":
            category_lower = category.lower()
            if category_lower == "videos": # mapped to others or handled specifically if needed, but CONTENT_TYPE_GROUPS doesn't have videos.
                # Let's add video mimes to others or define it
                pass
            
            if category_lower == "others":
                all_known_mimes = []
                for k, v in CONTENT_TYPE_GROUPS.items():
                    if k != "others":
                        all_known_mimes.extend(v)
                files = files.exclude(content_type__in=all_known_mimes)
            elif category_lower in CONTENT_TYPE_GROUPS:
                mime_types = CONTENT_TYPE_GROUPS[category_lower]
                files = files.filter(content_type__in=mime_types)
                
        if sort_by:
            if sort_by == 'size':
                files = files.order_by('file_size')
            elif sort_by == '-size':
                files = files.order_by('-file_size')
            else:
                files = files.order_by(sort_by)
        else:
            files = files.order_by("-file_size")
            
        return files
        
    @staticmethod
    def get_duplicate_files(user, search="", sort_by="-file_size"):
        from django.db.models import Count
        duplicates = File.objects.filter(user=user, is_deleted=False).values('checksum').annotate(count=Count('id')).filter(count__gt=1)
        checksums = [d['checksum'] for d in duplicates]
        
        files = File.objects.filter(user=user, checksum__in=checksums, is_deleted=False)
        if search:
            files = files.filter(original_name__icontains=search)
            
        if sort_by == 'size':
            files = files.order_by('checksum', 'file_size')
        elif sort_by == '-size':
            files = files.order_by('checksum', '-file_size')
        else:
            files = files.order_by('checksum', '-created_at')
            
        return files
        
    @staticmethod
    def get_old_files(user, search="", sort_by="last_accessed"):
        from django.utils import timezone
        import datetime
        six_months_ago = timezone.now() - datetime.timedelta(days=180)
        files = File.objects.filter(user=user, is_deleted=False, last_accessed__lt=six_months_ago)
        if search:
            files = files.filter(original_name__icontains=search)
            
        if sort_by == 'size':
            files = files.order_by('file_size')
        elif sort_by == '-size':
            files = files.order_by('-file_size')
        else:
            files = files.order_by('last_accessed')
            
        return files
        
    @staticmethod
    def permanent_delete_files(user, file_ids):
        files = File.objects.filter(user=user, id__in=file_ids)
        total_freed = 0
        for f in files:
            if not f.is_deleted:
                # If it's already soft deleted, it might still take quota unless ClearTrash was called. 
                # Actually ClearTrash deletes the object entirely. So if it exists, it's taking quota.
                pass
            total_freed += f.file_size
            f.delete() # hard delete
            
        if total_freed > 0:
            StorageService.release(user.id, total_freed)
            
        return total_freed






 
 
# ─── Thread ───────────────────────────────────────────────────────────────────
 
class ThreadService:
 
    @staticmethod
    def create(user, validated_data: dict) -> ProjectThread:
        """Create a thread and auto-add the root node."""
        with transaction.atomic():
            thread = ProjectThread.objects.create(created_by=user, **validated_data)
            # Auto-create the root node
            root = ProjectNode.objects.create(
                thread=thread,
                title=thread.title,
                description="Project root node",
                created_by=user,
                stage=0,
                row=0,
                status="ACTIVE"
            )
            NodeActivity.objects.create(
                node=root,
                actor=user,
                event_type=NodeActivity.EventType.CREATED,
                message=f'Thread "{thread.title}" initialized with root node.',
            )
        return thread
 
    @staticmethod
    def get_graph(thread_id: int) -> dict:
        """Return all nodes and dependency edges for ReactFlow."""
        nodes = ProjectNode.objects.filter(thread_id=thread_id, is_deleted=False)
        node_ids = nodes.values_list("id", flat=True)
        edges = NodeDependency.objects.filter(
            source_node_id__in=node_ids,
            target_node_id__in=node_ids,
        )
        return {"nodes": nodes, "edges": edges}
 
 
# ─── Node ─────────────────────────────────────────────────────────────────────
 
class NodeService:
 
    @staticmethod
    def add_node(thread: ProjectThread, user, validated_data: dict) -> ProjectNode:
        """Create a child node and log the activity."""
        # Auto-position: offset from parent if given
        parent = validated_data.get("parent_node")
        if parent and not validated_data.get("stage"):
            validated_data["stage"] = parent.stage + 1
            validated_data["row"] = 0
 
        node = ProjectNode.objects.create(thread=thread, created_by=user, **validated_data)
        NodeActivity.objects.create(
            node=node,
            actor=user,
            event_type=NodeActivity.EventType.CREATED,
            message=f'Node "{node.title}" created.',
        )
        return node
 
    @staticmethod
    def add_branch(thread: ProjectThread, user, parent_node: ProjectNode, validated_data: dict) -> ProjectNode:
        """Create a branch node diverging from parent_node."""
        validated_data["parent_node"] = parent_node
        validated_data["branch_root"] = parent_node
        # Branches offset on stage/row
        validated_data["stage"] = parent_node.stage + 1
        sibling_count = ProjectNode.objects.filter(branch_root=parent_node).count()
        validated_data["row"] = sibling_count + 1
 
        node = ProjectNode.objects.create(thread=thread, created_by=user, **validated_data)
        NodeActivity.objects.create(
            node=node,
            actor=user,
            event_type=NodeActivity.EventType.CREATED,
            message=f'Branch "{node.title}" created from "{parent_node.title}".',
        )
        return node
 
    @staticmethod
    def update_node(node: ProjectNode, user, validated_data: dict) -> ProjectNode:
        old_status = node.status
        for attr, value in validated_data.items():
            setattr(node, attr, value)
        node.save()
 
        if "status" in validated_data and validated_data["status"] != old_status:
            NodeActivity.objects.create(
                node=node,
                actor=user,
                event_type=NodeActivity.EventType.STATUS_CHANGED,
                message=f'Status changed from {old_status} to {node.status}.',
            )
        else:
            NodeActivity.objects.create(
                node=node,
                actor=user,
                event_type=NodeActivity.EventType.UPDATED,
                message=f'Node "{node.title}" updated.',
            )
        return node
 
    @staticmethod
    def soft_delete(node: ProjectNode, user):
        """Archive instead of hard-delete; mark all downstream nodes as BLOCKED."""
        with transaction.atomic():
            node.is_deleted = True
            node.status = ProjectNode.Status.ARCHIVED
            node.save()
 
            # Find all downstream nodes that depend on this one via BFS
            downstream_ids = set()
            queue = [node.id]
            while queue:
                current_id = queue.pop(0)
                # Find direct children of the current node
                direct_downstream = list(NodeDependency.objects.filter(
                    source_node_id=current_id
                ).values_list("target_node_id", flat=True))
                
                for downstream_id in direct_downstream:
                    if downstream_id not in downstream_ids:
                        downstream_ids.add(downstream_id)
                        queue.append(downstream_id)
 
            if downstream_ids:
                ProjectNode.objects.filter(id__in=downstream_ids).update(
                    status=ProjectNode.Status.BLOCKED
                )
 
            NodeActivity.objects.create(
                node=node,
                actor=user,
                event_type=NodeActivity.EventType.STATUS_CHANGED,
                message=f'Node "{node.title}" archived. Downstream nodes marked as BLOCKED.',
            )
 
    @staticmethod
    def update_position(node: ProjectNode, stage: int, row: int):
        """Quick positional update from canvas drag — no activity log needed."""
        node.stage = stage
        node.row = row
        node.save(update_fields=["stage", "row"])
 
 
# ─── Dependency ───────────────────────────────────────────────────────────────
 
class DependencyService:
    @staticmethod
    def _restore_downstream(source_node: ProjectNode, user):

        queue = [source_node.id]
        visited = set()

        while queue:
            node_id = queue.pop(0)

            if node_id in visited:
                continue

            visited.add(node_id)

            try:
                node = ProjectNode.objects.get(
                    id=node_id,
                    is_deleted=False
                )
            except ProjectNode.DoesNotExist:
                continue

            if node.status == ProjectNode.Status.NEEDS_REVIEW:
                node.status = ProjectNode.Status.ACTIVE
                node.save(update_fields=["status"])

                NodeActivity.objects.create(
                    node=node,
                    actor=user,
                    event_type=NodeActivity.EventType.STATUS_CHANGED,
                    message='Automatically restored to ACTIVE after dependency recovery.',
                )

            next_ids = NodeDependency.objects.filter(
                source_node=node
            ).values_list("target_node_id", flat=True)

            queue.extend(next_ids)
 
    @staticmethod
    def _has_cycle(source_id: int, target_id: int) -> bool:
        """BFS from target — if we can reach source, adding this edge creates a cycle."""
        visited = set()
        queue = [target_id]
        while queue:
            current = queue.pop(0)
            if current == source_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            children = NodeDependency.objects.filter(
                source_node_id=current
            ).values_list("target_node_id", flat=True)
            queue.extend(children)
        return False
 
    @staticmethod
    def add_dependency(source: ProjectNode, target: ProjectNode, dependency_type: str, user) -> NodeDependency:

        if DependencyService._has_cycle(source.id, target.id):
            raise ValidationError("Adding this dependency would create a circular reference.")
        if source.status==ProjectNode.Status.INACTIVE or source.status==ProjectNode.Status.BLOCKED:
            raise ValidationError("Cannot add dependency from an inactive node.")
 
        # Ensure only one outgoing dependency from source (cascading deactivation)
        old_deps = NodeDependency.objects.filter(source_node=source)
        if old_deps.exists():
            target_ids = list(old_deps.values_list("target_node_id", flat=True))
            old_deps.delete()
            
            # Cascade: all orphaned nodes become INACTIVE and lose their outgoing branches
            queue = target_ids
            visited = set()
            while queue:
                curr_id = queue.pop(0)
                if curr_id in visited: continue
                visited.add(curr_id)
                
                try:
                    curr_node = ProjectNode.objects.get(id=curr_id)
                    curr_node.status = ProjectNode.Status.INACTIVE
                    curr_node.save(update_fields=["status"])
                    
                    # Find and delete its outgoing dependencies, adding targets to the queue
                    outgoing = NodeDependency.objects.filter(source_node_id=curr_id)
                    next_targets = list(outgoing.values_list("target_node_id", flat=True))
                    outgoing.delete()
                    queue.extend(next_targets)
                    
                    NodeActivity.objects.create(
                        node=curr_node,
                        actor=user,
                        event_type=NodeActivity.EventType.STATUS_CHANGED,
                        message=f'Node "{curr_node.title}" deactivated because its parent dependency was removed.',
                    )
                except ProjectNode.DoesNotExist:
                    continue
        dep = NodeDependency.objects.create(
            source_node=source,
            target_node=target,
            dependency_type=dependency_type,
        )

        target.status=ProjectNode.Status.ACTIVE
        target.save(update_fields=["status"])
        DependencyService._restore_downstream(target, user)
        NodeActivity.objects.create(
            node=source,
            actor=user,
            event_type=NodeActivity.EventType.DEPENDENCY_ADDED,
            message=f'Dependency updated: "{source.title}" now points to "{target.title}".',
        )
        return dep
 
    @staticmethod
    def update_dependency(dep: NodeDependency, dependency_type: str, user) -> NodeDependency:
        if dependency_type not in dict(NodeDependency.DependencyType.choices):
            from django.core.exceptions import ValidationError
            raise ValidationError("Invalid dependency type.")
        dep.dependency_type = dependency_type
        dep.save(update_fields=["dependency_type"])
        NodeActivity.objects.create(
            node=dep.source_node,
            actor=user,
            event_type=NodeActivity.EventType.UPDATED,
            message=f'Dependency type updated to "{dependency_type}".',
        )
        return dep

    @staticmethod
    def remove_dependency(dep: NodeDependency, user):
        source_node = dep.source_node
        target_node = dep.target_node

        dep.delete()

        FileService._propagate_impact(target_node, user)

        NodeActivity.objects.create(
            node=target_node,
            actor=user,
            event_type=NodeActivity.EventType.STATUS_CHANGED,
            message=f'Dependency from "{source_node.title}" removed. Marked as NEEDS_REVIEW.',
        )