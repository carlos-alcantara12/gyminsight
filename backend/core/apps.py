from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Gestão da academia"

    def ready(self):
        from . import audit_signals  # noqa: F401
