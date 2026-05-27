from django.db import models
import random
import string


def generate_designation_id():
    while True:
        code = ''.join(
            random.choices(string.ascii_uppercase + string.digits, k=4)
        )

        if not Designation.objects.filter(id=code).exists():
            return code


class Designation(models.Model):
    id = models.CharField(
        primary_key=True,
        max_length=4,
        default=generate_designation_id,
        editable=False,
        unique=True
    )

    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class AdminLog(models.Model):
    class ActivityType(models.TextChoices):
        USER_REGISTERED = "USER_REGISTERED", "User Registered"
        REACTIVATION_REQUEST = "REACTIVATION_REQUEST", "Reactivation Request"
        DESIGNATION_CHANGE_REQUEST = "DESIGNATION_CHANGE_REQUEST", "Designation Change Request"
        USER_BLOCKED = "USER_BLOCKED", "User Blocked"
        USER_UNBLOCKED = "USER_UNBLOCKED", "User Unblocked"
        USER_DELETED = "USER_DELETED", "User Deleted"
        USER_RESTORED = "USER_RESTORED", "User Restored"
        NEW_USER_RESOLVED = "NEW_USER_RESOLVED", "New User Request Resolved"
        DESIGNATION_CHANGE_RESOLVED = "DESIGNATION_CHANGE_RESOLVED", "Designation Change Request Resolved"
        REACTIVATION_RESOLVED = "REACTIVATION_RESOLVED", "Reactivation Request Resolved"

    admin = models.ForeignKey(
        'files.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admin_logs"
    )
    target_user = models.ForeignKey(
        'files.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="target_admin_logs"
    )
    activity_type = models.CharField(max_length=50, choices=ActivityType.choices)
    action_details = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admin_activity_logs"
        ordering = ['-timestamp']