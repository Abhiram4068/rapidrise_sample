from .models import User, File, FileShareLink, Collection, CollectionFile, ScheduledMail, ReactivationRequest
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
    
class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower().strip()
    
class ResetPasswordSerializer(serializers.Serializer):
    uid          = serializers.CharField()
    token        = serializers.CharField()
    new_password = serializers.CharField(min_length=8, write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data):
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        
        validate_password(data["new_password"])
        return data


class UserProfileSerializer(serializers.ModelSerializer):
    date_joined = serializers.SerializerMethodField()
    total_files = serializers.IntegerField(read_only=True)
    status = serializers.SerializerMethodField(source="is_active", read_only=True) 
    designation = serializers.SerializerMethodField()
    storage_used_bytes=serializers.SerializerMethodField()
    has_pending_reactivation_request = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "designation", "date_joined", "total_files", "date_of_birth", "status", "account_status", "storage_used_bytes", "has_pending_reactivation_request", "is_staff", "is_superuser"]
        read_only_fields = fields

    def get_date_joined(self, obj):
        return obj.date_joined.strftime("%B %d %Y")

    def get_status(self, obj):
        return "Active" if obj.is_active else "Unactive"

    def get_has_pending_reactivation_request(self, obj):
        return ReactivationRequest.objects.filter(user=obj, is_resolved=False).exists()

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

class ReactivationRequestSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_full_name = serializers.SerializerMethodField()
    designation = serializers.CharField(source='user.designation', read_only=True)

    class Meta:
        model = ReactivationRequest
        fields = ["id", "user_id", "user_email", "user_full_name", "designation", "reason", "created_at", "is_resolved"]
        read_only_fields = ["id", "user_id", "user_email", "user_full_name", "designation", "created_at", "is_resolved"]

    def get_user_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}"

class DeactivateAccountSerializer(serializers.Serializer):
    password = serializers.CharField(required=True, write_only=True)

    def validate_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Password verification failed. Incorrect password.")
        return value

      
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
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'image/webp',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation'
        
    ]
        
        for file in files:
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

class FileViewInlineSerializer(serializers.ModelSerializer):
    class Meta:
        model = File
        fields = ['id', 'original_name', 'content_type']
        read_only_fields = ['id', 'original_name', 'content_type']
class FileShareLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = FileShareLink
        fields = ['id', 'recipient_email', 'is_active', 'expiration_datetime', 'accessed', 'created_at']

class FilesListSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    updated_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    file_size = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    shares = serializers.SerializerMethodField()
    is_starred=serializers.BooleanField(required=False)
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
            'file_url',
            'archived_at',
            'status',
            'shares'
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
    def get_status(self, obj):
        if obj.archived_at:
            return "Archived"
    def get_shares(self, obj):
            active_shares = obj.shares.filter(is_active=True).exclude(
                expiration_datetime__lt=timezone.now()
            )
            return FileShareLinkSerializer(active_shares, many=True).data

    def get_is_starred(self, obj):
        return obj.is_starred


class FileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = File
        fields = ["display_name", "description", "updated_at", "is_starred"]

    def validate_display_name(self, value):
        if value is not None and len(value.strip()) == 0:
            raise serializers.ValidationError(
                "Display name cannot be empty."
            )
        return value
    def validate_description(self, value):
        if value is not None and not value.strip():
            return None
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
    is_starred=serializers.SerializerMethodField()
    
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
            "file_url",
            "is_starred"
        ]
        read_only_fields = ["id", "added_at", "file"]
    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and request:
            return request.build_absolute_uri(obj.file.file.url)
        return None
    def get_is_starred(self, obj):
        return obj.file.is_starred if obj.file else False

class FileShareCreateSerializer(serializers.Serializer):
    recipient_emails=serializers.ListField(
        child=serializers.EmailField(),
        allow_empty=False
    )
    expiration_datetime=serializers.IntegerField(min_value=1, max_value=168)
    title=serializers.CharField(max_length=500, required=False, allow_blank=True)
    message=serializers.CharField(max_length=500, required=False, allow_blank=True)
    schedule_at = serializers.DateTimeField(required=False)
    permission = serializers.ChoiceField(
        choices=['view_only', 'view_download', 'one_time_download', 'full_access'],
        default='view_only'
    )
    download_limit = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True
    )
    view_limit = serializers.IntegerField(min_value=1, required=False, allow_null=True)  

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
    def validate(self, data):
        permission = data.get('permission', 'view_only')

        # one_time_download always forces download_limit to 1
        if permission == 'one_time_download':
            data['download_limit'] = 1
            data['view_limit'] = None

        # download_limit only applies to view_download
        if permission not in ('view_download',):
            data['download_limit'] = None

        # view_limit only applies to view_only and view_download
        if permission not in ('view_only', 'view_download'):
            data['view_limit'] = None

        return data

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

    permission = serializers.CharField(read_only=True)
    download_limit = serializers.IntegerField(read_only=True, allow_null=True)
    
    download_count = serializers.IntegerField(read_only=True)
    downloads_remaining = serializers.SerializerMethodField() 

    view_limit = serializers.IntegerField(read_only=True, allow_null=True)      
    view_count = serializers.IntegerField(read_only=True)                        
    views_remaining = serializers.SerializerMethodField() 
    class Meta:
        model = FileShareLink
        fields = [
            'id', 'file_name', 'file_size', 'owner_email', 
            'recipient_email', 'created_at', 'expiration_datetime',
            'accessed_at', 'is_active', 'share_url', 'status', 'content_type', 'revoked_at',
            'file_id',
            'permission', 'download_limit', 'download_count', 'downloads_remaining', 

            'view_limit', 'view_count', 'views_remaining',  
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
    def get_downloads_remaining(self, obj):
        if obj.permission == 'one_time_download':
            return 0 if obj.download_count >= 1 else 1
        if obj.permission == 'view_download' and obj.download_limit is not None:
            remaining = obj.download_limit - obj.download_count
            return max(remaining, 0)
        return None  

    def get_views_remaining(self, obj):
        if obj.permission in ('view_only', 'view_download') and obj.view_limit is not None:
            return max(obj.view_limit - obj.view_count, 0)
        return None 
    

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
    token = serializers.CharField()

    def validate_token(self, value):
        try:
            share = FileShareLink.objects.select_related('file', 'owner').get(
                share_token=value
            )
        except FileShareLink.DoesNotExist:
            raise serializers.ValidationError("This link is invalid or does not exist.")

        # Priority 1: Check if expired (even if inactive/revoked, expiration is often the primary reason)
        if share.expiration_datetime and share.expiration_datetime < timezone.now():
            raise serializers.ValidationError("This access link has expired.")

        # Priority 2: Check if manually revoked
        if share.revoked_at:
            raise serializers.ValidationError("This access link has been revoked.")

        # Priority 3: Check general activity (e.g. one-time used)
        if not share.is_active:
            if share.permission == 'one_time_download' and share.accessed:
                raise serializers.ValidationError("This one-time link has already been used.")
            raise serializers.ValidationError("This access link is currently inactive.")

        self.share = share
        return value

class ReportQuerySerializer(serializers.Serializer):
    download = serializers.BooleanField(required=False, default=False)
    timeline = serializers.ChoiceField(choices=['weekly', 'monthly'], required=False)
    search = serializers.CharField(required=False, allow_blank=True, default='')

# serializers.py

class StorageByTypeItemSerializer(serializers.Serializer):
    bytes = serializers.IntegerField()
    human = serializers.CharField()
    percentage = serializers.FloatField()


class StorageSummarySerializer(serializers.Serializer):
    storage_limit_bytes = serializers.IntegerField()
    storage_used_bytes = serializers.IntegerField()
    free_storage_bytes = serializers.IntegerField()

    storage_limit_human = serializers.CharField()
    storage_used_human = serializers.CharField()
    free_storage_human = serializers.CharField()

    percentage_used = serializers.DecimalField(max_digits=5, decimal_places=2)
    is_storage_critical = serializers.BooleanField()

    # ← removed storage_by_type field declaration from here

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep["storage_by_type"] = {
            key: StorageByTypeItemSerializer(val).data
            for key, val in instance.get("storage_by_type", {}).items()
        }
        return rep



from rest_framework import serializers
from .models import ProjectThread, ProjectNode, NodeDependency, NodeFile, NodeActivity, ProjectStage


# ─── Thread ───────────────────────────────────────────────────────────────────

class ProjectStageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectStage
        fields = ["id", "thread", "name", "created_at"]
        read_only_fields = ["id", "thread", "created_at"]

class ThreadSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField(read_only=True)
    node_count = serializers.SerializerMethodField()
    file_count = serializers.SerializerMethodField()

    class Meta:
        model = ProjectThread
        fields = ["id", "title", "description", "created_by", "created_at", "node_count", "file_count"]
        read_only_fields = ["id", "created_by", "created_at"]

    def get_node_count(self, obj):
        return obj.nodes.filter(is_deleted=False).count()
    def get_file_count(self, obj):
        from files.models import NodeFile
        return NodeFile.objects.filter(node__thread=obj).count()


class ThreadCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectThread
        fields = ["title", "description"]


# ─── Node ─────────────────────────────────────────────────────────────────────

class NodeSerializer(serializers.ModelSerializer):
    created_by = serializers.StringRelatedField(read_only=True)
    parent_node_id = serializers.PrimaryKeyRelatedField(
        source="parent_node",
        queryset=ProjectNode.objects.all(),
        allow_null=True,
        required=False,
    )
    branch_root_id = serializers.PrimaryKeyRelatedField(
        source="branch_root",
        queryset=ProjectNode.objects.all(),
        allow_null=True,
        required=False,
    )
    file_count = serializers.SerializerMethodField()
    is_branch = serializers.SerializerMethodField()

    class Meta:
        model = ProjectNode
        fields = [
            "id", "thread", "title", "description", "status",
            "parent_node_id", "branch_root_id",
            "stage", "row",
            "created_by", "created_at", "updated_at",
            "is_deleted", "file_count", "is_branch",
        ]
        read_only_fields = ["id", "thread", "created_by", "created_at", "updated_at", "is_deleted"]

    def get_file_count(self, obj):
        return obj.files.count()

    def get_is_branch(self, obj):
        return obj.branch_root_id is not None


class NodeCreateSerializer(serializers.ModelSerializer):
    parent_node_id = serializers.PrimaryKeyRelatedField(
        source="parent_node",
        queryset=ProjectNode.objects.all(),
        allow_null=True,
        required=False,
    )
    branch_root_id = serializers.PrimaryKeyRelatedField(
        source="branch_root",
        queryset=ProjectNode.objects.all(),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = ProjectNode
        fields = ["title", "description", "parent_node_id", "branch_root_id", "stage", "row"]


class NodeUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectNode
        fields = ["title", "description", "status", "stage", "row"]


# ─── Dependency ───────────────────────────────────────────────────────────────

class DependencySerializer(serializers.ModelSerializer):
    source_node_title = serializers.CharField(source="source_node.title", read_only=True)
    target_node_title = serializers.CharField(source="target_node.title", read_only=True)

    class Meta:
        model = NodeDependency
        fields = [
            "id", "source_node", "target_node",
            "source_node_title", "target_node_title",
            "dependency_type", "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, data):
        src = data.get("source_node")
        tgt = data.get("target_node")
        if src == tgt:
            raise serializers.ValidationError("A node cannot depend on itself.")
            
        if NodeDependency.objects.filter(source_node=src, target_node=tgt).exists():
            raise serializers.ValidationError("This dependency already exists.")

        if NodeDependency.objects.filter(source_node=tgt, target_node=src).exists():
            raise serializers.ValidationError(f"Cannot create dependency: \"{tgt.title}\" already depends on \"{src.title}\".")
            
        return data


# ─── File ─────────────────────────────────────────────────────────────────────

class NodeFileSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.StringRelatedField(read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = NodeFile
        fields = ["id", "node", "file", "original_name", "uploaded_by", "created_at", "file_url"]
        read_only_fields = ["id", "node", "original_name", "uploaded_by", "created_at"]

    def get_file_url(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url


class NodeFileUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, value):
        max_size_mb = 100
        if value.size > max_size_mb * 1024 * 1024:
            raise serializers.ValidationError(f"File size must not exceed {max_size_mb} MB.")
        return value


# ─── Activity ─────────────────────────────────────────────────────────────────

class NodeActivitySerializer(serializers.ModelSerializer):
    actor = serializers.StringRelatedField(read_only=True)

    class Meta:
        model = NodeActivity
        fields = ["id", "node", "actor", "event_type", "message", "created_at"]
        read_only_fields = ["id", "node", "actor", "event_type", "message", "created_at"]


# ─── Graph (combined payload for canvas) ──────────────────────────────────────

class GraphNodeSerializer(serializers.ModelSerializer):
    """Slim node shape consumed by ReactFlow."""
    is_branch = serializers.SerializerMethodField()
    file_count = serializers.SerializerMethodField()

    class Meta:
        model = ProjectNode
        fields = [
            "id", "title", "description", "status",
            "parent_node", "branch_root",
            "stage", "row",
            "is_branch", "file_count",
        ]

    def get_is_branch(self, obj):
        return obj.branch_root_id is not None

    def get_file_count(self, obj):
        return obj.files.count()


class GraphEdgeSerializer(serializers.ModelSerializer):
    """Slim dependency shape consumed by ReactFlow."""
    class Meta:
        model = NodeDependency
        fields = ["id", "source_node", "target_node", "dependency_type"]