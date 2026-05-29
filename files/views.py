from files.serializers import StorageSummarySerializer
from files.services import StorageService
from django.conf import settings
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from django.http import FileResponse
from django.core.exceptions import ValidationError, PermissionDenied
from files.serializers import (
    RegisterSerializer, LoginSerializer, UserProfileSerializer,ChangePasswordSerialzier, DeactivateAccountSerializer, ChunkUploadSerializer, ChunkUploadStatusQuerySerializer, ChunkUploadControlSerializer, FilesListSerializer, FileUpdateSerializer ,FileShareSerializer, FileShareCreateSerializer, PublicFileSerializer,CollectionSerializer, CollectionFileSerializer
    ,ScheduledMailSerializer, FileShareListSerializer, ReportQuerySerializer, ToggleMonthlyReportSerializer, DesignationSerializer, ResetPasswordSerializer, ForgotPasswordSerializer, ReactivationRequestSerializer, DesignationChangeRequestListSerializer, DesignationChangeRequestCreateSerializer, DesignationChangeRequestAdminSerializer
    )
from files.models import ReactivationRequest, DesignationChangeRequest, ChunkUploadSession
from files.services import (
    create_user, authenticate_and_generate_token, AuthenticationError ,AuthService, UserProfileService, FileService, ChunkUploadService, FileShareService, ViewFileShareService, CollectionService, ReportService, AccountService, ThreadService, StageService, NodeService, DependencyService
    )
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import NotFound, ValidationError as DRFValidationError
from files.authentication import CookieJWTAuthentication
from files.exceptions import StorageLimitExceeded
from django.db.models import F, Sum, Q
from rest_framework import serializers
from .permissions import IsActiveAccount


import logging
logger = logging.getLogger(__name__)



def _set_auth_cookies(response, access_token, refresh_token=None):
    response.set_cookie(
        key=settings.AUTH_COOKIE_ACCESS,
        value=access_token,
        httponly=settings.AUTH_COOKIE_HTTP_ONLY,
        secure=settings.AUTH_COOKIE_SECURE,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        max_age=int(settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()),
        path="/",
    )

    if refresh_token:
        response.set_cookie(
            key=settings.AUTH_COOKIE_REFRESH,
            value=refresh_token,
            httponly=settings.AUTH_COOKIE_HTTP_ONLY,
            secure=settings.AUTH_COOKIE_SECURE,
            samesite=settings.AUTH_COOKIE_SAMESITE,
            max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
            path="/api/token/refresh/",
        )


def _clear_auth_cookies(response):
    response.delete_cookie(
        key=settings.AUTH_COOKIE_ACCESS,
        path="/",
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )
    response.delete_cookie(
        key=settings.AUTH_COOKIE_REFRESH,
        path="/api/token/refresh/",
        samesite=settings.AUTH_COOKIE_SAMESITE,
    )


class RegisterView(APIView):
    authentication_classes=[]
    permission_classes=[AllowAny]
    
    def post(self, request):
        serializer=RegisterSerializer(data=request.data)
        
        serializer.is_valid(raise_exception=True)
        try:
            create_user(serializer.validated_data)
        except ValueError as e:
            if "Email already exists" in str(e):
                return Response(
                    {'email':str(e)},
                    status=status.HTTP_400_BAD_REQUEST
                )
            return Response(
                {'error':str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        return Response(
            {'message':'User Registered successfully!!!'},
            status=status.HTTP_201_CREATED
        )

class DesignationListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        from .services import DesignationListService
        designations = DesignationListService.get_active_designations()
        serializer = DesignationSerializer(designations, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
class LoginView(APIView):
    authentication_classes=[]
    permission_classes=[AllowAny]
    
    def post(self, request):
        serializer=LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        try:
            result=authenticate_and_generate_token(
                email=serializer.validated_data['email'],
                password=serializer.validated_data['password']
            )
        except AuthenticationError as e:
            return Response(
                {'error':str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        user=result['user']
        tokens=result['tokens']
        response_data = {
            "message": "Login successful",
            "user": UserProfileSerializer(user).data,
            "account_status": user.account_status
        }
        response = Response(response_data, status=status.HTTP_200_OK)
        _set_auth_cookies(response, tokens["access"], tokens["refresh"])

        return response


class TokenRefreshCookieView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.COOKIES.get(settings.AUTH_COOKIE_REFRESH)
        if not refresh_token:
            return Response(
                {"detail": "Refresh token cookie missing"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            refresh = RefreshToken(refresh_token)
            access = str(refresh.access_token)
            user_id = refresh.payload.get('user_id')
        except TokenError:
            return Response(
                {"detail": "Invalid refresh token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        user_data = {"authenticated": True}
        if user_id:
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user = User.objects.get(id=user_id)
                
                # ✅ Check account status
                if hasattr(user, "account_status") and user.account_status in ["blocked", "deleted"]:
                    response = Response(
                        {"detail": f"Access denied. Your account is {user.account_status}."},
                        status=status.HTTP_403_FORBIDDEN
                    )
                    _clear_auth_cookies(response)
                    return response

                user_data = UserProfileSerializer(user, context={"request": request}).data
                user_data["authenticated"] = True
                user_data["account_status"] = user.account_status
            except Exception:
                pass

        response = Response({"message": "Token refreshed", "user": user_data}, status=status.HTTP_200_OK)
        _set_auth_cookies(response, access)
        return response


class LogoutView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        response = Response({"message": "Logged out"}, status=status.HTTP_200_OK)
        _clear_auth_cookies(response)
        return response

class ForgotPasswordView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Always return 200 — never reveal if the email exists
        data=AuthService.request_password_reset(serializer.validated_data["email"])
        return Response(data)

class ResetPasswordView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            AuthService.confirm_password_reset(
                uid          = serializer.validated_data["uid"],
                token        = serializer.validated_data["token"],
                new_password = serializer.validated_data["new_password"],
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"detail": "Password reset successful. You can now log in."},
            status=status.HTTP_200_OK,
        )
class UserProfileView(APIView):
    permission_classes = [IsActiveAccount]
    serializer_class = UserProfileSerializer

    def get(self, request) -> Response:
        user = UserProfileService.get_profile(user=request.user)
        serializer = self.serializer_class(user, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request) -> Response:
        user = UserProfileService.update_profile(user=request.user, data=request.data)
        serializer = self.serializer_class(user, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

class ChangePasswordView(APIView):
    permission_classes=[IsAuthenticated]
    serializer_class=ChangePasswordSerialzier
    def post(self, request):

        serializer=self.serializer_class(
            data = request.data,
            context = {'request':request}
        )
        serializer.is_valid(raise_exception=True)
        AuthService.change_password(
            data=serializer.validated_data,
            user=request.user,
            request=request
        )
        return Response(
            {"message":"Password changed successfully"},
            status=status.HTTP_200_OK
            )

class DeactivateAccountView(APIView):
    permission_classes = [IsActiveAccount]
    serializer_class = DeactivateAccountSerializer

    def post(self, request):
        print(request.data)
        serializer = self.serializer_class(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        
        AuthService.deactivate_account(user=request.user)
        
        response = Response(
            {"message": "Account deactivated successfully. You can request reactivation later if needed."},
            status=status.HTTP_200_OK
        )
        _clear_auth_cookies(response)
        return response

class ReactivationRequestView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = ReactivationRequestSerializer

    def get(self, request):
        # Admin can search through all requests, regular users see their own
        if request.user.is_staff or request.user.is_superuser:
            queryset = ReactivationRequest.objects.all().order_by('-created_at')
            search = request.query_params.get('search', '').strip()
            if search:
                queryset = queryset.filter(
                    Q(user__email__icontains=search) |
                    Q(user__first_name__icontains=search) |
                    Q(user__last_name__icontains=search) |
                    Q(reason__icontains=search)
                )
        else:
            queryset = ReactivationRequest.objects.filter(user=request.user).order_by('-created_at')

        paginator = DefaultPageNumberPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        
        if page is not None:
            serializer = self.serializer_class(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)

        serializer = self.serializer_class(queryset, many=True, context={'request': request})
        return Response(serializer.data)

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        AccountService.submit_reactivation_request(
            user=request.user,
            reason=serializer.validated_data['reason']
        )
        
        return Response(
            {"message": "Reactivation request submitted successfully. The admin will review it soon."},
            status=status.HTTP_201_CREATED
        )




class DesignationChangeRequestView(APIView):
    """
    GET  /api/designation-change/   — list the authenticated user's own requests
    POST /api/designation-change/   — submit a new designation change request
    """
    permission_classes = [IsActiveAccount]
 
    def get(self, request):
        requests = UserProfileService.get_user_designation_requests(user=request.user)
        serializer = DesignationChangeRequestListSerializer(requests, many=True)
        return Response(serializer.data)
 
    def post(self, request):
        serializer = DesignationChangeRequestCreateSerializer(
            data=request.data,
            context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
 
        try:
            request_obj = UserProfileService.create_designation_request(
                user=request.user,
                requested_designation=serializer.validated_data["requested_designation"],
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
 
        out = DesignationChangeRequestListSerializer(request_obj)
        return Response(out.data, status=status.HTTP_201_CREATED)


import time
from rest_framework.exceptions import ValidationError

class ChunkUploadView(APIView):
    permission_classes = [IsActiveAccount]

    def post(self, request):
        payload = {
            "upload_id":    request.data.get("upload_id"),
            "chunk_index":  request.data.get("chunk_index"),
            "total_chunks": request.data.get("total_chunks"),
            "file_name":    request.data.get("file_name"),
            "file_size":    request.data.get("file_size"),
            "content_type": request.data.get("content_type"),
            "file":         request.FILES.get("file"),
        }
        action = request.data.get("action")
        if action is not None and action != "":
            payload["action"] = action
        description = request.data.get("description")
        if description is not None and description != "":
            payload["description"] = description

        serializer = ChunkUploadSerializer(data=payload)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        upload_id = data["upload_id"]
        chunk_index = data["chunk_index"]
        total_chunks = data["total_chunks"]

        try:
            session = ChunkUploadService.get_or_create_session(
                user=request.user,
                upload_id=upload_id,
                file_name=data["file_name"],
                file_size=data["file_size"],
                content_type=data["content_type"],
                total_chunks=total_chunks,
                description=data.get("description"),
            )

            if session.status == ChunkUploadSession.Status.CANCELLED:
                return Response(
                    {"error": "This upload was cancelled. Start a new upload."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if session.status == ChunkUploadSession.Status.COMPLETED:
                return Response(
                    {"error": "This upload is already completed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            session = ChunkUploadService.sync_session_from_disk(session)
            already_uploaded = chunk_index in (session.chunks_received or [])

            # Storage quota check only when starting a new upload (no chunks yet)
            if chunk_index == 0 and not session.chunks_received:
                request.user.refresh_from_db()
                try:
                    serializer.validate_storage(request.user)
                except serializers.ValidationError as e:
                    return Response(e.detail, status=status.HTTP_409_CONFLICT)

            if not already_uploaded:
                save_result = ChunkUploadService.save_chunk_file(
                    upload_id, chunk_index, data["file"]
                )
                if not save_result.get("skipped"):
                    session = ChunkUploadService.mark_chunk_received(session, chunk_index)
            else:
                session = ChunkUploadService.sync_session_from_disk(session)

            progress = ChunkUploadService.progress_payload(
                session,
                extra={
                    "chunk_index": chunk_index,
                    "already_uploaded": already_uploaded,
                    "message": f"Chunk {chunk_index} received",
                },
            )

            all_chunks_ready = len(session.chunks_received or []) >= total_chunks
            is_last_chunk = chunk_index == total_chunks - 1

            if is_last_chunk and all_chunks_ready:
                result = FileService.complete_chunk_upload(
                    user=request.user,
                    upload_id=upload_id,
                    total_chunks=total_chunks,
                    file_name=data["file_name"],
                    file_size=data["file_size"],
                    content_type=data["content_type"],
                    description=data.get("description"),
                    action=data.get("action"),
                )
                progress["status"] = ChunkUploadSession.Status.COMPLETED
                progress["progress_percent"] = 100
                return Response(
                    {
                        "message": "File uploaded successfully",
                        "file": result,
                        **progress,
                    },
                    status=status.HTTP_201_CREATED,
                )

            return Response(progress, status=status.HTTP_200_OK)

        except DRFValidationError as e:
            detail = e.detail
            if isinstance(detail, dict):
                detail = {
                    k: v[0] if isinstance(v, list) and len(v) == 1 else v
                    for k, v in detail.items()
                }
            logger.warning(f"Chunk upload validation error | detail={detail}")
            return Response(detail, status=status.HTTP_409_CONFLICT)
        except StorageLimitExceeded as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Unexpected chunk upload error | error={str(e)}")
            return Response({"error": "An unexpected error occurred."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ChunkUploadStatusView(APIView):
    """GET upload progress and which chunks are already on the server."""
    permission_classes = [IsActiveAccount]

    def get(self, request):
        serializer = ChunkUploadStatusQuerySerializer(
            data={"upload_id": request.query_params.get("upload_id")}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            progress = ChunkUploadService.get_status(
                request.user, serializer.validated_data["upload_id"]
            )
            return Response(progress, status=status.HTTP_200_OK)
        except DRFValidationError as e:
            return Response(e.detail, status=status.HTTP_404_NOT_FOUND)


class ChunkUploadControlView(APIView):
    """POST pause, resume, or cancel an in-progress upload."""
    permission_classes = [IsActiveAccount]

    def post(self, request):
        serializer = ChunkUploadControlSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        upload_id = serializer.validated_data["upload_id"]
        action = serializer.validated_data["action"]

        try:
            if action == "pause":
                result = ChunkUploadService.pause_session(request.user, upload_id)
            elif action == "resume":
                result = ChunkUploadService.resume_session(request.user, upload_id)
            else:
                result = ChunkUploadService.cancel_session(request.user, upload_id)
            return Response(result, status=status.HTTP_200_OK)
        except DRFValidationError as e:
            return Response(e.detail, status=status.HTTP_404_NOT_FOUND)

# class FileUploadView(APIView):
#     permission_classes = [IsActiveAccount]

#     def post(self, request):
#         start_time = time.time()
#         logger.info(f"File upload request started | user_id={request.user.id}")

#         serializer = FileUploadSerialzier(
#             data=request.data,
#             context={'request': request}
#         )
#         if not serializer.is_valid():
#             return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

#         files = serializer.validated_data['files']
#         action = request.data.get("action")

#         try:
#             logger.info(f"{len(files)} files received for upload | user_id={request.user.id}")
#             result = FileService.upload_files(
#                 user=request.user, 
#                 files=files, 
#                 action=action, 
#                 description=request.data.get("description")
#             )
            
#             uploaded_count = len(result["uploaded"])
#             failed_count = len(result["failed"])
            
#             duration = time.time() - start_time
#             logger.info(
#                 f"File upload cycle complete | user_id={request.user.id} | "
#                 f"success={uploaded_count} | failed={failed_count} | duration={duration:.2f}s"
#             )

#             # If everything failed, might want a different status code, but 207 Multi-Status or 201 with failed list is common
#             status_code = status.HTTP_201_CREATED if uploaded_count > 0 else status.HTTP_400_BAD_REQUEST
            
#             return Response(
#                 {
#                     'message': f'{uploaded_count} file(s) uploaded, {failed_count} failed',
#                     'uploaded': result["uploaded"],
#                     'failed': result["failed"]
#                 },
#                 status=status_code
#             )

#         except ValidationError as e:
#             detail = e.detail
#             if isinstance(detail, dict):
#                 detail = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in detail.items()}
#             logger.warning(f"Validation error during upload | user_id={request.user.id} | detail={detail}")
#             return Response(detail, status=status.HTTP_409_CONFLICT)

#         except Exception as e:
#             logger.error(f"Unexpected error during file upload | user_id={request.user.id} | error={str(e)}")
#             return Response({'error': 'An unexpected error occurred during upload.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
class FileDownloadView(APIView):
    permission_classes=[IsAuthenticated]
    def get(self, request, file_id):
        return FileService.download_file(request.user, file_id)

class FileViewInlineView(APIView):
    """
    Serves the file content for inline viewing in the browser.
    """
    permission_classes = [IsActiveAccount]
    def get(self, request, file_id):
        return FileService.view_file_inline(request.user, file_id)
    

class DefaultPageNumberPagination(PageNumberPagination):
  page_size = 12
  page_size_query_param = "page_size"
  max_page_size = 100

  
class FileListView(APIView):
  permission_classes = [IsActiveAccount]
  serializer_class = FilesListSerializer
  pagination_class = DefaultPageNumberPagination
  def get(self, request):
      search = (request.query_params.get("search") or "").strip()
      qs = FileService.user_list_files(user=request.user)  # should be a queryset
      # Make sure you have a stable order
      qs = qs.order_by("-created_at")
      if search:
          # Must match serializer/view field
          qs = qs.filter(original_name__icontains=search)
      paginator = self.pagination_class()
      page_qs = paginator.paginate_queryset(qs, request, view=self)
      serializer = self.serializer_class(page_qs, many=True,  context={'request': request})
      
      return paginator.get_paginated_response(serializer.data)
  
class FileDetailView(APIView):
  
  permission_classes = [IsActiveAccount]
  serializer_class = FilesListSerializer

  def get(self, request, pk):
        
        """
        Retrieve single file details for the authenticated user.
        """

        # Service layer call
        file_obj = FileService.get_file_detail(
            user=request.user,
            file_id=pk
        )

        serializer = self.serializer_class(file_obj, context={'request': request})

        return Response(serializer.data, status=status.HTTP_200_OK)
    
class FileUpdateView(APIView):
    permission_classes = [IsActiveAccount]
    serializer_class = FileUpdateSerializer
    def patch(self, request, pk):
        """
        Update file metadata (display_name, description only)
        """

        serializer = self.serializer_class(
            data=request.data,
            partial=True
        )
        
        serializer.is_valid(raise_exception=True)
        print(serializer.validated_data)
        file_obj = FileService.get_file_detail(
            user=request.user,
            file_id=pk
        )
        updated_file_obj = FileService.update_file_details(
            file_obj=file_obj,
            data=serializer.validated_data
        )

        return Response(
            self.serializer_class(updated_file_obj).data,
            status=status.HTTP_200_OK
        )


class FileDeleteView(APIView):
    """
    View for handling deleting, viewing the recently deleted files and restoring the deleted files within the expiry
    """
    permission_classes=[IsAuthenticated]
    serializer_class=FilesListSerializer
    pagination_class = DefaultPageNumberPagination

    def delete(self, request, file_id):
        FileService.user_delete_file(
            request.user,
            file_id
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
    

    def get(self, request):
        search = request.query_params.get("search", "").strip()
        deleted_files = FileService.get_user_deleted_files(user=request.user)

        if search:
            deleted_files = deleted_files.filter(
                Q(original_name__icontains=search) |
                Q(description__icontains=search)
            )

        total_size = deleted_files.aggregate(total_size=Sum('file_size'))['total_size'] or 0

        paginator = self.pagination_class()
        try:
            page_qs = paginator.paginate_queryset(deleted_files, request, view=self)
            serializer = self.serializer_class(page_qs, many=True)
            response = paginator.get_paginated_response(serializer.data)
            response.data['total_size'] = total_size
            return response
        except NotFound:
            return Response(
                {
                    "count": deleted_files.count(),
                    "next": None,
                    "previous": None,
                    "results": [],
                    "total_size": total_size
                },
                status=status.HTTP_200_OK
            )

    def post(self, request, file_id):
        FileService.user_restore_file(
            request.user,
            file_id
        )
        return Response(
            {'detail':'File restored successfuly!'},
            status=status.HTTP_200_OK
        )

class BulkFileDeleteView(APIView):
    """
    View for bulk deleting multiple files.
    """
    permission_classes = [IsActiveAccount]

    def post(self, request):
        file_ids = request.data.get('file_ids', [])
        if not file_ids:
            return Response({"error": "No file IDs provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            count = FileService.bulk_delete_files(request.user, file_ids)
            return Response({"message": f"{count} files moved to trash"}, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
class ClearTrash(APIView):
    """
    View for handling trash clear functionality
    """
    permission_classes=[IsAuthenticated]
    serializer_class=FilesListSerializer
    def delete(self, request, file_id): 
        FileService.permanent_delete_file(user=request.user, file_id=file_id)
        return Response(
            status=status.HTTP_204_NO_CONTENT
        )

class BulkRestoreFileView(APIView):
    """
    View for bulk restoring multiple files from trash.
    """
    permission_classes = [IsActiveAccount]

    def post(self, request):
        file_ids = request.data.get('file_ids', [])
        if not file_ids:
            return Response({"error": "No file IDs provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            count = FileService.bulk_restore_deleted_files(request.user, file_ids)
            return Response({"message": f"{count} files restored from trash"}, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class EmptyTrashView(APIView):
    """
    View for permanently clearing all files in trash for the authenticated user.
    """
    permission_classes = [IsActiveAccount]

    def delete(self, request):
        try:
            count = FileService.empty_user_trash(request.user)
            return Response({"message": f"Trash emptied successfully. {count} items removed."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
class BulkUnarchiveFileView(APIView):
    """
    View for bulk unarchiving multiple files.
    """
    permission_classes = [IsActiveAccount]

    def post(self, request):
        file_ids = request.data.get('file_ids', [])
        if not file_ids:
            return Response({"error": "No file IDs provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            count = FileService.bulk_unarchive_files(request.user, file_ids)
            return Response({"message": f"{count} files restored from archive"}, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

from django.db.models import Q
class ArchiveFile(APIView):
    """
    view for handling the get method for archived files
    """
    permission_classes=[IsAuthenticated]
    serializer_class=FilesListSerializer
    pagination_class = DefaultPageNumberPagination
    def get(self, request):
        search=request.query_params.get("search", "").strip()
        archived_files=FileService.get_user_archived_files(
            user=request.user,
            search=search
        )
        total_size = archived_files.aggregate(total_size=Sum('file_size'))['total_size'] or 0

        if archived_files.exists():
            paginator = self.pagination_class()
            page_qs = paginator.paginate_queryset(archived_files, request, view=self)
            serializer=self.serializer_class(page_qs, many=True)
            response = paginator.get_paginated_response(serializer.data)
            response.data['total_size'] = total_size
            return response
        return Response({
            "count": 0,
            "next": None,
            "previous": None,
            "results": [],
            "total_size": total_size,
            "message":"No archived files found!"
        }, status=status.HTTP_200_OK)



class FileArchiveView(APIView):
    """
    View for handling archiving, viewing the archived files and restoring the archived files 
    """
    permission_classes=[IsAuthenticated]
    serializer_class=FilesListSerializer
    def post(self, request, file_id):
        FileService.user_archive_file(
            request.user,
            file_id
        )
        return Response(
            { "message": "File archived successfully"},
            status=status.HTTP_200_OK)

class FileUnarchiveView(APIView):
    """
    view for unarchive archived files
    """
    permission_classes=[IsAuthenticated]
    serializer_class=FilesListSerializer
    def post(self, request, file_id):
        FileService.user_unarchive_file(
            request.user,
            file_id
        )
        return Response(
            { "message": "File restored successfully"},
            status=status.HTTP_200_OK)

class BulkFileArchiveView(APIView):
    """
    View for bulk archiving multiple files.
    """
    permission_classes = [IsActiveAccount]

    def post(self, request):
        file_ids = request.data.get('file_ids', [])
        if not file_ids:
            return Response({"error": "No file IDs provided"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            count = FileService.bulk_archive_files(request.user, file_ids)
            return Response({"message": f"{count} files archived successfully"}, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class ArchiveDeleteFileView(APIView):
    """
    View to soft-delete archived files (supports multiple files)

    """
    permission_classes=[IsAuthenticated]
    serializer_class=FilesListSerializer
    def put(self, request):
        try:
            updated_count = FileService.delete_archived_files(
                user=request.user,
                file_ids=request.data.get('file_ids', [])
            )
            return Response(
                {"message": f"{updated_count} file(s) deleted successfully."},
                status=status.HTTP_200_OK
            )
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        
        
class FileStarredList(APIView):
    """"
    Lists all the files that are starred by the user
    """
    permission_classes=[IsAuthenticated]
    serializer_class=FilesListSerializer
    def get(self, request):
        starred_files=FileService.get_user_starred_files(request.user)
        if starred_files.exists():
            serializer = FilesListSerializer(starred_files, many=True, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(
            {"message":"No starred files!"},
            status=status.HTTP_200_OK
        )
        
class CollectionStarredList(APIView):
    """
    List all the starred collections for the auth user
    """
    permission_classes=[IsAuthenticated]
    def get(self, request):
        starred_folders=CollectionService.get_user_starred_collections(request.user)
        if starred_folders.exists():
            serializer=CollectionSerializer(starred_folders, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(
            {"message":"No starred collections!"},
            status=status.HTTP_200_OK
        )
    

class RecentView(APIView):
    """
    view for retrieving recent files for auth user
    """
    def get(self, request):
        recent_files=FileService.get_recent_files(request.user)
        if not recent_files.exists():
            return Response({"message":"No files uploaded yet"}, status=status.HTTP_204_NO_CONTENT)
        serializer=FilesListSerializer(recent_files, many=True,  context={'request': request})
        return Response({
            "files":serializer.data
        }, status=status.HTTP_200_OK)

class FileShareCreateListUpdateView(APIView):
    permission_classes = [IsActiveAccount]

    def post(self, request, file_id):
        serializer=FileShareCreateSerializer(data=request.data, context={'request': request}
)
        if serializer.is_valid():
            try:
                shares = []
                for email in serializer.validated_data['recipient_emails']:
                    share=FileShareService.create_share_token(file_id=file_id,
                                                              owner=request.user,
                                                              recipient_email=email,
                                                              expiration_datetime=serializer.validated_data['expiration_datetime'],
                                                              title=serializer.validated_data.get('title', ''),
                                                              message=serializer.validated_data.get('message', ''),
                                                              schedule_at=serializer.validated_data.get('schedule_at'),
                                                              permission=serializer.validated_data.get('permission', 'view_only'),
                                                              download_limit=serializer.validated_data.get('download_limit')  ,
                                                              view_limit=serializer.validated_data.get('view_limit')
                                                              )
                    shares.append(share)
                response_serializer=FileShareSerializer(shares, many=True, context={'request': request})
                return Response(
                    {'message':f'File shared successfully with {len(shares)} recipient(s)',
                    'data':response_serializer.data
                    },
                    status=status.HTTP_201_CREATED
                )
            except ValueError as e:
                return Response(
                    {'error':str(e)},
                    status=status.HTTP_404_NOT_FOUND
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request):
        shares=FileShareService.get_user_shares(request.user)
        total_mails_send = shares.count()

        page=int(request.query_params.get('page', 1))
        page_size=int(request.query_params.get('page_size',10))
        start=(page-1)*page_size
        end=start+page_size
        paginated_shares = shares[start:end]    
        serializer=FileShareListSerializer(paginated_shares, many=True, context={'request': request})
        return Response({
            "current_page": page,
            "total_pages": (total_mails_send + page_size - 1) ,
            "total_mails_send": total_mails_send,
            "user_data": UserProfileSerializer(request.user).data,
            "account_status": request.user.account_status,
            "data": serializer.data
        }, status=status.HTTP_200_OK)
        
        
    def put(self, request, share_id):
        """
        view for revoking the shared files
        """
        try:
            FileShareService.revoke_share(file_share_id=share_id, owner=request.user)
            return Response(
                {'message':'File revoked successfully'},
                status=status.HTTP_200_OK
            )
        except ValueError as e:
            return Response(
                {'error':str(e)},
                status=status.HTTP_404_NOT_FOUND
            )




from .serializers import BulkFileShareSerializer
from .services import FileShareService
from .serializers import ShareBundleSerializer


import traceback

class BulkFileShareView(APIView):

    permission_classes = [IsActiveAccount]

    def post(self, request):

        serializer = BulkFileShareSerializer(
            data=request.data,
            context={'request': request}
        )

        serializer.is_valid(raise_exception=True)

        print(serializer.validated_data)

        try:

            bundle = FileShareService.create_bulk_share(
                owner=request.user,
                file_ids=serializer.validated_data['file_ids'],
                recipient_emails=serializer.validated_data['recipient_emails'],
                expiration_datetime=serializer.validated_data['expiration_datetime'],
                permission=serializer.validated_data['permission'],
                title=serializer.validated_data.get('title', ''),
                message=serializer.validated_data.get('message', ''),
                schedule_at=serializer.validated_data.get('schedule_at'),
                download_limit=serializer.validated_data.get('download_limit'),
                view_limit=serializer.validated_data.get('view_limit')
            )

            response_serializer = ShareBundleSerializer(
                bundle,
                context={'request': request}
            )

            return Response(
                {
                    "message": (
                        f"{len(serializer.validated_data['file_ids'])} "
                        f"files shared successfully with "
                        f"{len(serializer.validated_data['recipient_emails'])} "
                        f"recipient(s)"
                    ),
                    "data": response_serializer.data
                },
                status=status.HTTP_201_CREATED
            )

        except ValueError as e:

            print("ValueError:", str(e))

            return Response(
                {
                    "error": str(e)
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        except Exception as e:

            print("Unexpected Error:", str(e))
            traceback.print_exc()

            return Response(
                {
                    "error": "Something went wrong while sharing files."
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )




class FileShareScheduleCreateListView(APIView):
    permission_classes = [IsActiveAccount]

    def post(self, request, file_id):
        serializer = FileShareCreateSerializer(
            data=request.data, context={'request': request}
        )
        if serializer.is_valid():
            schedule_at = serializer.validated_data.get('schedule_at')
            if not schedule_at:
                return Response(
                    {"schedule_at": ["This field is required for scheduled share."]},
                    status=status.HTTP_400_BAD_REQUEST
                )
            try:
                shares = []
                for email in serializer.validated_data['recipient_emails']:
                    share = FileShareService.create_share_token(
                        file_id=file_id,
                        owner=request.user,
                        recipient_email=email,
                        expiration_datetime=serializer.validated_data['expiration_datetime'],
                        title=serializer.validated_data.get('title', ''),
                        message=serializer.validated_data.get('message', ''),
                        schedule_at=schedule_at
                    )
                    shares.append(share)
                response_serializer = FileShareSerializer(shares, many=True, context={'request': request})
                return Response(
                    {
                        'message': f'Email scheduled successfully for {len(shares)} recipient(s)',
                        'data': response_serializer.data
                    },
                    status=status.HTTP_201_CREATED
                )
            except ValueError as e:
                return Response(
                    {'error': str(e)},
                    status=status.HTTP_404_NOT_FOUND
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request):
        status_filter = request.query_params.get('status', None)    
        result = FileShareService.get_scheduled_mails(request.user, status_filter)
        
        if not result["mails"].exists():
            return Response(
                {"message": "No scheduled mails"},
                status=status.HTTP_204_NO_CONTENT
            )
        paginator = DefaultPageNumberPagination()
        paginated_qs = paginator.paginate_queryset(result["mails"], request)
        
        serializer = ScheduledMailSerializer(
            paginated_qs, many=True, context={'request': request}
        )
        return Response(
            {
                "total": result["total"],
                 "filtered_total": result["filtered_total"],
                "pending": result["pending"],
                "completed": result["completed"],
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )
        
class FileShareScheduleCalendarView(APIView):
    permission_classes = [IsActiveAccount]

    def get(self, request):
        try:
            month = int(request.query_params.get('month', datetime.now().month))
            year  = int(request.query_params.get('year',  datetime.now().year))
        except ValueError:
            return Response(
                {"error": "month and year must be integers"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not (1 <= month <= 12):
            return Response(
                {"error": "month must be between 1 and 12"},
                status=status.HTTP_400_BAD_REQUEST
            )

        status_filter = request.query_params.get('status', None)
        mails = FileShareService.get_scheduled_mails_for_calendar(
            user=request.user,
            month=month,
            year=year,
            status_filter=status_filter
        )

        serializer = ScheduledMailSerializer(mails, many=True, context={'request': request})
        return Response(
            {
                "month": month,
                "year": year,
                "count": mails.count(),
                "data": serializer.data
            },
            status=status.HTTP_200_OK
        )

class RevokeScheduledMailView(APIView):
    permission_classes = [IsActiveAccount]

    def post(self, request, mail_id):   
        try:
            FileShareService.revoke_scheduled_mail(request.user, mail_id)
            
            return Response(
                {"message": "Scheduled email revoked successfully"},
                status=status.HTTP_200_OK
            )
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


class PublicFileAccessView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, token):
        from django.http import Http404
        try:
            share = ViewFileShareService.get_share_or_404(token)
        except Http404:
            return Response({'error': 'Share link not found or deleted.'}, status=status.HTTP_404_NOT_FOUND)
        except ValueError as e:
            error_msg = str(e)
            status_code = status.HTTP_403_FORBIDDEN
            if 'expired' in error_msg.lower():
                status_code = status.HTTP_410_GONE
            return Response({'error': error_msg}, status=status_code)

        action = request.query_params.get('action')
        if not action:
            # Return JSON metadata for initial verification & rendering
            owner = share.owner
            sender_name = owner.get_full_name() or owner.email
            sender_email = owner.email

            is_bundle = getattr(share, 'is_bundle', False)
            if not is_bundle and hasattr(share, 'file') and share.file:
                file_name = share.file.original_name
                file_size = share.file.file_size
                content_type = share.file.content_type
                accessed = getattr(share, 'accessed', False)
            else:
                bundle_obj = getattr(share, 'bundle', None) or share
                file_name = getattr(bundle_obj, 'title', '') or "Bulk Share Package"
                file_size = sum(item.file.file_size for item in bundle_obj.items.all()) if hasattr(bundle_obj, 'items') else 0
                content_type = "application/zip"
                accessed = getattr(share, 'accessed', False) if not isinstance(share, ShareBundle) else (share.download_count > 0)

            return Response({
                'file_name': file_name,
                'file_size': file_size,
                'content_type': content_type,
                'sender': sender_name,
                'sender_name': sender_name,
                'sender_email': sender_email,
                'expiration': share.expiration_datetime,
                'expiration_datetime': share.expiration_datetime,
                'permission': share.permission,
                'accessed': accessed,
                'view_limit': share.view_limit,
                'view_count': share.view_count,
                'download_limit': share.download_limit,
                'download_count': share.download_count,
            }, status=status.HTTP_200_OK)

        # Increment access count and return file only when action is requested
        ViewFileShareService.increment_access_counts(share, action)
        
        if share.is_bundle:
            file_obj, filename = ViewFileShareService.get_zip_response(share)
        else:
            file_obj, filename = ViewFileShareService.get_file_response(share)
            
        return FileResponse(file_obj, as_attachment=True, filename=filename)

from django.utils import timezone

class PublicFileVerifyView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request, token):
        serializer = PublicFileSerializer(data={'token': token})
        if not serializer.is_valid():
            error_message = next(iter(serializer.errors.values()))[0]
            
            status_code = status.HTTP_404_NOT_FOUND
            if 'expired' in str(error_message).lower():
                status_code = status.HTTP_410_GONE
            elif 'revoked' in str(error_message).lower() or 'used' in str(error_message).lower():
                status_code = status.HTTP_403_FORBIDDEN
            
            return Response({'error': str(error_message)}, status=status_code)

        share = serializer.share
        return Response({
            'file_name': share.file.original_name,
            'file_size': share.file.file_size,
            'content_type': share.file.content_type,
            'sender': share.owner.get_full_name() or share.owner.email,
            'expiration': share.expiration_datetime,
            'permission': share.permission,
            'accessed': share.accessed,
            'view_limit': share.view_limit,
            'view_count': share.view_count,
            'download_limit': share.download_limit,
            'download_count': share.download_count,
        })
            
class CollectionListCreateView(APIView):
    permission_classes = [IsActiveAccount]

    def get(self, request):
        logger.info(f"Fetching collections | user_id={request.user.id}")
        collections = CollectionService.get_user_collections(request.user)
        search = request.query_params.get('search', '').strip()

        if search:
            logger.info(f"Search applied | user_id={request.user.id} | search={search}")
            collections = collections.filter(name__icontains=search)
        sort_by = request.query_params.get('sort_by', 'created_at')
        sort_order = request.query_params.get('sort_order', 'desc')
        allowed_sort_fields = ['created_at', 'name', 'total_size', 'total_files']
        if sort_by not in allowed_sort_fields:
            sort_by = 'created_at'

        if sort_order == 'asc':
            collections = collections.order_by(sort_by)
        else:
            collections = collections.order_by(f'-{sort_by}')
        total_collections=collections.count()
        logger.info(f"Collections fetched | user_id={request.user.id} | count={total_collections}")

        serializer = CollectionSerializer(collections, many=True)
        return Response(
            {
                "total_collections":total_collections,
                "collections":serializer.data
            },             
            status=status.HTTP_200_OK
            )

    def post(self, request):
        logger.info(f"Create collection request | user_id={request.user.id}")
        serializer = CollectionSerializer(data=request.data)
        if not serializer.is_valid():
            logger.error(f"Invalid collection data | user_id={request.user.id} | errors={serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            collection = CollectionService.create_collection(
                user=request.user,
                validated_data=serializer.validated_data,
            )
            logger.info(
                f"Collection created successfully | user_id={request.user.id} | collection_id={collection.id}"
            )
        except ValidationError as e:
            logger.error(f"Validation error | user_id={request.user.id} | error={e}")
            return Response({"detail": e.detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            CollectionSerializer(collection).data,
            status=status.HTTP_201_CREATED,
        )


class CollectionDetailView(APIView):
    permission_classes = [IsActiveAccount]

    def get(self, request, collection_id):
        try:
            collection = CollectionService.get_single_collection(request.user, collection_id)
        except ValidationError as e:
            return Response({"detail": e.message}, status=status.HTTP_404_NOT_FOUND)
        serializer = CollectionSerializer(collection)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def patch(self, request, collection_id):
        serializer = CollectionSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            collection = CollectionService.update_collection(
                user=request.user,
                collection_id=collection_id,
                validated_data=serializer.validated_data,
            )
        except ValidationError as e:
            return Response({"detail": e.detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CollectionSerializer(collection).data, status=status.HTTP_200_OK)

    def delete(self, request, collection_id):
        try:
            CollectionService.delete_collection(request.user, collection_id)
        except ValidationError as e:
            return Response({"detail": e.detail}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CollectionFileView(APIView):
    permission_classes = [IsActiveAccount]
    serializer_class = CollectionFileSerializer
    pagination_class = DefaultPageNumberPagination
    
    def get(self, request, collection_id):
        """List all files inside a collection."""
        try:
            collection_files = CollectionService.get_collection_files(request.user, collection_id)
        except ValidationError as e:
            return Response({"detail": e.message}, status=status.HTTP_404_NOT_FOUND)
        search = request.query_params.get('search', '').strip()
        if search:
            collection_files = collection_files.filter(file__original_name__icontains=search)
        paginator = self.pagination_class()
        page_qs = paginator.paginate_queryset(collection_files, request, view=self)
        serializer = self.serializer_class(page_qs, many=True, context={'request': request})
        
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, collection_id, file_id):
        """Add a file to a collection."""
        serializer = CollectionFileSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            collection_file = CollectionService.add_file_to_collection(
                user=request.user,
                collection_id=collection_id,
                file_id=file_id
            )
        except ValidationError as e:
            return Response({"detail": e.detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            CollectionFileSerializer(collection_file).data,
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request, collection_id, file_id):
        """Remove a file from a collection."""
        try:
            CollectionService.remove_file_from_collection(request.user, collection_id, file_id)
        except ValidationError as e:
            return Response({"detail": e.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)



import csv
from django.http import HttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import PermissionDenied
from django.http import StreamingHttpResponse
from datetime import datetime




class ReportDownloadView(APIView):
    permission_classes = [IsActiveAccount]
    pagination_class = DefaultPageNumberPagination 

    def get(self, request):
        # Validate query params
        serializer = ReportQuerySerializer(data=request.query_params)
        
        serializer.is_valid(raise_exception=True)

        download = serializer.validated_data.get("download")
        timeline = serializer.validated_data.get("timeline")
        search = serializer.validated_data.get("search", "")
        is_toggle = serializer.validated_data.get("is_toggle")

        # Fetch data
        shares, mails = ReportService.get_queryset(request.user, timeline, search)

        # Build response
        data = ReportService.build_response_data(shares, mails)

        #dashboard metrics
        dashboard = ReportService.get_dashboard_metrics(request.user)

        # Download case
        if download:
            csv_buffer = ReportService.generate_csv(data)

            response = HttpResponse(
                csv_buffer.getvalue(),
                content_type="text/csv"
            )
            response["Content-Disposition"] = 'attachment; filename="mail_report.csv"'
            return response
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(data, request, view=self)

        paginated_response = paginator.get_paginated_response(page)
        paginated_response.data["dashboard"] = dashboard
        paginated_response.data["is_toggle"] = request.user.monthly_report_enabled

        return paginated_response

class ToggleMonthlyReportView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        serializer = ToggleMonthlyReportSerializer(
            request.user,
            data={'monthly_report_enabled': not request.user.monthly_report_enabled},
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            'monthly_report_enabled': serializer.instance.monthly_report_enabled,
            'detail': f"Monthly reports {'enabled' if serializer.instance.monthly_report_enabled else 'disabled'}."
        })

class StorageSummaryView(APIView):

    permission_classes = [IsActiveAccount]

    def get(self, request):

        summary_data = StorageService.get_storage_summary(
            user=request.user
        )

        serializer = StorageSummarySerializer(summary_data)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK
        )


class DashboardView(APIView):
    permission_classes = [IsActiveAccount]

    def get(self, request):
        from files.services import DashboardClass
        data = DashboardClass.get_dashboard_data(request.user)
        
        # Serialize active links manually since it's simple
        active_links_serialized = []
        for link in data['active_links']:
            active_links_serialized.append({
                "id": str(link.id),
                "title": f"hivedrive.io/s/{link.share_token[:6]}", # simulate shortened link
                "expiry": f"Expires on {link.expiration_datetime.strftime('%b %d')}",
                "clicks": 0, # Placeholder if no clicks field
                "active": link.is_active,
                "share_token": link.share_token
            })
            
        recent_activities_serialized = []
        for act in data['recent_activities']:
            # time formatting
            time_str = act["time"].strftime('%b %d')
            recent_activities_serialized.append({
                "id": act["id"],
                "icon": act["icon"],
                "title": act["title"],
                "sub": act["sub"],
                "time": time_str
            })
            
        response_data = {
            "kpi": data["kpi"],
            "storage_summary": data["storage_summary"],
            "active_links": active_links_serialized,
            "recent_activities": recent_activities_serialized
        }
        
        return Response(response_data, status=status.HTTP_200_OK)
    
class StorageManagementView(APIView):
    permission_classes = [IsActiveAccount]
    pagination_class = DefaultPageNumberPagination

    def get(self, request):
        from files.services import StorageManagementService
        
        filter_type = request.query_params.get('filter_type', 'category') # category, duplicates, old
        category = request.query_params.get('category', 'All')
        search = request.query_params.get('search', '')
        sort_by = request.query_params.get('sort_by', '-size')
        
        if filter_type == 'duplicates':
            files = StorageManagementService.get_duplicate_files(request.user, search, sort_by)
        elif filter_type == 'old':
            files = StorageManagementService.get_old_files(request.user, search, sort_by)
        else:
            files = StorageManagementService.get_files_by_category(request.user, category, search, sort_by)
            
        paginator = self.pagination_class()
        page_qs = paginator.paginate_queryset(files, request, view=self)
        serializer = FilesListSerializer(page_qs, many=True, context={'request': request})
        
        return paginator.get_paginated_response(serializer.data)

class StoragePermanentDeleteView(APIView):
    permission_classes = [IsActiveAccount]

    def post(self, request):
        from files.services import StorageManagementService
        
        file_ids = request.data.get('file_ids', [])
        if not file_ids:
            return Response({"error": "No file_ids provided"}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            total_freed = StorageManagementService.permanent_delete_files(request.user, file_ids)
            return Response({"message": f"Successfully deleted {len(file_ids)} files. Freed {total_freed} bytes."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)





"""
views.py — request/response only. All logic delegated to services.

URL structure:
    /api/threads/                           GET, POST
    /api/threads/<id>/                      GET, PUT, DELETE
    /api/threads/<id>/graph/                GET  (ReactFlow payload)
    /api/threads/<thread_id>/nodes/         GET, POST
    /api/nodes/<id>/                        GET, PUT, DELETE
    /api/nodes/<id>/branch/                 POST
    /api/nodes/<id>/position/               PATCH  (drag on canvas)
    /api/nodes/<id>/dependencies/           GET, POST
    /api/dependencies/<id>/                 DELETE
    /api/nodes/<id>/files/                  GET, POST
    /api/files/<id>/                        DELETE
    /api/nodes/<id>/activity/              GET
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import NodeDependency, NodeFile, ProjectNode, ProjectThread, NodeActivity, ProjectStage
from .serializers import (
    DependencySerializer,
    GraphEdgeSerializer,
    GraphNodeSerializer,
    NodeActivitySerializer,
    NodeCreateSerializer,
    NodeFileSerializer,
    NodeFileUploadSerializer,
    NodeSerializer,
    NodeUpdateSerializer,
    ThreadCreateSerializer,
    ThreadSerializer,
    ProjectStageSerializer,
)
from .services import DependencyService, FileService, NodeService, ThreadService, StageService


# ─── Thread ───────────────────────────────────────────────────────────────────

class ThreadListCreateView(APIView):
    permission_classes = [IsActiveAccount]

    def get(self, request):
        threads = ProjectThread.objects.filter(created_by=request.user)
        return Response(ThreadSerializer(threads, many=True).data)
    def post(self, request):
        serializer = ThreadCreateSerializer(
            data=request.data,
            context={"request": request}
        )

        serializer.is_valid(raise_exception=True)

        thread = ThreadService.create(
            request.user,
            serializer.validated_data
        )

        return Response(
            ThreadSerializer(thread).data,
            status=status.HTTP_201_CREATED,
        )


class ThreadDetailView(APIView):
    permission_classes = [IsActiveAccount]

    def _get_thread(self, pk, user):
        try:
            return ProjectThread.objects.get(pk=pk, created_by=user)
        except ProjectThread.DoesNotExist:
            return None

    def get(self, request, pk):
        thread = self._get_thread(pk, request.user)
        if not thread:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ThreadSerializer(thread).data)

    def put(self, request, pk):
        thread = self._get_thread(pk, request.user)
        if not thread:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ThreadSerializer(thread, data=request.data, partial=True,context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({
            "message": "Thread updated successfully.",
            "data": serializer.data
        })

    def delete(self, request, pk):

        ThreadService.delete_thread(
            request.user,
            pk
        )

        return Response(
            status=status.HTTP_204_NO_CONTENT
        )


class ThreadGraphView(APIView):
    """Returns all nodes + edges shaped for ReactFlow."""
    permission_classes = [IsActiveAccount]

    def get(self, request, pk):
        try:
            ProjectThread.objects.get(pk=pk, created_by=request.user)
        except ProjectThread.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        graph = ThreadService.get_graph(pk)
        return Response({
            "nodes": GraphNodeSerializer(graph["nodes"], many=True).data,
            "edges": GraphEdgeSerializer(graph["edges"], many=True).data,
            "stages": ProjectStageSerializer(graph["stages"], many=True).data,
        })


class ThreadStageListCreateView(APIView):
    permission_classes = [IsActiveAccount]

    def get(self, request, thread_id):
        try:
            ProjectThread.objects.get(pk=thread_id, created_by=request.user)
        except ProjectThread.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            
        stages = ProjectStage.objects.filter(thread_id=thread_id)
        return Response(ProjectStageSerializer(stages, many=True).data)

    def post(self, request, thread_id):
        try:
            thread = ProjectThread.objects.get(pk=thread_id, created_by=request.user)
        except ProjectThread.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            
        serializer = ProjectStageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        stage = serializer.save(thread=thread)
        NodeActivity.objects.create(
            stage=stage,
            actor=request.user,
            event_type=NodeActivity.EventType.CREATED,
            message=f'Stage "{stage.name}" created.',
        )
        data = ProjectStageSerializer(stage).data
        data["detail"] = f'Stage "{stage.name}" created successfully.'
        return Response(data, status=status.HTTP_201_CREATED)


class ThreadStageDetailView(APIView):
    permission_classes = [IsActiveAccount]

    def _get_stage(self, pk, user):
        try:
            return ProjectStage.objects.get(pk=pk, thread__created_by=user)
        except ProjectStage.DoesNotExist:
            return None

    def put(self, request, pk):
        stage = self._get_stage(pk, request.user)
        if not stage:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = ProjectStageSerializer(stage, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        stage = serializer.save()
        data = serializer.data
        data["detail"] = f'Stage "{stage.name}" renamed successfully.'
        return Response(data)

    def delete(self, request, pk):
        stage = self._get_stage(pk, request.user)
        if not stage:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            name = StageService.delete_stage(stage, request.user)
        except DRFValidationError as e:
            detail = e.detail.get("detail") if isinstance(e.detail, dict) else e.detail
            if isinstance(detail, list):
                detail = detail[0]
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"detail": f'Stage "{name}" deleted successfully.'},
            status=status.HTTP_200_OK,
        )


# ─── Node ─────────────────────────────────────────────────────────────────────

class NodeListCreateView(APIView):
    permission_classes = [IsActiveAccount]

    def _get_thread(self, thread_id, user):
        try:
            return ProjectThread.objects.get(pk=thread_id, created_by=user)
        except ProjectThread.DoesNotExist:
            return None

    def get(self, request, thread_id):
        thread = self._get_thread(thread_id, request.user)
        if not thread:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        nodes = ProjectNode.objects.filter(thread=thread, is_deleted=False)
        return Response(NodeSerializer(nodes, many=True).data)

    def post(self, request, thread_id):
        thread = self._get_thread(thread_id, request.user)
        if not thread:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = NodeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        node = NodeService.add_node(thread, request.user, serializer.validated_data)
        data = NodeSerializer(node).data
        data["detail"] = f'Node "{node.title}" created successfully.'
        return Response(data, status=status.HTTP_201_CREATED)


class NodeDetailView(APIView):
    permission_classes = [IsActiveAccount]

    def _get_node(self, pk, user):
        try:
            return ProjectNode.objects.get(pk=pk, thread__created_by=user, is_deleted=False)
        except ProjectNode.DoesNotExist:
            return None

    def get(self, request, pk):
        node = self._get_node(pk, request.user)
        if not node:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(NodeSerializer(node).data)

    def put(self, request, pk):
        node = self._get_node(pk, request.user)
        if not node:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = NodeUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        node = NodeService.update_node(node, request.user, serializer.validated_data)
        data = NodeSerializer(node).data
        data["detail"] = f'Node "{node.title}" updated successfully.'
        return Response(data)

    def delete(self, request, pk):
        node = self._get_node(pk, request.user)
        if not node:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if NodeService.is_root_node(node):
            return Response(
                {"detail": "The root node of a thread cannot be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            NodeService.soft_delete(node, request.user)
        except DRFValidationError as e:
            detail = e.detail.get("detail") if isinstance(e.detail, dict) else e.detail
            if isinstance(detail, list):
                detail = detail[0]
            return Response({"detail": detail}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"detail": f'Node "{node.title}" deleted successfully.'},
            status=status.HTTP_200_OK,
        )


class NodeBranchView(APIView):
    """POST /api/nodes/<id>/branch/ — create a branch diverging from this node."""
    permission_classes = [IsActiveAccount]

    def post(self, request, pk):
        try:
            parent = ProjectNode.objects.get(pk=pk, thread__created_by=request.user, is_deleted=False)
        except ProjectNode.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = NodeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        node = NodeService.add_branch(parent.thread, request.user, parent, serializer.validated_data)
        return Response(NodeSerializer(node).data, status=status.HTTP_201_CREATED)


class NodePositionView(APIView):
    """PATCH /api/nodes/<id>/position/ — update canvas position after drag."""
    permission_classes = [IsActiveAccount]

    def patch(self, request, pk):
        try:
            node = ProjectNode.objects.get(pk=pk, thread__created_by=request.user, is_deleted=False)
        except ProjectNode.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        stage = request.data.get("stage")
        row = request.data.get("row")
        if stage is None or row is None:
            return Response({"detail": "stage and row required."}, status=status.HTTP_400_BAD_REQUEST)

        NodeService.update_position(node, int(stage), int(row))
        return Response({"stage": node.stage, "row": node.row})


# ─── Dependencies ─────────────────────────────────────────────────────────────

class DependencyListCreateView(APIView):
    permission_classes = [IsActiveAccount]

    def get(self, request, node_id):
        try:
            node = ProjectNode.objects.get(pk=node_id, thread__created_by=request.user)
        except ProjectNode.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        deps = NodeDependency.objects.filter(source_node=node) | NodeDependency.objects.filter(target_node=node)
        return Response(DependencySerializer(deps, many=True).data)

    def post(self, request, node_id):
        try:
            source = ProjectNode.objects.get(pk=node_id, thread__created_by=request.user, is_deleted=False)
        except ProjectNode.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = DependencySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target_id = serializer.validated_data["target_node"].id
        try:
            target = ProjectNode.objects.get(pk=target_id, thread=source.thread, is_deleted=False)
        except ProjectNode.DoesNotExist:
            return Response({"detail": "Target node not found or belongs to a different thread."}, status=status.HTTP_404_NOT_FOUND)

        try:
            source.refresh_from_db()
            dep = DependencyService.add_dependency(
                source, target,
                serializer.validated_data.get("dependency_type", NodeDependency.DependencyType.DEPENDS_ON),
                request.user,
            )
        except DRFValidationError as e:
            msg = e.detail[0] if isinstance(e.detail, (list, dict)) else str(e.detail)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
             return Response({"detail": f"Dependency error: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

        data = DependencySerializer(dep).data
        data["detail"] = "Connection created successfully."
        return Response(data, status=status.HTTP_201_CREATED)


class DependencyDetailView(APIView):
    permission_classes = [IsActiveAccount]

    def patch(self, request, pk):
        try:
            dep = NodeDependency.objects.get(pk=pk, source_node__thread__created_by=request.user)
        except NodeDependency.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
            
        dependency_type = request.data.get("dependency_type")
        if not dependency_type:
            return Response({"detail": "dependency_type is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            dep = DependencyService.update_dependency(dep, dependency_type, request.user)
        except DRFValidationError as e:
            msg = e.detail[0] if isinstance(e.detail, (list, dict)) else str(e.detail)
            return Response({"detail": msg}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
            
        data = DependencySerializer(dep).data
        data["detail"] = "Connection updated successfully."
        return Response(data)

    def delete(self, request, pk):
        try:
            dep = NodeDependency.objects.get(pk=pk, source_node__thread__created_by=request.user)
        except NodeDependency.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        DependencyService.remove_dependency(dep, request.user)
        return Response({"detail": "Connection removed successfully."}, status=status.HTTP_200_OK)


# ─── Files ────────────────────────────────────────────────────────────────────

class NodeFileListCreateView(APIView):
    permission_classes = [IsActiveAccount]

    def get(self, request, node_id):
        try:
            node = ProjectNode.objects.get(pk=node_id, thread__created_by=request.user, is_deleted=False)
        except ProjectNode.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        files = NodeFile.objects.filter(node=node, status=NodeFile.Status.ACTIVE)
        return Response(NodeFileSerializer(files, many=True, context={"request": request}).data)

    def post(self, request, node_id):
        try:
            node = ProjectNode.objects.get(pk=node_id, thread__created_by=request.user, is_deleted=False)
        except ProjectNode.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = NodeFileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        node_file = FileService.upload(node, request.user, serializer.validated_data["file"])
        data = NodeFileSerializer(node_file, context={"request": request}).data
        data["detail"] = f'"{node_file.original_name}" uploaded successfully.'
        return Response(data, status=status.HTTP_201_CREATED)


class NodeFileDetailView(APIView):
    permission_classes = [IsActiveAccount]

    def delete(self, request, pk):
        try:
            node_file = NodeFile.objects.get(pk=pk, node__thread__created_by=request.user)
        except NodeFile.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        name = node_file.original_name
        FileService.delete_file(node_file, request.user)
        return Response(
            {"detail": f'"{name}" removed from the node successfully.'},
            status=status.HTTP_200_OK,
        )


# ─── Activity ─────────────────────────────────────────────────────────────────

class NodeActivityView(APIView):
    permission_classes = [IsActiveAccount]

    def get(self, request, node_id):
        try:
            node = ProjectNode.objects.get(pk=node_id, thread__created_by=request.user)
        except ProjectNode.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        activities = NodeActivity.objects.filter(node=node)
        return Response(NodeActivitySerializer(activities, many=True).data)