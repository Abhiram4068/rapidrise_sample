from django.db import models
import uuid
from django.conf import settings
from django.contrib.auth.models import BaseUserManager, AbstractUser
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum

class UserManager(BaseUserManager):
    """"
    Custom user manager to use email as the unique identifier instead of username
    """
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email must be provided!")
        email=self.normalize_email(email)
        user=self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Super user must have is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Super user must have is_superuser=True')
        if extra_fields.get('is_active') is not True:
            raise ValueError('Super user must have is_active=True')
        return self.create_user(email=email, password=password, **extra_fields)
class User(AbstractUser):

    class AccountStatus(models.TextChoices):
        WAITING_FOR_APPROVAL = "Waiting For Approval", "Waiting For Approval"
        ACTIVE = "active", "Active"
        DEACTIVATED = "deactivated", "Deactivated"
        BLOCKED = "blocked", "Blocked"
        REJECTED = "rejected", "Rejected"
        DELETED = "deleted", "Deleted"

    username = None
    email = models.EmailField(unique=True)
    date_of_birth = models.DateField(null=True, blank=True)

    designation = models.ForeignKey(
        "administration.Designation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="users",
    )
    account_status = models.CharField(
        max_length=20,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE
    )
    storage_limit_bytes = models.BigIntegerField(default=1_073_741_824)
    storage_used_bytes = models.BigIntegerField(default=0)
    deleted_at=models.DateTimeField(null=True, blank=True)
    monthly_report_enabled = models.BooleanField(default=False)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['first_name', 'date_of_birth']


    objects = UserManager()

    def __str__(self):
        return self.email

    class Meta:
        db_table = "auth_users"


def user_directory_path(instance, filename):
    """Files uploaded to: media/userfiles/<user_id>/<filename>"""
    return f"userfiles/{instance.user.id}/{filename}"

def default_expiry():
    return timezone.now() + timedelta(days=10)

class File(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="files"
    )
    file = models.FileField(upload_to=user_directory_path)
    original_name = models.CharField(max_length=255)
    file_size = models.BigIntegerField()
    content_type = models.CharField(max_length=100)
    checksum = models.CharField(max_length=64, blank=True, null=True)
    description=models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)
    is_archive = models.BooleanField(default=False)
    archived_at = models.DateTimeField(null=True, blank=True)
    is_starred = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    display_name = models.CharField(max_length=255, blank=True, null=True)
    last_accessed = models.DateTimeField(
        default=timezone.now
    )
    class Meta:
        db_table = "files"

    def __str__(self):
        return f"{self.original_name} - {self.user.email}"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at


class ChunkUploadSession(models.Model):
    """Tracks in-progress chunked uploads for pause, resume, and retry."""

    class Status(models.TextChoices):
        UPLOADING = "uploading", "Uploading"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    upload_id = models.CharField(max_length=128, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="chunk_upload_sessions",
    )
    file_name = models.CharField(max_length=255)
    file_size = models.BigIntegerField()
    content_type = models.CharField(max_length=100)
    total_chunks = models.PositiveIntegerField()
    chunks_received = models.JSONField(default=list)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.UPLOADING,
    )
    description = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "chunk_upload_sessions"
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self):
        return f"{self.upload_id} ({self.status})"


class FileShareLink(models.Model):
    id=models.UUIDField(
        primary_key=True,
         default=uuid.uuid4,
        editable=False
    )
    file=models.ForeignKey(
        'File',
        on_delete=models.CASCADE,
        related_name='shares',
        db_index=True,
        null=True,
        blank=True
    )
    owner=models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='shared_files',
        db_index=True
    )
    recipient_email=models.EmailField(db_index=True)
    share_token=models.CharField(
        max_length=64,
        unique=True,
        db_index=True
    )
    expiration_datetime=models.DateTimeField()
    created_at=models.DateTimeField(auto_now_add=True)
    accessed=models.BooleanField(default=False)
    accessed_at=models.DateTimeField(blank=True, null=True)
    is_active=models.BooleanField(default=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    permission = models.CharField(
        max_length=20,
        choices=[
            ('view_only', 'View Only'),
            ('view_download', 'View + Download'),
            ('one_time_download', 'One-time Download'),
            ('full_access', 'Full Access'),
        ],
        default='view_only'
    )
    download_limit = models.PositiveIntegerField(null=True, blank=True)
    download_count = models.PositiveIntegerField(default=0)
    view_limit = models.PositiveIntegerField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    bundle = models.ForeignKey(
    'ShareBundle',
    on_delete=models.CASCADE,
    related_name='share_links',
    null=True,
    blank=True
)
    def __str__(self):
        return f"{self.file} shared with {self.recipient_email}"
    class Meta:
        db_table = "file_share_links"
        ordering = ["-created_at"]

class ShareBundle(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)

    share_token = models.CharField(max_length=255, unique=True)

    title = models.CharField(max_length=500, blank=True)
    message = models.TextField(blank=True)

    permission = models.CharField(
        max_length=30,
        choices=[
            ('view_only', 'View Only'),
            ('view_download', 'View + Download'),
            ('one_time_download', 'One Time Download'),
            ('full_access', 'Full Access')
        ],
        default='view_only'
    )

    expiration_datetime = models.DateTimeField()

    zip_file = models.FileField(upload_to='share_bundles/', null=True, blank=True)
    download_count = models.PositiveIntegerField(default=0)
    view_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    download_limit = models.IntegerField(null=True, blank=True)
    view_limit = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)


class ShareBundleItem(models.Model):
    bundle = models.ForeignKey(
        ShareBundle,
        related_name='items',
        on_delete=models.CASCADE
    )

    file = models.ForeignKey(File, on_delete=models.CASCADE)


class BundleRecipient(models.Model):
    bundle = models.ForeignKey(
        ShareBundle,
        related_name='recipients',
        on_delete=models.CASCADE
    )

    recipient_email = models.EmailField()

    accessed = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)




class ScheduledMail(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        REVOKED = "revoked", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    share = models.ForeignKey(
        "FileShareLink",
        on_delete=models.CASCADE,
        related_name="scheduled_mails",
    )
    title = models.TextField(blank=True, default="")
    message = models.TextField(blank=True, default="")
    scheduled_for = models.DateTimeField(db_index=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    task_id = models.CharField(max_length=255, blank=True, null=True)
    sent_at = models.DateTimeField(blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "scheduled_mails"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.share_id} @ {self.scheduled_for} [{self.status}]"
    
#collections for files
class Collection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="collections"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_starred = models.BooleanField(default=False)
    
    class Meta:
        db_table = "collections"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                name="unique_collection_name_per_user"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.user.email})"


    def get_total_files(self):
        return self.collection_files.count()

    def get_total_size(self):
        result = self.collection_files.aggregate(
            total=Sum("file__file_size")
        )
        return result["total"] or 0


class CollectionFile(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        ARCHIVED = "ARCHIVED", "Archived"
        TRASHED = "TRASHED", "Trashed"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    collection = models.ForeignKey(
        Collection,
        on_delete=models.CASCADE,
        related_name="collection_files"
    )
    file = models.ForeignKey(
        File,
        on_delete=models.CASCADE,
        related_name="file_collections"
    )
    added_at = models.DateTimeField(auto_now_add=True)
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="added_collection_files"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE
    )

    class Meta:
        db_table = "collection_files"
        ordering = ["-added_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["collection", "file"],
                name="unique_file_per_collection"
            )
        ]

    def __str__(self):
        return f"{self.file.original_name} → {self.collection.name}"


class DesignationChangeRequest(models.Model):

    class StatusChoices(models.TextChoices):
        PENDING  = "pending",  "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="designation_change_requests"
    )

    current_designation = models.ForeignKey(
        "administration.Designation",
        on_delete=models.PROTECT,
        related_name="designation_changes_from",
    )
    requested_designation = models.ForeignKey(
        "administration.Designation",
        on_delete=models.PROTECT,
        related_name="designation_changes_to",
    )

    status = models.CharField(
        max_length=10,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING
    )

    admin_note = models.TextField(blank=True, default="")

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_designation_requests"
    )

    created_at  = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "designation_change_requests"
        ordering = ["-created_at"]

    def __str__(self):
        current = self.current_designation.name if self.current_designation_id else "—"
        requested = self.requested_designation.name if self.requested_designation_id else "—"
        return f"{self.user.email}: {current} → {requested} [{self.status}]"


#threads
class ProjectThread(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="threads")
    created_at = models.DateTimeField(auto_now_add=True)
 
    def __str__(self):
        return self.title
 
    class Meta:
        ordering = ["-created_at"]
 
 
class ProjectStage(models.Model):
    thread = models.ForeignKey(ProjectThread, on_delete=models.CASCADE, related_name="stages")
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.thread.title} - {self.name}"

    class Meta:
        ordering = ["created_at"]


class ProjectNode(models.Model):
 
    class Status(models.TextChoices):
        INACTIVE = "INACTIVE", "Inactive"
        ACTIVE = "ACTIVE", "Active"
        NEEDS_REVIEW = "NEEDS_REVIEW", "Needs Review"
        OUTDATED = "OUTDATED", "Outdated"
        BLOCKED = "BLOCKED", "Blocked"
        ARCHIVED = "ARCHIVED", "Archived"
 
    thread = models.ForeignKey(ProjectThread, on_delete=models.CASCADE, related_name="nodes")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INACTIVE)
 
    # Tree structure
    parent_node = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    # Tracks which node this branch diverged from (null = main chain)
    branch_root = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="branches"
    )
 
    # Table layout position
    stage = models.ForeignKey(ProjectStage, on_delete=models.SET_NULL, null=True, blank=True, related_name="nodes")
    row = models.IntegerField(default=0)
 
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="nodes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
 
    is_deleted = models.BooleanField(default=False)  # Soft delete
 
    def __str__(self):
        return f"{self.thread.title} → {self.title}"
 
    class Meta:
        ordering = ["created_at"]
 
 
class NodeDependency(models.Model):
 
    class DependencyType(models.TextChoices):
        DEPENDS_ON = "DEPENDS_ON", "Depends On"
        REQUIRED_FOR = "REQUIRED_FOR", "Required For"
        WAITING_FOR = "WAITING_FOR", "Waiting For"
        RELATED = "RELATED", "Related"
        NOT_SURE = "NOT_SURE", "Not Sure"
        NEEDS_REVIEW = "NEEDS_REVIEW", "Needs Review"
 
    source_node = models.ForeignKey(
        ProjectNode, on_delete=models.CASCADE, related_name="outgoing_dependencies"
    )
    target_node = models.ForeignKey(
        ProjectNode, on_delete=models.CASCADE, related_name="incoming_dependencies"
    )
    dependency_type = models.CharField(
        max_length=20, choices=DependencyType.choices, default=DependencyType.DEPENDS_ON
    )
    created_at = models.DateTimeField(auto_now_add=True)
 
    class Meta:
        unique_together = ("source_node", "target_node")
 
    def __str__(self):
        return f"{self.source_node.title} → {self.target_node.title}"
 
 
class NodeFile(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        ARCHIVED = "ARCHIVED", "Archived"
        TRASHED = "TRASHED", "Trashed"
    node = models.ForeignKey(ProjectNode, on_delete=models.CASCADE, related_name="files")
    file = models.FileField(upload_to="node_files/")
    original_name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="uploaded_files")
    vault_file = models.ForeignKey('File', on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE
    )
    def __str__(self):
        return f"{self.node.title} / {self.original_name}"
 
    class Meta:
        ordering = ["-created_at"]
 
 
class NodeActivity(models.Model):
 
    class EventType(models.TextChoices):
        CREATED = "CREATED", "Created"
        UPDATED = "UPDATED", "Updated"
        FILE_UPLOADED = "FILE_UPLOADED", "File Uploaded"
        FILE_DELETED = "FILE_DELETED", "File Deleted"
        STATUS_CHANGED = "STATUS_CHANGED", "Status Changed"
        DEPENDENCY_ADDED = "DEPENDENCY_ADDED", "Dependency Added"
        COMMENTED = "COMMENTED", "Commented"
 
    node = models.ForeignKey(ProjectNode, on_delete=models.CASCADE, related_name="activities")
    actor = models.ForeignKey(User, on_delete=models.CASCADE)
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
 
    def __str__(self):
        return f"{self.node.title} — {self.event_type}"
 
    class Meta:
        ordering = ["-created_at"]

class ReactivationRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="reactivation_requests"
    )
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_resolved = models.BooleanField(default=False)

    class Meta:
        db_table = "reactivation_requests"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Reactivation request for {self.user.email} at {self.created_at}"