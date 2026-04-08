from django.urls import path
from files.views import (
    RegisterView, LoginView, TokenRefreshCookieView, LogoutView, FileUploadView, FileDownloadView, FileListView, FileUpdateView, FileArchiveView,FileDetailView,FileDeleteView, FileShareCreateView, PublicFileAccessView,
    CollectionListCreateView, CollectionDetailView, CollectionFileView, FileStarredList, CollectionStarredList, RecentView
    )
"""
    app level urls
"""
app_name='files'

urlpatterns=[
    #auth urls
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshCookieView.as_view(), name='token-refresh'),
    path('auth/logout/', LogoutView.as_view(), name='logout'),
    #file download urls
    path('files/', FileUploadView.as_view(), name='file-upload'),
    path('<uuid:file_id>/file-download/', FileDownloadView.as_view(), name='file-download'),
    path('file-list/', FileListView.as_view(), name='file-list'),
    path('files/<uuid:pk>/update/', FileUpdateView.as_view(), name='file-update'),
    path('files/<uuid:pk>/', FileDetailView.as_view(), name='file-detail'),
    path('files/<uuid:file_id>/file-delete/', FileDeleteView.as_view(), name='file-delete'),
    path('files/<uuid:file_id>/archive/', FileArchiveView.as_view(), name='file-archive'),
    path('files/view-recently-deleted/',FileDeleteView.as_view(), name='view-recently-deleted'),

    path('files/recents/',RecentView.as_view(), name='recent-files' ),
    #starred files and folders-------------------------------------------------------------------
    path('files/starred/', FileStarredList.as_view(), name='starred-files'),
    path('collections/starred/', CollectionStarredList.as_view(), name='starred-files'),
    #--------------------------------------------------------------------------------------------
    path('files/<uuid:file_id>/restore/recently-deleted/',FileDeleteView.as_view(), name='restore-recently-deleted'),
    #collection urls
    path("collections/", CollectionListCreateView.as_view()),
    path("collections/<uuid:collection_id>/", CollectionDetailView.as_view()),
    path("collections/<uuid:collection_id>/files/", CollectionFileView.as_view()),
    path("collections/<uuid:collection_id>/files/<uuid:file_id>/", CollectionFileView.as_view()),
    #file share and download urls
    path('files/<uuid:file_id>/share/', FileShareCreateView.as_view(), name='share-create'),
    path('files/public/<str:token>/', PublicFileAccessView.as_view(), name='public-file-access'),

]
