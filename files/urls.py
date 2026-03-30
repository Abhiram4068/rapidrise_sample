from django.urls import path
from files.views import (
    RegisterView, LoginView, TokenRefreshCookieView, LogoutView, FileUploadView, FileDownloadView, FileListView, FileDetailView,FileDeleteView, FileShareCreateView, PublicFileAccessView
    )
"""
    app level urls
"""
app_name='files'

urlpatterns=[
    #auth urls
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshCookieView.as_view(), name='token-refresh'),
    path('logout/', LogoutView.as_view(), name='logout'),
    #file download urls
    path('file-upload', FileUploadView.as_view(), name='file-upload'),
    path('<uuid:file_id>/file-download/', FileDownloadView.as_view(), name='file-download'),
    path('file-list/', FileListView.as_view(), name='file-list'),
    path('files/<uuid:pk>/', FileDetailView.as_view(), name='file-detail'),
    path('files/<uuid:file_id>/file-delete/', FileDeleteView.as_view(), name='file-delete'),
    path('files/view-recently-deleted/',FileDeleteView.as_view(), name='view-recently-deleted'),
    path('files/<uuid:file_id>/restore/recently-deleted/',FileDeleteView.as_view(), name='restore-recently-deleted'),
    #file share and download urls
    path('files/<uuid:file_id>/share/', FileShareCreateView.as_view(), name='share-create'),
    path('files/public/<str:token>/', PublicFileAccessView.as_view(), name='public-file-access'),
]
