from django.urls import path

from . import views


app_name = "requests_app"

urlpatterns = [
    path(
        "",
        views.home,
        name="home",
    ),
    path(
        "request/<int:pk>/",
        views.request_detail,
        name="request_detail",
    ),
    path(
        "request/<int:pk>/approve/",
        views.approve_request,
        name="approve_request",
    ),
    path(
        "consolidations/",
        views.consolidation_list,
        name="consolidation_list",
    ),
    path(
        "consolidations/create/",
        views.consolidation_create,
        name="consolidation_create",
    ),
    path(
        "consolidations/<int:pk>/",
        views.consolidation_detail,
        name="consolidation_detail",
    ),
    path(
        "consolidations/<int:pk>/sap-preview/",
        views.consolidation_sap_preview,
        name="consolidation_sap_preview",
    ),
    path(
        "consolidations/<int:pk>/send-to-sap/",
        views.consolidation_send_to_sap,
        name="consolidation_send_to_sap",
    ),
    path(
        "consolidations/<int:pk>/export/excel/",
        views.consolidation_export_excel,
        name="consolidation_export_excel",
    ),
    path(
        "consolidations/<int:pk>/export/csv/",
        views.consolidation_export_csv,
        name="consolidation_export_csv",
    ),
    path(
        "consolidations/<int:pk>/export/json/",
        views.consolidation_export_json,
        name="consolidation_export_json",
    ),
    path(
        "requests/<int:pk>/demo-process/",
        views.demo_process,
        name="demo_process",
    ),
    path(
    "requests/<int:pk>/gemini-process/",
    views.gemini_process,
    name="gemini_process",
    ),
]
