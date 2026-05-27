from django.urls import path
from .views import (AdminDashboardStatsView, AdminReactivationRequestListView, AdminResolveReactivationView, AdminUserListView, AdminUserDetailsView, AdminBlockUserView,
AdminViewNewUserRequests, AdminResolveNewUserRequest, AdminBlockedUserListView, AdminUnblockUserView, AdminDeletedUserListView, AdminDeleteUserView, AdminRestoreUserView,
AdminDesignationChangeRequestListView, AdminResolveDesignationChangeRequestView, AdminDesignationListCreateDeleteView, AdminDesignationDestroyView,
AdminLogListView)

urlpatterns = [
    path('stats/', AdminDashboardStatsView.as_view(), name='admin-stats'),
    path('reactivation-request/', AdminReactivationRequestListView.as_view(), name='admin-requests'),
    path('reactivation-requests/<str:pk>/resolve/', AdminResolveReactivationView.as_view(), name='admin-resolve-request'),
    path('users/', AdminUserListView.as_view(), name='admin-users'),
    path('user/<int:pk>/', AdminUserDetailsView.as_view(), name='admin-user-details'),
    path('user/<int:pk>/block/', AdminBlockUserView.as_view(), name='admin-user-block'),
    path('user/<int:pk>/unblock/', AdminUnblockUserView.as_view(), name='admin-user-unblock'),
    path('user/<int:pk>/delete/', AdminDeleteUserView.as_view(), name='admin-user-delete'),
    path('user/<int:pk>/restore/', AdminRestoreUserView.as_view(), name='admin-user-restore'),
    path('new-users/', AdminViewNewUserRequests.as_view(), name='admin-user-request-view'),
    path('new-users/<int:pk>/resolve/', AdminResolveNewUserRequest.as_view(), name='admin-resolve-new-user'),
    path('blocked-users/', AdminBlockedUserListView.as_view(), name='admin-blocked-users'),
    path('deleted-users/', AdminDeletedUserListView.as_view(), name='admin-deleted-users'),
    path('designations/', AdminDesignationListCreateDeleteView.as_view(), name='admin-designation-list-create-delete'),
    path('designations/<str:pk>/', AdminDesignationDestroyView.as_view(), name='admin-designation-destroy'),
    path('designation-requests/', AdminDesignationChangeRequestListView.as_view(), name='admin-designation-requests'),
    path('designation-requests/<int:pk>/resolve/', AdminResolveDesignationChangeRequestView.as_view(), name='admin-resolve-designation-request'),
    path('activity-logs/', AdminLogListView.as_view(), name='admin-activity-logs'),
]
