from celery import shared_task
from django.utils import timezone
from datetime import timedelta

from .models import ScheduledMail, File

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_scheduled_share_email(self, scheduled_mail_id):
    scheduled_mail = ScheduledMail.objects.select_related("share__file", "share__owner").get(
        id=scheduled_mail_id
    )

    if scheduled_mail.status != ScheduledMail.Status.PENDING:
        return

    from .services import FileShareService

    try:
        email_sent = FileShareService.send_share_email(
            share=scheduled_mail.share,
            title=scheduled_mail.title,
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


@shared_task
def auto_clear_trash():
    """
    celery task to clear trash after 30 days
    """    
    threshold_date = timezone.now() - timedelta(minutes=2)
    trashed_files = File.objects.filter(
        is_deleted=True,
        deleted_at__lte=threshold_date
    )
    count = trashed_files.count()
    if count > 0:
        for file in trashed_files:
            file.delete()
            print(f"Deleted trashed file: {file.id}")
    return f"Cleared {count} trashed files"


@shared_task
def auto_clear_scheduled_mails_history():
    threshold_date = timezone.now() - timedelta(minutes=2)
    scheduled_mails = ScheduledMail.objects.filter(
        status__in=[
            ScheduledMail.Status.SENT,
            ScheduledMail.Status.FAILED,
            ScheduledMail.Status.REVOKED,
        ],
        created_at__lte=threshold_date
    )
    count = scheduled_mails.count()
    if count > 0:
        # We delete individually if we want to run potential model delete hooks/signals, 
        # or just use scheduled_mails.delete() for mass deletion.
        # Keeping loop/print to match trash feedback style.
        for mail in scheduled_mails:
            mail_id = mail.id
            mail.delete()
            print(f"Deleted scheduled mail history: {mail_id}")
    return f"Cleared {count} scheduled mails history"
    
@shared_task
def auto_generate_report():
    from .services import ReportService
    from django.contrib.auth import get_user_model
    from django.core.files.base import ContentFile
    from .models import File
    
    User = get_user_model()
    
    print("[REPORT_GEN_V2] Starting monthly report generation...")
    
    for user in User.objects.filter(is_active=True):
        try:
            print(f"Generating report for: {user.email}")
            
            shares, mails = ReportService.get_queryset(user, timeline='monthly', search='')
            data = ReportService.build_response_data(shares, mails)
            csv_buffer = ReportService.generate_csv(data)
            csv_content = csv_buffer.getvalue()
            
            file_name = f"Monthly_Report_{timezone.now().strftime('%Y_%m_%d')}.csv"
            
            # Avoid duplicate reports on the same day
            File.objects.filter(
                user=user,
                original_name=file_name,
                content_type="text/csv"
            ).delete()
            
            File.objects.create(
                user=user,
                file=ContentFile(csv_content.encode('utf-8'), name=file_name),
                original_name=file_name,
                file_size=len(csv_content.encode('utf-8')),  # byte-accurate size
                content_type="text/csv"
            )
            
            print(f"Report saved for {user.email}: {file_name}")
            
            # Also email the CSV to the user
            from django.core.mail import EmailMessage
            email = EmailMessage(
                subject="Your Monthly Report",
                body=f"Hello,\n\nPlease find your monthly report ({file_name}) attached for your review. It has also been saved to your 'Files' section in the app.",
                to=[user.email],
            )
            email.attach(file_name, csv_content, "text/csv")
            email.send()
            
            print(f"Report emailed to {user.email}")
            
        except Exception as e:
            print(f"Failed for {user.email}: {e}")