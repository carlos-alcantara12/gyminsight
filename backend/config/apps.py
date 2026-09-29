from django.contrib.admin.apps import AdminConfig


class GymInsightAdminConfig(AdminConfig):
    default_site = "config.admin_site.GymInsightAdminSite"
