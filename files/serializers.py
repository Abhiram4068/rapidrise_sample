from .models import User, File, FileShareLink, Collection, CollectionFile, ScheduledMail
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.db import models
from django.utils import timezone
from datetime import timedelta
 
import logging
logger = logging.getLogger(__name__)

class RegisterSerializer(serializers.ModelSerializer):
    confirm_password=serializers.CharField(write_only=True, min_length=8)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
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

class UserProfileSerializer(serializers.ModelSerializer):
    date_joined = serializers.SerializerMethodField()
    total_files = serializers.IntegerField(read_only=True)
    status = serializers.SerializerMethodField(source="is_active", read_only=True) 
    designation = serializers.SerializerMethodField()
    storage_used_bytes=serializers.SerializerMethodField()
    storage_used_bytes=serializers.SerializerMethodField()
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "designation", "date_joined", "total_files", "date_of_birth", "status", "storage_used_bytes"]
        read_only_fields = fields

    def get_date_joined(self, obj):
        return obj.date_joined.strftime("%B %d %Y")

    def get_status(self, obj):
        return "Active" if obj.is_active else "Unactive"

    def get_designation(self, obj):
        return obj.get_designation_display()

    def get_storage_used_bytes(self, obj):
        return obj.storage_used_bytes

class ChangePasswordSerialzier(serializers.Serializer):
    current_password=serializers.CharField(required=True, write_only=True)
    new_password=serializers.CharField(required=True, write_only=True)
    confirm_password=serializers.CharField(required=True, write_only=True)

    def validate_current_password(self, value):
        user=self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Invalid Credentials!!!")
        return value
    def validate(self, data):
        if data["new_password"]!=data["confirm_password"]:
            raise serializers.ValidationError({"confirm_password":"Passwords doesnt match"})

        validate_password(data["new_password"], self.context["request"].user)

        if (self.context["request"].user.check_password(data["new_password"])):
            raise serializers.ValidationError({"new_password": "New password cannot be same as old password"})
        return data

      
class FileUploadSerialzier(serializers.Serializer):
    files=serializers.ListField(
        child=serializers.FileField(
            max_length=100000000,
            allow_empty_file=False
        ),
        allow_empty=False
    )
    
    def validate_files(self, files):
        max_file_size=100*1024*1024
        ALLOWED_CONTENT_TYPES = [
        'image/jpeg',
        'image/png',
        'application/pdf',
        'text/plain',
        'application/msword',
        'application/octet-stream',
        'application/vnd.ms-excel',
        'application/zip',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        
    ]
        
        for file in files:
            print(file.content_type)
            if file.size>max_file_size:
                logger.warning(
                    f"File too large | name={file.name} | size={file.size}"
                )
                raise serializers.ValidationError(
                    f"File '{file.name}' exceeds maximum size of 100MB"
                )
            if file.content_type not in ALLOWED_CONTENT_TYPES:
                logger.warning(
                    f"File type not allowed | name={file.name} | type={file.content_type}"
                )
                raise serializers.ValidationError(
                    f"File '{file.name}' is not allowed"
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
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    updated_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    file_size = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model=File
        fields=[
            'id',
            'original_name',
            'is_starred',
            'file_size',
            'content_type',
            'description',
            'created_at',
            'display_name',
            'deleted_at',
            'is_deleted',
            'updated_at',
            'file_url'
        ]
    def get_file_size(self, obj):
        size = obj.file_size or 0 
        if obj.file_size is None:
            logger.warning(f"File size is None for file {obj.id}")
        kb = 1024
        mb = 1024 * 1024
        gb = 1024 * 1024 * 1024
        if size < kb:
            return f"{size} B"
        elif size < mb:
            return f"{size / kb:.2f} KB"
        elif size < gb:
            return f"{size / mb:.2f} MB"
        else:
            return f"{size / gb:.2f} GB"
    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.url)
        return None


class FileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = File
        fields = ["display_name", "description", "updated_at", "is_starred"]

    def validate_display_name(self, value):
        if value and len(value.strip()) == 0:
            raise serializers.ValidationError("Display name cannot be empty.")
        return value
    
    
class CollectionSerializer(serializers.ModelSerializer):
    total_files = serializers.SerializerMethodField()
    total_size = serializers.SerializerMethodField()

    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    updated_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)

    class Meta:
        model = Collection
        fields = [
            "id",
            "name",
            "description",
            "is_starred",
            "created_at",
            "updated_at",
            "total_files",
            "total_size",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_total_files(self, obj):
        return obj.get_total_files()

    def get_total_size(self, obj):
        return obj.get_total_size()


class CollectionFileSerializer(serializers.ModelSerializer):
    file_name = serializers.CharField(source="file.original_name", read_only=True)
    file_size = serializers.IntegerField(source="file.file_size", read_only=True)
    content_type = serializers.CharField(source="file.content_type", read_only=True)
    display_name=serializers.CharField(source="file.display_name", read_only=True)
    added_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    file_url=serializers.SerializerMethodField()

    class Meta:
        model = CollectionFile
        fields = [
            "id",
            "file_name",
            "file_size",
            "content_type",
            "display_name",
            "added_at",
            "file",
            "file_url"
        ]
        read_only_fields = ["id", "added_at", "file"]
    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.file.url)
        return None

class FileShareCreateSerializer(serializers.Serializer):
    recipient_emails=serializers.ListField(
        child=serializers.EmailField(),
        allow_empty=False
    )
    expiration_datetime=serializers.IntegerField(min_value=1, max_value=168)
    title=serializers.CharField(max_length=500, required=False, allow_blank=True)
    message=serializers.CharField(max_length=500, required=False, allow_blank=True)
    schedule_at = serializers.DateTimeField(required=False)

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

    def validate_schedule_at(self, value):
        if value <= timezone.now():
            raise serializers.ValidationError("Schedule time must be in the future.")
        return value

class FileShareListSerializer(serializers.ModelSerializer):
    file_name=serializers.CharField(source='file.original_name', read_only=True)
    file_size=serializers.IntegerField(source='file.file_size', read_only=True)
    owner_email = serializers.EmailField(source='owner.email', read_only=True)
    recipient_email = serializers.EmailField(read_only=True)
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    expiration_datetime = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    accessed_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    is_active = serializers.SerializerMethodField()
    share_url = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    content_type = serializers.CharField(source='file.content_type', read_only=True)
    file_id = serializers.UUIDField(source='file.id', read_only=True)
    class Meta:
        model = FileShareLink
        fields = [
            'id', 'file_name', 'file_size', 'owner_email', 
            'recipient_email', 'created_at', 'expiration_datetime',
            'accessed_at', 'is_active', 'share_url', 'status', 'content_type', 'revoked_at',
            'file_id'
        ]
    def get_is_active(self, obj):
        return obj.is_active
    def get_share_url(self, obj):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(f'/api/files/public/{obj.share_token}/')
        return f'/api/files/public/{obj.share_token}/'
    def get_status(self, obj):
        now = timezone.now()

        if obj.accessed_at and obj.is_active:
            return "Accessed"

        if obj.expiration_datetime and now > obj.expiration_datetime:
            return "Expired"

        if not obj.is_active and obj.revoked_at:
            return "Revoked"

        return "Active"     

    def get_content_type(self, obj):
        return obj.file.content_type

    def get_file_id(self, obj):
        return obj.file.id
    

class ScheduledMailSerializer(serializers.ModelSerializer):
    # FileShareLink fields via the 'share' FK
    file_name = serializers.CharField(source='share.file.original_name', read_only=True)
    file_size = serializers.IntegerField(source='share.file.file_size', read_only=True)
    owner_email = serializers.EmailField(source='share.owner.email', read_only=True)
    recipient_email = serializers.EmailField(source='share.recipient_email', read_only=True)
    share_token = serializers.CharField(source='share.share_token', read_only=True)
    is_share_active = serializers.BooleanField(source='share.is_active', read_only=True)
    share_url = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    share=serializers.SerializerMethodField()
    accessed_at = serializers.SerializerMethodField()
    expiration_datetime=serializers.CharField(source="share.expiration_datetime", read_only=True)
    class Meta:
        model = ScheduledMail
        fields = [
            'id', 'file_name', 'file_size', 'owner_email', 'recipient_email',
            'title', 'message', 'scheduled_for', 'status','share',
            'sent_at', 'error_message', 'created_at',
            'share_token', 'is_share_active', 'share_url', 'content_type', 'accessed_at','expiration_datetime'
        ]
        read_only_fields = ['id', 'status', 'sent_at', 'error_message', 'created_at']

    def get_share_url(self, obj):
        request = self.context.get('request')
        token = obj.share.share_token
        if request:
            return request.build_absolute_uri(f'/api/files/public/{token}/')
        return f'/api/files/public/{token}/'
    def get_content_type(self, obj):
        return obj.share.file.content_type
    def get_share(self, obj):
        if obj.share.accessed:
            return "Accessed"
        if obj.share.is_active:
            return "Active"
        return "Revoked"
    def get_accessed_at(self, obj):
        return obj.share.accessed_at

class FileShareSerializer(serializers.ModelSerializer):
    """
    serializer for viewing the shared files
    """
    file_name=serializers.CharField(source='file.original_name', read_only=True)
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
        return timezone.now()>obj.expiration_datetime
    def get_share_url(self, obj):
        request=self.context.get('request')
        if request:
            return request.build_absolute_uri(f'/api/files/public/{obj.share_token}/')
        return f'/api/files/public/{obj.share_token}/'
    

class PublicFileSerializer(serializers.Serializer):
    token=serializers.CharField()

    def validate_token(self, value):
        """
        validate whether the share object exists and is active
        """
        try:
            share=FileShareLink.objects.select_related('file').get(
                share_token=value,
                is_active=True
            )
        except FileShareLink.DoesNotExist:
            raise serializers.ValidationError("Invalid or the link have expired")
        if timezone.now() > share.expiration_datetime:
            raise serializers.ValidationError("Share link have expired")
        self.share = share
        return value