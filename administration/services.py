from django.utils import timezone
from rest_framework.exceptions import NotFound
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.conf import settings
from .models import Designation
from django.shortcuts import get_object_or_404
import logging
logger = logging.getLogger(__name__)

User = get_user_model()

class AdminUserService:
    @staticmethod
    def get_users_for_admin():
        from django.db.models import Q
        allowed_statuses = [
            User.AccountStatus.ACTIVE,
            User.AccountStatus.BLOCKED,
            User.AccountStatus.DEACTIVATED
        ]
        return User.objects.filter(
    account_status__in=allowed_statuses,
    is_superuser=False,
    is_staff=False
).order_by('-date_joined').distinct()

    @staticmethod
    def get_blocked_users():
        return User.objects.filter(account_status=User.AccountStatus.BLOCKED).order_by('-date_joined')

    @staticmethod
    def unblock_user(pk):
        try:
            user = User.objects.get(pk=pk)
            user.account_status = User.AccountStatus.ACTIVE
            user.save()
            def send_email():
                try:
                    send_mail(
                        subject="Your Account has been UNBLOCKED",
message=( f"Hi {user.first_name},\n\n" "Your HiveDrive account has been reviewed and the suspension has been revoked by the administrator. " "Your account access has now been fully restored.\n\n" "You can log in and continue using the platform normally.\n\n" "Regards,\n" "HiveDrive Administration Team" ),    
                    from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                except Exception as e:
                    print(e)

            import threading
            thread = threading.Thread(target=send_email)
            thread.start()
            return user
        except User.DoesNotExist:
            raise NotFound("User not found")

    @staticmethod
    def get_user_details(pk):
        try:
            allowed_statuses = [
            User.AccountStatus.ACTIVE,
            User.AccountStatus.DEACTIVATED,
            User.AccountStatus.BLOCKED,
            User.AccountStatus.DELETED
            ]
            user_details=User.objects.get(id=pk, account_status__in=allowed_statuses, is_superuser=False)
            return user_details
        except User.DoesNotExist:
            raise NotFound("User doesnt exists or is deleted")

    @staticmethod
    def block_user(pk):
        allowed_statuses = [
            User.AccountStatus.ACTIVE,
            User.AccountStatus.DEACTIVATED
            ]
        try:
            user = User.objects.get(pk=pk, account_status__in=allowed_statuses)
            user.account_status = User.AccountStatus.BLOCKED
            user.save()
            def send_email():
                try:
                    send_mail(
                        subject="Your Account has been Blocked",
                        message=f"Hi {user.first_name},\n\nYour account has been Blocked by HiveDrive administrator.\n",
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                except Exception as e:
                    print(e)

            import threading
            thread = threading.Thread(target=send_email)
            thread.start()
            return user
        except User.DoesNotExist:
            raise NotFound("User not found")

    @staticmethod
    def get_new_user_request():
        return User.objects.filter(account_status=User.AccountStatus.WAITING_FOR_APPROVAL).order_by('-date_joined')

    @staticmethod
    def resolve_new_user_request(user_id, action):
        try:
            user = User.objects.get(id=user_id, account_status=User.AccountStatus.WAITING_FOR_APPROVAL)
            user_email=user.email
            if action == 'accept':
                user.account_status = User.AccountStatus.ACTIVE
                def send_email():
                    try:
                        send_mail(
                            subject="Your Account Request Has Been Approved",
                            message=(
                                f"Hi {user.first_name},\n\n"
                                "Your registration request has been approved by the administrator.\n"
                                "Your account is now active and you can log in to access the platform.\n\n"
                                "If you did not create this account, please contact support immediately.\n\n"
                                "Thank you."
                            ),
                            from_email=settings.DEFAULT_FROM_EMAIL,
                            recipient_list=[user_email],
                            fail_silently=False,
                        )
                    except Exception as e:
                        logger.error(f"Failed to send approval email to {user_email}: {e}")

                import threading
                threading.Thread(target=send_email).start()
            elif action == 'reject':
                user.account_status = User.AccountStatus.REJECTED
            else:
                raise ValueError("Invalid action. Must be 'accept' or 'reject'.")
            user.save()
            return user
        except User.DoesNotExist:
            raise NotFound("Pending user request not found.")

    @staticmethod
    def get_deleted_users():
        return User.objects.filter(account_status=User.AccountStatus.DELETED).order_by('-date_joined')
        
    @staticmethod
    def delete_user(pk):
        allowed_statuses = [
            User.AccountStatus.ACTIVE,
            User.AccountStatus.DEACTIVATED,
            User.AccountStatus.BLOCKED,
            ]
        try:
            user = User.objects.get(pk=pk,account_status__in=allowed_statuses)
            user.account_status = User.AccountStatus.DELETED
            user.deleted_at=timezone.now()
            user.save()
            def send_email():
                try:
                    send_mail(
                        subject="Your Account has been Deleted",
                        message=f"Hi {user.first_name},\n\nYour account has been Deleted by HiveDrive administrator.\n",
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                except Exception as e:
                    print(e)

            import threading
            thread = threading.Thread(target=send_email)
            thread.start()
            return user
        except User.DoesNotExist:
            raise NotFound("User not found")

    @staticmethod
    def restore_user(pk):
        from datetime import timedelta
        try:
            user = User.objects.get(pk=pk, account_status=User.AccountStatus.DELETED)
            if user.deleted_at and timezone.now() - user.deleted_at > timedelta(days=30):
                raise ValueError("User cannot be restored after 30 days of deletion.")
            
            user.account_status = User.AccountStatus.ACTIVE
            user.deleted_at = None
            user.save()
            def send_email():
                try:
                    send_mail(
                        subject="Your Account has been Restored",
                       message=(
                                f"Hi {user.first_name},\n\n"
                                "Your HiveDrive account has been successfully restored by the administrator. "
                                "You can now log in and continue using the platform normally.\n\n"
                                "If you experience any issues accessing your account, please contact support.\n\n"
                                "Regards,\n"
                                "HiveDrive Team"
                            ),
                                                    from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[user.email],
                        fail_silently=False,
                    )
                except Exception as e:
                    print(e)

            import threading
            thread = threading.Thread(target=send_email)
            thread.start()
            return user
        except User.DoesNotExist:
            raise NotFound("Deleted user not found.")

    @staticmethod
    def get_designation_change_requests():
        from files.models import DesignationChangeRequest
        return DesignationChangeRequest.objects.filter(status=DesignationChangeRequest.StatusChoices.PENDING).order_by('-created_at')

    @staticmethod
    def resolve_designation_change_request(pk, action, admin_user):
        from files.models import DesignationChangeRequest
        try:
            request = DesignationChangeRequest.objects.get(pk=pk, status=DesignationChangeRequest.StatusChoices.PENDING)
            
            if action == 'approve':
                user = request.user
                user.designation = request.requested_designation
                user.save()
                
                request.status = DesignationChangeRequest.StatusChoices.APPROVED
            elif action == 'reject':
                request.status = DesignationChangeRequest.StatusChoices.REJECTED
            else:
                raise ValueError("Invalid action. Must be 'approve' or 'reject'.")

            request.resolved_by = admin_user
            request.resolved_at = timezone.now()
            request.save()
            return request
        except DesignationChangeRequest.DoesNotExist:
            raise NotFound("Designation change request not found or already resolved.")

class AdminDashboardService:
    @staticmethod
    def get_stats():
        from django.utils import timezone
        from datetime import timedelta
        from files.models import ProjectNode, ReactivationRequest, File
        
        total_files = File.objects.count()
        pending_reactivation_requests = ReactivationRequest.objects.filter(is_resolved=False).count()
        
        # User stats
        active_users = User.objects.filter(account_status=User.AccountStatus.ACTIVE).count()
        deactivated_users = User.objects.filter(account_status=User.AccountStatus.DEACTIVATED).count()
        blocked_users = User.objects.filter(account_status=User.AccountStatus.BLOCKED).count()
        pending_registration_approvals = User.objects.filter(account_status=User.AccountStatus.WAITING_FOR_APPROVAL).count()
        
        # Idle users (e.g., active but haven't logged in for 30 days)
        thirty_days_ago = timezone.now() - timedelta(days=30)
        idle_users = User.objects.filter(
            account_status=User.AccountStatus.ACTIVE, 
            last_login__lt=thirty_days_ago
        ).count()

        # History pending approvals
        pending_history_approvals = ProjectNode.objects.filter(status='NEEDS_REVIEW').count()
        
        return {
            "total_files": total_files,
            "active_users": active_users,
            "deactivated_users": deactivated_users,
            "blocked_users": blocked_users,
            "idle_users": idle_users,
            "pending_deactivation_requests": pending_reactivation_requests,
            "pending_registration_approvals": pending_registration_approvals,
            "pending_history_approvals": pending_history_approvals,
        }



class DesignationService:

    @staticmethod
    def get_all_designations():
        return Designation.objects.all()
    
    @staticmethod
    def create_designation(validated_data: dict) -> Designation:
        return Designation.objects.create(**validated_data)

    @staticmethod
    def delete_designation(pk: int) -> dict:
        """Hard-delete a designation by PK."""
        designation = get_object_or_404(Designation, pk=pk)
        name = designation.name
        designation.delete()
        return {"message": f"Designation '{name}' has been removed successfully."}