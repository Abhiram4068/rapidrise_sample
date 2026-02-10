from django.contrib.auth import get_user_model
from .models import User, File, FileShareLink
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
    

class FileService:
    """
    Handles uploads with checksum-based deduplication,
    secure downloads with ownership validation,
    user-scoped listing, and soft deletion.
    """
    @staticmethod
    @transaction.atomic
    def upload_files(user, files:List, description=None):
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
            uploaded_files.append({
                'id':str(file_instance.id),
                'name':file_instance.original_name,
                "size": file_instance.file_size,
                "content_type": file_instance.content_type,
                "checksum": file_instance.checksum,
                "created_at": file_instance.created_at,
                "is_duplicate": is_duplicate,
            })
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
        all_files=File.objects.filter(user=user, is_deleted=False)
        return all_files

    @staticmethod
    def user_delete_file(user, file_id):
        file_obj=get_object_or_404(
            File, user=user, id=file_id, is_deleted=False
        )
        file_obj.is_deleted=True
        file_obj.save()

    @staticmethod
    def _calculate_checksum(file_obj):
        hash_md5 = hashlib.md5()
        file_obj.seek(0)
        for chunk in file_obj.chunks():
            hash_md5.update(chunk)
        file_obj.seek(0)
        return hash_md5.hexdigest()
        
            
    
class FileShareService:
    """
    service handles the file sharing business logic
    """
    @staticmethod
    def generate_share_token():
        return secrets.token_urlsafe(32)
    @staticmethod
    def create_share_token(file_id, owner, recipient_email, expiration_hours, message):
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

        email_sent=FileShareService.send_share_email(share, message)
        if not email_sent:
            print("Error")
        return share
    @staticmethod
    def send_share_email(share, message):
        """
        send email
        """
        email_subject = f"{share.owner.email} shared '{share.file.original_name}' with you"
        email_body = f"""
        Hi,

        {share.owner.email} has shared a file with you.

        File: {share.file.original_name}
        Size: {share.file.file_size / (1024 * 1024):.2f} MB

        {f'Message from sender: "{message}"' if message else ''}

        Click here to access the file:


        This link will expire on {share.expiration_datetime.strftime('%B %d, %Y')}.

        ⚠️ IMPORTANT: 
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
            print("Error sending file")
            return False


