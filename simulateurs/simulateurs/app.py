"""Simulateurs fidèles des services tiers pour la recette (jamais en production).

- **SMS** (COM-05) : opérateur HTTP générique (`POST /sms/messages`, jeton Bearer) ; messages consultables.
- **DocuSeal** (SIG-01 à SIG-04) : sous-ensemble de l'API DocuSeal 3.x utilisé par la plateforme —
  `POST /api/submissions/pdf`, `GET /api/submissions/{id}`, `GET /api/submissions/{id}/documents`,
  `DELETE /api/submissions/{id}`, `PUT /api/submitters/{id}` (relance), en-tête `X-Auth-Token` ;
  page de signature `/s/{slug}` respectant l'ordre des signataires ; webhooks `form.viewed`,
  `form.completed`, `submission.completed`, `submission.expired` envoyés avec l'en-tête secret configuré.
- **PayFiP** (TAR-07, lot 7) : voir `payfip.py`.

Les données sont en mémoire : un redémarrage remet le simulateur à zéro.
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import html
import itertools
import logging
import os
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from .pdf import pdf_texte

journal = logging.getLogger("simulateurs")
COMPTEUR = itertools.count(1)
VERROU = threading.Lock()


def maintenant() -> datetime:
    return datetime.now(UTC)


def reglage(nom: str) -> str:
    """Valeur d'un réglage : variable `NOM`, ou fichier désigné par `NOM_FICHIER` (secret Docker)."""
    fichier = os.environ.get(f"{nom}_FICHIER")
    if fichier and os.path.isfile(fichier):
        with open(fichier, encoding="utf-8") as lecture:
            return lecture.read().strip()
    return os.environ.get(nom, "")


# --- SMS ---------------------------------------------------------------------------------------------


@dataclass
class Sms:
    identifiant: str
    destinataire: str
    expediteur: str
    texte: str
    reference: str
    recu_le: str


SMS: list[Sms] = []


def _jeton_valide(request: Request, attendu: str) -> bool:
    fourni = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    return bool(attendu) and hmac.compare_digest(fourni, attendu)


async def recevoir_sms(request: Request) -> Response:
    if not _jeton_valide(request, reglage("SIMULATEUR_SMS_JETON")):
        return JSONResponse({"erreur": "jeton invalide"}, status_code=401)
    corps = await request.json()
    if not str(corps.get("destinataire", "")).startswith("+33") or not corps.get("texte"):
        return JSONResponse({"erreur": "destinataire ou texte invalide"}, status_code=422)
    sms = Sms(
        f"SMS{next(COMPTEUR):06d}",
        corps["destinataire"],
        str(corps.get("expediteur", ""))[:11],
        str(corps["texte"])[:320],
        str(corps.get("reference", "")),
        maintenant().isoformat(),
    )
    with VERROU:
        SMS.append(sms)
    return JSONResponse({"identifiant": sms.identifiant, "statut": "remis"}, status_code=201)


async def lister_sms(request: Request) -> Response:
    if request.url.path.endswith(".json") or "application/json" in request.headers.get("accept", ""):
        return JSONResponse([s.__dict__ for s in reversed(SMS)])
    lignes = "".join(
        f"<tr><td>{html.escape(s.recu_le)}</td><td>{html.escape(s.destinataire)}</td><td>{html.escape(s.texte)}</td></tr>"
        for s in reversed(SMS)
    )
    return HTMLResponse(
        PAGE.format(
            titre="SMS reçus — simulateur",
            contenu=f"<h1>SMS reçus</h1><table><caption>Derniers SMS remis à l'opérateur simulé</caption>"
            f"<thead><tr><th scope='col'>Reçu le</th><th scope='col'>Destinataire</th><th scope='col'>Texte</th></tr></thead>"
            f"<tbody>{lignes or '<tr><td colspan=3>Aucun SMS.</td></tr>'}</tbody></table>",
        )
    )


# --- DocuSeal ------------------------------------------------------------------------------------------


@dataclass
class Signataire:
    id: int
    role: str
    email: str
    name: str
    slug: str
    order: int
    status: str = "awaiting"
    opened_at: str | None = None
    completed_at: str | None = None
    sent_count: int = 1


@dataclass
class Soumission:
    id: int
    name: str
    document_nom: str
    document: bytes
    ordonnee: bool
    expire_at: str | None
    submitters: list[Signataire] = field(default_factory=list)
    status: str = "pending"
    created_at: str = field(default_factory=lambda: maintenant().isoformat())
    completed_at: str | None = None
    archived_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


SOUMISSIONS: dict[int, Soumission] = {}


def _base() -> str:
    return os.environ.get("SIMULATEUR_URL_PUBLIQUE", "http://localhost:53010").rstrip("/")


def _autorise(request: Request) -> bool:
    attendu = reglage("SIMULATEUR_DOCUSEAL_JETON")
    return bool(attendu) and hmac.compare_digest(request.headers.get("x-auth-token", ""), attendu)


def _refus() -> JSONResponse:
    return JSONResponse({"error": "Not authenticated"}, status_code=401)


def _expirer_si_besoin(soumission: Soumission) -> None:
    if soumission.status == "pending" and soumission.expire_at and datetime.fromisoformat(soumission.expire_at) <= maintenant():
        soumission.status = "expired"
        _webhook("submission.expired", soumission)


def _signataire_json(s: Signataire, soumission: Soumission) -> dict[str, Any]:
    return {
        "id": s.id,
        "submission_id": soumission.id,
        "uuid": s.slug,
        "slug": s.slug,
        "email": s.email,
        "name": s.name,
        "role": s.role,
        "status": s.status,
        "opened_at": s.opened_at,
        "completed_at": s.completed_at,
        "embed_src": f"{_base()}/s/{s.slug}",
    }


def _soumission_json(soumission: Soumission) -> dict[str, Any]:
    termine = soumission.status == "completed"
    return {
        "id": soumission.id,
        "name": soumission.name,
        "status": soumission.status,
        "created_at": soumission.created_at,
        "completed_at": soumission.completed_at,
        "archived_at": soumission.archived_at,
        "expire_at": soumission.expire_at,
        "metadata": soumission.metadata,
        "submitters": [_signataire_json(s, soumission) for s in soumission.submitters],
        "documents": [{"name": soumission.document_nom, "url": f"{_base()}/fichiers/{soumission.id}/signe.pdf"}]
        if termine
        else [],
        "audit_log_url": f"{_base()}/fichiers/{soumission.id}/preuve.pdf" if termine else None,
        "combined_document_url": f"{_base()}/fichiers/{soumission.id}/signe.pdf" if termine else None,
    }


TACHES: set[asyncio.Task[None]] = set()


async def _remettre(url: str, corps: dict[str, Any], entetes: dict[str, str]) -> None:
    try:
        async with httpx.AsyncClient(timeout=15, verify=os.environ.get("SIMULATEUR_VERIFIER_TLS", "1") == "1") as client:
            await client.post(url, json=corps, headers=entetes)
    except httpx.HTTPError as erreur:
        journal.warning("Webhook %s non remis : %s", corps.get("event_type"), type(erreur).__name__)


def _webhook(evenement: str, soumission: Soumission, signataire: Signataire | None = None) -> None:
    """Envoi du webhook comme DocuSeal, après la réponse : corps JSON {event_type, timestamp, data}, en-tête secret."""
    url = os.environ.get("SIMULATEUR_DOCUSEAL_WEBHOOK_URL", "")
    if not url:
        return
    if signataire is not None:
        donnees = _signataire_json(signataire, soumission) | {"submission": {"id": soumission.id}}
    else:
        donnees = _soumission_json(soumission)
    corps = {"event_type": evenement, "timestamp": maintenant().isoformat(), "data": donnees}
    entete = os.environ.get("SIMULATEUR_DOCUSEAL_WEBHOOK_ENTETE", "X-Docuseal-Secret")
    tache = asyncio.get_running_loop().create_task(
        _remettre(url, corps, {entete: reglage("SIMULATEUR_DOCUSEAL_WEBHOOK_SECRET")})
    )
    TACHES.add(tache)
    tache.add_done_callback(TACHES.discard)


async def creer_soumission_pdf(request: Request) -> Response:
    if not _autorise(request):
        return _refus()
    corps = await request.json()
    documents = corps.get("documents") or []
    signataires = corps.get("submitters") or []
    if not documents or not signataires:
        return JSONResponse({"error": "documents and submitters are required"}, status_code=422)
    try:
        contenu = base64.b64decode(documents[0]["file"], validate=True)
    except KeyError, ValueError:
        return JSONResponse({"error": "file must be base64"}, status_code=422)
    if not contenu.startswith(b"%PDF-"):
        return JSONResponse({"error": "file must be a PDF"}, status_code=422)
    soumission = Soumission(
        id=next(COMPTEUR),
        name=str(corps.get("name") or documents[0].get("name") or "Document"),
        document_nom=str(documents[0].get("name") or "document.pdf"),
        document=contenu,
        ordonnee=corps.get("order", "preserved") == "preserved",
        expire_at=corps.get("expire_at"),
        metadata=corps.get("metadata") or {},
    )
    for rang, s in enumerate(signataires, start=1):
        soumission.submitters.append(
            Signataire(
                id=next(COMPTEUR),
                role=str(s.get("role") or f"Signataire {rang}"),
                email=str(s.get("email", "")),
                name=str(s.get("name", "")),
                slug=secrets.token_urlsafe(10),
                order=int(s.get("order", rang - 1)),
            )
        )
    with VERROU:
        SOUMISSIONS[soumission.id] = soumission
    return JSONResponse(_soumission_json(soumission))


def _trouver(request: Request) -> Soumission | None:
    try:
        return SOUMISSIONS.get(int(request.path_params["identifiant"]))
    except ValueError:
        return None


async def lire_soumission(request: Request) -> Response:
    if not _autorise(request):
        return _refus()
    soumission = _trouver(request)
    if soumission is None or soumission.archived_at:
        return JSONResponse({"error": "Not found"}, status_code=404)
    _expirer_si_besoin(soumission)
    return JSONResponse(_soumission_json(soumission))


async def documents_soumission(request: Request) -> Response:
    if not _autorise(request):
        return _refus()
    soumission = _trouver(request)
    if soumission is None or soumission.archived_at:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return JSONResponse({"id": soumission.id, "documents": _soumission_json(soumission)["documents"]})


async def archiver_soumission(request: Request) -> Response:
    if not _autorise(request):
        return _refus()
    soumission = _trouver(request)
    if soumission is None:
        return JSONResponse({"error": "Not found"}, status_code=404)
    soumission.archived_at = maintenant().isoformat()
    soumission.document = b""
    return JSONResponse({"id": soumission.id, "archived_at": soumission.archived_at})


async def relancer_signataire(request: Request) -> Response:
    if not _autorise(request):
        return _refus()
    identifiant = int(request.path_params["identifiant"])
    for soumission in SOUMISSIONS.values():
        for s in soumission.submitters:
            if s.id == identifiant:
                s.sent_count += 1
                return JSONResponse(_signataire_json(s, soumission))
    return JSONResponse({"error": "Not found"}, status_code=404)


async def fichier(request: Request) -> Response:
    soumission = _trouver(request)
    if soumission is None or soumission.status != "completed" or soumission.archived_at:
        return Response(status_code=404)
    if request.path_params["nature"] == "signe.pdf":
        mention = "\n".join(f"% signé par {s.name} <{s.email}> le {s.completed_at}" for s in soumission.submitters)
        return Response(soumission.document + f"\n{mention}\n".encode(), media_type="application/pdf")
    lignes = [f"Journal de preuve — soumission {soumission.id}", f"Document : {soumission.document_nom}", ""]
    for s in soumission.submitters:
        lignes += [f"{s.role} : {s.name} <{s.email}>", f"  ouvert le {s.opened_at}", f"  signé le {s.completed_at}"]
    return Response(pdf_texte(lignes), media_type="application/pdf")


def _signataire_par_slug(slug: str) -> tuple[Soumission, Signataire] | None:
    for soumission in SOUMISSIONS.values():
        for s in soumission.submitters:
            if hmac.compare_digest(s.slug, slug):
                return soumission, s
    return None


def _tour(soumission: Soumission, signataire: Signataire) -> bool:
    if not soumission.ordonnee:
        return True
    precedents = [s for s in soumission.submitters if s.order < signataire.order]
    return all(s.status == "completed" for s in precedents)


async def page_signature(request: Request) -> Response:
    trouve = _signataire_par_slug(request.path_params["slug"])
    if trouve is None:
        return HTMLResponse(
            PAGE.format(titre="Lien invalide", contenu="<h1>Ce lien de signature n'est pas valable.</h1>"), status_code=404
        )
    soumission, signataire = trouve
    _expirer_si_besoin(soumission)
    if soumission.status == "expired":
        contenu = "<h1>Délai de signature dépassé</h1><p>Contactez l'organisme qui vous a envoyé le document.</p>"
    elif signataire.status == "completed":
        contenu = "<h1>Document signé</h1><p>Merci, votre signature est enregistrée.</p>"
    elif not _tour(soumission, signataire):
        contenu = "<h1>En attente</h1><p>Un autre signataire doit signer avant vous.</p>"
    else:
        if signataire.opened_at is None:
            signataire.opened_at = maintenant().isoformat()
            signataire.status = "opened"
            _webhook("form.viewed", soumission, signataire)
        contenu = (
            f"<h1>Signature : {html.escape(soumission.name)}</h1>"
            f"<p>Signataire : {html.escape(signataire.name)} ({html.escape(signataire.role)})</p>"
            f"<form method='post' action='/s/{signataire.slug}'>"
            "<p><label><input type='checkbox' name='accord' required> J'ai lu le document et je le signe.</label></p>"
            "<p><button type='submit'>Signer le document</button></p></form>"
        )
    return HTMLResponse(PAGE.format(titre=f"Signature — {html.escape(soumission.name)}", contenu=contenu))


async def signer(request: Request) -> Response:
    trouve = _signataire_par_slug(request.path_params["slug"])
    if trouve is None:
        return Response(status_code=404)
    soumission, signataire = trouve
    _expirer_si_besoin(soumission)
    formulaire = await request.form()
    if (
        soumission.status != "pending"
        or signataire.status == "completed"
        or not _tour(soumission, signataire)
        or not formulaire.get("accord")
    ):
        return RedirectResponse(f"/s/{signataire.slug}", status_code=303)
    signataire.status = "completed"
    signataire.completed_at = maintenant().isoformat()
    signataire.opened_at = signataire.opened_at or signataire.completed_at
    _webhook("form.completed", soumission, signataire)
    if all(s.status == "completed" for s in soumission.submitters):
        soumission.status = "completed"
        soumission.completed_at = maintenant().isoformat()
        _webhook("submission.completed", soumission)
    return RedirectResponse(f"/s/{signataire.slug}", status_code=303)


async def expirer(request: Request) -> Response:
    """Outil de recette : rendre une soumission expirée immédiatement (SIG-04)."""
    if not _autorise(request):
        return _refus()
    soumission = _trouver(request)
    if soumission is None:
        return Response(status_code=404)
    soumission.expire_at = maintenant().isoformat()
    _expirer_si_besoin(soumission)
    return JSONResponse(_soumission_json(soumission))


async def lister_soumissions(request: Request) -> Response:
    """Outil de recette : liens de signature des soumissions en cours (jeton exigé)."""
    if not _autorise(request):
        return _refus()
    return JSONResponse([_soumission_json(s) for s in SOUMISSIONS.values() if not s.archived_at])


async def accueil(request: Request) -> Response:
    return HTMLResponse(
        PAGE.format(
            titre="Simulateurs de recette",
            contenu="<h1>Simulateurs de recette</h1><ul><li><a href='/sms'>SMS reçus</a></li>"
            "<li>DocuSeal : API sur /api (jeton X-Auth-Token)</li><li>PayFiP : /payfip</li></ul>",
        )
    )


async def sante(request: Request) -> Response:
    return JSONResponse({"etat": "ok"})


PAGE = (
    "<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'><title>{titre}</title><style>"
    "body{{font-family:system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;line-height:1.5}}"
    "button{{font-size:1rem;padding:.5rem 1rem}}table{{border-collapse:collapse}}"
    "td,th{{border:1px solid #888;padding:.25rem .5rem}}</style></head><body><main>{contenu}</main></body></html>"
)


def creer_application() -> Starlette:
    """Les simulateurs n'existent qu'en recette : sans `SIMULATEUR_RECETTE=1`, ils refusent de démarrer."""
    from .payfip import ROUTES_PAYFIP

    if os.environ.get("SIMULATEUR_RECETTE") != "1":
        raise RuntimeError("Simulateurs de recette : SIMULATEUR_RECETTE=1 requis (jamais en production).")

    return Starlette(
        routes=[
            Route("/", accueil),
            Route("/sante", sante),
            Route("/sms/messages", recevoir_sms, methods=["POST"]),
            Route("/sms", lister_sms),
            Route("/sms.json", lister_sms),
            Route("/api/submissions/pdf", creer_soumission_pdf, methods=["POST"]),
            Route("/api/submissions", lister_soumissions, methods=["GET"]),
            Route("/api/submissions/{identifiant}", lire_soumission, methods=["GET"]),
            Route("/api/submissions/{identifiant}", archiver_soumission, methods=["DELETE"]),
            Route("/api/submissions/{identifiant}/documents", documents_soumission, methods=["GET"]),
            Route("/api/submitters/{identifiant:int}", relancer_signataire, methods=["PUT"]),
            Route("/simulateur/submissions/{identifiant}/expirer", expirer, methods=["POST"]),
            Route("/fichiers/{identifiant}/{nature:str}", fichier),
            Route("/s/{slug}", page_signature, methods=["GET"]),
            Route("/s/{slug}", signer, methods=["POST"]),
            *ROUTES_PAYFIP,
        ]
    )
