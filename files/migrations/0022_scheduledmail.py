from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0021_alter_user_role"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScheduledMail",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("message", models.TextField(blank=True, default="")),
                ("scheduled_for", models.DateTimeField(db_index=True)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")], default="pending", max_length=20)),
                ("task_id", models.CharField(blank=True, max_length=255, null=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("share", models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="scheduled_mails", to="files.filesharelink")),
            ],
            options={
                "db_table": "scheduled_mails",
                "ordering": ["-created_at"],
            },
        ),
    ]
