from django.apps import AppConfig


class FinancesConfig(AppConfig):
    name = "apps.finances"
    label = "finances"
    verbose_name = "Tarifs, factures et cautions"

    def ready(self) -> None:
        from apps.reservations import services
        from apps.reservations.conditions import enregistrer_verification

        from . import contexte_documents  # noqa: F401 — enregistre les contextes de fusion des pièces comptables
        from .cautions import caution_manquante, preparer
        from .facturation import acompte_manquant, apres_annulation_tardive

        enregistrer_verification("acompte", acompte_manquant)
        enregistrer_verification("caution", caution_manquante)
        if preparer not in services.CROCHETS["validation"]:
            services.CROCHETS["validation"].append(preparer)
        if apres_annulation_tardive not in services.CROCHETS["annulation_tardive"]:
            services.CROCHETS["annulation_tardive"].append(apres_annulation_tardive)
