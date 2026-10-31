from django.apps import AppConfig


class PilotageConfig(AppConfig):
    name = "apps.pilotage"
    label = "pilotage"
    verbose_name = "Pilotage, statistiques et éditions"

    def ready(self) -> None:
        from apps.noyau.demo import socle

        from .demo import charger as charger_demo

        if charger_demo not in socle.EXTENSIONS:
            socle.EXTENSIONS.append(charger_demo)
