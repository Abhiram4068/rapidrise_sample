from django.urls import path
from .views import AdminDashboardStatsView, AdminReactivationRequestListView, AdminResolveReactivationView

urlpatterns = [
    path('stats/', AdminDashboardStatsView.as_view(), name='admin-stats'),
    path('reactivation-requests/', AdminReactivationRequestListView.as_view(), name='admin-requests'),
    path('reactivation-requests/<int:pk>/resolve/', AdminResolveReactivationView.as_view(), name='admin-resolve-request'),
]
