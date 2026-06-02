import base64
import requests
import logging
from django.conf import settings
from email.utils import parseaddr

logger = logging.getLogger(__name__)

class BrevoEmailService:
    @staticmethod
    def send_email(
        subject: str,
        text_content: str,
        recipient_list: list,
        html_content: str = None,
        from_email: str = None,
        attachments: list = None
    ) -> bool:
        """
        Sends an email using Brevo's Transactional Email API over HTTPS.
        
        :param subject: Email subject line.
        :param text_content: Plain text content of the email.
        :param recipient_list: List of recipient email addresses.
        :param html_content: Optional HTML content of the email.
        :param from_email: Optional sender email address. Defaults to settings.DEFAULT_FROM_EMAIL.
        :param attachments: Optional list of attachments. Each attachment should be a tuple/list:
                           (filename, content, mimetype) where content is bytes/str.
        :return: True if successful, False otherwise.
        """
        api_key = getattr(settings, "BREVO_API_KEY", None)
        if not api_key:
            logger.error("Brevo API key is not configured. Please set BREVO_API_KEY in settings.")
            return False

        # Prepare sender
        sender_email = from_email or getattr(settings, "DEFAULT_FROM_EMAIL", None)
        if not sender_email:
            logger.error("No sender email found. Please configure DEFAULT_FROM_EMAIL.")
            return False

        sender_name, sender_addr = parseaddr(sender_email)
        if not sender_addr:
            sender_addr = sender_email
        if not sender_name:
            sender_name = "HiveDrive"

        # Prepare recipients
        to_payload = []
        for recipient in recipient_list:
            if not recipient:
                continue
            rec_name, rec_addr = parseaddr(recipient)
            to_payload.append({
                "email": rec_addr or recipient,
                "name": rec_name or None
            })

        if not to_payload:
            logger.error("Recipient list is empty.")
            return False

        # Prepare payload
        payload = {
            "sender": {
                "name": sender_name,
                "email": sender_addr
            },
            "to": to_payload,
            "subject": subject,
        }

        if html_content:
            payload["htmlContent"] = html_content
        if text_content:
            payload["textContent"] = text_content

        # Process attachments
        if attachments:
            brevo_attachments = []
            for att in attachments:
                if isinstance(att, dict):
                    brevo_attachments.append(att)
                elif isinstance(att, (list, tuple)) and len(att) >= 2:
                    filename = att[0]
                    content = att[1]
                    # Encode to base64
                    if isinstance(content, str):
                        content_bytes = content.encode('utf-8')
                    else:
                        content_bytes = content
                    
                    b64_content = base64.b64encode(content_bytes).decode('utf-8')
                    brevo_attachments.append({
                        "name": filename,
                        "content": b64_content
                    })
            if brevo_attachments:
                payload["attachment"] = brevo_attachments

        headers = {
            "api-key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        url = "https://api.brevo.com/v3/smtp/email"

        try:
            logger.info(f"Sending email to {recipient_list} with subject '{subject}' via Brevo HTTPS API...")
            response = requests.post(url, json=payload, headers=headers, timeout=15)
            if response.status_code in [200, 201, 202]:
                logger.info(f"Successfully sent email to {recipient_list} via Brevo API.")
                return True
            else:
                logger.error(
                    f"Failed to send email via Brevo API. "
                    f"Status Code: {response.status_code}, Response: {response.text}"
                )
                return False
        except Exception as e:
            logger.exception(f"Exception occurred while sending email via Brevo API: {str(e)}")
            return False
