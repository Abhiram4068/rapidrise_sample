from django.urls import path
from files.views import (
    RegisterView, LoginView, TokenRefreshCookieView,DesignationListView, ChangePasswordView,LogoutView, UserProfileView, FileUploadView, ClearTrash, FileDownloadView, FileListView, FileUpdateView, ArchiveFile, FileArchiveView, FileUnarchiveView,FileDetailView,FileDeleteView, FileShareCreateListUpdateView, PublicFileAccessView,
    CollectionListCreateView, CollectionDetailView, CollectionFileView, FileStarredList, CollectionStarredList, RecentView, FileShareScheduleCreateListView, FileShareScheduleCalendarView, RevokeScheduledMailView, ReportDownloadView, ArchiveDeleteFileView
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
    path("designations/", DesignationListView.as_view(), name="designations"),
    #profile
    path('profile/', UserProfileView.as_view(), name='user-profile'),
    #password change
    path("auth/change-password/",ChangePasswordView.as_view(), name="change-password" ),
    #file download urls
    path('files/', FileUploadView.as_view(), name='file-upload'),
    path('<uuid:file_id>/file-download/', FileDownloadView.as_view(), name='file-download'),
    path('file-list/', FileListView.as_view(), name='file-list'),
    path('files/<uuid:pk>/update/', FileUpdateView.as_view(), name='file-update'),
    path('files/<uuid:pk>/', FileDetailView.as_view(), name='file-detail'),
    path('files/<uuid:file_id>/delete/', FileDeleteView.as_view(), name='file-delete'),
    path('files/view-recently-deleted/',FileDeleteView.as_view(), name='view-recently-deleted'),
    path('files/clear-trash/<uuid:file_id>/',ClearTrash.as_view(), name='clear-trash'),
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
    path('files/<uuid:file_id>/share/', FileShareCreateListUpdateView.as_view(), name='share-create'),
    path('files/<uuid:share_id>/revoke/', FileShareCreateListUpdateView.as_view(), name='share-update'),
    path('files/shares/', FileShareCreateListUpdateView.as_view(), name='user-shares'),



    path('files/<uuid:file_id>/share/schedule/', FileShareScheduleCreateListView.as_view(), name='share-schedule'),
    path('scheduled-mails/', FileShareScheduleCreateListView.as_view(), name='scheduled-mails'),
    path('scheduled-mails/calendar/', FileShareScheduleCalendarView.as_view(), name='scheduled-mails-calendar'),
    path('scheduled-mails/<uuid:mail_id>/revoke/', RevokeScheduledMailView.as_view(), name='revoke-scheduled-mail'),
    path('files/public/<str:token>/', PublicFileAccessView.as_view(), name='public-file-access'),

    #report downloads
    path('report-downloads/', ReportDownloadView.as_view(), name='report-downloads'),


    #files archive 
    path('files/<uuid:file_id>/archive/', FileArchiveView.as_view(), name='file-archive'),
    path('files/<uuid:file_id>/unarchive/', FileUnarchiveView.as_view(), name='file-unarchive'),
    path('files/archives/', ArchiveFile.as_view(), name='archives'),
    path('files/archives/delete/', ArchiveDeleteFileView.as_view(), name='archives-delete'),
    
]
