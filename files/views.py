from django.conf import settings
from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from django.http import FileResponse
from django.core.exceptions import ValidationError
from files.serializers import (
    RegisterSerializer, LoginSerializer, UserProfileSerializer,ChangePasswordSerialzier, FileUploadSerialzier, FilesListSerializer, FileUpdateSerializer ,FileShareSerializer, FileShareCreateSerializer, PublicFileSerializer,CollectionSerializer, CollectionFileSerializer
    ,ScheduledMailSerializer, FileShareListSerializer
    )
from files.services import (
    create_user, get_designation, authenticate_and_generate_token, AuthenticationError ,AuthService, UserProfileService, FileService, FileShareService, ViewFileShareService, CollectionService
    )
from rest_framework.pagination import PageNumberPagination


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
        designation = get_designation()
        return Response(designation)

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
        response = Response({
            'message':'Login successful',
            'user':{
                'id':user.id,
                'email':user.email,
                'first_name':user.first_name
                }
        },status=status.HTTP_200_OK
        )
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
        except TokenError:
            return Response(
                {"detail": "Invalid refresh token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        response = Response({"message": "Token refreshed"}, status=status.HTTP_200_OK)
        _set_auth_cookies(response, access)
        return response


class LogoutView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        response = Response({"message": "Logged out"}, status=status.HTTP_200_OK)
        _clear_auth_cookies(response)
        return response

class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]
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
        print(request.data)
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

import time
class FileUploadView(APIView):
    permission_classes=[IsAuthenticated]
    
    def post(self, request):
        
        start_time = time.time()
        logger.info(f"File upload request started | user_id={request.user.id}")

        serializer=FileUploadSerialzier(
            data=request.data,
            context={'request':request}
            )
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )
        files=serializer.validated_data['files']
       
        try:
            logger.info(f"{len(files)} files received for upload | user_id={request.user.id}")
            uploaded_files=FileService.upload_files(user=request.user, files=files) 
            duration = time.time() - start_time
            logger.info(
                f"File upload success | user_id={request.user.id} | count={len(uploaded_files)} | duration={duration}"
            )
            return Response(
                {
                    'message':f'{len(uploaded_files)} files uploaded successfully',
                    'files':uploaded_files
                },
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
            logger.error(
                f"File upload failed | user_id={request.user.id} | error={str(e)}"
            )
            return Response(
                {'error':str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
class FileDownloadView(APIView):
    permission_classes=[IsAuthenticated]
    def get(self, request, file_id):
        return FileService.download_file(request.user, file_id)
    

class DefaultPageNumberPagination(PageNumberPagination):
  page_size = 12
  page_size_query_param = "page_size"
  max_page_size = 100

  
class FileListView(APIView):
  permission_classes = [IsAuthenticated]
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
  
  permission_classes = [IsAuthenticated]
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
    permission_classes = [IsAuthenticated]
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

    def delete(self, request, file_id):
        FileService.user_delete_file(
            request.user,
            file_id
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
    

    def get(self, request):
        deleted_files=FileService.get_user_deleted_files(user=request.user)
        serializer = self.serializer_class(deleted_files, many=True)
        return Response(serializer.data)

    def post(self, request, file_id):
        FileService.user_restore_file(
            request.user,
            file_id
        )
        return Response(
            {'detail':'File restored successfuly!'},
            status=status.HTTP_200_OK
        )
class ClearTrash(APIView):
    """
    View for handling trash clear functionality
    """
    permission_classes=[IsAuthenticated]
    serializer_class=FilesListSerializer
    def delete(self, request, file_id): 
        deleted_file=FileService.get_deleted_file_by_id(user=request.user, file_id=file_id)
        deleted_file.delete()
        return Response(
            status=status.HTTP_204_NO_CONTENT
        )
    
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
            status=status.HTTP_204_NO_CONTENT)
        
        
class FileStarredList(APIView):
    """"
    Lists all the files that are starred by the user
    """
    permission_classes=[IsAuthenticated]
    serializer_class=FilesListSerializer
    def get(self, request):
        starred_files=FileService.get_user_starred_files(request.user)
        if starred_files.exists():
            serializer = FilesListSerializer(starred_files, many=True)
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
        serializer=FilesListSerializer(recent_files, many=True)
        return Response({
            "files":serializer.data
        }, status=status.HTTP_200_OK)

class FileShareCreateListUpdateView(APIView):
    permission_classes = [IsAuthenticated]

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
                                                              expiration_hours=serializer.validated_data['expiration_datetime'],
                                                              title=serializer.validated_data.get('title', ''),
                                                              message=serializer.validated_data.get('message', ''),
                                                              schedule_at=serializer.validated_data.get('schedule_at')  
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
            "total_pages": (total_mails_send + page_size - 1),
            "total_mails_send": total_mails_send,
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

class FileShareScheduleCreateListView(APIView):
    permission_classes = [IsAuthenticated]

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
                        expiration_hours=serializer.validated_data['expiration_datetime'],
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
        

class RevokeScheduledMailView(APIView):
    permission_classes = [IsAuthenticated]

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
    authentication_classes=[]
    permission_classes=[]

    def get(self, request, token):
        serializer=PublicFileSerializer(data={'token':token})
        if not serializer.is_valid():
            error_message=serializer.errors['token'][0]
            status_code=410 if 'expired' in str(error_message).lower() else 404
            return Response({'error':str(error_message)}, status=status_code)
        
        share=serializer.share
        if share.accessed:
                return Response(
                    {
                        'error': 'File has already been accessed',
                        'message': 'This shared link can only be accessed once for security reasons.'
                    },
                    status=status.HTTP_403_FORBIDDEN
                )

        ViewFileShareService.mark_as_accessed(share)

        file_obj, filename = ViewFileShareService.get_file_response(share)

        return FileResponse(
                file_obj,
                as_attachment=False,
                filename=filename
        )


logger = logging.getLogger("collections")
        
class CollectionListCreateView(APIView):
    permission_classes = [IsAuthenticated]

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
            return Response({"detail": e.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            CollectionSerializer(collection).data,
            status=status.HTTP_201_CREATED,
        )


class CollectionDetailView(APIView):
    permission_classes = [IsAuthenticated]

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
            return Response({"detail": e.message}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CollectionSerializer(collection).data, status=status.HTTP_200_OK)

    def delete(self, request, collection_id):
        try:
            CollectionService.delete_collection(request.user, collection_id)
        except ValidationError as e:
            return Response({"detail": e.message}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CollectionFileView(APIView):
    permission_classes = [IsAuthenticated]
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
            return Response({"detail": e.message}, status=status.HTTP_400_BAD_REQUEST)
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