from django.db import models
import uuid
from django.conf import settings
from django.contrib.auth.models import BaseUserManager, AbstractUser

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
    username=None
    email=models.EmailField(unique=True)
    date_of_birth=models.DateField(null=True, blank=True)
    USERNAME_FIELD='email'
    REQUIRED_FIELDS=['first_name', 'date_of_birth']
    objects=UserManager()
    def __str__(self):
        return self.email



def user_directory_path(instance, filename):
    """Files uploaded to: media/user_<uuid>/<file_uuid>/<filename>"""
    return f"userfiles/user_{instance.user.id}/{instance.id}/{filename}"


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
    
    def __str__(self):
        return f"{self.original_name} - {self.user.email}"

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

    def __str__(self):
        return f"{self.file} shared with {self.recipient_email}"