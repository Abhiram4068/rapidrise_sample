from django.contrib.auth import get_user_model
from .models import User, File, FileShareLink, Collection, CollectionFile, ScheduledMail
from django.db import transaction, IntegrityError
from rest_framework_simplejwt.tokens import RefreshToken
import hashlib
from typing import List
from django.http import FileResponse
from django.shortcuts import get_object_or_404
import secrets
from django.utils import timezone
from datetime import timedelta
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum, Count


import logging
logger = logging.getLogger(__name__)


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
    
class UserProfileService:
    @staticmethod
    def get_profile(user: User):
        return (
            User.objects
            .filter(pk=user.pk)
            .annotate(total_files=Count("files"))  # related_name
            .only("id", "email", "first_name", "last_name", "role")
            .first()
        )
    @staticmethod
    def update_profile(user: User, data: dict) -> User:
        updatable_fields = ["first_name", "last_name", "date_of_birth", "role"]
        
        for field in updatable_fields:
            if field in data:
                setattr(user, field, data[field])
        
        user.save(update_fields=updatable_fields)
        return user

class FileService:
    """
    Handles uploads with checksum-based deduplication,
    secure downloads with ownership validation,
    user-scoped listing, and soft deletion.
    """
    @staticmethod
    @transaction.atomic
    
    def upload_files(user, files:List, description=None):
        logger.info(f"Starting file processing | user_id={user.id}")
        uploaded_files=[]
        for file_obj in files:
            checksum=FileService._calculate_checksum(file_obj)
            
            
            existing_file=File.objects.filter(checksum=checksum).first()
            if existing_file:
                file_instance=File.objects.create(
                    user=user,
                    file=existing_file.file,
                    original_name=file_obj.name,
                    description=description,
                    file_size=file_obj.size,
                    content_type=file_obj.content_type,
                    checksum=checksum
                )
                is_duplicate=True
            else:
                file_instance=File.objects.create(
                    user=user,
                    file=file_obj,
                    original_name=file_obj.name,
                    description=description,
                    file_size=file_obj.size,
                    content_type=file_obj.content_type,
                    checksum=checksum
                )
                is_duplicate=False
            logger.debug(
                f"Processing file | name={file_obj.name} | size={file_obj.size}"
            )
            
            logger.info(
                f"File saved | file_id={file_instance.id} | user_id={user.id}"
            )
            uploaded_files.append({
                'id':str(file_instance.id),
                'name':file_instance.original_name,
                "size": file_instance.file_size,
                "content_type": file_instance.content_type,
                "checksum": file_instance.checksum,
                "created_at": file_instance.created_at
            })
        logger.info(f"All files processed successfully | count={len(uploaded_files)}")


        return uploaded_files

    @staticmethod
    def download_file(user, file_id):
        file_obj=get_object_or_404(File, id=file_id, user=user)

        return FileResponse(
            file_obj.file.open('rb'),
            as_attachment=True,
            filename=file_obj.original_name
        )

    @staticmethod
    def user_list_files(user):
        all_files=File.objects.filter(user=user, is_deleted=False, is_archive=False)
        return all_files
    
    @staticmethod
    def get_file_detail(user, file_id):
        file_obj=get_object_or_404(
            File, user=user, id=file_id, is_deleted=False, is_archive=False
        )
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
        file_obj.save(update_fields=['is_archive'])
        
    @staticmethod
    def get_user_starred_files(user):
        starred_files=File.objects.filter(user=user, is_starred=True, is_deleted=False)
        return starred_files

    @staticmethod
    def get_user_deleted_files(user):
        all_deleted_files=File.objects.filter(user=user, is_deleted=True)
        return all_deleted_files
    
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
        return File.objects.filter(user=user, is_deleted=False, is_archive=False).order_by('-created_at')[:6]
        
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
            
        scheduled_mail.status = ScheduledMail.Status.CANCELLED
        scheduled_mail.save(update_fields=["status"])
        
        if scheduled_mail.task_id:
            from celery.result import AsyncResult
            AsyncResult(scheduled_mail.task_id).revoke()
            
        return scheduled_mail

    @staticmethod
    def get_scheduled_mails(user):
        queryset = ScheduledMail.objects.filter(
            share__owner=user
        ).select_related('share', 'share__file', 'share__owner')
        
        return {
            "total": queryset.count(),
            "pending": queryset.filter(status=ScheduledMail.Status.PENDING).count(),
            "completed": queryset.filter(status=ScheduledMail.Status.SENT).count(),
            "mails": queryset
        }

        

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


