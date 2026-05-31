from django.db.models import Q
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from .models import (
    User, File, FileShareLink, Collection, CollectionFile, ScheduledMail,
    ReactivationRequest, DesignationChangeRequest, ChunkUploadSession,
)
from django.db.models import F
from django.db import transaction, IntegrityError
from rest_framework_simplejwt.tokens import RefreshToken
import hashlib
from datetime import date
from typing import List
from django.http import FileResponse
from django.shortcuts import get_object_or_404
import secrets
from django.utils import timezone
from django.utils.timezone import localtime
import zipfile
import io
from datetime import timedelta
import csv
from io import StringIO
from .email_template import (
    send_templated_mail,
    send_templated_email,
    send_templated_html_mail,
    build_file_share_email_html,
    build_bulk_share_email_html,
    get_sender_designation,
)
from django.conf import settings
from django.core.files.base import ContentFile
from django.db.models import Sum, Count
from django.contrib.auth import update_session_auth_hash
from .exceptions import StorageLimitExceeded
import logging
logger = logging.getLogger(__name__)
import os
import threading
import shutil
import time
import uuid
from rest_framework.exceptions import ValidationError as DRFValidationError, ValidationError
from django.core.exceptions import ValidationError as DjangoValidationError
from datetime import datetime
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.tokens import default_token_generator
from .models import NodeActivity, NodeDependency, NodeFile, ProjectNode, ProjectThread, ProjectStage



def create_user(validated_data):
    try:
        with transaction.atomic():
            validated_data["account_status"] = User.AccountStatus.WAITING_FOR_APPROVAL
            user = User.objects.create_user(**validated_data)
            from administration.services import AdminLogService
            from administration.models import AdminLog
            AdminLogService.log_activity(
                activity_type=AdminLog.ActivityType.USER_REGISTERED,
                target_user=user,
                action_details=f"New user registration request from {user.email}."
            )
            return user
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
        raise AuthenticationError("Invalid credentials")
    if not user.check_password(password):
        raise AuthenticationError("Invalid credentials")
    if not user.is_active:
        raise AuthenticationError("Account is disabled")
    if user.account_status == User.AccountStatus.BLOCKED:
        raise AuthenticationError("Your account has been blocked by the administrator. Access to this platform has been permanently restricted until reviewed by the admin team. Only an administrator can revoke this restriction and restore account access.")
    if user.account_status == User.AccountStatus.DELETED:
        raise AuthenticationError("Your account has been deleted by the administrator. Access to this platform has been permanently restricted until reviewed by the admin team. Only an administrator can revoke this restriction and restore account access.")
    if user.account_status == User.AccountStatus.WAITING_FOR_APPROVAL:
        raise AuthenticationError("Your account is awaiting admin approval.")
    user.last_login=timezone.now()
    user.save(update_fields=['last_login'])
    refresh=RefreshToken.for_user(user)
    return {
        'user':user,
        'tokens':{
            'access':str(refresh.access_token),
            'refresh':str(refresh)
        }
    }

class DesignationListService:
    @staticmethod
    def get_active_designations():
        from administration.models import Designation
        return Designation.objects.all().order_by('name')


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
        f"{settings.FRONTEND_BASE_URL}"
        f"/auth/reset-password/confirm/"
        f"?uid={uid}&token={token}"
    )
    

        def _send_email():
            try:
                send_templated_mail(
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

    @staticmethod
    def deactivate_account(user):
        """
        Deactivate user account by setting account_status to deactivated.
        User remains is_active=True to allow login for reactivation requests.
        """
        user.account_status = User.AccountStatus.DEACTIVATED
        user.deactivated_at = timezone.now()
        user.save(update_fields=['account_status', 'deactivated_at'])
        
        logger.info(f"Account deactivated for user: {user.email}")
        
        def send_email():
            try:
                send_templated_mail(
                    subject="Your Account has been Deactivated",
                    message=f"Hi {user.first_name},\n\nYour account has been deactivated as per your request.\nIf this was a mistake, you can log in and submit a reactivation request to the admin.",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                )
            except Exception as e:
                logger.error(f"Failed to send deactivation email to {user.email}: {e}")

        import threading
        thread = threading.Thread(target=send_email)
        thread.start()
        
        return True

class AccountService:
    @staticmethod
    def submit_reactivation_request(user, reason):
        """
        Submit a request to the admin for account reactivation.
        """
        if ReactivationRequest.objects.filter(user=user, is_resolved=False).exists():
            raise DRFValidationError("You already have a pending reactivation request.")
        
        request = ReactivationRequest.objects.create(
            user=user,
            reason=reason
        )
        from administration.services import AdminLogService
        from administration.models import AdminLog
        AdminLogService.log_activity(
            activity_type=AdminLog.ActivityType.REACTIVATION_REQUEST,
            target_user=user,
            action_details=f"Account reactivation request submitted by {user.email}."
        )
        logger.info(f"Reactivation request submitted by user: {user.email}")
        return request


class UserProfileService:
 
    @staticmethod
    def get_profile(user: User):
        return (
            User.objects
            .filter(pk=user.pk)
            .annotate(total_files=Count(
                "files",
                filter=Q(files__is_deleted=False)
            ))
            .only("id", "email", "first_name", "last_name", "designation", "date_of_birth")
            .first()
        )
 
    @staticmethod
    def update_profile(user: User, data: dict) -> User:
        updatable_fields = ["first_name", "last_name", "date_of_birth"]
        fields_to_save = []
        for field in updatable_fields:
            if field in data:
                setattr(user, field, data[field])
                fields_to_save.append(field)
        if fields_to_save:
            user.save(update_fields=fields_to_save)
        return user
    
    # ── Designation Change Request ─────────────────────────────────────────
 
    @staticmethod
    def get_user_designation_requests(user: User):
        """Return all designation change requests belonging to the given user."""
        return DesignationChangeRequest.objects.filter(user=user)
 
    @staticmethod
    def create_designation_request(user: User, requested_designation) -> DesignationChangeRequest:
        """
        Submit a new designation change request.
        `requested_designation` is an administration.Designation instance or pk.
        """
        from administration.models import Designation

        if not isinstance(requested_designation, Designation):
            requested_designation = Designation.objects.get(pk=requested_designation)

        if user.designation_id == requested_designation.pk:
            raise ValueError(
                "Requested designation must be different from your current designation."
            )

        if not user.designation_id:
            raise ValueError("Your account has no current designation assigned.")

        if DesignationChangeRequest.objects.filter(
            user=user,
            status=DesignationChangeRequest.StatusChoices.PENDING
        ).exists():
            raise ValueError(
                "You already have a pending designation change request. "
                "Please wait for it to be resolved before submitting a new one."
            )

        request = DesignationChangeRequest.objects.create(
            user=user,
            current_designation=user.designation,
            requested_designation=requested_designation,
            status=DesignationChangeRequest.StatusChoices.PENDING,
        )
        from administration.services import AdminLogService
        from administration.models import AdminLog
        AdminLogService.log_activity(
            activity_type=AdminLog.ActivityType.DESIGNATION_CHANGE_REQUEST,
            target_user=user,
            action_details=f"Designation change request from '{user.designation}' to '{requested_designation}' submitted by {user.email}."
        )
        return request

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




class ChunkUploadService:
    """Chunked upload sessions: store, resume, pause, cancel, and progress."""

    SESSION_TTL_HOURS = 24
    UPLOAD_ID_PATTERN = r"^[a-zA-Z0-9_-]+$"

    @staticmethod
    def _validate_upload_id(upload_id):
        import re
        if not re.match(ChunkUploadService.UPLOAD_ID_PATTERN, str(upload_id)):
            raise ValueError("Invalid upload_id")

    @staticmethod
    def _temp_dir(upload_id):
        ChunkUploadService._validate_upload_id(upload_id)
        return os.path.join(settings.MEDIA_ROOT, "temp_uploads", str(upload_id))

    @staticmethod
    def list_chunk_indices_on_disk(upload_id):
        temp_dir = ChunkUploadService._temp_dir(upload_id)
        if not os.path.isdir(temp_dir):
            return []
        indices = []
        for name in os.listdir(temp_dir):
            if name.startswith("chunk_"):
                try:
                    indices.append(int(name.split("_", 1)[1]))
                except ValueError:
                    continue
        return sorted(indices)

    @staticmethod
    def sync_session_from_disk(session):
        on_disk = ChunkUploadService.list_chunk_indices_on_disk(session.upload_id)
        merged = sorted(set(session.chunks_received or []) | set(on_disk))
        if merged != session.chunks_received:
            session.chunks_received = merged
            session.save(update_fields=["chunks_received", "updated_at"])
        return session

    @staticmethod
    def get_next_chunk_index(session):
        received = set(session.chunks_received or [])
        for i in range(session.total_chunks):
            if i not in received:
                return i
        return session.total_chunks

    @staticmethod
    def progress_payload(session, extra=None):
        session = ChunkUploadService.sync_session_from_disk(session)
        received = session.chunks_received or []
        total = session.total_chunks
        percent = int((len(received) / total) * 100) if total else 0
        payload = {
            "upload_id": session.upload_id,
            "status": session.status,
            "file_name": session.file_name,
            "file_size": session.file_size,
            "total_chunks": total,
            "uploaded_chunks": received,
            "chunks_uploaded": len(received),
            "next_chunk": ChunkUploadService.get_next_chunk_index(session),
            "progress_percent": percent,
        }
        if extra:
            payload.update(extra)
        return payload

    @staticmethod
    def get_session_for_user(user, upload_id):
        try:
            session = ChunkUploadSession.objects.get(upload_id=upload_id, user=user)
        except ChunkUploadSession.DoesNotExist:
            raise DRFValidationError({"upload_id": "Upload session not found."})
        if session.expires_at and session.expires_at < timezone.now():
            raise DRFValidationError({"upload_id": "Upload session has expired."})
        return session

    @staticmethod
    def get_or_create_session(user, upload_id, file_name, file_size, content_type, total_chunks, description=None):
        ChunkUploadService._validate_upload_id(upload_id)
        expires_at = timezone.now() + timedelta(hours=ChunkUploadService.SESSION_TTL_HOURS)

        session, created = ChunkUploadSession.objects.get_or_create(
            upload_id=upload_id,
            user=user,
            defaults={
                "file_name": file_name,
                "file_size": int(file_size),
                "content_type": content_type,
                "total_chunks": int(total_chunks),
                "chunks_received": [],
                "status": ChunkUploadSession.Status.UPLOADING,
                "description": description,
                "expires_at": expires_at,
            },
        )

        if not created:
            if session.file_name != file_name or session.file_size != int(file_size):
                raise DRFValidationError(
                    {"upload_id": "This upload id is already used for a different file."}
                )
            if session.total_chunks != int(total_chunks):
                session.total_chunks = int(total_chunks)
                session.save(update_fields=["total_chunks", "updated_at"])
            if session.status == ChunkUploadSession.Status.PAUSED:
                session.status = ChunkUploadSession.Status.UPLOADING
                session.save(update_fields=["status", "updated_at"])

        return ChunkUploadService.sync_session_from_disk(session)

    @staticmethod
    def chunk_already_stored(upload_id, chunk_index):
        path = os.path.join(ChunkUploadService._temp_dir(upload_id), f"chunk_{chunk_index}")
        return os.path.isfile(path) and os.path.getsize(path) > 0

    @staticmethod
    def save_chunk_file(upload_id, chunk_index, chunk_file):
        ChunkUploadService._validate_upload_id(upload_id)
        temp_dir = ChunkUploadService._temp_dir(upload_id)
        os.makedirs(temp_dir, exist_ok=True)
        chunk_path = os.path.join(temp_dir, f"chunk_{chunk_index}")

        if ChunkUploadService.chunk_already_stored(upload_id, chunk_index):
            return {"path": chunk_path, "skipped": True}

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                if hasattr(chunk_file, "seek"):
                    chunk_file.seek(0)
                with open(chunk_path, "wb+") as dest:
                    for data in chunk_file.chunks():
                        dest.write(data)
                return {"path": chunk_path, "skipped": False}
            except Exception as e:
                logger.warning(f"Chunk upload failed attempt {attempt}: {str(e)}")
                if os.path.exists(chunk_path):
                    os.remove(chunk_path)
                if attempt == max_retries:
                    raise
                time.sleep(1)

    @staticmethod
    def mark_chunk_received(session, chunk_index):
        received = list(session.chunks_received or [])
        if chunk_index not in received:
            received.append(chunk_index)
            received.sort()
            session.chunks_received = received
            session.status = ChunkUploadSession.Status.UPLOADING
            session.save(update_fields=["chunks_received", "status", "updated_at"])
        return session

    @staticmethod
    def set_status(session, status):
        session.status = status
        session.save(update_fields=["status", "updated_at"])
        return session

    @staticmethod
    def pause_session(user, upload_id):
        session = ChunkUploadService.get_session_for_user(user, upload_id)
        ChunkUploadService.set_status(session, ChunkUploadSession.Status.PAUSED)
        return ChunkUploadService.progress_payload(session)

    @staticmethod
    def resume_session(user, upload_id):
        session = ChunkUploadService.get_session_for_user(user, upload_id)
        if session.status == ChunkUploadSession.Status.COMPLETED:
            raise DRFValidationError({"upload_id": "Upload already completed."})
        ChunkUploadService.set_status(session, ChunkUploadSession.Status.UPLOADING)
        return ChunkUploadService.progress_payload(session)

    @staticmethod
    def cancel_session(user, upload_id):
        session = ChunkUploadService.get_session_for_user(user, upload_id)
        temp_dir = ChunkUploadService._temp_dir(upload_id)
        if os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        session.status = ChunkUploadSession.Status.CANCELLED
        session.chunks_received = []
        session.save(update_fields=["status", "chunks_received", "updated_at"])
        return {"upload_id": upload_id, "status": session.status, "message": "Upload cancelled."}

    @staticmethod
    def mark_completed(session):
        session.status = ChunkUploadSession.Status.COMPLETED
        session.save(update_fields=["status", "updated_at"])

    @staticmethod
    def get_status(user, upload_id):
        session = ChunkUploadService.get_session_for_user(user, upload_id)
        return ChunkUploadService.progress_payload(session)

import magic
class FileService:
    """
    Handles uploads with checksum-based deduplication,
    secure downloads with ownership validation,
    user-scoped listing, and soft deletion.
    """
    
    @staticmethod
    def store_chunk(upload_id, chunk_index, chunk_file):
        """Stores a single chunk (delegates to ChunkUploadService)."""
        result = ChunkUploadService.save_chunk_file(upload_id, chunk_index, chunk_file)
        return result["path"]

    @staticmethod
    def complete_chunk_upload(user, upload_id, total_chunks, file_name, file_size, content_type, description=None, action=None):
        """
        Assembles chunks and completes the upload.
        """
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', str(upload_id)):
            raise Exception("Invalid upload_id")
            
        temp_dir = os.path.join(settings.MEDIA_ROOT, "temp_uploads", str(upload_id))
        if not os.path.exists(temp_dir):
            raise Exception("Upload session not found")
            
        # Verify all chunks exist
        for i in range(int(total_chunks)):
            if not os.path.exists(os.path.join(temp_dir, f"chunk_{i}")):
                raise Exception(f"Missing chunk {i}")
                
        # Merge chunks
        unique_name = f"{uuid.uuid4()}_{file_name}"
        final_relative_path = f"uploads/{unique_name}"
        final_full_path = os.path.join(settings.MEDIA_ROOT, final_relative_path)
        os.makedirs(os.path.dirname(final_full_path), exist_ok=True)
        
        hash_md5 = hashlib.md5()
        actual_size = 0
        
        try:
            with open(final_full_path, "wb+") as dest:
                for i in range(int(total_chunks)):
                    chunk_path = os.path.join(temp_dir, f"chunk_{i}")
                    with open(chunk_path, "rb") as ch_file:
                        while True:
                            data = ch_file.read(8192)
                            if not data:
                                break
                            dest.write(data)
                            hash_md5.update(data)
                            actual_size += len(data)
            
            if actual_size != int(file_size):
                raise Exception("Incomplete upload detected: size mismatch")
                
        except Exception as e:
            if os.path.exists(final_full_path):
                os.remove(final_full_path)
            raise Exception(f"Failed to assemble chunks: {str(e)}")
            
        checksum = hash_md5.hexdigest()
        
        # Cleanup temp dir and DB session
        shutil.rmtree(temp_dir, ignore_errors=True)
        try:
            session = ChunkUploadSession.objects.get(upload_id=upload_id, user=user)
            ChunkUploadService.mark_completed(session)
        except ChunkUploadSession.DoesNotExist:
            pass
        
        uploaded_path = final_relative_path
        
        class DummyFile:
            def __init__(self, name, size, type):
                self.name = name
                self.size = size
                self.content_type = type
                
        file_obj = DummyFile(file_name, int(file_size), content_type)
        
        try:
            with transaction.atomic():
                existing_file = File.objects.filter(
                    checksum=checksum, 
                    user=user, 
                    is_deleted=False
                ).first()

                if existing_file:
                    if not action:
                        if os.path.exists(final_full_path):
                            os.remove(final_full_path)
                        raise DRFValidationError({
                            "duplicate": True,
                            "message": f"File '{file_obj.name}' already exists",
                            "existing_file_id": str(existing_file.id),
                            "file_name": file_obj.name,
                        })

                    if action == "replace":
                        StorageService.release(user.id, existing_file.file_size)
                        StorageService.claim(user.id, file_obj.size)
                        
                        if existing_file.file:
                            existing_file.file.delete(save=False)
                        
                        existing_file.file.name = uploaded_path
                        existing_file.original_name = file_obj.name
                        existing_file.file_size = file_obj.size
                        existing_file.content_type = file_obj.content_type
                        existing_file.save()
                        
                        return {
                            "id": str(existing_file.id),
                            "name": existing_file.original_name,
                            "status": "success"
                        }

                    if action == "keep_both":
                        file_obj.name = FileService._rename_file(file_obj.name)

                StorageService.claim(user.id, file_obj.size)
                
                new_file = File.objects.create(
                    user=user,
                    file=uploaded_path,
                    original_name=file_obj.name,
                    file_size=file_obj.size,
                    content_type=file_obj.content_type,
                    checksum=checksum,
                    description=description
                )
                
                return {
                    "id": str(new_file.id),
                    "name": new_file.original_name,
                    "status": "success"
                }

        except Exception as e:
            if os.path.exists(final_full_path):
                os.remove(final_full_path)
            raise

    @staticmethod
    def _safe_store_file(file_obj):
        """
        Manually handles physical storage with retries and size validation.
        Calculates checksum during write to avoid multiple reads.
        Returns (relative_path, checksum).
        """
        MAX_RETRIES = 3
        unique_name = f"{uuid.uuid4()}_{file_obj.name}"
        temp_relative_path = f"temp_uploads/{unique_name}.uploading"
        final_relative_path = f"uploads/{unique_name}"

        temp_full_path = os.path.join(settings.MEDIA_ROOT, temp_relative_path)
        final_full_path = os.path.join(settings.MEDIA_ROOT, final_relative_path)

        # Ensure directories exist
        os.makedirs(os.path.dirname(temp_full_path), exist_ok=True)
        os.makedirs(os.path.dirname(final_full_path), exist_ok=True)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                hash_md5 = hashlib.md5()
                if hasattr(file_obj, 'seek'):
                    file_obj.seek(0)

                with open(temp_full_path, "wb+") as destination:
                    for chunk in file_obj.chunks():
                        destination.write(chunk)
                        hash_md5.update(chunk)

                uploaded_size = os.path.getsize(temp_full_path)
                if uploaded_size != file_obj.size:
                    raise Exception("Incomplete upload detected: size mismatch")

                # Atomic move to final location
                shutil.move(temp_full_path, final_full_path)
                return final_relative_path, hash_md5.hexdigest()

            except Exception as e:
                logger.warning(f"Upload attempt {attempt} failed for {file_obj.name}: {str(e)}")
                if os.path.exists(temp_full_path):
                    os.remove(temp_full_path)
                
                if attempt == MAX_RETRIES:
                    raise Exception(f"Failed to store file after {MAX_RETRIES} attempts: {str(e)}")
                
                time.sleep(2)

    @staticmethod
    def upload_files(user, files: List, description=None, action=None):
        """
        Handles batch upload with deduplication logic (replace/keep_both).
        Check for duplicates occurs AFTER physical storage to ensure data integrity.
        """
        uploaded_files = []
        failed_files = []

        for file_obj in files:
            uploaded_path = None
            try:
                # 1. Physical storage first (returns path and checksum)
                uploaded_path, checksum = FileService._safe_store_file(file_obj)
                full_path = os.path.join(settings.MEDIA_ROOT, uploaded_path)
                
                with transaction.atomic():
                    # 2. Check for duplicates using the freshly calculated checksum
                    existing_file = File.objects.filter(
                        checksum=checksum, 
                        user=user, 
                        is_deleted=False
                    ).first()

                    # 3. Duplicate Logic
                    if existing_file:
                        if not action:
                            # Cleanup stored file since we won't be using it
                            if os.path.exists(full_path):
                                os.remove(full_path)
                            raise DRFValidationError({
                                "duplicate": True,
                                "message": f"File '{file_obj.name}' already exists",
                                "existing_file_id": str(existing_file.id),
                                "file_name": file_obj.name,
                            })

                        if action == "replace":
                            # Storage account adjustment
                            StorageService.release(user.id, existing_file.file_size)
                            StorageService.claim(user.id, file_obj.size)
                            
                            # Cleanup old file
                            if existing_file.file:
                                existing_file.file.delete(save=False)
                            
                            existing_file.file.name = uploaded_path
                            existing_file.original_name = file_obj.name
                            existing_file.file_size = file_obj.size
                            existing_file.content_type = file_obj.content_type
                            existing_file.save()
                            
                            uploaded_files.append({
                                "id": str(existing_file.id),
                                "name": existing_file.original_name,
                                "status": "success"
                            })
                            continue

                        if action == "keep_both":
                            # Rename for clarity in DB, physical path is already unique
                            file_obj.name = FileService._rename_file(file_obj.name)

                    # 4. Storage Quota Check and DB Record Creation
                    StorageService.claim(user.id, file_obj.size)
                    
                    new_file = File.objects.create(
                        user=user,
                        file=uploaded_path,
                        original_name=file_obj.name,
                        file_size=file_obj.size,
                        content_type=file_obj.content_type,
                        checksum=checksum,
                        description=description
                    )
                    
                    uploaded_files.append({
                        "id": str(new_file.id),
                        "name": new_file.original_name,
                        "status": "success"
                    })

            except DRFValidationError as e:
                # e.detail contains the structured {duplicate: True, ...} dict
                failed_files.append({
                    "file": file_obj.name,
                    "status": "failed",
                    "reason": e.detail 
                })
            except Exception as e:
                # General error - cleanup physical file if it was created
                if uploaded_path:
                    full_path = os.path.join(settings.MEDIA_ROOT, uploaded_path)
                    if os.path.exists(full_path):
                        os.remove(full_path)

                logger.exception(f"File process failed: {file_obj.name}")
                failed_files.append({
                    "file": file_obj.name,
                    "status": "failed",
                    "reason": str(e)
                })

        return {
            "uploaded": uploaded_files,
            "failed": failed_files
        }

    


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
        NodeFile.objects.filter(vault_file=file_obj).update(status=NodeFile.Status.TRASHED)
        updated = CollectionFile.objects.filter(file=file_obj).update(status=CollectionFile.Status.TRASHED)


    @staticmethod
    def user_archive_file(user, file_id):
        file_obj=get_object_or_404(
            File, user=user, id=file_id, is_deleted=False, is_archive=False
        )
        file_obj.is_archive=True
        file_obj.archived_at=timezone.now()
        file_obj.save(update_fields=['is_archive', 'archived_at'])
        NodeFile.objects.filter(vault_file=file_obj).update(status=NodeFile.Status.ARCHIVED)
        CollectionFile.objects.filter(file=file_obj).update(status=CollectionFile.Status.ARCHIVED)

    @staticmethod
    def bulk_delete_files(user, file_ids):
        if not file_ids or not isinstance(file_ids, list):
            raise ValueError("Provide a valid list of file_ids.")

        files = File.objects.filter(id__in=file_ids, user=user, is_deleted=False)
        NodeFile.objects.filter(vault_file__in=files).update(status=NodeFile.Status.TRASHED)
        CollectionFile.objects.filter(file__in=files).update(status=CollectionFile.Status.TRASHED)
        return files.update(is_deleted=True, deleted_at=timezone.now())

    @staticmethod
    def bulk_archive_files(user, file_ids):
        if not file_ids or not isinstance(file_ids, list):
            raise ValueError("Provide a valid list of file_ids.")
        files = File.objects.filter(id__in=file_ids, user=user, is_deleted=False, is_archive=False)
        NodeFile.objects.filter(vault_file__in=files).update(status=NodeFile.Status.ARCHIVED)
        CollectionFile.objects.filter(file__in=files).update(status=CollectionFile.Status.ARCHIVED)
        return files.update(is_archive=True, archived_at=timezone.now())

    @staticmethod
    def user_unarchive_file(user, file_id):
        file_obj=get_object_or_404(
            File, user=user, id=file_id, is_deleted=False, is_archive=True
        )
        file_obj.is_archive=False
        file_obj.archived_at=None
        file_obj.save(update_fields=['is_archive', 'archived_at'])
        NodeFile.objects.filter(vault_file=file_obj).update(status=NodeFile.Status.ACTIVE)
        CollectionFile.objects.filter(file=file_obj).update(status=CollectionFile.Status.ACTIVE)
        
    @staticmethod
    def get_user_starred_files(user):
        starred_files=File.objects.filter(user=user, is_starred=True, is_deleted=False,  is_archive=False)
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

        CollectionFile.objects.filter(file__in=files).update(status=CollectionFile.Status.TRASHED)
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
    def permanent_delete_file(user, file_id):
        file_obj = get_object_or_404(
            File, user=user, id=file_id, is_deleted=True
        )
        
        # 1. Delete associated records first
        NodeFile.objects.filter(vault_file=file_obj).delete()
        CollectionFile.objects.filter(file=file_obj).delete()
        
        # 2. Release storage quota
        StorageService.release(user.id, file_obj.file_size)
        
        # 3. Delete the physical file
        if file_obj.file:
            file_obj.file.delete(save=False)
            
        # 4. Delete the database record
        file_obj.delete()
        
        return file_obj
    
    @staticmethod
    def user_restore_file(user, file_id):
        file_obj=File.objects.get(user= user, id=file_id)
        file_obj.is_deleted=False
        file_obj.save(update_fields=['is_deleted'])
        NodeFile.objects.filter(vault_file=file_obj).update(status=NodeFile.Status.ACTIVE)
        CollectionFile.objects.filter(file=file_obj).update(status=CollectionFile.Status.ACTIVE)
        return file_obj

    @staticmethod
    def bulk_restore_deleted_files(user, file_ids):
        if not file_ids or not isinstance(file_ids, list):
            raise ValueError("Provide a valid list of file_ids.")
        files = File.objects.filter(id__in=file_ids, user=user, is_deleted=True)
        NodeFile.objects.filter(vault_file__in=files).update(status=NodeFile.Status.ACTIVE)
        CollectionFile.objects.filter(file__in=files).update(status=CollectionFile.Status.ACTIVE)
        return files.update(is_deleted=False)

    @staticmethod
    def empty_user_trash(user):
        with transaction.atomic():
            files = File.objects.filter(user=user, is_deleted=True)
            total_size = files.aggregate(Sum('file_size'))['file_size__sum'] or 0
            count = files.count()
            
            # Permanently delete associated files
            for f in files:
                if f.file:
                    f.file.delete(save=False)
            NodeFile.objects.filter(vault_file__in=files).delete()
            CollectionFile.objects.filter(file__in=files).delete()
            files.delete()
            StorageService.release(user.id, total_size)
            return count

    
    @staticmethod
    def bulk_unarchive_files(user, file_ids):
        if not file_ids or not isinstance(file_ids, list):
            raise ValueError("Provide a valid list of file_ids.")
        files = File.objects.filter(id__in=file_ids, user=user, is_archive=True)
        NodeFile.objects.filter(vault_file__in=files).update(status=NodeFile.Status.ACTIVE)
        CollectionFile.objects.filter(file__in=files).update(status=CollectionFile.Status.ACTIVE)
        return files.update(is_archive=False, archived_at=None)

    @staticmethod
    def get_recent_files(user):
        return File.objects.filter(user=user, is_deleted=False, is_archive=False).order_by('-last_accessed')[:9]

    @staticmethod
    def _compute_checksum(file) -> str:
        """SHA-256 checksum of an in-memory/uploaded file. Rewinds the file pointer after reading."""
        hasher = hashlib.sha256()
        file.seek(0)
        for chunk in file.chunks():
            hasher.update(chunk)
        file.seek(0)
        return hasher.hexdigest()

    @staticmethod
    def vault_upload(user, file, original_name=None) -> File:
        checksum = FileService._compute_checksum(file)
        
        # Detect real content type via magic
        file.seek(0)
        file_bytes = file.read(2048)
        file.seek(0)
        detected_type = magic.from_buffer(file_bytes, mime=True)

        # Claim storage for the user
        StorageService.claim(user.id, file.size)

        # Create the vault file (main storage)
        vault_file = File.objects.create(
            user=user,
            file=file,
            original_name=original_name or file.name,
            file_size=file.size,
            content_type=detected_type,
            checksum=checksum,
        )

        file.seek(0)
        return vault_file
        
 
    @staticmethod
    def upload(node: ProjectNode, user, file) -> NodeFile:
        # Calculate checksum to check for existing file in main storage
        checksum = FileService._compute_checksum(file)
        existing_file = File.objects.filter(user=user, checksum=checksum, is_deleted=False).first()

        # 1. Determine names
        vault_filename = file.name
        node_filename = file.name

        if existing_file:
            name, ext = os.path.splitext(file.name)
            # Temporary name for vault creation to avoid confusion
            # The actual renaming format filename_node_file-d (where -d is node/file details)
            suffix = f"_node_{node.id}"
            vault_filename = f"{name}{suffix}{ext}"
            node_filename = vault_filename

        # 2. Add to main storage (Vault) and claim storage
        vault_file = FileService.vault_upload(user, file, original_name=vault_filename)

        # 3. If it was a duplicate, we update the name to include file ID as well if needed
        if existing_file:
            name, ext = os.path.splitext(vault_filename)
            final_name = f"{name}_{vault_file.id}{ext}"
            vault_file.original_name = final_name
            vault_file.save(update_fields=["original_name"])
            node_filename = final_name

        # 4. Add to node storage
        node_file = NodeFile.objects.create(
            node=node,
            file=vault_file.file,
            original_name=node_filename,
            uploaded_by=user,
            vault_file=vault_file,
        )

        # Inline impact propagation (no Celery — synchronous for now)
        FileService._propagate_impact(node, user)

        NodeActivity.objects.create(
            node=node,
            actor=user,
            event_type=NodeActivity.EventType.FILE_UPLOADED,
            message=f'"{node_filename}" uploaded to "{node.title}".',
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
        vault_file = node_file.vault_file
        
        # 1. Delete the main storage file if it exists
        if vault_file:
            StorageService.release(user.id, vault_file.file_size)
            vault_file.file.delete(save=False)
            vault_file.delete()

        # 2. Delete the node file record and physical file
        node_file.file.delete(save=False)
        node_file.delete()
        
        FileService._propagate_impact(node, user)
        NodeActivity.objects.create(
            node=node,
            actor=user,
            event_type=NodeActivity.EventType.FILE_DELETED,
            message=f'"{name}" deleted from "{node.title}".',
        )
        
from django.db.models import Sum, Count, Q
from django.core.exceptions import PermissionDenied
from .models import Collection, CollectionFile, File


class CollectionService:
    @staticmethod
    def get_user_collections(user):
        return (
            Collection.objects.filter(user=user)
            .annotate(
                total_files=Count(
                    "collection_files__file__id",
                    filter=Q(
                        collection_files__status=CollectionFile.Status.ACTIVE,
                        collection_files__file__is_deleted=False,
                        collection_files__file__is_archive=False
                    ),
                    distinct=True
                ),
                total_size=Sum(
                    "collection_files__file__file_size",
                    filter=Q(
                        collection_files__status=CollectionFile.Status.ACTIVE,
                        collection_files__file__is_deleted=False,
                        collection_files__file__is_archive=False
                    )
                ),
            )
            .order_by("-created_at")
        )

    @staticmethod
    def get_single_collection(user, collection_id):
        """Return a single collection with annotations. Raises if not found or not owner."""
        try:
            return (
                Collection.objects.filter(user=user)
                .annotate(
                    total_files=Count(
                        "collection_files__file",
                        filter=Q(
                            collection_files__status=CollectionFile.Status.ACTIVE,
                            collection_files__file__is_deleted=False,
                            collection_files__file__is_archive=False
                        ),
                        distinct=True
                    ),
                    total_size=Sum(
                        "collection_files__file__file_size",
                        filter=Q(
                            collection_files__status=CollectionFile.Status.ACTIVE,
                            collection_files__file__is_deleted=False,
                            collection_files__file__is_archive=False
                        )
                    ),
                )
                .get(id=collection_id)
            )
        except Collection.DoesNotExist:
            raise DRFValidationError("Collection not found.")

    @staticmethod
    def create_collection(user, validated_data):
        """Create a new collection for the user."""
        try:
            return Collection.objects.create(user=user, **validated_data)
        except IntegrityError:
            raise ValidationError({
                "name": ["You already have a collection with this name."]
            })

    @staticmethod
    def update_collection(user, collection_id, validated_data):
        """Update name or description of a collection."""
        try:
            collection = Collection.objects.get(id=collection_id, user=user)
        except Collection.DoesNotExist:
            raise DRFValidationError("Collection not found.")

        for attr, value in validated_data.items():
            setattr(collection, attr, value)
        try:
            collection.save()
        except IntegrityError:
            raise DRFValidationError({
                "name": ["A collection with this name already exists."]
            })
        return collection


    @staticmethod
    def delete_collection(user, collection_id):
        """Hard delete a collection. Cascades to CollectionFile rows."""
        try:
            collection = Collection.objects.get(id=collection_id, user=user)
        except Collection.DoesNotExist:
            raise DRFValidationError("Collection not found.")
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
            raise DRFValidationError("Collection not found.")

        try:
            file = File.objects.get(id=file_id, user=user)
        except File.DoesNotExist:
            raise DRFValidationError("File not found.")

        collection_file, created = CollectionFile.objects.get_or_create(
            collection=collection,
            file=file,
            defaults={"added_by": user},
        )

        if not created:
            raise DRFValidationError("This file is already in the collection.")

        return collection_file
    
    
    @staticmethod
    def get_collection_files(user, collection_id):
        """Return all files inside a collection. Validates ownership."""
        try:
            collection = Collection.objects.get(id=collection_id, user=user)
        except Collection.DoesNotExist:
            raise DRFValidationError("Collection not found.")
        
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
            raise DRFValidationError("Collection not found.")

        deleted_count, _ = CollectionFile.objects.filter(
            collection=collection, file__id=file_id
        ).delete()

        if deleted_count == 0:
            raise DRFValidationError("File not found in this collection.")  
    
class FileShareService:
    """
    service handles the file sharing business logic
    """
    @staticmethod
    def generate_share_token():
        return secrets.token_urlsafe(32)

    @staticmethod
    def create_share_token(file_id, owner, recipient_email, expiration_datetime, title, message, schedule_at=None,
                           permission='view_only', download_limit=None, view_limit=None):
        """
        Creates a file share link for a single file.
        """
        try:
            file = File.objects.get(id=file_id, user=owner)
        except File.DoesNotExist:
            raise ValueError("File not found or you don't have the permission")
        
        share_token = FileShareService.generate_share_token()
        expiration_datetime = timezone.now() + timedelta(hours=expiration_datetime)

        share = FileShareLink.objects.create(
            file=file,
            owner=owner,
            recipient_email=recipient_email.lower(),
            share_token=share_token,
            expiration_datetime=expiration_datetime,
            permission=permission,
            download_limit=download_limit,
            view_limit=view_limit
        )

        if schedule_at:
            from .models import ScheduledMail
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
    def send_bulk_share_email(bundle_id):
        from .models import ShareBundle, FileShareLink
        try:
            bundle = ShareBundle.objects.select_related('owner', 'owner__designation').get(id=bundle_id)
            share_links = FileShareLink.objects.filter(bundle=bundle).order_by('created_at')
            sent_to = set()

            for share in share_links:
                if share.recipient_email in sent_to:
                    continue
                sent_to.add(share.recipient_email)

                owner = bundle.owner
                sender_name = owner.get_full_name() or owner.email
                designation = get_sender_designation(owner)
                package_title = bundle.title or 'Shared file package'
                subject = f"File shared with you: {package_title}"
                share_url = f"{settings.FRONTEND_BASE_URL}/files/public/{share.share_token}/"
                expires_on = bundle.expiration_datetime.strftime('%B %d, %Y at %I:%M %p')
                file_count = bundle.items.count()

                plain_body = (
                    f"Hi,\n\n"
                    f"{sender_name} shared a ZIP package with you.\n\n"
                    f"Package: {package_title}\n"
                    f"Files: {file_count}\n"
                    f"Expires: {expires_on}\n\n"
                    f"Open the HTML version of this email and use the download button to access your files."
                )
                if designation:
                    plain_body = plain_body.replace(
                        f"{sender_name} shared",
                        f"{sender_name} ({designation}) shared",
                        1,
                    )

                html_content = build_bulk_share_email_html(
                    package_title=package_title,
                    file_count=file_count,
                    sender_name=sender_name,
                    sender_email=owner.email,
                    sender_designation=designation,
                    personal_message=bundle.message,
                    cta_url=share_url,
                    expires_on=expires_on,
                )

                send_templated_email(
                    subject,
                    plain_body,
                    settings.DEFAULT_FROM_EMAIL,
                    [share.recipient_email],
                    content_html=html_content,
                )
            return True
        except Exception as e:
            logger.error(f"Error sending bulk share email: {e}")
            return False

    @staticmethod
    @transaction.atomic
    def create_bulk_share(
        owner,
        file_ids,
        recipient_emails,
        expiration_datetime,
        permission,
        title='',
        message='',
        download_limit=None,
        view_limit=None
    ):

        files = File.objects.filter(
            id__in=file_ids,
            user=owner
        )

        if files.count() != len(file_ids):
            raise ValueError(
                "Some files are invalid or inaccessible."
            )

        token = FileShareService.generate_share_token()

        expiration_datetime = (
            timezone.now() +
            timedelta(hours=expiration_datetime)
        )

        from .models import ShareBundle, ShareBundleItem, BundleRecipient
        bundle = ShareBundle.objects.create(
            owner=owner,
            share_token=token,
            title=title,
            message=message,
            permission=permission,
            expiration_datetime=expiration_datetime,
            download_limit=download_limit,
            view_limit=view_limit
        )

        # ---------------------------------
        # BULK INSERT FILES
        # ---------------------------------

        bundle_items = [
            ShareBundleItem(
                bundle=bundle,
                file=file
            )
            for file in files
        ]
        ShareBundleItem.objects.bulk_create(bundle_items)

        # One share link per recipient (whole package), not one per file.
        primary_file = files.first()
        from .models import FileShareLink
        FileShareLink.objects.bulk_create([
            FileShareLink(
                bundle=bundle,
                file=primary_file,
                owner=owner,
                recipient_email=email.lower(),
                share_token=FileShareService.generate_share_token(),
                expiration_datetime=expiration_datetime,
                permission=permission,
                download_limit=download_limit,
                view_limit=view_limit,
            )
            for email in recipient_emails
        ])

        # ---------------------------------
        # ZIP FILE CREATION
        # ---------------------------------
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for item in bundle_items:
                file_obj = item.file
                if file_obj.file:
                    file_name = file_obj.original_name or os.path.basename(file_obj.file.name)
                else:
                    # In case of local files or other scenarios where f.file is not a FieldFile
                    file_name = file_obj.original_name or f"file_{file_obj.id}"
                
                try:
                    with file_obj.file.open('rb') as f:
                        zip_file.writestr(file_name, f.read())
                except Exception as e:
                    logger.error(f"Failed to add file {file_obj.id} to zip: {e}")

        zip_content = zip_buffer.getvalue()
        zip_filename = f"share_bundle_{bundle.share_token[:8]}.zip"
        bundle.zip_file.save(zip_filename, ContentFile(zip_content), save=True)

        # Bulk share always sends immediately (not via ScheduledMail).
        import threading
        threading.Thread(
            target=FileShareService.send_bulk_share_email,
            args=(bundle.id,),
        ).start()

        return bundle

    @staticmethod
    def send_share_email(share, message, title=None):
        """
        send email
        """
        owner = share.owner
        sender_name = owner.get_full_name() or owner.email
        designation = get_sender_designation(owner)
        email_subject = f"{sender_name} shared '{share.file.original_name}' with you"
        share_url = f"{settings.FRONTEND_BASE_URL}/files/public/{share.share_token}/"
        expires_on = share.expiration_datetime.strftime('%B %d, %Y at %I:%M %p')
        file_size_mb = share.file.file_size / (1024 * 1024)

        plain_body = (
            f"Hi,\n\n"
            f"{sender_name} has shared a file with you.\n\n"
            f"File: {share.file.original_name}\n"
            f"Size: {file_size_mb:.2f} MB\n"
        )
        if title and title.strip():
            plain_body += f"Title: {title.strip()}\n"
        if message and message.strip():
            plain_body += f"Message: {message.strip()}\n"
        plain_body += (
            f"Expires: {expires_on}\n\n"
            f"Open the HTML version of this email and use the button to access the file.\n\n"
            f"This link is personal. Recipient: {share.recipient_email}"
        )
        if designation:
            plain_body = plain_body.replace(
                f"{sender_name} has shared",
                f"{sender_name} ({designation}) has shared",
                1,
            )

        html_content = build_file_share_email_html(
            share_title=title or '',
            file_name=share.file.original_name,
            file_size_mb=file_size_mb,
            sender_name=sender_name,
            sender_email=owner.email,
            sender_designation=designation,
            personal_message=message,
            cta_url=share_url,
            expires_on=expires_on,
            recipient_email=share.recipient_email,
        )

        try:
            send_templated_html_mail(
                subject=email_subject,
                plain_message=plain_body,
                content_html=html_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[share.recipient_email],
                fail_silently=False,
            )
            return True
        except Exception as e:
            logger.error("Error sending file share email | share_id=%s | error=%s", share.id, str(e))
            return False


    @staticmethod
    def get_user_shares(user):
        shares=FileShareLink.objects.filter(owner=user).select_related('file', 'bundle')
        return shares

    @staticmethod
    def revoke_share(file_share_id, owner):
        try:
            file_share = FileShareLink.objects.get(id=file_share_id, owner=owner, accessed=False)
        except FileShareLink.DoesNotExist:
            raise ValueError("You haven't made this share or you don't have the permission")

        now = timezone.now()
        if file_share.bundle_id:
            bundle = file_share.bundle
            FileShareLink.objects.filter(bundle=bundle, owner=owner).update(
                revoked_at=now,
                is_active=False,
            )
            bundle.is_active = False
            bundle.save(update_fields=['is_active'])
        else:
            file_share.revoked_at = now
            file_share.is_active = False
            file_share.save(update_fields=['revoked_at', 'is_active'])
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
    def enforces_access_limits(share):
        """Standard immediate single-file shares use view/download limits; zip bundles and scheduled delivery do not."""
        from .models import FileShareLink, ShareBundle, ScheduledMail

        if isinstance(share, ShareBundle):
            return False
        if getattr(share, 'bundle_id', None):
            return False
        return not ScheduledMail.objects.filter(
            share=share,
            status=ScheduledMail.Status.SENT,
        ).exists()

    @staticmethod
    def get_public_share_type(share):
        from .models import ShareBundle, ScheduledMail

        if isinstance(share, ShareBundle) or getattr(share, 'bundle_id', None):
            return 'zip_bundle'
        if ScheduledMail.objects.filter(
            share=share,
            status=ScheduledMail.Status.SENT,
        ).exists():
            return 'scheduled'
        return 'standard'

    @staticmethod
    def _get_bundle_from_share(share):
        from .models import ShareBundle

        if isinstance(share, ShareBundle):
            return share
        if getattr(share, 'bundle_id', None):
            return share.bundle
        return None

    @staticmethod
    def _mark_bundle_package_accessed(bundle, accessed_at=None, mark_download=False):
        """When a bundle link is used, mark every share link in the package as accessed."""
        from .models import FileShareLink

        if bundle is None:
            return

        now = accessed_at or timezone.now()
        link_updates = {'accessed': True, 'accessed_at': now}
        if mark_download:
            link_updates['download_count'] = bundle.download_count or 0

        FileShareLink.objects.filter(bundle=bundle).update(**link_updates)

        if bundle.accessed_at is None:
            bundle.accessed_at = now
            bundle.save(update_fields=['accessed_at'])

    @staticmethod
    def build_public_metadata(share):
        from .models import ShareBundle, ScheduledMail

        owner = share.owner
        sender_name = owner.get_full_name() or owner.email
        share_type = ViewFileShareService.get_public_share_type(share)
        enforces_limits = ViewFileShareService.enforces_access_limits(share)
        is_bundle = share_type == 'zip_bundle'

        scheduled_mail = None
        if share_type == 'scheduled':
            scheduled_mail = (
                ScheduledMail.objects.filter(
                    share=share,
                    status=ScheduledMail.Status.SENT,
                )
                .order_by('-sent_at')
                .first()
            )

        if not is_bundle and hasattr(share, 'file') and share.file:
            file_name = share.file.original_name
            file_size = share.file.file_size
            content_type = share.file.content_type
            accessed = getattr(share, 'accessed', False)
            file_count = 1
        else:
            bundle_obj = getattr(share, 'bundle', None) or share
            file_name = getattr(bundle_obj, 'title', '') or 'Shared file package'
            file_count = bundle_obj.items.count() if hasattr(bundle_obj, 'items') else 0
            file_size = (
                sum(item.file.file_size for item in bundle_obj.items.all())
                if hasattr(bundle_obj, 'items')
                else 0
            )
            content_type = 'application/zip'
            accessed = (
                getattr(share, 'accessed', False)
                if not isinstance(share, ShareBundle)
                else (share.download_count > 0)
            )

        bundle_obj = getattr(share, 'bundle', None) or (
            share if isinstance(share, ShareBundle) else None
        )

        if isinstance(share, ShareBundle):
            accessed_at = share.accessed_at
        else:
            accessed_at = getattr(share, 'accessed_at', None)

        return {
            'share_type': share_type,
            'enforces_limits': enforces_limits,
            'is_bundle': is_bundle,
            'file_name': file_name,
            'file_size': file_size,
            'content_type': content_type,
            'file_count': file_count,
            'sender': sender_name,
            'sender_name': sender_name,
            'sender_email': owner.email,
            'expiration': share.expiration_datetime,
            'expiration_datetime': share.expiration_datetime,
            'permission': share.permission,
            'accessed': accessed,
            'accessed_at': accessed_at,
            'is_active': getattr(share, 'is_active', True),
            'view_limit': share.view_limit if enforces_limits else None,
            'view_count': share.view_count if enforces_limits else None,
            'download_limit': share.download_limit if enforces_limits else None,
            'download_count': share.download_count if enforces_limits else None,
            'bundle_title': getattr(bundle_obj, 'title', '') or '' if bundle_obj else '',
            'bundle_message': getattr(bundle_obj, 'message', '') or '' if bundle_obj else '',
            'is_scheduled_delivery': share_type == 'scheduled',
            'scheduled_for': scheduled_mail.scheduled_for if scheduled_mail else None,
            'scheduled_title': scheduled_mail.title if scheduled_mail else '',
            'scheduled_message': scheduled_mail.message if scheduled_mail else '',
            'delivered_at': scheduled_mail.sent_at if scheduled_mail else None,
        }

    def get_share_or_404(token, action=None):
            """
            Look up the token in FileShareLink first, then ShareBundle.
            Attaches an `is_bundle` flag so the view knows which type it got.
            Raises Http404 if not found, or ValueError if expired/revoked/limits exceeded.
            action-aware: only validates the limit relevant to the current action.
            """
            from .models import FileShareLink, ShareBundle
            from django.http import Http404

            # Try single-file or bundle-based share link
            try:
                share = FileShareLink.objects.select_related('file', 'owner', 'bundle').get(
                    share_token=token
                )
                if not share.is_active and share.revoked_at:
                    raise ValueError("This share link has been revoked.")
                enforces = ViewFileShareService.enforces_access_limits(share)
                if enforces and share.permission == "one_time_download" and not share.is_active:
                    raise ValueError("This share link has already been used.")
                
                if share.expiration_datetime and share.expiration_datetime < timezone.now():
                    raise ValueError("This share link has expired.")

                if enforces:
                    if action == 'view':
                        if share.view_limit and share.view_count >= share.view_limit:
                            raise ValueError("View limit reached for this share.")
                    elif action == 'download':
                        if share.download_limit and share.download_count >= share.download_limit:
                            raise ValueError("Download limit reached for this share.")

                share.is_bundle = True if share.bundle else False
                if action == 'view' and share.is_bundle:
                    raise ValueError("This package can only be downloaded as a ZIP file.")
                return share

            except FileShareLink.DoesNotExist:
                pass

            # Try bundle share
            try:
                bundle = ShareBundle.objects.select_related('owner').get(
                    share_token=token
                )
                if not bundle.is_active:
                    raise ValueError("This share link has been revoked.")
                if bundle.expiration_datetime and bundle.expiration_datetime < timezone.now():
                    raise ValueError("This share link has expired.")

                if action == 'view':
                    raise ValueError("This package can only be downloaded as a ZIP file.")

                bundle.is_bundle = True
                return bundle

            except ShareBundle.DoesNotExist:
                pass

            raise Http404("Share link not found.")

    @staticmethod
    def increment_access_counts(share, action):
        """Increment only the relevant count based on action, and deactivate link only when all limits are exhausted."""

        if action == 'view':
            share.view_count = (share.view_count or 0) + 1
            fields_to_save = ['view_count']
            share.save(update_fields=fields_to_save)

            if hasattr(share, 'bundle') and share.bundle:
                bundle = share.bundle
                bundle.view_count = (bundle.view_count or 0) + 1
                bundle.save(update_fields=['view_count'])

        elif action == 'download':
            from .models import ShareBundle

            share.download_count = (share.download_count or 0) + 1
            share.save(update_fields=['download_count'])

            bundle = ViewFileShareService._get_bundle_from_share(share)
            if bundle is not None:
                if not isinstance(share, ShareBundle) and getattr(share, 'bundle_id', None):
                    bundle.download_count = (bundle.download_count or 0) + 1
                    bundle.save(update_fields=['download_count'])
                ViewFileShareService._mark_bundle_package_accessed(
                    bundle,
                    mark_download=True,
                )

        # ── Deactivation check (runs after either action) ──────────────────────
        if not ViewFileShareService.enforces_access_limits(share):
            return

        # One-time download: deactivate immediately after first download
        if share.permission == 'one_time_download' and action == 'download':
            share.accessed = True
            share.is_active = False
            share.accessed_at = timezone.now()
            share.save(update_fields=['accessed', 'is_active', 'accessed_at'])
            return

        # For all other permissions: only deactivate when BOTH limits are exhausted.
        # A limit of None means unlimited — treat it as not reached.
        view_exhausted = share.view_limit is not None and share.view_count >= share.view_limit
        download_exhausted = share.download_limit is not None and share.download_count >= share.download_limit

        # If a side has no limit set, don't count it as a blocking condition
        view_blocks = share.view_limit is not None and view_exhausted
        download_blocks = share.download_limit is not None and download_exhausted

        # Only deactivate if every limit that EXISTS is exhausted
        limits_exist = share.view_limit is not None or share.download_limit is not None
        all_exhausted = (share.view_limit is None or view_exhausted) and \
                        (share.download_limit is None or download_exhausted)

        if limits_exist and all_exhausted:
            share.accessed = True
            share.is_active = False
            share.accessed_at = timezone.now()
            share.save(update_fields=['accessed', 'is_active', 'accessed_at'])

        # Bundle deactivation: same logic
        if hasattr(share, 'bundle') and share.bundle:
            bundle = share.bundle
            b_view_exhausted = bundle.view_limit is not None and bundle.view_count >= bundle.view_limit
            b_download_exhausted = bundle.download_limit is not None and bundle.download_count >= bundle.download_limit
            b_limits_exist = bundle.view_limit is not None or bundle.download_limit is not None
            b_all_exhausted = (bundle.view_limit is None or b_view_exhausted) and \
                            (bundle.download_limit is None or b_download_exhausted)

            if b_limits_exist and b_all_exhausted:
                bundle.is_active = False
                bundle.save(update_fields=['is_active'])

    @staticmethod
    def get_file_response(share):
        return share.file.file.open("rb"), share.file.original_name

    @staticmethod
    def get_zip_response(share):
        """Return the zip file and filename for a ShareBundle or bundle-based FileShareLink."""
        target = share.bundle if hasattr(share, 'bundle') and share.bundle else share
        if not target.zip_file:
            raise ValueError("No zip file available for this bundle.")
        return target.zip_file.open("rb"), f"{target.title or 'shared_files'}.zip"

    @staticmethod
    def record_link_opened(share):
        """Set accessed_at the first time a recipient opens the public share URL (metadata GET)."""
        from .models import ShareBundle

        now = timezone.now()
        bundle = ViewFileShareService._get_bundle_from_share(share)

        if bundle is not None:
            if isinstance(share, ShareBundle):
                if share.accessed_at is None:
                    share.accessed_at = now
                    share.save(update_fields=['accessed_at'])
            elif share.accessed_at is None:
                share.accessed_at = now
                update_fields = ['accessed_at']
                if share.permission != 'one_time_download':
                    share.accessed = True
                    update_fields.append('accessed')
                share.save(update_fields=update_fields)

            ViewFileShareService._mark_bundle_package_accessed(bundle, accessed_at=now)
            return share

        if share.accessed_at is None:
            share.accessed_at = now
            update_fields = ['accessed_at']
            # One-time links: only mark accessed after download, not on page open.
            if share.permission != 'one_time_download':
                share.accessed = True
                update_fields.append('accessed')
            share.save(update_fields=update_fields)
        return share

    @staticmethod
    def mark_as_accessed(share):
        return ViewFileShareService.record_link_opened(share)

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
        
        if timeline == 'monthly':
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
                "file_name": share.file.original_name if share.file else (
                    share.bundle.title or "Bulk Share Package"
                ),
                "recipient": share.recipient_email,
                "status": "shared",
                "sent_at": localtime(share.created_at),
                "sort_time": share.created_at,
                "accessed": share.accessed,
                "accessed_at": share.accessed_at
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
                "accessed_at": share.accessed_at
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
            "Share type",
            "File name",
            "Recipient",
            "Status",
            "Sent at",
            "Accessed"
        ])

        for row in data:
            writer.writerow([
                row["type"],
                row["file_name"],
                row["recipient"],
                row["status"],
                row["sent_at"].strftime("%d %b %Y, %I:%M %p"),
                "Yes" if row["accessed"] else "No"
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
        
        # Next Report In (Remaining days in current month)
        import calendar
        last_day = calendar.monthrange(now.year, now.month)[1]
        next_report_days = max(0, last_day - now.day)
        
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
            expiration_datetime__gt=now,
            file__isnull=False
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
            
        recent_shares = FileShareLink.objects.filter(owner=user, file__isnull=False).select_related('file').order_by('-created_at')[:5]
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
            
            # Create a default stage
            stage1 = ProjectStage.objects.create(thread=thread, name="Stage 1")
            
            # Auto-create the root node
            root = ProjectNode.objects.create(
                thread=thread,
                title=thread.title,
                description="Project root node",
                created_by=user,
                stage=stage1,
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
        """Return all nodes, dependency edges, and stages for ReactFlow."""
        nodes = ProjectNode.objects.filter(thread_id=thread_id, is_deleted=False)
        node_ids = nodes.values_list("id", flat=True)
        edges = NodeDependency.objects.filter(
            source_node_id__in=node_ids,
            target_node_id__in=node_ids,
        )
        stages = ProjectStage.objects.filter(thread_id=thread_id)
        return {"nodes": nodes, "edges": edges, "stages": stages}

    @staticmethod
    def delete_thread(user, thread_id):

        thread = get_object_or_404(
            ProjectThread,
            id=thread_id,
            created_by=user
        )
        
        # Cleanly delete all nodes and their files (releasing storage)
        nodes = ProjectNode.objects.filter(thread=thread)
        for node in nodes:
            node_files = NodeFile.objects.filter(node=node)
            for node_file in node_files:
                FileService.delete_file(node_file, user)
            node.delete()

        thread.delete()
        return True


class StageService:

    @staticmethod
    def create_stage(thread, validated_data: dict, user) -> ProjectStage:
        stage = ProjectStage.objects.create(
            thread=thread,
            name=validated_data["name"],
        )
        root = (
            ProjectNode.objects.filter(thread=thread, is_deleted=False)
            .order_by("created_at", "id")
            .first()
        )
        if root:
            NodeActivity.objects.create(
                node=root,
                actor=user,
                event_type=NodeActivity.EventType.CREATED,
                message=f'Stage "{stage.name}" created.',
            )
        return stage

    @staticmethod
    def delete_stage(stage: ProjectStage, user) -> str:
        """Delete a stage if it has no active nodes. Returns the stage name."""
        node_count = ProjectNode.objects.filter(stage=stage, is_deleted=False).count()
        if node_count > 0:
            raise DRFValidationError(
                {
                    "detail": (
                        f'Cannot delete stage "{stage.name}" because it still contains '
                        f"{node_count} active node(s)."
                    )
                }
            )
        name = stage.name
        stage.delete()
        return name
 
 
# ─── Node ─────────────────────────────────────────────────────────────────────
 
class NodeService:

    @staticmethod
    def is_root_node(node: ProjectNode) -> bool:
        """Root node: auto-created with the thread (first node), or id matches thread id."""
        if node.id == node.thread_id:
            return True
        root_id = (
            ProjectNode.objects.filter(thread_id=node.thread_id, is_deleted=False)
            .order_by("created_at", "id")
            .values_list("id", flat=True)
            .first()
        )
        return root_id == node.id
 
    @staticmethod
    def add_node(thread: ProjectThread, user, validated_data: dict) -> ProjectNode:
        """Create a child node and log the activity."""
        # Auto-position: offset from parent if given
        parent = validated_data.get("parent_node")
        if parent and not validated_data.get("stage"):
            # Try to find the next stage in the sequence
            current_stage = parent.stage
            next_stage = ProjectStage.objects.filter(
                thread=thread, 
                created_at__gt=current_stage.created_at
            ).order_by('created_at').first()
            
            if next_stage:
                validated_data["stage"] = next_stage
            else:
                # If no next stage exists, stay in current stage or we could create one,
                # but better to stick to current if we don't know the name.
                validated_data["stage"] = current_stage
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
        # Try to find the next stage
        current_stage = parent_node.stage
        next_stage = ProjectStage.objects.filter(
            thread=thread, 
            created_at__gt=current_stage.created_at
        ).order_by('created_at').first()
        
        validated_data["stage"] = next_stage if next_stage else current_stage
        
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
        if NodeService.is_root_node(node):
            raise DRFValidationError(
                {"detail": "The root node cannot be deleted. It is required for this thread."}
            )

        with transaction.atomic():
            node_title = node.title 
            node_id = node.id
 
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
            node.delete()
 
            if downstream_ids:
                ProjectNode.objects.filter(id__in=downstream_ids).update(
                    status=ProjectNode.Status.BLOCKED
                )
 

 
    @staticmethod
    def update_position(node: ProjectNode, stage_id: int, row: int):
        """Quick positional update from canvas drag — no activity log needed."""
        if stage_id:
            node.stage_id = stage_id
        node.row = row
        node.save(update_fields=["stage", "row"])
 
 
# ─── Dependency ───────────────────────────────────────────────────────────────
 
class DependencyService:
    @staticmethod
    def get_target_node(target_id, thread) -> ProjectNode:
        try:
            return ProjectNode.objects.get(
                pk=target_id,
                thread=thread,
                is_deleted=False,
            )
        except ProjectNode.DoesNotExist:
            raise DRFValidationError(
                {"detail": "Target node not found or belongs to a different thread."}
            )

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
        source.refresh_from_db()
        if source.id == target.id:
            raise DRFValidationError("A node cannot depend on itself.")

        if source.thread_id != target.thread_id:
            raise DRFValidationError("Nodes must belong to the same thread to create a dependency.")

        if NodeDependency.objects.filter(source_node=source, target_node=target).exists():
            raise DRFValidationError(f"A dependency already exists from \"{source.title}\" to \"{target.title}\".")

        if DependencyService._has_cycle(source.id, target.id):
            raise DRFValidationError("Adding this dependency would create a circular reference (cycle).")

        if source.status == ProjectNode.Status.INACTIVE:
            raise DRFValidationError("Cannot create a dependency from an inactive node.")

        if source.status == ProjectNode.Status.BLOCKED:
            raise DRFValidationError("Cannot create a dependency from a blocked node.")
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