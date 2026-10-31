"""Aides de test du portail : compte actif et client authentifié comme la façade le ferait."""

from __future__ import annotations

from django.contrib.auth.hashers import make_password
from rest_framework.test import APIClient

from apps.comptes.models import CompteUsager
from apps.comptes.services import ouvrir_session
from apps.usagers.models import Contact, Usager
from tests.fabriques import usager_avec_contact

MOT_DE_PASSE = "Gymnase-Trapeze-2026!"


def compte_actif(usager: Usager | None = None) -> CompteUsager:
    usager = usager or usager_avec_contact()
    contact = usager.rattachements.select_related("contact").first().contact
    return CompteUsager.objects.create(
        contact=contact, identifiant=contact.courriel.lower(), mot_de_passe=make_password(MOT_DE_PASSE), statut="actif"
    )


def client_contact(contact: Contact | CompteUsager) -> APIClient:
    compte = contact if isinstance(contact, CompteUsager) else contact.compte
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Portail {ouvrir_session(compte)}")
    return client
