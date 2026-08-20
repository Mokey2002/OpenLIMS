from django.apps import AppConfig


class PipelinesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "pipelines"

    def ready(self):
        from . import signals  # noqa: F401
