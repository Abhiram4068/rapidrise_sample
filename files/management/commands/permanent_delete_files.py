from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
from files.models import File

BATCH_SIZE = 100

class Command(BaseCommand):
    help = "Permanently delete files that were soft deleted 10 days ago"

    def handle(self, *args, **kwargs):
        cutoff = timezone.now() - timedelta(days=10)

        self.stdout.write(f"Cleanup started. Cutoff: {cutoff}")

        while True:
            files = File.objects.filter(
                is_deleted=True,
                deleted_at__lte=cutoff
            )[:BATCH_SIZE]

            if not files:
                break

            for file in files:
                try:
                    with transaction.atomic():
                       
                        if file.file:
                            file.file.delete(save=False)

                      
                        file.delete()

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"Failed to delete file {file.id}: {e}"
                        )
                    )

        self.stdout.write(
            self.style.SUCCESS("Permanent deletion completed.")
        )
