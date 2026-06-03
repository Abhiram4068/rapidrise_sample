from supabase import create_client
from django.conf import settings
from django.core.files.storage import Storage
from django.core.files.base import ContentFile
from django.utils.deconstruct import deconstructible
import mimetypes

supabase = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SERVICE_ROLE_KEY,
)

@deconstructible
class SupabaseStorage(Storage):
    def __init__(self, bucket_name='files'):
        # Fallback to 'files' if SUPABASE_BUCKET is None or not set
        setting_bucket = getattr(settings, 'SUPABASE_BUCKET', None)
        self.bucket_name = setting_bucket if setting_bucket else bucket_name
        self.client = supabase

    def _open(self, name, mode='rb'):
        # Download the file from Supabase as bytes
        file_data = self.client.storage.from_(self.bucket_name).download(name)
        return ContentFile(file_data)

    def _save(self, name, content):
        content.seek(0)
        file_bytes = content.read()
        content_type = getattr(content, 'content_type', None)
        if not content_type:
            content_type, _ = mimetypes.guess_type(name)
        if not content_type:
            content_type = 'application/octet-stream'

        file_options = {
            "content-type": content_type,
            "upsert": "true"
        }
        self.client.storage.from_(self.bucket_name).upload(name, file_bytes, file_options)
        return name

    def exists(self, name):
        try:
            path_parts = name.split('/')
            if len(path_parts) > 1:
                folder = "/".join(path_parts[:-1])
                filename = path_parts[-1]
            else:
                folder = ""
                filename = name
                
            res = self.client.storage.from_(self.bucket_name).list(folder)
            if isinstance(res, list):
                for file_obj in res:
                    if file_obj['name'] == filename:
                        return True
            return False
        except Exception:
            return False

    def url(self, name):
        try:
            # Generate a signed URL valid for 1 hour (3600 seconds)
            res = self.client.storage.from_(self.bucket_name).create_signed_url(name, 3600)
            if isinstance(res, dict):
                return res.get('signedURL', '')
            if hasattr(res, 'signed_url'):
                return res.signed_url
            if type(res) is str:
                return res
            return str(res)
        except Exception:
            return ""

    def size(self, name):
        try:
            path_parts = name.split('/')
            if len(path_parts) > 1:
                folder = "/".join(path_parts[:-1])
                filename = path_parts[-1]
            else:
                folder = ""
                filename = name
            res = self.client.storage.from_(self.bucket_name).list(folder)
            if isinstance(res, list):
                for file_obj in res:
                    if file_obj['name'] == filename:
                        return file_obj.get('metadata', {}).get('size', 0)
            return 0
        except Exception:
            return 0

    def delete(self, name):
        try:
            self.client.storage.from_(self.bucket_name).remove([name])
        except Exception:
            pass