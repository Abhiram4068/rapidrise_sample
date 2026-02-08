from django.urls import path
from files.views import (
    RegisterView, LoginView, FileUploadView
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
    path('file-upload', FileUploadView.as_view(), name='file-upload')
]