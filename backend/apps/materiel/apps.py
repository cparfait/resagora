from django.apps import AppConfig


class MaterielConfig(AppConfig):
    name = "apps.materiel"
    label = "materiel"
    verbose_name = "Matériel des équipements"

    def ready(self) -> None:
        from apps.finances import cautions, facturation
        from apps.noyau.demo import socle
        from apps.reservations import services as reservations

        from . import signaux  # noqa: F401 — le matériel suit les séances déplacées, supprimées, refusées
        from .demo import charger as charger_demo
        from .services import apres_annulation, blocage_caution, prestations_du_dossier

        # Une réservation annulée libère son matériel ; un prêt d'un matériel facturé entre au devis (TAR-04).
        if apres_annulation not in reservations.CROCHETS["annulation"]:
            reservations.CROCHETS["annulation"].append(apres_annulation)
        if prestations_du_dossier not in facturation.SOURCES_PRESTATIONS:
            facturation.SOURCES_PRESTATIONS.append(prestations_du_dossier)
        # Pas de restitution de caution tant que du matériel est dehors ou des manquants non réglés (RG-11).
        if blocage_caution not in cautions.BLOCAGES_RESTITUTION:
            cautions.BLOCAGES_RESTITUTION.append(blocage_caution)
        if charger_demo not in socle.EXTENSIONS:
            socle.EXTENSIONS.append(charger_demo)
