from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()

class AdminUserListSerializer(serializers.ModelSerializer):
    total_files_uploaded = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'email', 'first_name', 'last_name', 'designation', 
            'account_status', 'is_staff', 'is_superuser', 'is_active', 
            'storage_limit_bytes', 'storage_used_bytes', 'date_joined',
            'last_login', 'total_files_uploaded'
        ]

    def get_total_files_uploaded(self, obj):
        return obj.files.filter(is_deleted=False).count()
