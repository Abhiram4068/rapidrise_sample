from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.contrib.auth import get_user_model
from files.models import File, ReactivationRequest
from files.serializers import ReactivationRequestSerializer, UserProfileSerializer
from django.db.models import Count, Sum

User = get_user_model()

class IsAdminUser(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user and request.user.is_staff

class AdminDashboardStatsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        total_users = User.objects.count()
        total_files = File.objects.count()
        pending_requests = ReactivationRequest.objects.filter(is_resolved=False).count()
        
        # Additional stats
        active_users = User.objects.filter(is_active=True).count()
        deactivated_users = User.objects.filter(account_status='DEACTIVATED').count()
        
        return Response({
            "total_users": total_users,
            "total_files": total_files,
            "pending_reactivation_requests": pending_requests,
            "active_users": active_users,
            "deactivated_users": deactivated_users,
        })

class AdminReactivationRequestListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        requests = ReactivationRequest.objects.all().order_by('-created_at')
        # We need a custom serializer or one that includes user details
        data = []
        for req in requests:
            data.append({
                "id": req.id,
                "user": {
                    "id": req.user.id,
                    "email": req.user.email,
                    "full_name": f"{req.user.first_name} {req.user.last_name}",
                },
                "reason": req.reason,
                "is_resolved": req.is_resolved,
                "created_at": req.created_at,
            })
        return Response(data)

class AdminResolveReactivationView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        try:
            react_req = ReactivationRequest.objects.get(pk=pk)
            action = request.data.get('action') # 'approve' or 'reject'
            
            if action == 'approve':
                user = react_req.user
                user.account_status = 'ACTIVE'
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
