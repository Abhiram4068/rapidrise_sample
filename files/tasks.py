from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from .models import FileShareLink

@shared_task(bind=True, max_retries=3)
def send_share_email_task(self, share_id, message):
    try:
        share = FileShareLink.objects.select_related('file', 'owner').get(id=share_id)

        email_subject = f"{share.owner.email} shared '{share.file.original_name}' with you"

        share_url = f"{settings.BACKEND_BASE_URL}/api/files/public/{share.share_token}/"

        email_body = f"""
Hi,

{share.owner.email} has shared a file with you.

File: {share.file.original_name}
Size: {share.file.file_size / (1024 * 1024):.2f} MB

{f'Message from sender: "{message}"' if message else ''}

Click here to access:
{share_url}

This link expires on {share.expiration_datetime.strftime('%B %d, %Y')}
"""

        send_mail(
            subject=email_subject,
            message=email_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[share.recipient_email],
            fail_silently=False
        )

        return "Email sent"

    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)