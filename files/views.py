from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status
from django.http import FileResponse
from files.serializers import (
    RegisterSerializer, LoginSerializer, FileUploadSerialzier, FilesListSerializer, FileShareSerializer, FileShareCreateSerializer, PublicFileSerializer
    )
from files.services import (
    create_user, authenticate_and_generate_token, AuthenticationError ,FileService, FileShareService, ViewFileShareService
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
                email=serializer._validated_data['email'],
                password=serializer.validated_data['password']
            )
        except AuthenticationError as e:
            return Response(
                {'error':str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
        user=result['user']
        tokens=result['tokens']
        return Response({
            'message':'Login successful',
            'user':{
                'id':user.id,
                'email':user.email,
                'first_name':user.first_name
                },
            'tokens':tokens
        },status=status.HTTP_200_OK
        )
       
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

class FileListView(APIView):
    permission_classes=[IsAuthenticated]
    serializer_class=FilesListSerializer

    def get(self, request):
        user_files=FileService.user_list_files(
            user=request.user
        )
        serializer = self.serializer_class(user_files, many=True)

        return Response(serializer.data)

class FileDeleteView(APIView):
    permission_classes=[IsAuthenticated]
    
    def delete(self, request, file_id):
        FileService.user_delete_file(
            request.user,
            file_id
        )
        return Response(
            {"detail": "File deleted successfully"},
            status=status.HTTP_204_NO_CONTENT
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
                as_attachment=True,
                filename=filename
        )