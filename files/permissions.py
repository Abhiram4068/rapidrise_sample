from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied

class IsActiveAccount(IsAuthenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False

        blocked_statuses = [
            request.user.AccountStatus.DEACTIVATED
            ]

        if request.user.account_status in blocked_statuses:
            raise PermissionDenied(
                "Your account is deactivated."
            )

        return True