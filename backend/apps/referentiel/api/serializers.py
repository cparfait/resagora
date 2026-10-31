from __future__ import annotations

from typing import Any

from rest_framework import serializers

from ..models import Batiment, Espace, FamilleEspace, Site


class SiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = ["id", "code", "nom", "adresse", "code_postal", "commune", "telephone", "actif"]


class BatimentSerializer(serializers.ModelSerializer):
    site_nom = serializers.CharField(source="site.nom", read_only=True)

    class Meta:
        model = Batiment
        fields = ["id", "site", "site_nom", "nom", "erp_categorie", "erp_type", "actif"]


class FamilleEspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = FamilleEspace
        fields = ["id", "code", "libelle", "ordre"]


class EspaceSerializer(serializers.ModelSerializer):
    site = serializers.IntegerField(source="batiment.site_id", read_only=True)
    site_nom = serializers.CharField(source="batiment.site.nom", read_only=True)
    batiment_nom = serializers.CharField(source="batiment.nom", read_only=True)
    famille_libelle = serializers.CharField(source="famille.libelle", read_only=True)

    class Meta:
        model = Espace
        fields = [
            "id",
            "code",
            "nom",
            "batiment",
            "batiment_nom",
            "site",
            "site_nom",
            "parent",
            "famille",
            "famille_libelle",
            "description",
            "capacite",
            "surface_m2",
            "accessible_pmr",
            "equipements",
            "activites",
            "gardiennage_requis",
            "temps_ouverture_min",
            "temps_fermeture_min",
            "partageable",
            "capacite_simultanee",
            "reservable_portail",
            "actif",
        ]

    def validate(self, donnees: dict[str, Any]) -> dict[str, Any]:
        parent = donnees.get("parent", getattr(self.instance, "parent", None))
        batiment = donnees.get("batiment", getattr(self.instance, "batiment", None))
        if parent is not None:
            if self.instance is not None and (
                parent.pk == self.instance.pk or parent.pk in {e.pk for e in self.instance.descendants()}
            ):
                raise serializers.ValidationError({"parent": "Un espace ne peut pas être inclus dans lui-même."})
            if batiment is not None and parent.batiment_id != batiment.pk:
                raise serializers.ValidationError({"parent": "L'espace englobant doit être dans le même bâtiment."})
        if (
            self.instance is not None
            and batiment is not None
            and batiment.pk != self.instance.batiment_id
            and self.instance.sous_espaces.exists()
        ):
            raise serializers.ValidationError(
                {"batiment": "Déplacez d'abord les sous-espaces : un espace divisé reste dans son bâtiment."}
            )
        partageable = donnees.get("partageable", getattr(self.instance, "partageable", False))
        if not partageable and donnees.get("capacite_simultanee", 1) > 1:
            raise serializers.ValidationError(
                {"capacite_simultanee": "Seul un espace partageable accepte plusieurs réservations simultanées."}
            )
        return donnees
