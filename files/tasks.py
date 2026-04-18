from celery import shared_task
from django.utils import timezone

from .models import ScheduledMail


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_scheduled_share_email(self, scheduled_mail_id):
    scheduled_mail = ScheduledMail.objects.select_related("share__file", "share__owner").get(
        id=scheduled_mail_id
    )

    if scheduled_mail.status == ScheduledMail.Status.SENT:
        return

    from .services import FileShareService

    try:
        email_sent = FileShareService.send_share_email(
            share=scheduled_mail.share,
            message=scheduled_mail.message,
        )
        if not email_sent:
            raise ValueError("Email could not be sent.")
    except Exception as exc:
        scheduled_mail.error_message = str(exc)
        scheduled_mail.save(update_fields=["error_message"])
        if self.request.retries >= self.max_retries:
            scheduled_mail.status = ScheduledMail.Status.FAILED
            scheduled_mail.save(update_fields=["status"])
        raise self.retry(exc=exc)

    scheduled_mail.status = ScheduledMail.Status.SENT
    scheduled_mail.sent_at = timezone.now()
    scheduled_mail.error_message = ""
    scheduled_mail.save(update_fields=["status", "sent_at", "error_message"])



