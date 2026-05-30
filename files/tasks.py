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


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_bulk_share_email(self, bundle_id):
    from .services import FileShareService
    try:
        result = FileShareService.send_bulk_share_email(bundle_id)
        if not result:
            raise ValueError("Bulk share email could not be sent.")
    except Exception as exc:
        raise self.retry(exc=exc)


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
    users = User.objects.filter(account_status=User.AccountStatus.ACTIVE, monthly_report_enabled=True)
    
    for user in users:
        print(f"Users found for reports: {user.email}")
        try:
            print(f"Generating report for: {user.email}")
            
            shares, mails = ReportService.get_queryset(user, timeline='monthly', search='')
            if not shares.exists() and not mails.exists():
                continue
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
            from django.conf import settings
            from .email_template import build_simple_notification_html, send_templated_email
            plain_body = (
                f"Hello,\n\n"
                f"Please find your monthly report ({file_name}) attached for your review. "
                f"It has also been saved to your 'Files' section in the app."
            )
            send_templated_email(
                subject="Your Monthly Report",
                body=plain_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
                attachments=[(file_name, csv_content, "text/csv")],
                content_html=build_simple_notification_html(
                    eyebrow='Monthly report',
                    title='Your report is ready',
                    paragraphs=[
                        'Your monthly activity report has been generated and attached to this email.',
                        f'File name: {file_name}',
                        "A copy has also been saved to your Files section in HiveDrive.",
                    ],
                ),
            )
            
            print(f"Report emailed to {user.email}")
            
        except Exception as e:
            print(f"Failed for {user.email}: {e}")


@shared_task
def auto_delete_users():
    from django.contrib.auth import get_user_model
    User = get_user_model()

    threshold_date = timezone.now() - timedelta(minutes=1)
    deleted_users = User.objects.filter(
        account_status=User.AccountStatus.DELETED,
        deleted_at__lte=threshold_date
    )
    count = deleted_users.count()
    for user in deleted_users:
        email = user.email
        user.delete()
        print(f"Permanently deleted user: {email}")
    return f"Permanently deleted {count} users"


@shared_task
def auto_clear_old_admin_logs():
    from administration.models import AdminLog
    threshold_date = timezone.now() - timedelta(days=30)
    logs = AdminLog.objects.filter(timestamp__lte=threshold_date)
    count = logs.count()
    logs.delete()
    print(f"Cleared {count} admin logs older than 30 days")
    return f"Cleared {count} old admin logs"