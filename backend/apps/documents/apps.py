from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    name = "apps.documents"
    label = "documents"
    verbose_name = "Documents et signature"

    def ready(self) -> None:
        from apps.reservations.conditions import enregistrer_verification

        from .services import convention_manquante

        enregistrer_verification("convention", convention_manquante)
