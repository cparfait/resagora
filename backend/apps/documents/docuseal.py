"""Client de l'API DocuSeal 3.x (SIG-01 à SIG-04) appelé depuis le LAN.

Opérations utilisées : création d'une soumission depuis un PDF (`POST /api/submissions/pdf`, signataires
ordonnés `order=preserved`, `expire_at`), lecture d'état (`GET /api/submissions/{id}`), documents signés
(`GET /api/submissions/{id}/documents`), relance d'un signataire (`PUT /api/submitters/{id}` avec
`send_email`), archivage après récupération (`DELETE /api/submissions/{id}`). Authentification par
l'en-tête `X-Auth-Token` (jeton d'API, secret `docuseal_api_jeton`).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from django.conf import settings

from apps.noyau.exceptions import ErreurMetier


class DocuSealIndisponible(ErreurMetier):
    statut_http = 503


@dataclass(frozen=True)
class SignataireDocuSeal:
    identifiant: str
    courriel: str
    role: str
    statut: str
    lien: str
    signe_le: str | None


@dataclass(frozen=True)
class EtatSoumission:
    identifiant: str
    statut: str  # pending | completed | expired | declined
    signataires: list[SignataireDocuSeal]
    documents: list[str]
    preuve: str | None


class ClientDocuSeal:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.base = settings.DOCUSEAL_URL.rstrip("/")
        self.transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base,
            timeout=30,
            transport=self.transport,
            verify=settings.DOCUSEAL_VERIFIER_TLS,
            headers={"X-Auth-Token": settings.DOCUSEAL_JETON, "Accept": "application/json"},
        )

    def _appel(self, methode: str, chemin: str, **options: Any) -> Any:
        try:
            with self._client() as client:
                reponse = client.request(methode, chemin, **options)
        except httpx.HTTPError as erreur:
            raise DocuSealIndisponible(
                "Le service de signature électronique est injoignable. Utilisez le circuit manuel ou réessayez plus tard.",
                code="docuseal_indisponible",
            ) from erreur
        if reponse.status_code == 404:
            raise ErreurMetier("Soumission introuvable côté signature électronique.", code="soumission_introuvable")
        if reponse.status_code >= 400:
            raise DocuSealIndisponible(
                f"Le service de signature a refusé la demande (code {reponse.status_code}).", code="docuseal_refus"
            )
        return reponse.json() if reponse.content else {}

    @staticmethod
    def _lien_public(lien: str) -> str:
        """Les liens de signature pointent vers l'adresse publique (DMZ) et non vers l'adresse interne."""
        return lien.replace(settings.DOCUSEAL_URL.rstrip("/"), settings.DOCUSEAL_URL_PUBLIQUE.rstrip("/"), 1)

    def _etat(self, donnees: dict[str, Any]) -> EtatSoumission:
        return EtatSoumission(
            identifiant=str(donnees["id"]),
            statut=str(donnees.get("status", "pending")),
            signataires=[
                SignataireDocuSeal(
                    identifiant=str(s["id"]),
                    courriel=str(s.get("email", "")),
                    role=str(s.get("role", "")),
                    statut=str(s.get("status", "")),
                    lien=self._lien_public(str(s.get("embed_src", ""))),
                    signe_le=s.get("completed_at"),
                )
                for s in donnees.get("submitters", [])
            ],
            documents=[str(d["url"]) for d in donnees.get("documents", []) if d.get("url")],
            preuve=donnees.get("audit_log_url"),
        )

    def creer(
        self, nom: str, pdf: bytes, signataires: list[dict[str, str]], expire_le: datetime, reference: str
    ) -> EtatSoumission:
        corps = {
            "name": nom,
            "documents": [{"name": f"{reference}.pdf", "file": base64.b64encode(pdf).decode()}],
            "submitters": [
                {"role": s["role"], "email": s["courriel"], "name": s["nom"], "order": rang} for rang, s in enumerate(signataires)
            ],
            "order": "preserved",
            "send_email": False,
            "expire_at": expire_le.isoformat(),
            "metadata": {"reference": reference},
        }
        return self._etat(self._appel("POST", "/api/submissions/pdf", json=corps))

    def lire(self, identifiant: str) -> EtatSoumission:
        return self._etat(self._appel("GET", f"/api/submissions/{identifiant}"))

    def telecharger(self, url: str) -> bytes:
        """Les URL publiées (adresse publique) sont lues par l'adresse interne du service."""
        url = url.replace(settings.DOCUSEAL_URL_PUBLIQUE.rstrip("/"), self.base, 1)
        if not url.startswith(self.base + "/"):
            raise DocuSealIndisponible("Adresse de document inattendue : téléchargement refusé.", code="docuseal_url_refusee")
        try:
            with self._client() as client:
                reponse = client.get(url)
        except httpx.HTTPError as erreur:
            raise DocuSealIndisponible("Téléchargement du document signé impossible.", code="docuseal_indisponible") from erreur
        if reponse.status_code != 200 or not reponse.content.startswith(b"%PDF-"):
            raise DocuSealIndisponible("Le document signé reçu n'est pas un PDF.", code="docuseal_document_invalide")
        return reponse.content

    def relancer(self, identifiant_signataire: str) -> None:
        self._appel("PUT", f"/api/submitters/{identifiant_signataire}", json={"send_email": True})

    def archiver(self, identifiant: str) -> None:
        self._appel("DELETE", f"/api/submissions/{identifiant}")
