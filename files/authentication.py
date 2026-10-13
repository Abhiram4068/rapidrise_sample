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

        return (user, validated_token)