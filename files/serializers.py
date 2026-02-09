from .models import User, File
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.db import models

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