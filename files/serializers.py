from .models import User, File, FileShareLink, ShareBundle, Collection, CollectionFile, ScheduledMail, ReactivationRequest, DesignationChangeRequest, Team,TeamMember
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.db import models
from django.utils import timezone
from datetime import timedelta
from administration.models import Designation 
import logging
logger = logging.getLogger(__name__)

class RegisterSerializer(serializers.ModelSerializer):
    confirm_password=serializers.CharField(write_only=True, min_length=8)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    email = serializers.EmailField()
    designation = serializers.PrimaryKeyRelatedField(
        queryset=Designation.objects.all(),
        required=True,
    )

    class Meta:
        model=User
        fields=[
            'email',
            'first_name',
            'last_name',
            'date_of_birth',
            'designation',
            'password',
            'confirm_password'
        ]
        extra_kwargs={
            'password':{'write_only':True, 'min_length':8},
            'last_name':{'required':False, 'allow_blank':True},
            'date_of_birth':{'required':False}
        }
    def validate_email(self, value):
        email=value.lower().strip()
        existing_user=User.objects.filter(email=email).first()
        if existing_user:
            if existing_user.account_status == User.AccountStatus.WAITING_FOR_APPROVAL:
                raise serializers.ValidationError("Your account is waiting for approval. Please contact the administrator.")
            elif existing_user.account_status == User.AccountStatus.BLOCKED:
                raise serializers.ValidationError("Your account has been blocked by the administrator. Access to this platform has been permanently restricted until reviewed by the admin team. Only an administrator can revoke this restriction and restore account access.")
            elif existing_user.account_status == User.AccountStatus.DELETED:
                raise serializers.ValidationError("Your account has been deleted by the administrator. Access to this platform has been permanently restricted until reviewed by the admin team. Only an administrator can revoke this restriction and restore account access.")
            else:
                raise serializers.ValidationError("Email already exists")
        return value
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

class DesignationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Designation
        fields = ['id', 'name']

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
        fields = ["id", "email", "first_name", "last_name", "designation", "designation_id", "date_joined", "total_files", "date_of_birth", "status", "account_status", "storage_used_bytes", "has_pending_reactivation_request", "is_staff", "is_superuser"]
        read_only_fields = fields

    def get_date_joined(self, obj):
        return obj.date_joined.strftime("%B %d %Y")

    def get_status(self, obj):
        return "Active" if obj.is_active else "Unactive"

    def get_has_pending_reactivation_request(self, obj):
        return ReactivationRequest.objects.filter(user=obj, is_resolved=False).exists()

    def get_designation(self, obj):
        return obj.designation.name if obj.designation_id else None

    def get_storage_used_bytes(self, obj):
        return obj.storage_used_bytes

class ChangePasswordSerialzier(serializers.Serializer):
    current_password=serializers.CharField(required=True, write_only=True)
    new_password=serializers.CharField(required=True, write_only=True)
    confirm_password=serializers.CharField(required=True, write_only=True)

    def validate_current_password(self, value):
        user=self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Incorrect current password. Please try again.")
        return value
    def validate(self, data):
        if data["new_password"]!=data["confirm_password"]:
            raise serializers.ValidationError({"confirm_password":"Passwords doesnt match"})

        validate_password(data["new_password"], self.context["request"].user)

        if (self.context["request"].user.check_password(data["new_password"])):
            raise serializers.ValidationError({"new_password": "New password cannot be same as old password"})
        return data
class DesignationChangeRequestAdminSerializer(serializers.ModelSerializer):
    """
    Used by admins to list all requests and resolve (approve / reject) them.
    """
    user_email     = serializers.EmailField(source="user.email",      read_only=True)
    user_full_name = serializers.SerializerMethodField()
    current_designation_display   = serializers.CharField(source="current_designation.name", read_only=True)
    requested_designation_display = serializers.CharField(source="requested_designation.name", read_only=True)
 
    class Meta:
        model  = DesignationChangeRequest
        fields = [
            "id",
            "user_email",
            "user_full_name",
            "current_designation",
            "current_designation_display",
            "requested_designation",
            "requested_designation_display",
            "status",
            "admin_note",
            "created_at",
            "resolved_at",
        ]
        read_only_fields = [
            "id", "user_email", "user_full_name",
            "current_designation", "current_designation_display",
            "requested_designation", "requested_designation_display",
            "created_at", "resolved_at",
        ]
 
    def get_user_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()
 

class DesignationChangeRequestCreateSerializer(serializers.ModelSerializer):
    """
    Used by the user to submit a new designation change request.
    `requested_designation` is the administration.Designation primary key (e.g. AJNW).
    """
    requested_designation = serializers.PrimaryKeyRelatedField(
        queryset=Designation.objects.all(),
    )

    class Meta:
        model  = DesignationChangeRequest
        fields = ["id", "requested_designation", "status", "created_at"]
        read_only_fields = ["id", "status", "created_at"]
 
    def validate_requested_designation(self, value):
        user = self.context["request"].user
        if not user.designation_id:
            raise serializers.ValidationError(
                "Your account has no current designation assigned."
            )
        if value.pk == user.designation_id:
            raise serializers.ValidationError(
                "Requested designation must be different from your current designation."
            )
        return value
 
    def validate(self, attrs):
        user = self.context["request"].user
        if DesignationChangeRequest.objects.filter(
            user=user, status=DesignationChangeRequest.StatusChoices.PENDING
        ).exists():
            raise serializers.ValidationError(
                "You already have a pending designation change request. "
                "Please wait for it to be resolved before submitting a new one."
            )
        return attrs
 
 
class DesignationChangeRequestListSerializer(serializers.ModelSerializer):
    """
    Used by the user to list their own past requests.
    """
    current_designation_display   = serializers.CharField(source="current_designation.name", read_only=True)
    requested_designation_display = serializers.CharField(source="requested_designation.name", read_only=True)
 
    class Meta:
        model  = DesignationChangeRequest
        fields = [
            "id",
            "current_designation",
            "current_designation_display",
            "requested_designation",
            "requested_designation_display",
            "status",
            "admin_note",
            "created_at",
            "resolved_at",
        ]
        read_only_fields = fields
class ReactivationRequestSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_full_name = serializers.SerializerMethodField()
    designation = serializers.SerializerMethodField()

    def get_designation(self, obj):
        return obj.user.designation.name if obj.user.designation_id else None

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

      
import magic
from rest_framework import serializers
from .services import StorageService

ALLOWED_CONTENT_TYPES = {
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/csv",
    "image/jpeg",
    "image/png",
    "application/pdf",
    "image/webp",
    "application/zip",
    "application/x-zip-compressed",
    "application/json",
    "application/xml",
    "text/xml",
    "application/octet-stream"
}

MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB per file
MAX_STORAGE_BYTES   = 1 * 1024 * 1024 * 1024  # 1 GB per user
MAX_CHUNK_BYTES     = 10 * 1024 * 1024  # must match frontend CHUNK_SIZE


def _format_bytes(n: int) -> str:
    MB = 1024 * 1024
    GB = 1024 * 1024 * 1024
    if n < MB:
        return f"{n / 1024:.2f} KB"
    elif n < GB:
        return f"{n / MB:.2f} MB"
    return f"{n / GB:.2f} GB"


# ─── Chunk upload serializer ──────────────────────────────────────────────────

class ChunkUploadSerializer(serializers.Serializer):
    upload_id    = serializers.CharField()
    chunk_index  = serializers.IntegerField(min_value=0)
    total_chunks = serializers.IntegerField(min_value=1)
    file_name    = serializers.CharField()
    file_size    = serializers.IntegerField(min_value=1)
    content_type = serializers.CharField()          # client-declared, cross-checked by magic
    file         = serializers.FileField()
    action       = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    description  = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    team_id      = serializers.UUIDField(required=False, allow_null=True)

    # ── per-field validators ──────────────────────────────────────────────────

    def validate_file_size(self, value):
        if value > MAX_FILE_SIZE_BYTES:
            raise serializers.ValidationError(
                f"File size {_format_bytes(value)} exceeds the {_format_bytes(MAX_FILE_SIZE_BYTES)} limit."
            )
        return value

    def validate_file(self, file):
        """
        Per-chunk: enforce chunk byte limit.
        First chunk only: python-magic MIME detection and allow-list check.
        """
        file.seek(0, 2)
        real_size = file.tell()
        file.seek(0)

        if real_size > MAX_CHUNK_BYTES:
            raise serializers.ValidationError(
                f"Uploaded chunk size {_format_bytes(real_size)} exceeds the "
                f"{_format_bytes(MAX_CHUNK_BYTES)} chunk limit."
            )

        chunk_index = self.initial_data.get("chunk_index")
        try:
            chunk_index = int(chunk_index)
        except (TypeError, ValueError):
            chunk_index = 0

        if chunk_index != 0:
            return file

        header = file.read(2048)
        file.seek(0)

        detected_mime = magic.from_buffer(header, mime=True)

        if detected_mime not in ALLOWED_CONTENT_TYPES:
            raise serializers.ValidationError(
                f"File type '{detected_mime}' is not allowed."
            )

        self._detected_mime = detected_mime
        return file

    # ── cross-field validation ────────────────────────────────────────────────
    def validate(self, data):
        if data["chunk_index"] >= data["total_chunks"]:
            raise serializers.ValidationError(
                {"chunk_index": "chunk_index must be less than total_chunks."}
            )

        if data["chunk_index"] == 0:
            detected = getattr(self, "_detected_mime", None)
            declared = data.get("content_type", "")

            if detected:
                if detected == "application/octet-stream":
                    # magic couldn't identify the real type (common for ZIP-based Office formats)
                    # trust declared type if it's in the allow-list, else reject
                    if declared and declared not in ALLOWED_CONTENT_TYPES:
                        raise serializers.ValidationError(
                            {"content_type": f"Declared content type '{declared}' is not allowed."}
                        )
                    data["content_type"] = declared or detected
                elif declared in ("", "application/octet-stream"):
                    data["content_type"] = detected
                elif detected != declared:
                    raise serializers.ValidationError(
                        {
                            "content_type": (
                                f"Declared content type '{declared}' does not match "
                                f"the detected type '{detected}'."
                            )
                        }
                    )

        return data

    # ── storage quota check (only on first chunk) ─────────────────────────────

    def validate_storage(self, user):
        """
        Call this explicitly in the view after is_valid(), only for chunk_index == 0.
        Uses StorageService.claim pattern: raises ValidationError if quota exceeded.
        """
        file_size    = self.validated_data["file_size"]
        current_usage = user.storage_used_bytes          # already up-to-date (refresh_from_db in view)
        available     = MAX_STORAGE_BYTES - current_usage

        if file_size > available:
            raise serializers.ValidationError(
                {
                    "error": (
                        f"Insufficient storage. Only {_format_bytes(available)} left. "
                        "Try deleting some files!"
                    )
                }
            )


class ChunkUploadStatusQuerySerializer(serializers.Serializer):
    upload_id = serializers.CharField()


class ChunkUploadControlSerializer(serializers.Serializer):
    ACTION_CHOICES = ("pause", "resume", "cancel")

    upload_id = serializers.CharField()
    action = serializers.ChoiceField(choices=ACTION_CHOICES)

    def validate_upload_id(self, value):
        import re
        if not re.match(r"^[a-zA-Z0-9_-]+$", str(value)):
            raise serializers.ValidationError("Invalid upload_id format.")
        return value


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
    team_id = serializers.UUIDField(required=False, allow_null=True)
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
    file_name = serializers.SerializerMethodField()
    file_size = serializers.SerializerMethodField()
    owner_email = serializers.EmailField(source='owner.email', read_only=True)
    recipient_email = serializers.EmailField(read_only=True)
    created_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    expiration_datetime = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    accessed_at = serializers.DateTimeField(format="%Y-%m-%d %H:%M:%S", read_only=True)
    is_active = serializers.SerializerMethodField()
    share_url = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    content_type = serializers.SerializerMethodField()
    file_id = serializers.SerializerMethodField()
    bundle_id = serializers.UUIDField(source='bundle.id', read_only=True, allow_null=True)
    is_bundle = serializers.SerializerMethodField()

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
            'file_id', 'bundle_id', 'is_bundle',
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

        if obj.accessed:
            return "Accessed"

        if obj.expiration_datetime and now > obj.expiration_datetime:
            return "Expired"

        if not obj.is_active and obj.revoked_at:
            return "Revoked"

        return "Active"     

    def get_content_type(self, obj):
        if obj.file:
            return obj.file.content_type
        return "application/zip" # Fixed type for bundles

    def get_file_id(self, obj):
        return obj.file.id if obj.file else None

    def get_file_name(self, obj):
        if obj.file:
            return obj.file.original_name
        return obj.bundle.title or "Bulk Share Package"

    def get_file_size(self, obj):
        if obj.file:
            return obj.file.file_size
        return 0 # Bundle size calculated elsewhere if needed

    def get_is_bundle(self, obj):
        return obj.bundle is not None
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

class ShareBundleSerializer(serializers.ModelSerializer):
    owner_email = serializers.EmailField(source='owner.email', read_only=True)
    is_expired = serializers.SerializerMethodField()
    share_url = serializers.SerializerMethodField()
    file_count = serializers.SerializerMethodField()

    class Meta:
        model = ShareBundle
        fields = [
            'id', 'title', 'message', 'owner_email', 
            'share_token', 'expiration_datetime',
            'is_expired', 'share_url', 'file_count',
            'permission', 'download_limit', 'download_count',
            'view_limit', 'view_count', 'is_active'
        ]
        read_only_fields = ['id', 'share_token', 'download_count', 'view_count']

    def get_is_expired(self, obj):
        return timezone.now() > obj.expiration_datetime

    def get_share_url(self, obj):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(f'/api/files/public/{obj.share_token}/')
        return f'/api/files/public/{obj.share_token}/'

    def get_file_count(self, obj):
        return obj.items.count()


class BulkFileShareSerializer(serializers.Serializer):

    file_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        max_length=100
    )

    recipient_emails = serializers.ListField(
        child=serializers.EmailField(),
        allow_empty=False,
        max_length=50
    )

    expiration_datetime = serializers.IntegerField(
        min_value=1,
        max_value=168
    )

    title = serializers.CharField(
        max_length=500,
        required=False,
        allow_blank=True
    )

    message = serializers.CharField(
        max_length=2000,
        required=False,
        allow_blank=True
    )

    schedule_at = serializers.DateTimeField(
        required=False
    )

    team_id = serializers.UUIDField(
        required=False,
        allow_null=True
    )

    permission = serializers.ChoiceField(
        choices=[
            'view_only',
            'view_download',
            'one_time_download',
            'full_access'
        ],
        default='view_only'
    )

    download_limit = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True
    )

    view_limit = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True
    )

    def validate_file_ids(self, value):
        request = self.context.get('request')
        unique_file_ids = list(set(value))

        if len(unique_file_ids) != len(value):
            raise serializers.ValidationError(
                "Duplicate file ids are not allowed."
            )

        files = File.objects.filter(
            id__in=unique_file_ids,
            user=request.user
        )

        if files.count() != len(unique_file_ids):
            raise serializers.ValidationError(
                "Some files do not exist or you do not have permission."
            )

        return unique_file_ids


    def validate_recipient_emails(self, value):

        normalized_emails = [email.lower().strip() for email in value]

        unique_emails = list(set(normalized_emails))

        if len(unique_emails) != len(normalized_emails):
            raise serializers.ValidationError(
                "Duplicate recipient emails are not allowed."
            )

        request = self.context.get('request')

        if request.user.email.lower() in unique_emails:
            raise serializers.ValidationError(
                "You cannot share files with yourself."
            )

        return unique_emails


    def validate_schedule_at(self, value):

        if value <= timezone.now():
            raise serializers.ValidationError(
                "Schedule time must be in the future."
            )

        return value


    def validate(self, data):

        permission = data.get('permission')

        download_limit = data.get('download_limit')
        view_limit = data.get('view_limit')


        if permission == 'one_time_download':

            data['download_limit'] = 1
            data['view_limit'] = None



        elif permission == 'view_download':

            if download_limit is not None and download_limit < 1:
                raise serializers.ValidationError({
                    "download_limit":
                        "Download limit must be greater than 0."
                })

        else:
            data['download_limit'] = None


        if permission not in ['view_only', 'view_download']:
            data['view_limit'] = None

        if view_limit is not None and view_limit < 1:
            raise serializers.ValidationError({
                "view_limit":
                    "View limit must be greater than 0."
            })


        if len(data['file_ids']) > 20:
            raise serializers.ValidationError({
                "file_ids":
                    "Maximum 20 files allowed per share."
            })

        if len(data['recipient_emails']) > 10:
            raise serializers.ValidationError({
                "recipient_emails":
                    "Maximum 10 recipients allowed."
            })

        return data

    
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

    def validate(self, data):
        from .services import ViewFileShareService
        from django.http import Http404
        try:
            self.share = ViewFileShareService.get_share_or_404(data['token'])
        except (Http404, ValueError) as e:
            raise serializers.ValidationError(str(e))
        return data


class ReportQuerySerializer(serializers.Serializer):
    download = serializers.BooleanField(required=False, default=False)
    timeline = serializers.ChoiceField(choices=['monthly'], required=False)
    search = serializers.CharField(required=False, allow_blank=True, default='')
    

class ToggleMonthlyReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['monthly_report_enabled']

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
    is_root = serializers.SerializerMethodField()
    file_count = serializers.SerializerMethodField()

    class Meta:
        model = ProjectNode
        fields = [
            "id", "title", "description", "status",
            "parent_node", "branch_root",
            "stage", "row",
            "is_branch", "is_root", "file_count",
        ]

    def get_is_branch(self, obj):
        return obj.branch_root_id is not None

    def get_is_root(self, obj):
        from .services import NodeService
        return NodeService.is_root_node(obj)

    def get_file_count(self, obj):
        return obj.files.count()


class GraphEdgeSerializer(serializers.ModelSerializer):
    """Slim dependency shape consumed by ReactFlow."""
    class Meta:
        model = NodeDependency
        fields = ["id", "source_node", "target_node", "dependency_type"]

class TeamSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Team
        fields = ["id", "name", "member_count", "created_at"]
        read_only_fields = ["id", "member_count", "created_at"]

    def get_member_count(self, obj):
        return obj.member_count

    def validate_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Team name cannot be blank.")
        return value.strip()

from django.contrib.auth import get_user_model
class TeamMemberAddSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        return value.lower().strip()


class TeamMemberSerializer(serializers.ModelSerializer):

    class Meta:
        model = TeamMember
        fields = ["id", "email", "joined_at"]
        read_only_fields = fields