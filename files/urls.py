from django.urls import path
from files.views import (
    RegisterView, LoginView, FileUploadView, FileDownloadView, FileListView, FileDeleteView, FileShareCreateView
    )
"""
    app level urls
"""
app_name='files'

urlpatterns=[
    #auth urls
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    #file download urls
    path('file-upload', FileUploadView.as_view(), name='file-upload'),
    path('<uuid:file_id>/file-download/', FileDownloadView.as_view(), name='file-download'),
    path('file-list/', FileListView.as_view(), name='file-list'),
    path('<uuid:file_id>/file-delete/', FileDeleteView.as_view(), name='file-delete'),
    #file share and download urls
    path('files/<uuid:file_id>/share/', FileShareCreateView.as_view(), name='share-create'),
]