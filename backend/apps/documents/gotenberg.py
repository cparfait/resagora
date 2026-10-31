"""Conversion .docx → PDF/A-2b par Gotenberg 8 (route LibreOffice), sur le réseau interne du LAN (DOC-04).

`POST {GOTENBERG_URL}/forms/libreoffice/convert` (multipart : `files`, `pdfa=PDF/A-2b`, `pdfua=true`) ;
le PDF/UA balise la structure du document pour les lecteurs d'écran (RGAA, documents fournis).
"""

from __future__ import annotations

import httpx
from django.conf import settings

from apps.noyau.exceptions import ErreurMetier

TYPE_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class GotenbergIndisponible(ErreurMetier):
    statut_http = 503


def convertir_en_pdfa(nom: str, docx: bytes, transport: httpx.BaseTransport | None = None) -> bytes:
    url = f"{settings.GOTENBERG_URL.rstrip('/')}/forms/libreoffice/convert"
    try:
        with httpx.Client(timeout=settings.GOTENBERG_DELAI_SECONDES, transport=transport) as client:
            reponse = client.post(
                url,
                files={"files": (nom if nom.endswith(".docx") else f"{nom}.docx", docx, TYPE_DOCX)},
                data={"pdfa": "PDF/A-2b", "pdfua": "true"},
                headers={"Gotenberg-Output-Filename": "document"},
            )
    except httpx.HTTPError as erreur:
        raise GotenbergIndisponible(
            "Le service de conversion PDF est momentanément indisponible. Réessayez plus tard.", code="gotenberg_indisponible"
        ) from erreur
    if reponse.status_code != 200 or not reponse.content.startswith(b"%PDF-"):
        raise GotenbergIndisponible(
            f"La conversion du document en PDF a échoué (code {reponse.status_code}).", code="conversion_echouee"
        )
    return reponse.content
