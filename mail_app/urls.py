from django.urls import path

from .views import parse_audit_plan_pptx, send_obs_email

urlpatterns = [
    path("send-obs-email", send_obs_email, name="api_send_obs_email"),
    path("send-obs-email/", send_obs_email, name="api_send_obs_email_slash"),
    path(
        "parse-audit-plan-pptx",
        parse_audit_plan_pptx,
        name="api_parse_audit_plan_pptx",
    ),
    path(
        "parse-audit-plan-pptx/",
        parse_audit_plan_pptx,
        name="api_parse_audit_plan_pptx_slash",
    ),
]
