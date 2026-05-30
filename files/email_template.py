import html as html_module

from django.core.mail import EmailMultiAlternatives, send_mail as django_send_mail


def _esc(value) -> str:
    if value is None:
        return ''
    return html_module.escape(str(value))


def get_sender_designation(owner) -> str | None:
    if not getattr(owner, 'designation_id', None):
        return None
    designation = getattr(owner, 'designation', None)
    if designation is not None:
        return designation.name
    try:
        owner = owner.__class__.objects.select_related('designation').get(pk=owner.pk)
        return owner.designation.name if owner.designation_id else None
    except Exception:
        return None


def get_email_template(content_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>HiveDrive</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="background:#f4f4f4;padding:40px 16px;">
    <tr>
      <td align="center">
        <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="max-width:560px;">

          <!-- LOGO -->
          <tr>
            <td align="center" style="padding-bottom:24px;">
              <span style="font-size:24px;font-weight:700;color:#1a1a1a;letter-spacing:-0.5px;">
                HiveDrive
              </span>
            </td>
          </tr>

          <!-- CARD -->
          <tr>
            <td style="background:#ffffff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.08);">
              {content_html}
            </td>
          </tr>

          <!-- FOOTER -->
          <tr>
            <td style="padding-top:24px;text-align:center;">
              <p style="margin:0;font-size:12px;color:#9ca3af;line-height:1.6;">
                &copy; 2026 HiveDrive. All rights reserved.
              </p>
              <p style="margin:6px 0 0;font-size:12px;color:#9ca3af;">
                If you did not expect this email, you can safely ignore it.
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _card_body(content: str) -> str:
    return f'<div style="padding:36px 40px;">{content}</div>'


def _heading(text: str) -> str:
    return f'<h1 style="margin:0 0 8px;font-size:22px;font-weight:700;color:#1a1a1a;line-height:1.3;">{_esc(text)}</h1>'


def _subheading(text: str) -> str:
    return f'<p style="margin:0 0 8px;font-size:16px;font-weight:600;color:#1a1a1a;line-height:1.4;">{_esc(text)}</p>'


def _paragraph(text: str) -> str:
    return f'<p style="margin:0 0 16px;font-size:15px;line-height:1.7;color:#4b5563;">{_esc(text)}</p>'


def _divider() -> str:
    return '<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;"/>'


def _cta_button(text: str, url: str) -> str:
    safe_url = _esc(url)
    return f"""<table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin:24px 0;">
  <tr>
    <td align="left">
      <a href="{safe_url}" target="_blank"
        style="display:inline-block;padding:13px 32px;background:#3b82f6;
        color:#ffffff;font-size:15px;font-weight:600;text-decoration:none;border-radius:6px;
        letter-spacing:0.01em;">
        {_esc(text)}
      </a>
    </td>
  </tr>
</table>"""


def _meta_table(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return ''
    cells = ''
    for label, value in rows:
        cells += f"""<tr>
          <td style="padding:10px 0;border-bottom:1px solid #f3f4f6;font-size:12px;font-weight:600;
            text-transform:uppercase;letter-spacing:0.06em;color:#9ca3af;width:38%;vertical-align:top;">
            {_esc(label)}
          </td>
          <td style="padding:10px 0;border-bottom:1px solid #f3f4f6;font-size:14px;font-weight:500;
            color:#1a1a1a;vertical-align:top;">
            {_esc(value)}
          </td>
        </tr>"""
    return f"""<table width="100%" cellpadding="0" cellspacing="0" role="presentation"
  style="margin:20px 0 24px;background:#f9fafb;border-radius:6px;padding:4px 16px;">
  {cells}
</table>"""


def _footnote(text: str) -> str:
    return f'<p style="margin:0;font-size:13px;line-height:1.65;color:#9ca3af;">{_esc(text)}</p>'


def _sender_block(sender_name: str, sender_email: str, sender_designation: str | None = None) -> str:
    designation_html = ''
    if sender_designation:
        designation_html = (
            f'<span style="color:#6b7280;font-size:13px;"> · {_esc(sender_designation)}</span>'
        )
    return f"""<table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="margin:0 0 24px;">
  <tr>
    <td style="padding:0;">
      <p style="margin:0 0 2px;font-size:11px;font-weight:700;letter-spacing:0.08em;
        text-transform:uppercase;color:#9ca3af;">Shared by</p>
      <p style="margin:0;font-size:15px;font-weight:600;color:#1a1a1a;">
        {_esc(sender_name)}{designation_html}
      </p>
      <p style="margin:3px 0 0;font-size:13px;color:#6b7280;">{_esc(sender_email)}</p>
    </td>
  </tr>
</table>"""


def build_file_share_email_html(
    *,
    share_title: str,
    file_name: str,
    file_size_mb: float,
    sender_name: str,
    sender_email: str,
    sender_designation: str | None,
    personal_message: str | None,
    cta_url: str,
    expires_on: str,
    recipient_email: str,
) -> str:
    display_title = share_title.strip() if share_title and share_title.strip() else file_name
    content = ''
    content += _sender_block(sender_name, sender_email, sender_designation)
    content += _heading('Hi,')
    content += _subheading(display_title)
    if personal_message and personal_message.strip():
        content += _paragraph(personal_message.strip())
    content += _meta_table([
        ('File',      file_name),
        ('Size',      f'{file_size_mb:.2f} MB'),
        ('Expires',   expires_on),
        ('Recipient', recipient_email),
    ])
    content += _cta_button('Access Your File', cta_url)
    content += _divider()
    content += _footnote(
        'This link is personal. Do not forward it. '
        'You may need to verify your email to access the file.'
    )
    return _card_body(content)


def build_bulk_share_email_html(
    *,
    package_title: str,
    file_count: int,
    sender_name: str,
    sender_email: str,
    sender_designation: str | None,
    personal_message: str | None,
    cta_url: str,
    expires_on: str,
) -> str:
    title = package_title.strip() if package_title and package_title.strip() else 'Shared file package'
    content = ''
    content += _sender_block(sender_name, sender_email, sender_designation)
    content += _heading('Hi,')
    content += _subheading(title)
    if personal_message and personal_message.strip():
        content += _paragraph(personal_message.strip())
    content += _meta_table([
        ('Package',        title),
        ('Files included', str(file_count)),
        ('Format',         'ZIP archive'),
        ('Expires',        expires_on),
    ])
    content += _cta_button('Download Package', cta_url)
    content += _divider()
    content += _footnote('Download the package once to access all included files.')
    return _card_body(content)


def build_simple_notification_html(
    *,
    title: str,
    paragraphs: list[str],
    cta_text: str | None = None,
    cta_url: str | None = None,
) -> str:
    content = ''
    content += _heading('Hi,')
    content += _subheading(title)
    for para in paragraphs:
        if para.strip():
            content += _paragraph(para.strip())
    if cta_text and cta_url:
        content += _cta_button(cta_text, cta_url)
    content += _divider()
    content += _footnote('You are receiving this email from HiveDrive.')
    return _card_body(content)


def send_templated_html_mail(
    subject,
    plain_message,
    content_html,
    from_email,
    recipient_list,
    fail_silently=False,
):
    html_message = get_email_template(content_html)
    django_send_mail(
        subject=subject,
        message=plain_message,
        from_email=from_email,
        recipient_list=recipient_list,
        fail_silently=fail_silently,
        html_message=html_message,
    )


def send_templated_mail(
    subject,
    message,
    from_email,
    recipient_list,
    fail_silently=False,
):
    paragraphs = [p.strip() for p in message.strip().split('\n\n') if p.strip()]
    cta_url = None
    cta_text = None
    body_lines = []
    link_lines = []
    for block in paragraphs:
        if block.startswith('http://') or block.startswith('https://'):
            link_lines.append(block.split('\n')[0].strip())
        else:
            body_lines.append(block.replace('\n', ' '))

    if link_lines:
        cta_url = link_lines[0]
        cta_text = 'Continue'

    content = build_simple_notification_html(
        title=subject.replace(' — HiveDrive', '').strip(),
        paragraphs=body_lines,
        cta_text=cta_text,
        cta_url=cta_url,
    )
    send_templated_html_mail(
        subject, message, content, from_email, recipient_list, fail_silently
    )


def send_templated_email(
    subject,
    body,
    from_email,
    to,
    attachments=None,
    content_html=None,
):
    inner = content_html if content_html is not None else build_simple_notification_html(
        title=subject,
        paragraphs=[p.strip() for p in body.strip().split('\n\n') if p.strip()],
    )
    html_message = get_email_template(inner)
    email = EmailMultiAlternatives(subject, body, from_email, to)
    email.attach_alternative(html_message, 'text/html')
    if attachments:
        for name, content, mimetype in attachments:
            email.attach(name, content, mimetype)
    email.send()