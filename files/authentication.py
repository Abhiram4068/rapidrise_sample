from django.conf import settings
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.exceptions import AuthenticationFailed


class CookieJWTAuthentication(JWTAuthentication):
    """
    Custom JWT authentication that reads access token from cookies.

    Flow:
    1. Try cookie (primary)
    2. Optionally fallback to Authorization header
    """

    def authenticate(self, request):
        raw_token = None

        # ✅ 1. Try cookie FIRST (primary auth method)
        cookie_name = getattr(settings, "AUTH_COOKIE_ACCESS", "access_token")
        raw_token = request.COOKIES.get(cookie_name)

        # ✅ 2. Optional fallback to header (only if cookie missing)
        if raw_token is None:
            header = self.get_header(request)
            if header is not None:
                raw_token = self.get_raw_token(header)

        if raw_token is None:
            return None  # No auth provided

        try:
            validated_token = self.get_validated_token(raw_token)
        except Exception:
            raise AuthenticationFailed("Invalid or expired token")

        user = self.get_user(validated_token)

        if user is None:
            raise AuthenticationFailed("User not found")

        # ✅ Check account status (e.g., Blocked, Deleted)
        # This ensures that even if a user has a valid token, they are blocked immediately
        # if their account status changes.
        if hasattr(user, "account_status"):
            # In models.py, BLOCKED is "blocked" and DELETED is "deleted"
            if user.account_status in ["blocked", "deleted"]:
                raise AuthenticationFailed(f"Access denied. Your account is {user.account_status}.")

        return (user, validated_token)