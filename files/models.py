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

    class DesignationChoices(models.TextChoices):
        PROJECT_MANAGER = "project_manager", "Project Manager"
        TEAM_LEAD = "team_lead", "Team Lead"
        DELIVERY_MANAGER = "delivery_manager", "Delivery Manager"
        PRODUCT_MANAGER = "product_manager", "Product Manager"
        OPERATIONS_MANAGER = "operations_manager", "Operations Manager"
        PROGRAM_MANAGER = "program_manager", "Program Manager"

    username = None
    email = models.EmailField(unique=True)
    date_of_birth = models.DateField(null=True, blank=True)

    designation = models.CharField(
        max_length=20,
        choices=DesignationChoices.choices,
        default=DesignationChoices.PROJECT_MANAGER
    )
    storage_limit_bytes = models.BigIntegerField(default=1_073_741_824)
    storage_used_bytes = models.BigIntegerField(default=0)

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
    expires_at = models.DateTimeField(
        default=default_expiry,
        db_index=True
    )
    class Meta:
        db_table = "files"

    def __str__(self):
        return f"{self.original_name} - {self.user.email}"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

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
        db_index=True
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
    def __str__(self):
        return f"{self.file} shared with {self.recipient_email}"
    class Meta:
        db_table = "file_share_links"
        ordering = ["-created_at"]


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