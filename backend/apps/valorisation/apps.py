from django.apps import AppConfig


class ValorisationConfig(AppConfig):
    name = "apps.valorisation"
    label = "valorisation"
    verbose_name = "Valorisation des avantages en nature"

    def ready(self) -> None:
        from apps.documents.services import APRES_SIGNATURE
        from apps.noyau.demo import socle

        from . import contexte_documents  # noqa: F401 — contexte de fusion de l'attestation (VAL-04)
        from .demo import charger as charger_demo
        from .services import deposer_attestation

        if charger_demo not in socle.EXTENSIONS:
            socle.EXTENSIONS.append(charger_demo)
        if deposer_attestation not in APRES_SIGNATURE:
            APRES_SIGNATURE.append(deposer_attestation)
