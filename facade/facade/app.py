"""Façade DMZ du portail : aucune donnée métier, un seul flux sortant mTLS vers l'API (SEC-01).

Rôles : liste blanche des routes, sessions usagers (jeton API jamais exposé au navigateur),
CSRF et contrôle d'origine, limitation de débit (SEC-06), en-têtes de sécurité (SEC-05),
quarantaine et antivirus des fichiers (SEC-07), vérification des rappels DocuSeal et PayFiP
(SIG-02, TAR-07) avant relais, et relais de l'API mobile en option B (SEC-10).
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import logging
import secrets
import ssl
import uuid
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route as RouteStarlette

from .config import Configuration
from .fichiers import AnalyseurClamAV, FichierRefuse, Quarantaine
from .routes import DEBITS, Nature, Route, trouver
from .sessions import GestionnaireSessions, Magasin, MagasinValkey

journal = logging.getLogger("facade")

COOKIE_SESSION = "__Host-portail"
COOKIE_CSRF = "__Host-csrf-portail"
METHODES_SURES = {"GET", "HEAD", "OPTIONS"}
ENTETES_REPONSE_RELAYES = {"content-type", "content-disposition", "cache-control", "retry-after", "x-request-id"}
ENTETES_SECURITE = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}


def erreur(statut: int, code: str, message: str, **entetes: str) -> JSONResponse:
    return JSONResponse({"code": code, "message": message}, status_code=statut, headers=entetes or None)


class EntetesSecurite(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        reponse = await call_next(request)
        for nom, valeur in ENTETES_SECURITE.items():
            if nom == "Cache-Control" and nom in reponse.headers:
                continue
            reponse.headers[nom] = valeur
        if "server" in reponse.headers:
            del reponse.headers["server"]
        return reponse


class Facade:
    def __init__(
        self,
        config: Configuration,
        magasin: Magasin | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        analyseur: AnalyseurClamAV | None = None,
    ):
        self.config = config
        self.magasin: Magasin = magasin or MagasinValkey(config.valkey_url)
        self.sessions = GestionnaireSessions(self.magasin, config.duree_session_s, config.duree_session_max_s)
        self.quarantaine = Quarantaine(
            config.dossier_quarantaine,
            config.taille_max_fichier,
            analyseur or AnalyseurClamAV(config.clamav_hote, config.clamav_port),
        )
        if transport is not None:
            self.client = httpx.AsyncClient(base_url=config.api_url, transport=transport, timeout=config.delai_api_s)
        else:
            contexte = ssl.create_default_context(cafile=config.ac_api)
            contexte.minimum_version = ssl.TLSVersion.TLSv1_2
            contexte.load_cert_chain(config.certificat_client, config.cle_client)
            self.client = httpx.AsyncClient(base_url=config.api_url, verify=contexte, timeout=config.delai_api_s)

    # --- utilitaires ---------------------------------------------------------------------------

    def adresse_client(self, request: Request) -> str:
        transmise = [a.strip() for a in request.headers.get("x-forwarded-for", "").split(",") if a.strip()]
        if transmise and self.config.nombre_proxies:
            return transmise[-min(self.config.nombre_proxies, len(transmise))]
        return request.client.host if request.client else "inconnue"

    @staticmethod
    def cle_debit(adresse: str) -> str:
        """IPv6 : comptage par préfixe /64 (une box change d'adresse dans son préfixe)."""
        try:
            ip = ipaddress.ip_address(adresse)
        except ValueError:
            return adresse
        if ip.version == 6:
            return str(ipaddress.ip_network(f"{ip}/64", strict=False))
        return str(ip)

    def debit_depasse(self, route: Route, adresse: str) -> bool:
        maximum, fenetre = DEBITS[route.debit]
        maximum *= self.config.facteur_debit
        return self.magasin.incrementer(f"debit:{route.debit}:{self.cle_debit(adresse)}", fenetre) > maximum

    def cookie(self, reponse: Response, nom: str, valeur: str, duree: int, http_only: bool = True) -> None:
        nom_effectif = nom if self.config.cookies_securises else nom.removeprefix("__Host-")
        reponse.set_cookie(
            nom_effectif,
            valeur,
            max_age=duree,
            path="/",
            secure=self.config.cookies_securises,
            httponly=http_only,
            samesite="lax",
        )

    def lire_cookie(self, request: Request, nom: str) -> str | None:
        return request.cookies.get(nom if self.config.cookies_securises else nom.removeprefix("__Host-"))

    def origine_valide(self, request: Request) -> bool:
        origine = request.headers.get("origin") or request.headers.get("referer", "")
        return origine == self.config.origine or origine.startswith(self.config.origine + "/")

    def entetes_api(self, request: Request, jeton: str | None) -> dict[str, str]:
        entetes = {
            "Accept": "application/json",
            "Accept-Language": "fr",
            # Identifiant de corrélation toujours généré ici : celui envoyé par Internet n'est pas repris.
            "X-Request-Id": request.state.identifiant_requete,
            "X-Forwarded-For": self.adresse_client(request),
            "X-Forwarded-Proto": "https",
        }
        if jeton:
            entetes["Authorization"] = f"Portail {jeton}"
        return entetes

    @staticmethod
    def reponse_relayee(reponse_api: httpx.Response, corps: bytes | None = None) -> Response:
        entetes = {k: v for k, v in reponse_api.headers.items() if k.lower() in ENTETES_REPONSE_RELAYES}
        return Response(corps if corps is not None else reponse_api.content, status_code=reponse_api.status_code, headers=entetes)

    async def appeler(self, methode: str, chemin: str, **options: Any) -> httpx.Response | None:
        try:
            return await self.client.request(methode, chemin, **options)
        except (httpx.HTTPError, httpx.InvalidURL) as erreur_api:
            journal.error("API métier injoignable : %s", type(erreur_api).__name__)
            return None

    # --- routes locales ------------------------------------------------------------------------

    async def etat_session(self, request: Request) -> Response:
        request.state.identifiant_requete = uuid.uuid4().hex
        """Indique l'état de connexion et fournit le jeton CSRF (double soumission pour les visiteurs)."""
        identifiant = self.lire_cookie(request, COOKIE_SESSION)
        session = self.sessions.lire(identifiant)
        if session is not None:
            return JSONResponse(
                {"connecte": True, "csrf": session.csrf, "expire_dans": session.restant(), "contact": session.contact}
            )
        csrf = self.lire_cookie(request, COOKIE_CSRF) or secrets.token_urlsafe(32)
        reponse = JSONResponse({"connecte": False, "csrf": csrf, "expire_dans": 0, "contact": None})
        self.cookie(reponse, COOKIE_CSRF, csrf, 12 * 3600)
        return reponse

    async def prolonger_session(self, request: Request) -> Response:
        identifiant = self.lire_cookie(request, COOKIE_SESSION)
        session = self.sessions.lire(identifiant)
        if session is None or identifiant is None:
            return erreur(401, "session_expiree", "Votre session a expiré. Reconnectez-vous.")
        if not self.origine_valide(request) or not hmac.compare_digest(request.headers.get("x-csrf-token", ""), session.csrf):
            return erreur(403, "csrf", "Requête refusée. Rechargez la page.")
        session = self.sessions.prolonger(identifiant, session)
        reponse = JSONResponse(
            {"connecte": True, "csrf": session.csrf, "expire_dans": session.restant(), "contact": session.contact}
        )
        self.cookie(reponse, COOKIE_SESSION, identifiant, session.restant())
        return reponse

    async def sante(self, request: Request) -> Response:
        return JSONResponse({"etat": "ok"})

    # --- relais --------------------------------------------------------------------------------

    async def relayer(self, request: Request) -> Response:
        # Chemin exact de la requête (sans la normalisation d'URL qui retirerait des caractères de contrôle).
        chemin = request.scope["path"]
        request.state.identifiant_requete = uuid.uuid4().hex
        route = trouver(request.method, chemin, self.config.mobile_option)
        if route is None:
            return erreur(404, "introuvable", "Élément introuvable.")
        adresse = self.adresse_client(request)
        if self.debit_depasse(route, adresse):
            return erreur(
                429, "trop_de_requetes", "Trop de tentatives. Réessayez dans quelques minutes.", **{"Retry-After": "60"}
            )
        longueur = request.headers.get("content-length") or "0"
        if not longueur.isascii() or not longueur.isdigit():
            return erreur(400, "requete_invalide", "La requête est invalide.")
        taille_annoncee = int(longueur)
        limite = (
            self.config.taille_max_fichier + 1024 * 1024 if route.nature == Nature.TELEVERSEMENT else self.config.taille_max_json
        )
        if taille_annoncee > limite:
            return erreur(413, "trop_volumineux", "Le contenu envoyé est trop volumineux.")

        if route.nature == Nature.WEBHOOK_DOCUSEAL:
            return await self.relayer_webhook_docuseal(request, chemin)
        if route.nature == Nature.NOTIFICATION_PAYFIP:
            return await self.relayer_notification_payfip(request, chemin, adresse)
        if route.nature == Nature.MOBILE:
            return await self.relayer_mobile(request, chemin)

        identifiant = self.lire_cookie(request, COOKIE_SESSION)
        session = self.sessions.lire(identifiant)
        if route.session_requise and session is None:
            return erreur(401, "session_expiree", "Votre session a expiré. Reconnectez-vous.")
        if request.method not in METHODES_SURES:
            attendu = session.csrf if session else self.lire_cookie(request, COOKIE_CSRF)
            fourni = request.headers.get("x-csrf-token", "")
            if not self.origine_valide(request) or not attendu or not hmac.compare_digest(fourni, attendu):
                return erreur(403, "csrf", "Requête refusée. Rechargez la page.")
        entetes = self.entetes_api(request, session.jeton_api if session else None)
        parametres = list(request.query_params.multi_items())

        if route.nature == Nature.TELEVERSEMENT:
            return await self.relayer_televersement(request, chemin, entetes, parametres)

        corps = await request.body()
        if len(corps) > limite:
            return erreur(413, "trop_volumineux", "Le contenu envoyé est trop volumineux.")
        if corps:
            entetes["Content-Type"] = "application/json"
            try:
                json.loads(corps)
            except ValueError:
                return erreur(400, "json_invalide", "Le contenu envoyé est invalide.")
        reponse_api = await self.appeler(request.method, chemin, params=parametres, content=corps or None, headers=entetes)
        if reponse_api is None:
            return erreur(503, "indisponible", "Le service est momentanément indisponible. Réessayez plus tard.")

        if route.nature == Nature.CONNEXION:
            return self.ouvrir_session(reponse_api, identifiant)
        if route.nature == Nature.DECONNEXION:
            if identifiant:
                self.sessions.supprimer(identifiant)
            reponse = Response(status_code=204)
            reponse.delete_cookie(
                COOKIE_SESSION if self.config.cookies_securises else COOKIE_SESSION.removeprefix("__Host-"), path="/"
            )
            return reponse
        if reponse_api.status_code == 401 and identifiant:
            self.sessions.supprimer(identifiant)
        return self.reponse_relayee(reponse_api)

    def ouvrir_session(self, reponse_api: httpx.Response, ancienne: str | None = None) -> Response:
        if reponse_api.status_code != 200:
            return self.reponse_relayee(reponse_api)
        if ancienne:
            self.sessions.supprimer(ancienne)
        donnees = reponse_api.json()
        jeton = donnees.pop("jeton", None)
        if not jeton:
            return JSONResponse(donnees)
        identifiant, session = self.sessions.creer(jeton, donnees.get("contact") or {})
        donnees["csrf"] = session.csrf
        donnees["expire_dans"] = session.restant()
        reponse = JSONResponse(donnees)
        self.cookie(reponse, COOKIE_SESSION, identifiant, session.restant())
        return reponse

    async def relayer_televersement(
        self, request: Request, chemin: str, entetes: dict[str, str], parametres: list[tuple[str, str]]
    ) -> Response:
        try:
            formulaire = await request.form(max_files=1, max_fields=20)
        except Exception:
            return erreur(400, "formulaire_invalide", "Le formulaire envoyé est invalide.")
        fichier = formulaire.get("fichier")
        if fichier is None or isinstance(fichier, str):
            return erreur(400, "fichier_absent", "Aucun fichier n'a été joint.")
        contenu = await fichier.read(self.config.taille_max_fichier + 1)
        try:
            controle = self.quarantaine.controler(fichier.filename or "document", contenu)
        except FichierRefuse as refus:
            return erreur(422, refus.code, refus.message)
        finally:
            await formulaire.close()
        donnees = {k: v for k, v in formulaire.items() if isinstance(v, str)}
        entetes = {**entetes, "X-Empreinte-Sha256": controle.sha256, "X-Fichier-Controle": "clamav"}
        reponse_api = await self.appeler(
            "POST",
            chemin,
            params=parametres,
            data=donnees,
            files={"fichier": (controle.nom_origine, controle.contenu, controle.type_mime)},
            headers=entetes,
        )
        if reponse_api is None:
            return erreur(503, "indisponible", "Le service est momentanément indisponible. Réessayez plus tard.")
        return self.reponse_relayee(reponse_api)

    async def relayer_webhook_docuseal(self, request: Request, chemin: str) -> Response:
        attendu = self.config.secret_webhook_docuseal
        fourni = request.headers.get(self.config.entete_webhook_docuseal, "")
        if not attendu or not hmac.compare_digest(fourni, attendu):
            journal.warning("Webhook DocuSeal refusé : secret absent ou invalide")
            return erreur(401, "non_autorise", "Non autorisé.")
        corps = await request.body()
        reponse_api = await self.appeler(
            "POST", chemin, content=corps, headers={**self.entetes_api(request, None), "Content-Type": "application/json"}
        )
        if reponse_api is None:
            return erreur(503, "indisponible", "Service indisponible.")
        return self.reponse_relayee(reponse_api)

    async def relayer_notification_payfip(self, request: Request, chemin: str, adresse: str) -> Response:
        if not self.config.payfip_sans_filtre_ip and adresse not in self.config.ips_payfip:
            journal.warning("Notification PayFiP refusée depuis %s", adresse)
            return erreur(403, "non_autorise", "Non autorisé.")
        corps = await request.body()
        entetes = {
            **self.entetes_api(request, None),
            "Content-Type": request.headers.get("content-type", "application/x-www-form-urlencoded"),
        }
        reponse_api = await self.appeler("POST", chemin, content=corps, headers=entetes)
        if reponse_api is None:
            return erreur(503, "indisponible", "Service indisponible.")
        return self.reponse_relayee(reponse_api)

    async def relayer_mobile(self, request: Request, chemin: str) -> Response:
        """Option B : le proxy DMZ a vérifié le certificat d'appareil ; on transmet son empreinte à l'API."""
        certificat = request.headers.get(self.config.entete_certificat_appareil.lower(), "")
        if not certificat:
            return erreur(403, "certificat_appareil_requis", "Appareil non reconnu.")
        entetes = self.entetes_api(request, None)
        entetes["X-Certificat-Appareil"] = certificat[:2000]
        autorisation = request.headers.get("authorization", "")
        if autorisation.startswith("Appareil "):
            entetes["Authorization"] = autorisation[:600]
        corps = await request.body()
        if corps:
            entetes["Content-Type"] = request.headers.get("content-type", "application/json")
        reponse_api = await self.appeler(
            request.method, chemin, params=list(request.query_params.multi_items()), content=corps or None, headers=entetes
        )
        if reponse_api is None:
            return erreur(503, "indisponible", "Service indisponible.")
        return self.reponse_relayee(reponse_api)


def creer_application(config: Configuration | None = None, **dependances: Any) -> Starlette:
    facade = Facade(config or Configuration(), **dependances)
    methodes = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"]
    application = Starlette(
        routes=[
            RouteStarlette("/sante", facade.sante, methods=["GET"]),
            RouteStarlette("/api/portail/session", facade.etat_session, methods=["GET"]),
            RouteStarlette("/api/portail/session/prolonger", facade.prolonger_session, methods=["POST"]),
            RouteStarlette("/{chemin:path}", facade.relayer, methods=methodes),
        ],
        middleware=[Middleware(EntetesSecurite)],
    )
    application.state.facade = facade
    return application
