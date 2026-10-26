from django.apps import AppConfig


class AccessConfig(AppConfig):
    name = "access"
    verbose_name = "Access control (roles and branch scope)"

    def ready(self) -> None:
        from . import throttle  # noqa: F401  (connects the sign-in signal receivers)
