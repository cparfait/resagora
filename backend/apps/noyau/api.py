"""Vues génériques du canal gestion : lectures filtrées par périmètre, écritures journalisées (RG-14, SEC-08)."""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from django.db.models import Model, QuerySet
from rest_framework import viewsets
from rest_framework.serializers import BaseSerializer

from apps.audit.services import instantane, journaliser
from apps.habilitations.authentification import agent_courant
from apps.habilitations.permissions import action_de_la_vue
from apps.habilitations.services import filtrer_par_perimetre, peut
from apps.noyau.exceptions import AccesRefuse

journal_securite = logging.getLogger("securite")


class VuePerimetre(viewsets.ModelViewSet):
    """`chemin_site` : chemin ORM vers le site de l'objet (None = objet transversal)."""

    chemin_site: str | None = None
    actions_requises: dict[str, str] = {}

    def get_queryset(self) -> QuerySet[Any]:
        qs = super().get_queryset()
        action = action_de_la_vue(self, self.request)
        if action is None:
            return qs.none()
        if self.chemin_site is None:
            return qs if peut(agent_courant(self.request), action) else qs.none()
        return filtrer_par_perimetre(qs, agent_courant(self.request), action, self.chemin_site)

    def _verifier_objet(self, objet: Model) -> None:
        action = action_de_la_vue(self, self.request)
        if action is None or not peut(agent_courant(self.request), action, objet):
            journal_securite.warning(
                "Accès hors périmètre refusé : agent %s, action %s, objet %s",
                agent_courant(self.request).pk,
                action,
                objet._meta.label,
            )
            raise AccesRefuse("Cet élément est hors de votre périmètre.", code="hors_perimetre")

    def _verifier_lies(self, serializer: BaseSerializer[Any]) -> None:
        """Avant toute écriture : chaque objet lié (bâtiment, espace parent…) doit être dans le périmètre."""
        action = action_de_la_vue(self, self.request)
        donnees = getattr(serializer, "validated_data", {}) or {}
        for valeur in donnees.values():
            liste = valeur if isinstance(valeur, list) else [valeur]
            for objet in liste:
                if isinstance(objet, Model) and hasattr(objet, "sites_concernes") and objet.sites_concernes() is not None:
                    if action is None or not peut(agent_courant(self.request), action, objet):
                        raise AccesRefuse("Un élément lié est hors de votre périmètre.", code="hors_perimetre")

    def perform_create(self, serializer: BaseSerializer[Any]) -> None:
        self._verifier_lies(serializer)
        with transaction.atomic():
            objet = serializer.save()
            self._verifier_objet(objet)
            journaliser(f"creer_{objet._meta.model_name}", objet, apres=instantane(objet))

    def perform_update(self, serializer: BaseSerializer[Any]) -> None:
        self._verifier_lies(serializer)
        with transaction.atomic():
            avant = instantane(serializer.instance)
            objet = serializer.save()
            self._verifier_objet(objet)
            journaliser(f"modifier_{objet._meta.model_name}", objet, avant=avant, apres=instantane(objet))

    def perform_destroy(self, instance: Model) -> None:
        with transaction.atomic():
            journaliser(f"supprimer_{instance._meta.model_name}", instance, avant=instantane(instance))
            instance.delete()
