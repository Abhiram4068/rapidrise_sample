from administration import serializers
from administration import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.contrib.auth import get_user_model
from files.models import File, ReactivationRequest
from files.serializers import ReactivationRequestSerializer, UserProfileSerializer
from django.db.models import Count, Sum
from .serializers import AdminUserListSerializer, DesignationChangeRequestSerializer, DesignationSerializer
from .services import AdminUserService, DesignationService
from rest_framework.pagination import PageNumberPagination
from django.db import models
from django.db.models import Q

class StandardResultsPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = 'page_size'   # allow ?page_size=24 override if needed
    max_page_size = 100

User = get_user_model()

class IsAdminUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_staff

class AdminDashboardStatsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        from .services import AdminDashboardService
        stats = AdminDashboardService.get_stats()
        return Response(stats)

class AdminReactivationRequestListView(APIView):
    permission_classes = [IsAdminUser]
    serializer_class = ReactivationRequestSerializer
    def get(self, request):
        # Admin can search through all requests, regular users see their own
        if request.user.is_staff or request.user.is_superuser:
            queryset = ReactivationRequest.objects.filter(is_resolved=False).order_by('-created_at')
            search = request.query_params.get('search', '').strip()
            if search:
                queryset = queryset.filter(
                    Q(user__email__icontains=search) |
                    Q(user__first_name__icontains=search) |
                    Q(user__last_name__icontains=search) |
                    Q(user__account_status__icontains=search) |
                    Q(reason__icontains=search)
                )
        else:
            queryset = ReactivationRequest.objects.filter(user=request.user).order_by('-created_at')

        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        
        if page is not None:
            serializer = self.serializer_class(page, many=True, context={'request': request})
            return paginator.get_paginated_response(serializer.data)

        serializer = self.serializer_class(queryset, many=True, context={'request': request})
        return Response(serializer.data)

class AdminResolveReactivationView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        try:
            react_req = ReactivationRequest.objects.get(pk=pk)
            action = request.data.get('action') # 'approve' or 'reject'
            
            if action == 'approve':
                user = react_req.user
                user.account_status = User.AccountStatus.ACTIVE
                user.save()
                
                react_req.is_resolved = True
                react_req.save()
                return Response({"message": "Account reactivated successfully"})
            elif action == 'reject':
                react_req.is_resolved = True
                react_req.save()
                return Response({"message": "Reactivation request rejected"})
            else:
                return Response({"error": "Invalid action"}, status=status.HTTP_400_BAD_REQUEST)
                
        except ReactivationRequest.DoesNotExist:
            return Response({"error": "Request not found"}, status=status.HTTP_404_NOT_FOUND)

class AdminUserListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        users = AdminUserService.get_users_for_admin()
        search = request.query_params.get('search', '').strip()
        if search:
            search_query = (
                models.Q(first_name__icontains=search) |
                models.Q(last_name__icontains=search)  |
                models.Q(email__icontains=search)      |
                models.Q(designation__icontains=search) |
                models.Q(account_status__icontains=search)
            )
            if search.lower() == 'active':
                search_query |= models.Q(is_active=True)
            elif search.lower() == 'inactive':
                search_query |= models.Q(is_active=False)
            
            users = users.filter(search_query)
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(users, request)
        serializer = AdminUserListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class AdminUserDetailsView(APIView):
    permission_classes = [IsAdminUser]
    
    def get(self, request, pk):
        user_details=AdminUserService.get_user_details(pk)
        serializer = AdminUserListSerializer(user_details, many=False)
        return Response (serializer.data)

class AdminBlockUserView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        AdminUserService.block_user(pk)
        return Response({"message": "User blocked successfully"}, status=status.HTTP_200_OK)

class AdminUnblockUserView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        AdminUserService.unblock_user(pk)
        return Response({"message": "User unblocked successfully"}, status=status.HTTP_200_OK)


class AdminViewNewUserRequests(APIView):
    permission_classes= [IsAdminUser]

    def get(self, request):
        queryset = AdminUserService.get_new_user_request()
        
        search = request.query_params.get('search', '').strip()
        if search:
            search_query = (
                models.Q(first_name__icontains=search) |
                models.Q(last_name__icontains=search) |
                models.Q(email__icontains=search) |
                models.Q(designation__icontains=search) |
                models.Q(account_status__icontains=search)
            )
            if search.lower() == 'active':
                search_query |= models.Q(is_active=True)
            
            queryset = queryset.filter(search_query)

        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(
            queryset,
            request,
            view=self
        )
        if page is not None:
            serializer = AdminUserListSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        
        serializer = AdminUserListSerializer(queryset, many=True)
        return Response(serializer.data)


class AdminResolveNewUserRequest(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        action = request.data.get('action')
        
        if not action:
            return Response({"error": "action is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            AdminUserService.resolve_new_user_request(pk, action)
            message = "User accepted successfully" if action == 'accept' else "User rejected successfully"
            return Response({"message": message}, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class AdminBlockedUserListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        users = AdminUserService.get_blocked_users()
        search = request.query_params.get('search', '').strip()
        if search:
            search_query = (
                models.Q(first_name__icontains=search) |
                models.Q(last_name__icontains=search)  |
                models.Q(email__icontains=search)      |
                models.Q(designation__icontains=search) |
                models.Q(account_status__icontains=search)
            )
            users = users.filter(search_query)
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(users, request)
        serializer = AdminUserListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

class AdminDeletedUserListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        users = AdminUserService.get_deleted_users()
        search = request.query_params.get('search', '').strip()
        if search:
            search_query = (
                models.Q(first_name__icontains=search) |
                models.Q(last_name__icontains=search)  |
                models.Q(email__icontains=search)      |
                models.Q(designation__icontains=search) |
                models.Q(account_status__icontains=search)
            )
            users = users.filter(search_query)
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(users, request)
        serializer = AdminUserListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

class AdminDeleteUserView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        AdminUserService.delete_user(pk)
        return Response({"message": "User Deleted successfully"}, status=status.HTTP_200_OK)

class AdminRestoreUserView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        try:
            AdminUserService.restore_user(pk)
            return Response({"message": "User restored successfully"}, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class AdminDesignationListCreateDeleteView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        designations = DesignationService.get_all_designations()
        serializer = DesignationSerializer(designations, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = DesignationSerializer(data=request.data)
        if serializer.is_valid():
            designation = DesignationService.create_designation(serializer.validated_data)
            return Response(
                DesignationSerializer(designation).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class AdminDesignationDestroyView(APIView):
    permission_classes = [IsAdminUser]

    def delete(self, request, pk):
        result = DesignationService.delete_designation(pk)
        return Response(result, status=status.HTTP_200_OK)

class AdminDesignationChangeRequestListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        queryset = AdminUserService.get_designation_change_requests()
        
        search = request.query_params.get('search', '').strip()
        if search:
            queryset = queryset.filter(
                models.Q(user__email__icontains=search) |
                models.Q(user__first_name__icontains=search) |
                models.Q(user__last_name__icontains=search) |
                models.Q(requested_designation__icontains=search)
            )

        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        
        if page is not None:
            serializer = DesignationChangeRequestSerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)

        serializer = DesignationChangeRequestSerializer(queryset, many=True)
        return Response(serializer.data)

class AdminResolveDesignationChangeRequestView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        action = request.data.get('action') # 'approve' or 'reject'
        
        if not action:
            return Response({"error": "action is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            AdminUserService.resolve_designation_change_request(pk, action, request.user)
            message = f"Designation change request {action}d successfully."
            return Response({"message": message}, status=status.HTTP_200_OK)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
