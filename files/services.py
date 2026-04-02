from django.contrib.auth import get_user_model
from .models import User, File, FileShareLink
from django.db import transaction, IntegrityError
from rest_framework_simplejwt.tokens import RefreshToken
import hashlib
from typing import List
from django.http import FileResponse
from django.shortcuts import get_object_or_404
import secrets
from django.utils import timezone
from datetime import timedelta
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone

def create_user(validated_data):
    email=validated_data.get('email')
    if User.objects.filter(email=email).exists():
        raise ValueError("Email already exists")
    try:
        with transaction.atomic():
            return User.objects.create_user(**validated_data)
    except IntegrityError:
        raise ValueError("Unable to create user. Please try again")
    
class AuthenticationError(Exception):
    """
    Custom exception for authentication failures
    """
    pass
    
def authenticate_and_generate_token(email:str, password:str)->dict:
    try:
        user=User.objects.get(email=email)
    except User.DoesNotExist:
        raise AuthenticationError("User not found")
    if not user.check_password(password):
        raise AuthenticationError("Invalid credentials")
    if not user.is_active:
        raise AuthenticationError("Account is disabled")
    refresh=RefreshToken.for_user(user)
    return {
        'user':user,
        'tokens':{
            'access':str(refresh.access_token),
            'refresh':str(refresh)
        }
    }
    

class FileService:
    """
    Handles uploads with checksum-based deduplication,
    secure downloads with ownership validation,
    user-scoped listing, and soft deletion.
    """
    @staticmethod
    @transaction.atomic
    def upload_files(user, files:List, description=None):
        uploaded_files=[]
        for file_obj in files:
            checksum=FileService._calculate_checksum(file_obj)
            existing_file=File.objects.filter(checksum=checksum).first()
            if existing_file:
                file_instance=File.objects.create(
                    user=user,
                    file=existing_file.file,
                    original_name=file_obj.name,
                    description=description,
                    file_size=file_obj.size,
                    content_type=file_obj.content_type,
                    checksum=checksum
                )
                is_duplicate=True
            else:
                file_instance=File.objects.create(
                    user=user,
                    file=file_obj,
                    original_name=file_obj.name,
                    description=description,
                    file_size=file_obj.size,
                    content_type=file_obj.content_type,
                    checksum=checksum
                )
                is_duplicate=False
            FileService._generate_and_save_thumbnail(file_obj, file_instance)
            uploaded_files.append({
                'id':str(file_instance.id),
                'name':file_instance.original_name,
                "size": file_instance.file_size,
                "content_type": file_instance.content_type,
                "checksum": file_instance.checksum,
                "created_at": file_instance.created_at,
                "is_duplicate": is_duplicate,
            })
        return uploaded_files

    @staticmethod
    def download_file(user, file_id):
        file_obj=get_object_or_404(File, id=file_id, user=user)

        return FileResponse(
            file_obj.file.open('rb'),
            as_attachment=True,
            filename=file_obj.original_name
        )

    @staticmethod
    def user_list_files(user):
        all_files=File.objects.filter(user=user, is_deleted=False, is_archive=False)
        return all_files
    
    @staticmethod
    def get_file_detail(user, file_id):
        file_obj=get_object_or_404(
            File, user=user, id=file_id, is_deleted=False, is_archive=False
        )
        return file_obj
    
    @staticmethod
    def update_file_details(file_obj, data):
        file_obj.display_name = data.get("display_name", file_obj.display_name)
        file_obj.description = data.get("description", file_obj.description)
        file_obj.is_starred = data.get("is_starred", file_obj.is_starred)
        file_obj.save(update_fields=["display_name", "description", "updated_at","is_starred"])

        return file_obj
    
    @staticmethod
    def user_delete_file(user, file_id):
        file_obj=get_object_or_404(
            File, user=user, id=file_id, is_deleted=False
        )
        file_obj.is_deleted=True
        file_obj.deleted_at=timezone.now()
        file_obj.save(update_fields=['is_deleted', 'deleted_at'])

    @staticmethod
    def user_archive_file(user, file_id):
        file_obj=get_object_or_404(
            File, user=user, id=file_id, is_deleted=False, is_archive=False
        )
        file_obj.is_archive=True
        file_obj.save(update_fields=['is_archive'])

    @staticmethod
    def get_user_deleted_files(user):
        all_deleted_files=File.objects.filter(user=user, is_deleted=True)
        return all_deleted_files
    
    @staticmethod
    def user_restore_file(user, file_id):
        file_obj=File.objects.get(user= user, id=file_id)
        file_obj.is_deleted=False
        file_obj.save(update_fields=['is_deleted'])
        print(file_obj.is_deleted)
        return file_obj

    @staticmethod
    def _calculate_checksum(file_obj):
        hash_md5 = hashlib.md5()
        file_obj.seek(0)
        for chunk in file_obj.chunks():
            hash_md5.update(chunk)
        file_obj.seek(0)
        return hash_md5.hexdigest()
    
    @staticmethod
    def _generate_and_save_thumbnail(file_obj, file_instance):
        try:
            import os
            import io
            from PIL import Image
            from django.core.files.base import ContentFile

            name = (file_instance.original_name or "").lower()
            ct = (file_instance.content_type or "").lower()
            ext = os.path.splitext(name)[-1]

            thumb = None
            file_obj.seek(0)

            # Images
            if ct.startswith("image/") or ext in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                img = Image.open(file_obj)
                img.load()
                img.thumbnail((400, 400), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                thumb = ContentFile(buf.getvalue(), name="thumb.png")

            # PDF
            elif "pdf" in ct or ext == ".pdf":
                from pdf2image import convert_from_bytes
                file_obj.seek(0)
                pages = convert_from_bytes(file_obj.read(), first_page=1, last_page=1, size=(400, None))
                if pages:
                    buf = io.BytesIO()
                    pages[0].save(buf, format="PNG")
                    thumb = ContentFile(buf.getvalue(), name="thumb.png")

            # Office (docx, xlsx, pptx)
            elif ext in {".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"} or \
                any(x in ct for x in ["word", "excel", "powerpoint", "spreadsheet", "presentation"]):
                import subprocess, tempfile
                file_obj.seek(0)
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                    tmp.write(file_obj.read())
                    tmp_path = tmp.name
                out_dir = tempfile.mkdtemp()
                result = subprocess.run(
                    ["libreoffice", "--headless", "--convert-to", "png", "--outdir", out_dir, tmp_path],
                    capture_output=True, timeout=60
                )
                os.unlink(tmp_path)
                if result.returncode == 0:
                    png_files = sorted(f for f in os.listdir(out_dir) if f.endswith(".png"))
                    if png_files:
                        img = Image.open(os.path.join(out_dir, png_files[0]))
                        img.thumbnail((400, 400), Image.LANCZOS)
                        buf = io.BytesIO()
                        img.save(buf, format="PNG")
                        thumb = ContentFile(buf.getvalue(), name="thumb.png")

            # Video
            elif ct.startswith("video/") or ext in {".mp4", ".mov", ".mkv", ".webm"}:
                import subprocess, tempfile
                file_obj.seek(0)
                with tempfile.NamedTemporaryFile(suffix=ext or ".mp4", delete=False) as tmp:
                    tmp.write(file_obj.read())
                    tmp_path = tmp.name
                out_path = tmp_path + "_thumb.png"
                subprocess.run(
                    ["ffmpeg", "-y", "-i", tmp_path, "-ss", "00:00:01", "-vframes", "1", "-vf", "scale=400:-1", out_path],
                    capture_output=True, timeout=30
                )
                os.unlink(tmp_path)
                if os.path.exists(out_path):
                    img = Image.open(out_path)
                    img.thumbnail((400, 400), Image.LANCZOS)
                    buf = io.BytesIO()
                    img.save(buf, format="PNG")
                    thumb = ContentFile(buf.getvalue(), name="thumb.png")
                    os.unlink(out_path)

            if thumb:
                file_instance.thumbnail.save(f"thumb_{file_instance.id}.png", thumb, save=True)

        except Exception as e:
            pass  # never break the upload if thumbnail fails
            
            
    
class FileShareService:
    """
    service handles the file sharing business logic
    """
    @staticmethod
    def generate_share_token():
        return secrets.token_urlsafe(32)
    @staticmethod
    def create_share_token(file_id, owner, recipient_email, expiration_hours, message):
        """
        for creating a file token and returns a fileshare link
        """
        try:
            file=File.objects.get(id=file_id, user=owner)
        except File.DoesNotExist:
            raise ValueError("File not found or you dont have the permission")
        share_token=FileShareService.generate_share_token()
        expiration_datetime = timezone.now() + timedelta(hours=expiration_hours)

        share=FileShareLink.objects.create(
            file=file,
            owner=owner,
            recipient_email=recipient_email.lower(),
            share_token=share_token,
            expiration_datetime=expiration_datetime
        )

        email_sent=FileShareService.send_share_email(share, message)
        if not email_sent:
            print("Error")
        return share
    
    @staticmethod
    def send_share_email(share, message):
        """
        send email
        """
        email_subject = f"{share.owner.email} shared '{share.file.original_name}' with you"
        share_url = f"{settings.BACKEND_BASE_URL}/api/files/public/{share.share_token}/"

        email_body = f"""
        Hi,

        {share.owner.email} has shared a file with you.

        File: {share.file.original_name}
        Size: {share.file.file_size / (1024 * 1024):.2f} MB

        {f'Message from sender: "{message}"' if message else ''}

        Click here to access the file:
        {share_url}    def post(self, request):

        This link will expire on {share.expiration_datetime.strftime('%B %d, %Y')}.

        ⚠️ IMPORTANT: 
        - This link is personal and should not be shared with others.
        - You will need to verify your email address ({share.recipient_email}) to access the file.

        ---
        If you did not expect this file, please ignore this email.
                """
        try:
            send_mail(
                subject=email_subject,
                message=email_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[share.recipient_email],
                fail_silently=False
            )
            return True
        except Exception as e:
            print("Error sending file")
            return False
        

class ViewFileShareService:
    @staticmethod
    def get_file_response(share):
        return share.file.file.open("rb"), share.file.original_name

    
    @staticmethod
    def mark_as_accessed(share):
        if not share.accessed:
            share.accessed=True
            share.accessed_at=timezone.now()
            share.save(update_fields=["accessed", "accessed_at"])


