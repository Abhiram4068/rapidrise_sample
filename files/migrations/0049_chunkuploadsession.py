from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("files", "0048_filesharelink_bundle"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChunkUploadSession",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("upload_id", models.CharField(db_index=True, max_length=128, unique=True)),
                ("file_name", models.CharField(max_length=255)),
                ("file_size", models.BigIntegerField()),
                ("content_type", models.CharField(max_length=100)),
                ("total_chunks", models.PositiveIntegerField()),
                ("chunks_received", models.JSONField(default=list)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("uploading", "Uploading"),
                            ("paused", "Paused"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="uploading",
                        max_length=20,
                    ),
                ),
                ("description", models.CharField(blank=True, max_length=255, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("expires_at", models.DateTimeField()),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="chunk_upload_sessions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "chunk_upload_sessions",
                "indexes": [
                    models.Index(fields=["user", "status"], name="chunk_upl_user_id_8a1f2d_idx"),
                    models.Index(fields=["expires_at"], name="chunk_upl_expires_4c9e1a_idx"),
                ],
            },
        ),
    ]
