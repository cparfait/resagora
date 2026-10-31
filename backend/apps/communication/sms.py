"""Envoi de SMS par un adaptateur configurable (COM-05).

`SMS_ADAPTATEUR` :
- `desactive` (défaut) : aucun SMS n'est envoyé, la notification est marquée « ignorée » ;
- `http` : appel HTTPS d'un opérateur (ou du simulateur de recette) — `POST {SMS_URL}` avec un corps
  JSON `{"destinataire", "expediteur", "texte", "reference"}` et l'en-tête `Authorization: Bearer <secret sms_jeton>`.
  La réponse attendue est `2xx` avec `{"identifiant": "..."}`. Pour un opérateur au format différent,
  `SMS_CHAMPS` permet de renommer les champs (ex. `destinataire=to,expediteur=from,texte=message`).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

import httpx

from apps.noyau.secrets import secret

TELEPHONE_FR = re.compile(r"^(?:\+33|0)([67]\d{8})$")


class SmsIndisponible(OSError):
    """Opérateur injoignable ou réponse en erreur : l'envoi sera retenté."""


@dataclass(frozen=True)
class ResultatSms:
    envoye: bool
    identifiant: str = ""
    motif: str = ""


def normaliser_mobile(numero: str) -> str | None:
    """Numéro mobile français au format international (+336…, +337…) ; None si ce n'est pas un mobile."""
    chiffres = re.sub(r"[\s.\-()]", "", numero or "")
    correspondance = TELEPHONE_FR.match(chiffres)
    return f"+33{correspondance.group(1)}" if correspondance else None


def _champs() -> dict[str, str]:
    champs = {"destinataire": "destinataire", "expediteur": "expediteur", "texte": "texte", "reference": "reference"}
    for couple in filter(None, (os.environ.get("SMS_CHAMPS", "")).split(",")):
        source, _, cible = couple.partition("=")
        if source.strip() in champs and cible.strip():
            champs[source.strip()] = cible.strip()
    return champs


def envoyer_sms(numero: str, texte: str, reference: str, transport: httpx.BaseTransport | None = None) -> ResultatSms:
    adaptateur = os.environ.get("SMS_ADAPTATEUR", "desactive")
    if adaptateur == "desactive":
        return ResultatSms(False, motif="Envoi de SMS désactivé (SMS_ADAPTATEUR).")
    destinataire = normaliser_mobile(numero)
    if destinataire is None:
        return ResultatSms(False, motif="Numéro de mobile invalide.")
    if adaptateur != "http":
        raise ValueError(f"Adaptateur SMS inconnu : {adaptateur}")
    champs = _champs()
    corps = {
        champs["destinataire"]: destinataire,
        champs["expediteur"]: os.environ.get("SMS_EXPEDITEUR", "CHATILLON"),
        champs["texte"]: texte[:320],
        champs["reference"]: reference,
    }
    try:
        with httpx.Client(timeout=15, transport=transport) as client:
            reponse = client.post(
                os.environ["SMS_URL"], json=corps, headers={"Authorization": f"Bearer {secret('sms_jeton', defaut='')}"}
            )
    except httpx.HTTPError as erreur:
        raise SmsIndisponible(f"Opérateur SMS injoignable : {type(erreur).__name__}") from erreur
    if reponse.status_code >= 500 or reponse.status_code == 429:
        raise SmsIndisponible(f"Opérateur SMS indisponible ({reponse.status_code})")
    if reponse.status_code >= 400:
        return ResultatSms(False, motif=f"SMS refusé par l'opérateur ({reponse.status_code}).")
    try:
        identifiant = str(reponse.json().get("identifiant", ""))
    except ValueError:
        identifiant = ""
    return ResultatSms(True, identifiant=identifiant)
