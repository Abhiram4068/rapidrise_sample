from rest_framework import serializers
from django.contrib.auth import get_user_model
from files.models import DesignationChangeRequest

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


from .models import Designation


class DesignationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Designation
        fields = ['id', 'name','created_at']
        read_only_fields = ['id', 'created_at']

    def validate_name(self, value):
        value = value.strip()
        qs = Designation.objects.filter(name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                f"A designation with the name '{value}' already exists."
            )
        return value

class DesignationChangeRequestSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_full_name = serializers.SerializerMethodField()
    current_designation_display = serializers.CharField(source='get_current_designation_display', read_only=True)
    requested_designation_display = serializers.CharField(source='get_requested_designation_display', read_only=True)
    resolved_by_email = serializers.EmailField(source='resolved_by.email', read_only=True)

    class Meta:
        model = DesignationChangeRequest
        fields = [
            'id', 'user', 'user_email', 'user_full_name',
            'current_designation', 'current_designation_display',
            'requested_designation', 'requested_designation_display',
            'status', 'admin_note', 'created_at', 'resolved_at',
            'resolved_by', 'resolved_by_email'
        ]

    def get_user_full_name(self, obj):
        return f"{obj.user.first_name} {obj.user.last_name}".strip()


