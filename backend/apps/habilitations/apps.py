from django.apps import AppConfig


class HabilitationsConfig(AppConfig):
    name = "apps.habilitations"
    label = "habilitations"

    def ready(self) -> None:
        from . import schema  # noqa: F401
