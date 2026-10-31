"""DocuSeal simulé pour les tests unitaires (même contrat que le simulateur de recette `simulateurs/`)."""

from __future__ import annotations

import base64
import itertools
import json
from dataclasses import dataclass, field
from typing import Any

import httpx

BASE = "http://docuseal:3000"
PDF_SIGNE = b"%PDF-1.7\n% exemplaire signe\n%%EOF\n"
PDF_PREUVE = b"%PDF-1.7\n% journal de preuve\n%%EOF\n"


@dataclass
class FauxDocuSeal:
    soumissions: dict[int, dict[str, Any]] = field(default_factory=dict)
    archivees: list[int] = field(default_factory=list)
    relances: list[int] = field(default_factory=list)
    compteur: Any = field(default_factory=lambda: itertools.count(100))
    jeton: str = ""

    def signer(self, soumission: int, rang: int) -> None:
        signataire = self.soumissions[soumission]["submitters"][rang]
        signataire["status"] = "completed"
        signataire["completed_at"] = "2026-11-05T10:00:00+00:00"
        if all(s["status"] == "completed" for s in self.soumissions[soumission]["submitters"]):
            donnees = self.soumissions[soumission]
            donnees["status"] = "completed"
            donnees["documents"] = [{"name": "signe.pdf", "url": f"{BASE}/fichiers/{soumission}/signe.pdf"}]
            donnees["audit_log_url"] = f"{BASE}/fichiers/{soumission}/preuve.pdf"

    def expirer(self, soumission: int) -> None:
        self.soumissions[soumission]["status"] = "expired"

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.jeton = requete.headers.get("x-auth-token", "")
        chemin = requete.url.path
        if requete.method == "POST" and chemin == "/api/submissions/pdf":
            corps = json.loads(requete.content)
            assert base64.b64decode(corps["documents"][0]["file"]).startswith(b"%PDF-")
            identifiant = next(self.compteur)
            self.soumissions[identifiant] = {
                "id": identifiant,
                "status": "pending",
                "order": corps.get("order"),
                "expire_at": corps.get("expire_at"),
                "submitters": [
                    {
                        "id": next(self.compteur),
                        "email": s["email"],
                        "role": s["role"],
                        "status": "awaiting",
                        "embed_src": f"{BASE}/s/lien{identifiant}-{rang}",
                        "completed_at": None,
                    }
                    for rang, s in enumerate(corps["submitters"])
                ],
                "documents": [],
                "audit_log_url": None,
            }
            return httpx.Response(200, json=self.soumissions[identifiant])
        if chemin.startswith("/api/submissions/"):
            identifiant = int(chemin.rsplit("/", 1)[-1])
            if identifiant not in self.soumissions or identifiant in self.archivees:
                return httpx.Response(404, json={"error": "Not found"})
            if requete.method == "DELETE":
                self.archivees.append(identifiant)
                return httpx.Response(200, json={"id": identifiant})
            return httpx.Response(200, json=self.soumissions[identifiant])
        if requete.method == "PUT" and chemin.startswith("/api/submitters/"):
            self.relances.append(int(chemin.rsplit("/", 1)[-1]))
            return httpx.Response(200, json={})
        if chemin.endswith("/signe.pdf"):
            return httpx.Response(200, content=PDF_SIGNE)
        if chemin.endswith("/preuve.pdf"):
            return httpx.Response(200, content=PDF_PREUVE)
        return httpx.Response(404)
