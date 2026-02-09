from django.urls import path
from files.views import (
    RegisterView, LoginView, FileUploadView, FileDownloadView
    )
"""
    app level urls
"""
app_name='files'

urlpatterns=[
    #auth urls
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    #file sharing urls
    path('file-upload', FileUploadView.as_view(), name='file-upload'),
    path('<str:file_id>/file-download/', FileDownloadView.as_view(), name='file-download')
]