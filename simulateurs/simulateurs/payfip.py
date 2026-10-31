"""Simulateur PayFiP (DGFiP) pour la recette du lot 7 (TAR-07, POR-07).

Reproduit le service web SOAP « PaiementSecuriseService » utilisé par PayFiP Titres et Rôles et PayFiP
Régie :
- `creerPaiementSecurise` (numcli, exer, refdet, objet, montant en centimes, mel, urlnotif,
  urlredirect, saisie T/X/W) → `idOp` ;
- page de paiement `paiementws.web?idop=…` : payer (carte de test), refuser ou abandonner ;
- notification `POST urlnotif` (formulaire `idop=…`) puis redirection du navigateur vers `urlredirect` ;
- `recupererDetailPaiementSecurise` (idOp) → `resultrans` P (payé), R (refusé), A (abandonné),
  `numauto`, `dattrans` (JJMMAAAA), `heurtrans` (HHMM), montant, références.
Le simulateur refuse un `numcli` qui ne figure pas dans `SIMULATEUR_PAYFIP_NUMCLI` (liste séparée par des virgules).
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import httpx
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

journal = logging.getLogger("simulateurs.payfip")
PARIS = ZoneInfo("Europe/Paris")
CHAMPS_CREATION = ("numcli", "exer", "refdet", "objet", "montant", "mel", "urlnotif", "urlredirect", "saisie")


@dataclass
class Operation:
    id_op: str
    numcli: str
    exer: str
    refdet: str
    objet: str
    montant: str
    mel: str
    urlnotif: str
    urlredirect: str
    saisie: str
    resultrans: str = ""
    numauto: str = ""
    dattrans: str = ""
    heurtrans: str = ""


OPERATIONS: dict[str, Operation] = {}
TACHES: set[asyncio.Task[None]] = set()


def _valeur(xml: str, nom: str) -> str:
    trouve = re.search(rf"<(?:\w+:)?{nom}>([^<]*)</(?:\w+:)?{nom}>", xml)
    return html.unescape(trouve.group(1)).strip() if trouve else ""


def _enveloppe(corps: str) -> Response:
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<S:Envelope xmlns:S="http://schemas.xmlsoap.org/soap/envelope/"><S:Body>' + corps + "</S:Body></S:Envelope>",
        media_type="text/xml; charset=utf-8",
    )


def _faute(code: str, message: str) -> Response:
    reponse = _enveloppe(
        f"<S:Fault><faultcode>S:Server</faultcode><faultstring>{escape(message)}</faultstring>"
        f"<detail><ns2:FonctionnelleErreur xmlns:ns2='http://securite.service.tpa.cp.finances.gouv.fr/reponse'>"
        f"<code>{escape(code)}</code><libelle>{escape(message)}</libelle></ns2:FonctionnelleErreur></detail></S:Fault>"
    )
    reponse.status_code = 500
    return reponse


async def service_securite(request: Request) -> Response:
    xml = (await request.body()).decode("utf-8", errors="replace")
    if "creerPaiementSecurise" in xml:
        valeurs = {c: _valeur(xml, c) for c in CHAMPS_CREATION}
        autorises = {n.strip() for n in os.environ.get("SIMULATEUR_PAYFIP_NUMCLI", "").split(",") if n.strip()}
        if valeurs["numcli"] not in autorises:
            return _faute("P1", "Numéro de client inconnu ou inactif")
        if not valeurs["montant"].isdigit() or int(valeurs["montant"]) <= 0:
            return _faute("P5", "Montant invalide")
        if not re.fullmatch(r"\d{4}", valeurs["exer"]) or not valeurs["refdet"] or not valeurs["urlnotif"].startswith("http"):
            return _faute("P4", "Paramètres de paiement invalides")
        if valeurs["saisie"] not in {"T", "X", "W"}:
            return _faute("P6", "Mode de saisie invalide")
        operation = Operation(id_op=secrets.token_hex(16), **valeurs)
        OPERATIONS[operation.id_op] = operation
        return _enveloppe(
            "<ns2:creerPaiementSecuriseResponse xmlns:ns2='http://securite.service.tpa.cp.finances.gouv.fr/services/mas_securite/"
            f"contrat_paiement_securise/PaiementSecuriseService'><return><idOp>{operation.id_op}</idOp></return>"
            "</ns2:creerPaiementSecuriseResponse>"
        )
    if "recupererDetailPaiementSecurise" in xml:
        trouvee = OPERATIONS.get(_valeur(xml, "idOp"))
        if trouvee is None:
            return _faute("P2", "Opération inconnue")
        if not trouvee.resultrans:
            return _faute("P3", "Paiement non terminé")
        champs = {
            "dattrans": trouvee.dattrans,
            "heurtrans": trouvee.heurtrans,
            "exer": trouvee.exer,
            "idOp": trouvee.id_op,
            "mel": trouvee.mel,
            "montant": trouvee.montant,
            "numauto": trouvee.numauto,
            "numcli": trouvee.numcli,
            "objet": trouvee.objet,
            "refdet": trouvee.refdet,
            "resultrans": trouvee.resultrans,
            "saisie": trouvee.saisie,
        }
        retour = "".join(f"<{k}>{escape(v)}</{k}>" for k, v in champs.items())
        return _enveloppe(
            "<ns2:recupererDetailPaiementSecuriseResponse xmlns:ns2='http://securite.service.tpa.cp.finances.gouv.fr/services/"
            f"mas_securite/contrat_paiement_securise/PaiementSecuriseService'><return>{retour}</return>"
            "</ns2:recupererDetailPaiementSecuriseResponse>"
        )
    return _faute("P0", "Opération SOAP non prise en charge")


def _euros(centimes: str) -> str:
    valeur = int(centimes)
    return f"{valeur // 100},{valeur % 100:02d} €"


async def page_paiement(request: Request) -> Response:
    from .app import PAGE

    operation = OPERATIONS.get(request.query_params.get("idop", ""))
    if operation is None:
        return HTMLResponse(PAGE.format(titre="Paiement introuvable", contenu="<h1>Paiement introuvable</h1>"), status_code=404)
    if operation.resultrans:
        return HTMLResponse(PAGE.format(titre="Paiement terminé", contenu="<h1>Ce paiement est déjà traité.</h1>"))
    contenu = (
        "<h1>PayFiP — simulateur de recette</h1>"
        f"<p>Créancier n° {html.escape(operation.numcli)} — {html.escape(operation.objet)}</p>"
        f"<p>Référence {html.escape(operation.refdet)} (exercice {html.escape(operation.exer)})</p>"
        f"<p><strong>Montant : {_euros(operation.montant)}</strong></p>"
        f"<form method='post' action='/payfip/paiementws.web?idop={operation.id_op}'>"
        "<fieldset><legend>Résultat simulé</legend>"
        "<p><label><input type='radio' name='resultat' value='P' checked> Paiement accepté (carte de test)</label></p>"
        "<p><label><input type='radio' name='resultat' value='R'> Paiement refusé par la banque</label></p>"
        "<p><label><input type='radio' name='resultat' value='A'> Abandon par l'usager</label></p>"
        "</fieldset><p><button type='submit'>Valider</button></p></form>"
    )
    return HTMLResponse(PAGE.format(titre="Paiement PayFiP — simulateur", contenu=contenu))


async def _notifier(operation: Operation) -> None:
    try:
        async with httpx.AsyncClient(timeout=15, verify=os.environ.get("SIMULATEUR_VERIFIER_TLS", "1") == "1") as client:
            await client.post(operation.urlnotif, data={"idop": operation.id_op})
    except httpx.HTTPError as erreur:
        journal.warning("Notification PayFiP non remise : %s", type(erreur).__name__)


async def payer(request: Request) -> Response:
    operation = OPERATIONS.get(request.query_params.get("idop", ""))
    if operation is None or operation.resultrans:
        return Response(status_code=404)
    formulaire = await request.form()
    resultat = str(formulaire.get("resultat", "A"))
    instant = datetime.now(PARIS)
    operation.resultrans = resultat if resultat in {"P", "R", "A"} else "A"
    operation.numauto = f"{secrets.randbelow(10**6):06d}" if operation.resultrans == "P" else ""
    operation.dattrans, operation.heurtrans = instant.strftime("%d%m%Y"), instant.strftime("%H%M")
    tache = asyncio.get_running_loop().create_task(_notifier(operation))
    TACHES.add(tache)
    tache.add_done_callback(TACHES.discard)
    separateur = "&" if "?" in operation.urlredirect else "?"
    return RedirectResponse(f"{operation.urlredirect}{separateur}idop={operation.id_op}", status_code=303)


async def lister_operations(request: Request) -> Response:
    """Outil de recette : opérations reçues (JSON)."""
    from starlette.responses import JSONResponse

    donnees: list[dict[str, Any]] = [o.__dict__ for o in OPERATIONS.values()]
    return JSONResponse(donnees)


ROUTES_PAYFIP = [
    Route("/payfip/services/securite", service_securite, methods=["POST"]),
    Route("/payfip/paiementws.web", page_paiement, methods=["GET"]),
    Route("/payfip/paiementws.web", payer, methods=["POST"]),
    Route("/payfip/operations.json", lister_operations, methods=["GET"]),
]
