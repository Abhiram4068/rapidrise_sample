from .models import User, File, FileShareLink
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.db import models
from django.utils import timezone
from datetime import timedelta

class RegisterSerializer(serializers.ModelSerializer):
    confirm_password=serializers.CharField(write_only=True, min_length=8)
    class Meta:
        model=User
        fields=[
            'email',
            'first_name',
            'last_name',
            'date_of_birth',
            'password',
            'confirm_password'
        ]
        extra_kwargs={
            'password':{'write_only':True, 'min_length':8},
            'last_name':{'required':False, 'allow_blank':True},
            'date_of_birth':{'required':False}
        }
    def validate_email(self, value):
        return value.lower().strip()
    def validate(self, attrs):
        password=attrs.get('password')
        confirm_password=attrs.get('confirm_password')
        # print(password, confirm_password)
        if password!=confirm_password:
            raise serializers.ValidationError(
                {'confirm_password':'Passwords do not match'}
            )
        validate_password(password)
        attrs.pop('confirm_password')
        return attrs
    
class LoginSerializer(serializers.Serializer):
    email=serializers.EmailField(required=True)
    password=serializers.CharField(
        write_only=True,
        required=True
    )
    
    
    """
    file upload serializers
    """
class FileUploadSerialzier(serializers.Serializer):
    files=serializers.ListField(
        child=serializers.FileField(
            max_length=100000000,
            allow_empty_file=False
        ),
        allow_empty=False
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True
    )
    
    def validate_files(self, files):
        max_file_size=100*1024*1024
        
        for file in files:
            if file.size>max_file_size:
                raise serializers.ValidationError(
                    f"File '{file.name} exceeds maximum size of 100MB"
                )
        return files
    
    def validate(self, data):
        user=self.context['request'].user
        files=data.get('files', [])
        
        total_upload_size=sum(file.size for file in files)
        current_usage=File.objects.filter(user=user).aggregate(
            total=models.Sum('file_size')
        )['total'] or 0
        
        max_storage=1 * 1024 * 1024 * 1024 
        if total_upload_size+current_usage>max_storage:
            available_storage=max_storage-current_usage
            raise serializers.ValidationError(
                f"Insufficient storage space. Only {available_storage} left. Try deleting some files!"
            )
        return data

class FilesListSerializer(serializers.ModelSerializer):
    class Meta:
        model=File
        fields=[
            'id',
            'original_name',
            'file_size',
            'content_type',
            'description',
            'created_at'
        ]

class FileShareCreateSerializer(serializers.Serializer):
    recipient_email=serializers.EmailField()
    expiration_datetime=serializers.IntegerField(min_value=1, max_value=168)
    message=serializers.CharField(max_length=500, required=False, allow_blank=True)

    def validate_file_id(self, value):
        request=self.context.get('request')
        try:
            file=File.objects.get(id=value, user=request.user)
        except File.DoesNotExist:
            raise serializers.ValidationError("Files doesnt exist or you dont have the required permission")
        return value
    
    def validate_expiration_datetime(self, value):
        if value < 1:
            raise serializers.ValidationError("Minimum expiration time for the link is 1hr")
        if value > 168:
            raise serializers.ValidationError("Maximum expiration time for the link is 168hrs(7 days)")
        return value
    
class FileShareSerializer(serializers.ModelSerializer):
    """
    serializer for viewing the shared files
    """
    file_name=serializers.CharField(source='files.filename', read_only=True)
    file_size=serializers.IntegerField(source='file.file_size', read_only=True)
    owner_email = serializers.EmailField(source='owner.email', read_only=True)
    is_expired = serializers.SerializerMethodField()
    share_url = serializers.SerializerMethodField()

    class Meta:
        model=FileShareLink
        fields = [
            'id', 'file_name', 'file_size', 'owner_email', 
            'recipient_email', 'created_at', 'expiration_datetime',
            'accessed', 'accessed_at', 'is_active', 'is_expired', 'share_url'
        ]
        read_only_fields = ['id', 'created_at', 'accessed', 'accessed_at']
    def get_is_expired(self, obj):
        return timezone.now().date()>obj.expiration_datetime
    def get_share_url(self, obj):
        request=self.context.get('request')
        if request:
            return request.build_absolute_uri(f'/api/share/{obj.share_token}/')
        return f'/api/share/{obj.share_token}/'