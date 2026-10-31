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
        from .facturation import acompte_manquant, apres_annulation

        enregistrer_verification("acompte", acompte_manquant)
        enregistrer_verification("caution", caution_manquante)
        if preparer not in services.CROCHETS["validation"]:
            services.CROCHETS["validation"].append(preparer)
        # Séance annulée : avoir si elle était facturée, frais du barème si l'annulation est tardive (RG-08).
        if apres_annulation not in services.CROCHETS["annulation"]:
            services.CROCHETS["annulation"].append(apres_annulation)

        from apps.noyau.demo import socle

        from .demo import charger as charger_demo

        if charger_demo not in socle.EXTENSIONS:
            socle.EXTENSIONS.append(charger_demo)
