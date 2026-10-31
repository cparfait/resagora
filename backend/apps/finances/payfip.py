"""Client PayFiP (DGFiP) — lot 7, TAR-07 et POR-07.

PayFiP expose le service SOAP « PaiementSecuriseService » (guide de mise en œuvre PayFiP Titres et Rôles / Régie) :

- `creerPaiementSecurise` (numcli, exer, refdet, objet, montant en centimes, mel, urlnotif, urlredirect, saisie) rend
  l'identifiant d'opération `idOp` ; l'usager est ensuite redirigé vers `paiementws.web?idop=…` ;
- `recupererDetailPaiementSecurise` (idOp) rend le résultat : `resultrans` P (payé), V (payé par prélèvement,
  à confirmer dans le guide en vigueur), R (refusé), A (abandonné), `numauto`, `dattrans` (JJMMAAAA), `heurtrans`
  (HHMM), montant et références. Une faute à la lecture (paiement non terminé, opération inconnue ou expirée) veut
  dire « pas de résultat » : la tentative reste à relire (ADR 0008).

Deux modes, choisis par configuration (`PAYFIP_MODE`) : « titres » (PayFiP Titres et Rôles, factures prises en charge
par le comptable) ou « regie » (PayFiP Régie, factures payées à la régie avant le titre). `saisie` vaut T (test),
X (activation) ou W (production). Les appels partent du worker par le proxy de la Ville (`PAYFIP_PROXY`), jamais de
l'API du portail. La réponse XML est lue sans résolution d'entités ni accès réseau (XXE), taille bornée pendant la
lecture, et seules les valeurs placées sous `return` sont retenues. Le simulateur de recette (`simulateurs/payfip.py`)
reproduit ces opérations.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape

import httpx
from django.conf import settings
from lxml import etree

from apps.noyau.exceptions import ErreurMetier
from apps.reservations.recurrence import PARIS

journal = logging.getLogger(__name__)
ESPACE_NOMS = (
    "http://securite.service.tpa.cp.finances.gouv.fr/services/mas_securite/contrat_paiement_securise/PaiementSecuriseService"
)
RESULTATS = {"P": "payee", "V": "payee", "R": "refusee", "A": "abandonnee"}
TAILLE_MAX = 100_000
LECTEUR = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, remove_comments=True)


class PayFiPIndisponible(ErreurMetier):
    statut_http = 503


@dataclass(frozen=True)
class DetailPaiement:
    id_op: str
    resultrans: str
    numauto: str
    dattrans: str
    heurtrans: str
    montant: int
    refdet: str
    exer: str
    numcli: str
    saisie: str

    @property
    def statut(self) -> str | None:
        """Statut correspondant ; None pour un résultat inconnu (à contrôler par le service financier)."""
        return RESULTATS.get(self.resultrans)

    def horodatage(self) -> datetime | None:
        if not re.fullmatch(r"\d{8}", self.dattrans or "") or not re.fullmatch(r"\d{4}", self.heurtrans or ""):
            return None
        return datetime.strptime(self.dattrans + self.heurtrans, "%d%m%Y%H%M").replace(tzinfo=PARIS)


def _enveloppe(operation: str, champs: dict[str, str]) -> bytes:
    contenu = "".join(f"<{cle}>{escape(valeur)}</{cle}>" for cle, valeur in champs.items())
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:pai="{ESPACE_NOMS}"><soapenv:Header/><soapenv:Body>'
        f"<pai:{operation}><arg0>{contenu}</arg0></pai:{operation}>"
        "</soapenv:Body></soapenv:Envelope>"
    ).encode()


def _texte(element: Any, nom: str) -> str:
    trouve = element.find(f"{{*}}{nom}")
    if trouve is None:
        trouve = element.find(nom)
    return (trouve.text or "").strip() if trouve is not None else ""


def _valeurs(xml: bytes) -> dict[str, str]:
    """Valeurs placées directement sous `return` ; ErreurMetier « payfip_refus » si PayFiP signale une faute."""
    try:
        racine = etree.fromstring(xml, parser=LECTEUR)
    except etree.XMLSyntaxError as erreur:
        raise PayFiPIndisponible("Réponse de PayFiP illisible.", code="payfip_reponse_invalide") from erreur
    faute = next(iter(racine.iter("{*}Fault", "Fault")), None)
    if faute is not None:
        detail = next(iter(faute.iter("{*}FonctionnelleErreur", "FonctionnelleErreur")), None)
        code = _texte(detail, "code") if detail is not None else ""
        libelle = (_texte(detail, "libelle") if detail is not None else "") or _texte(faute, "faultstring")
        raise ErreurMetier(
            f"PayFiP a refusé l'opération ({code or 'faute'}) : {libelle[:200]}",
            code="payfip_refus",
            details={"code_payfip": code},
        )
    retour = next(iter(racine.iter("{*}return", "return")), None)
    if retour is None:
        raise PayFiPIndisponible("Réponse de PayFiP sans résultat.", code="payfip_reponse_invalide")
    return {etree.QName(e).localname: (e.text or "").strip() for e in retour if isinstance(e.tag, str) and not len(e)}


class ClientPayFiP:
    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.service = settings.PAYFIP_URL_SERVICE.rstrip("/")
        self.transport = transport

    def _appel(self, operation: str, champs: dict[str, str]) -> dict[str, str]:
        if not self.service:
            raise ErreurMetier("Le paiement en ligne n'est pas configuré (PAYFIP_URL_SERVICE).", code="payfip_non_configure")
        options: dict[str, Any] = {"timeout": 15, "transport": self.transport, "verify": settings.PAYFIP_VERIFIER_TLS}
        if settings.PAYFIP_PROXY and self.transport is None:
            options["proxy"] = settings.PAYFIP_PROXY
        try:
            with (
                httpx.Client(**options) as client,
                client.stream(
                    "POST",
                    self.service,
                    content=_enveloppe(operation, champs),
                    headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""'},
                ) as reponse,
            ):
                contenu = b""
                for morceau in reponse.iter_bytes():
                    contenu += morceau
                    if len(contenu) > TAILLE_MAX:
                        raise PayFiPIndisponible("Réponse de PayFiP trop volumineuse.", code="payfip_reponse_invalide")
                statut = reponse.status_code
        except httpx.HTTPError as erreur:
            raise PayFiPIndisponible("PayFiP est injoignable.", code="payfip_indisponible") from erreur
        if statut >= 500 and b"Fault" not in contenu:
            raise PayFiPIndisponible(f"PayFiP est indisponible (code {statut}).", code="payfip_indisponible")
        return _valeurs(contenu)

    def creer(self, *, exer: str, refdet: str, objet: str, montant: int, mel: str, urlnotif: str, urlredirect: str) -> str:
        valeurs = self._appel(
            "creerPaiementSecurise",
            {
                "exer": exer,
                "mel": mel,
                "montant": str(montant),
                "numcli": settings.PAYFIP_NUMCLI,
                "objet": objet[:100],
                "refdet": refdet,
                "saisie": settings.PAYFIP_SAISIE,
                "urlnotif": urlnotif,
                "urlredirect": urlredirect,
            },
        )
        identifiant = valeurs.get("idOp", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", identifiant):
            raise PayFiPIndisponible("Identifiant d'opération PayFiP absent ou invalide.", code="payfip_reponse_invalide")
        return identifiant

    def detail(self, id_op: str) -> DetailPaiement | None:
        """Détail d'une opération ; None si PayFiP n'a pas (encore) de résultat (faute à la lecture : paiement non
        terminé, opération inconnue ou expirée — le code est journalisé)."""
        try:
            v = self._appel("recupererDetailPaiementSecurise", {"idOp": id_op})
        except ErreurMetier as erreur:
            if erreur.code == "payfip_refus":
                journal.info("PayFiP : pas de résultat pour %s (faute %s)", id_op[:64], (erreur.details or {}).get("code_payfip"))
                return None
            raise
        montant = v.get("montant", "")
        return DetailPaiement(
            id_op=v.get("idOp", ""),
            resultrans=v.get("resultrans", ""),
            numauto=v.get("numauto", "")[:20],
            dattrans=v.get("dattrans", ""),
            heurtrans=v.get("heurtrans", ""),
            montant=int(montant) if montant.isdecimal() else -1,
            refdet=v.get("refdet", ""),
            exer=v.get("exer", ""),
            numcli=v.get("numcli", ""),
            saisie=v.get("saisie", ""),
        )

    @staticmethod
    def url_paiement(id_op: str) -> str:
        return f"{settings.PAYFIP_URL_PAIEMENT}?idop={id_op}"
