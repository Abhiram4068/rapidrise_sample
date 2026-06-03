from config.wsgi import application
from files.supabase_storage import supabase
import sys

try:
    print(dir(supabase.storage.from_('files')))
except Exception as e:
    print("Error:", e)
