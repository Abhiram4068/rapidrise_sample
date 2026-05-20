from django.urls import path
from files.views import (
    RegisterView, LoginView, TokenRefreshCookieView,DesignationListView, ChangePasswordView,LogoutView, ForgotPasswordView,ResetPasswordView,UserProfileView, FileUploadView, ChunkUploadView, ClearTrash, FileDownloadView, FileViewInlineView, FileListView, FileUpdateView, ArchiveFile, FileArchiveView, FileUnarchiveView,FileDetailView,FileDeleteView, FileShareCreateListUpdateView, PublicFileAccessView,
    CollectionListCreateView, CollectionDetailView, CollectionFileView, FileStarredList, CollectionStarredList, RecentView, FileShareScheduleCreateListView, FileShareScheduleCalendarView, RevokeScheduledMailView, ReportDownloadView, ArchiveDeleteFileView, StorageSummaryView, DashboardView, StorageManagementView, StoragePermanentDeleteView,
    DeactivateAccountView, ReactivationRequestView, ReactivationResolveView, BulkFileDeleteView, BulkFileArchiveView
    )
from . import views
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
    path("auth/forgot-password/",         ForgotPasswordView.as_view()),
    path("auth/reset-password/confirm/",  ResetPasswordView.as_view()),
    #profile
    path('profile/', UserProfileView.as_view(), name='user-profile'),
    path('auth/deactivate/', DeactivateAccountView.as_view(), name='deactivate_account'),
    path('auth/reactivation-request/', ReactivationRequestView.as_view(), name='reactivation_request'),
    path('auth/reactivation-request/<str:pk>/resolve/', ReactivationResolveView.as_view(), name='reactivation_resolve'),
    #password change
    path("auth/change-password/",ChangePasswordView.as_view(), name="change-password" ),
    #file download urls
    path('files/', FileUploadView.as_view(), name='file-upload'),
    path('files/upload/chunk/', ChunkUploadView.as_view(), name='chunk-upload'),
    path('<uuid:file_id>/file-download/', FileDownloadView.as_view(), name='file-download'),
    path('<uuid:file_id>/file-view-inline/', FileViewInlineView.as_view(), name='file-view-inline'),
    path('file-list/', FileListView.as_view(), name='file-list'),
    path('files/<uuid:pk>/update/', FileUpdateView.as_view(), name='file-update'),
    path('files/<uuid:pk>/', FileDetailView.as_view(), name='file-detail'),
    path('files/bulk-delete/', BulkFileDeleteView.as_view(), name='bulk-file-delete'),
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
    path('files/bulk-archive/', BulkFileArchiveView.as_view(), name='bulk-file-archive'),
    path('files/<uuid:file_id>/archive/', FileArchiveView.as_view(), name='file-archive'),
    path('files/<uuid:file_id>/unarchive/', FileUnarchiveView.as_view(), name='file-unarchive'),
    path('files/archives/', ArchiveFile.as_view(), name='archives'),
    path('files/archives/delete/', ArchiveDeleteFileView.as_view(), name='archives-delete'),

    #storage
    path("storage/summary/",StorageSummaryView.as_view(),name="storage-summary"),
    path("storage/manage/", StorageManagementView.as_view(), name="storage-manage"),
    path("storage/permanent-delete/", StoragePermanentDeleteView.as_view(), name="storage-permanent-delete"),
    
    #dashboard
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    # Threads
    path("threads/", views.ThreadListCreateView.as_view(), name="thread-list-create"),
    path("threads/<int:pk>/", views.ThreadDetailView.as_view(), name="thread-detail"),
    path("threads/<int:pk>/graph/", views.ThreadGraphView.as_view(), name="thread-graph"),
    path("threads/<int:thread_id>/stages/", views.ThreadStageListCreateView.as_view(), name="thread-stage-list-create"),
    path("stages/<int:pk>/", views.ThreadStageDetailView.as_view(), name="thread-stage-detail"),
 
    # Nodes (scoped to a thread)
    path("threads/<int:thread_id>/nodes/", views.NodeListCreateView.as_view(), name="node-list-create"),
 
    # Node detail operations
    path("nodes/<int:pk>/", views.NodeDetailView.as_view(), name="node-detail"),
    path("nodes/<int:pk>/branch/", views.NodeBranchView.as_view(), name="node-branch"),
    path("nodes/<int:pk>/position/", views.NodePositionView.as_view(), name="node-position"),
 
    # Dependencies
    path("nodes/<int:node_id>/dependencies/", views.DependencyListCreateView.as_view(), name="dependency-list-create"),
    path("dependencies/<int:pk>/", views.DependencyDetailView.as_view(), name="dependency-detail"),
 
    # Files
    path("nodes/<int:node_id>/files/", views.NodeFileListCreateView.as_view(), name="file-list-create"),
    path("files/<int:pk>/", views.NodeFileDetailView.as_view(), name="file-detail"),
 
    # Activity feed
    path("nodes/<int:node_id>/activity/", views.NodeActivityView.as_view(), name="node-activity"),
]

