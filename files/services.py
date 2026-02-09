from django.contrib.auth import get_user_model
from .models import User, File
from django.db import transaction, IntegrityError
from rest_framework_simplejwt.tokens import RefreshToken
import hashlib
from typing import List
from django.http import FileResponse
from django.shortcuts import get_object_or_404


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
        
            
    

