from django.apps import AppConfig


class PersonnelConfig(AppConfig):
    name = "apps.personnel"
    label = "personnel"
    verbose_name = "Personnel des équipements et application mobile"

    def ready(self) -> None:
        from apps.noyau.demo import socle

        from . import signaux  # noqa: F401 — recalcul des besoins quand les séances changent (RG-09)
        from .demo import charger as charger_demo

        if charger_demo not in socle.EXTENSIONS:
            socle.EXTENSIONS.append(charger_demo)
