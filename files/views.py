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
    RegisterSerializer, LoginSerializer, FileUploadSerialzier, FilesListSerializer, FileUpdateSerializer ,FileShareSerializer, FileShareCreateSerializer, PublicFileSerializer,CollectionSerializer, CollectionFileSerializer
    )
from files.services import (
    create_user, authenticate_and_generate_token, AuthenticationError ,FileService, FileShareService, ViewFileShareService, CollectionService
    )
from rest_framework.pagination import PageNumberPagination

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
        print(serializer.validated_data)
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

       
class FileUploadView(APIView):
    permission_classes=[IsAuthenticated]
    
    def post(self, request):
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
        description = serializer.validated_data.get("description")
        try:
            uploaded_files=FileService.upload_files(user=request.user, files=files, description=description) 
            return Response(
                {
                    'message':f'{len(uploaded_files)} files uploaded successfully',
                    'files':uploaded_files
                },
                status=status.HTTP_201_CREATED
            )
        except Exception as e:
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
      serializer = self.serializer_class(page_qs, many=True)
      
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

        serializer = self.serializer_class(file_obj)

        return Response(serializer.data, status=status.HTTP_200_OK)
    
class FileUpdateView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = FileUpdateSerializer
    def patch(self, request, pk):
        """
        Update file metadata (display_name, description only)
        """
        print(request.data)
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
    

class FileShareCreateView(APIView):
    permission_classes=[IsAuthenticated]

    def post(self, request, file_id):
        serializer=FileShareCreateSerializer(data=request.data, context={'request': request}
)
        if serializer.is_valid():
            try:
                share=FileShareService.create_share_token(file_id=file_id,
                                                          owner=request.user,
                                                          recipient_email=serializer.validated_data['recipient_email'],
                                                          expiration_hours=serializer.validated_data['expiration_datetime'],
                                                          message=serializer.validated_data.get('message', '')
                                                          )
                response_serializer=FileShareSerializer(share, context={'request': request}
)
                return Response(
                    {'message':'File shared successfully',
                    'data':response_serializer.data
                    },
                    status=status.HTTP_201_CREATED
                )
            except ValueError as e:
                return Response(
                    {'error':str(e)},
                    status=status.HTTP_404_OT_FOUND
                )
        return Response(serializer.errors, status=400)
    

class PublicFileAccessView(APIView):
    permission_classes=[]

    def get(self, request, token):
        serializer=PublicFileSerializer(data={'token':token})
        if not serializer.is_valid():
            error_message=serializer.errors['token'][0]
            status_code=410 if 'expired' in str(error_message).lower() else 404
            return Response({'error':str(error_message)}, status=status_code)
        
        share=serializer.share

        ViewFileShareService.mark_as_accessed(share)

        file_obj, filename = ViewFileShareService.get_file_response(share)

        return FileResponse(
                file_obj,
                as_attachment=False,
                filename=filename
        )
        
        
class CollectionListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):

        collections = CollectionService.get_user_collections(request.user)
        total_collections=collections.count()
        serializer = CollectionSerializer(collections, many=True)
        return Response(
            {
                "total_collections":total_collections,
                "collections":serializer.data
            },             
            status=status.HTTP_200_OK
            )

    def post(self, request):
        serializer = CollectionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            collection = CollectionService.create_collection(
                user=request.user,
                validated_data=serializer.validated_data,
            )
        except ValidationError as e:
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
        print(serializer.data)
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
    
    def get(self, request, collection_id):
        """List all files inside a collection."""
        try:
            collection_files = CollectionService.get_collection_files(request.user, collection_id)
            total_files=collection_files.count()
        except ValidationError as e:
            return Response({"detail": e.message}, status=status.HTTP_404_NOT_FOUND)
        
        serializer = CollectionFileSerializer(collection_files, many=True)
        
        return Response(
           {"collection_files": serializer.data,
            "count":total_files
            },
           
            status=status.HTTP_200_OK
            )

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