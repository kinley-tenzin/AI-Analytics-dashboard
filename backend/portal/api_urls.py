from django.urls import path

from . import admin_api, assistant_info, dashboards, overview, reports

app_name = "portal-api"
urlpatterns = [
    path("overview/", overview.overview, name="overview"),
    path("assistant/", assistant_info.assistant_info, name="assistant"),
    path("dashboards/", dashboards.list_dashboards, name="dashboards"),
    path("dashboards/<slug:key>/guest-token/", dashboards.guest_token, name="guest-token"),
    path("reports/", reports.list_reports, name="reports"),
    path("reports/<slug:key>/", reports.preview, name="report"),
    path("reports/<slug:key>.csv", reports.download_csv, name="report-csv"),
    path("admin/status/", admin_api.status, name="admin-status"),
    path("manage/dashboards/", admin_api.dashboards, name="manage-dashboards"),
    path("manage/dashboards/<slug:key>/", admin_api.dashboard, name="manage-dashboard"),
    path("admin/users/", admin_api.users, name="admin-users"),
]
