"""EXP-01 — Sauvegarde chiffrée et restauration réelles avec l'image PostgreSQL et les scripts de deploy/lan.

Le test reprend l'image, les options et les commandes de préparation des services de deploy/lan/compose.yaml : il
sauvegarde, modifie la base et les fichiers déposés, expédie les WAL, restaure à un instant donné dans des volumes
neufs, puis vérifie données, fichiers, chiffrement et refus. Conteneurs, volumes et réseau sont jetables.

Lancer avec : pytest -m integration (Docker requis ; n'utilise ni ne touche la pile de développement).
"""

from __future__ import annotations

import datetime
import secrets
import shutil
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

pytestmark = pytest.mark.integration

RACINE = Path(__file__).resolve().parents[2]
LAN = RACINE / "deploy" / "lan"
SCRIPTS = LAN / "sauvegarde"
INITDB = LAN / "postgres" / "initdb"
DOCKER = shutil.which("docker")
Processus = subprocess.CompletedProcess[str]


def _docker(*arguments: str, verifier: bool = True) -> Processus:
    assert DOCKER is not None
    # Arguments construits par le test lui-même (noms jetables, chemins du dépôt).
    resultat = subprocess.run(  # noqa: S603
        [DOCKER, *arguments], capture_output=True, text=True, encoding="utf-8", timeout=300, check=False
    )
    if verifier and resultat.returncode != 0:
        raise AssertionError(f"docker {' '.join(arguments)}\n{resultat.stdout}\n{resultat.stderr}")
    return resultat


def _paire_de_cles(dossier: Path, prefixe: str) -> None:
    cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nom = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Sauvegardes (test)")])
    maintenant = datetime.datetime.now(datetime.UTC)
    certificat = (
        x509.CertificateBuilder()
        .subject_name(nom)
        .issuer_name(nom)
        .public_key(cle.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(maintenant - datetime.timedelta(minutes=5))
        .not_valid_after(maintenant + datetime.timedelta(days=365))
        .sign(cle, hashes.SHA256())
    )
    (dossier / f"{prefixe}_certificat").write_bytes(certificat.public_bytes(serialization.Encoding.PEM))
    (dossier / f"{prefixe}_cle_privee").write_bytes(
        cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )


class Banc:
    """Une base « postgres » jetable configurée comme en production, et de quoi la sauvegarder."""

    def __init__(self, dossier: Path) -> None:
        services = yaml.safe_load((LAN / "compose.yaml").read_text(encoding="utf-8"))["services"]
        self.image: str = services["postgres"]["image"]
        self.commande: list[str] = services["postgres"]["command"]
        self.preparation_wal: list[str] = services["preparer-wal"]["entrypoint"]
        self.preparation_cible: list[str] = services["preparer-sauvegardes"]["entrypoint"]
        self.prefixe = f"exp01-{secrets.token_hex(4)}"
        self.secrets = dossier / "secrets"
        self.secrets.mkdir()
        self.mdp = secrets.token_urlsafe(18)
        for nom in ("postgres_password", "postgres_app_password", "postgres_sauvegarde_password"):
            (self.secrets / nom).write_text((self.mdp if nom == "postgres_password" else secrets.token_urlsafe(18)) + "\n")
        _paire_de_cles(self.secrets, "sauvegarde")
        _paire_de_cles(self.secrets, "autre")
        self.conteneurs: list[str] = []
        self.volumes: list[str] = []
        _docker("network", "create", self.nom("reseau"))

    def nom(self, suffixe: str) -> str:
        return f"{self.prefixe}-{suffixe}"

    def volume(self, suffixe: str) -> str:
        nom = self.nom(suffixe)
        if nom not in self.volumes:
            _docker("volume", "create", nom)
            self.volumes.append(nom)
        return nom

    def executer(self, *options: str, commande: list[str], verifier: bool = True) -> Processus:
        return _docker("run", "--rm", "--entrypoint", commande[0], *options, self.image, *commande[1:], verifier=verifier)

    def preparer(self) -> None:
        commun = ["--user", "0:0", "--cap-drop", "ALL", "--cap-add", "CHOWN", "--cap-add", "FOWNER"]
        wal, travail = f"{self.volume('wal')}:/archives", f"{self.volume('travail')}:/travail"
        self.executer(*commun, "-v", wal, "-v", travail, commande=self.preparation_wal)
        self.executer(*commun, "-v", f"{self.volume('sauvegardes')}:/sauvegardes", commande=self.preparation_cible)

    def demarrer_base(self, volume: str) -> str:
        nom = self.nom(volume)
        _docker(
            "run", "-d", "--name", nom, "--network", self.nom("reseau"), "--network-alias", "postgres",
            "-e", "POSTGRES_DB=equipements", "-e", "POSTGRES_USER=equipements",
            "-e", "POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password",
            "-v", f"{self.secrets}:/run/secrets:ro", "-v", f"{INITDB}:/docker-entrypoint-initdb.d:ro",
            "-v", f"{self.volume(volume)}:/var/lib/postgresql", "-v", f"{self.volume('wal')}:/archives",
            self.image, *self.commande,
        )  # fmt: skip
        self.conteneurs.append(nom)
        # Prête quand elle répond en TCP (le serveur temporaire de l'initialisation n'écoute que la socket locale).
        for _ in range(120):
            if self.sql(nom, "SELECT pg_is_in_recovery()", verifier=False).stdout.strip() == "f":
                return nom
            time.sleep(1)
        raise AssertionError(_docker("logs", nom, verifier=False).stderr[-3000:])

    def sql(self, conteneur: str, requete: str, *, verifier: bool = True) -> Processus:
        return _docker(
            "exec", "-e", f"PGPASSWORD={self.mdp}", conteneur,
            "psql", "-h", "127.0.0.1", "-U", "equipements", "-d", "equipements", "-AtX", "-v", "ON_ERROR_STOP=1", "-c", requete,
            verifier=verifier,
        )  # fmt: skip

    def sauvegarder(self, *variables: str, utilisateur: str = "equipements_sauvegarde", mdp: str = "") -> Processus:
        mdp = mdp or "postgres_sauvegarde_password"
        env = [option for variable in variables for option in ("-e", variable)]
        return self.executer(
            "--network", self.nom("reseau"), "--user", "999:999", "--read-only", "--tmpfs", "/tmp",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
            "-e", "PGHOST=postgres", "-e", f"PGUSER={utilisateur}", *env,
            "-v", f"{self.volume('sauvegardes')}:/sauvegardes", "-v", f"{self.volume('wal')}:/archives",
            "-v", f"{self.volume('travail')}:/travail", "-v", f"{self.volume('stockage')}:/stockage:ro",
            "-v", f"{SCRIPTS}:/opt/sauvegarde:ro",
            "-v", f"{self.secrets / mdp}:/run/secrets/postgres_sauvegarde_password:ro",
            "-v", f"{self.secrets / 'sauvegarde_certificat'}:/run/secrets/sauvegarde_certificat:ro",
            commande=["sh", "/opt/sauvegarde/sauvegarder.sh"], verifier=False,
        )  # fmt: skip

    def restaurer(self, volume: str, stockage: str, cle: str = "sauvegarde", **variables: str) -> Processus:
        env = [option for cle_env, valeur in variables.items() for option in ("-e", f"{cle_env}={valeur}")]
        return self.executer(
            "--user", "0:0", "--read-only", "--tmpfs", "/tmp", "--network", "none", "--cap-drop", "ALL",
            "--cap-add", "CHOWN", "--cap-add", "DAC_OVERRIDE", "--cap-add", "FOWNER",
            "--security-opt", "no-new-privileges:true", *env,
            "-v", f"{self.volume(volume)}:/var/lib/postgresql", "-v", f"{self.volume(stockage)}:/stockage",
            "-v", f"{self.volume('sauvegardes')}:/sauvegardes:ro", "-v", f"{self.volume('wal')}:/archives:ro",
            "-v", f"{SCRIPTS}:/opt/sauvegarde:ro",
            "-v", f"{self.secrets / f'{cle}_cle_privee'}:/run/secrets/sauvegarde_cle_privee:ro",
            commande=["sh", "/opt/sauvegarde/restaurer.sh"], verifier=False,
        )  # fmt: skip

    def dans_stockage(self, volume: str, script: str) -> Processus:
        return self.executer("-v", f"{self.volume(volume)}:/stockage", commande=["sh", "-c", script])

    def nettoyer(self) -> None:
        for nom in self.conteneurs:
            _docker("rm", "-f", "-v", nom, verifier=False)
        for nom in self.volumes:
            _docker("volume", "rm", "-f", nom, verifier=False)
        _docker("network", "rm", self.nom("reseau"), verifier=False)


@dataclass
class Resultats:
    sauvegarde: Processus
    cycle: Processus
    refus_replication: Processus
    refus_connexion: Processus
    archives_restantes: str
    en_clair: str
    restauration: Processus
    valeurs: str
    fichiers: str
    deuxieme: Processus
    sans_fuseau: Processus
    retour_ligne: Processus
    mauvaise_cle: Processus


ANCIEN = "touch -d '-5 minutes'"


@pytest.fixture(scope="module")
def scenario(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Resultats]:
    if DOCKER is None or _docker("info", verifier=False).returncode != 0:
        pytest.skip("Docker indisponible")
    banc = Banc(tmp_path_factory.mktemp("exp01"))
    try:
        banc.preparer()
        # Deux fichiers déposés avant la sauvegarde (il y a plus de 2 minutes).
        banc.dans_stockage(
            "stockage",
            "mkdir -p /stockage/ab && echo 'convention signée' > /stockage/ab/0123 && echo 'statuts' > /stockage/ab/4567"
            f" && {ANCIEN} /stockage/ab/0123 /stockage/ab/4567",
        )
        base = banc.demarrer_base("pgdata")
        banc.sql(base, "CREATE TABLE temoin (valeur text); INSERT INTO temoin VALUES ('avant_sauvegarde')")
        sauvegarde = banc.sauvegarder("SAUVEGARDE_UNE_FOIS=1")
        refus_replication = banc.sauvegarder("SAUVEGARDE_UNE_FOIS=1", utilisateur="equipements_app", mdp="postgres_app_password")
        mdp_sauvegarde = (banc.secrets / "postgres_sauvegarde_password").read_text().strip()
        refus_connexion = banc.executer(
            "--network", banc.nom("reseau"), "-e", f"PGPASSWORD={mdp_sauvegarde}",
            commande=["psql", "-h", "postgres", "-U", "equipements_sauvegarde", "-d", "equipements", "-c", "SELECT 1"],
            verifier=False,
        )  # fmt: skip

        # Après la sauvegarde : un fichier supprimé (purge par erreur), un fichier ajouté, des écritures.
        banc.dans_stockage(
            "stockage", f"rm /stockage/ab/0123 && echo 'attestation' > /stockage/ab/89ab && {ANCIEN} /stockage/ab/89ab"
        )
        banc.sql(base, "INSERT INTO temoin VALUES ('apres_sauvegarde')")
        time.sleep(1.5)
        cible = banc.sql(base, "SELECT now()").stdout.strip()
        time.sleep(1.5)
        banc.sql(base, "INSERT INTO temoin VALUES ('apres_cible')")
        segment = banc.sql(base, "SELECT pg_walfile_name(pg_switch_wal())").stdout.strip()
        for _ in range(60):
            if banc.sql(base, "SELECT last_archived_wal FROM pg_stat_archiver").stdout.strip() >= segment:
                break
            time.sleep(1)
        cycle = banc.sauvegarder("SAUVEGARDE_UNE_FOIS=1", "SAUVEGARDE_SANS_BASE=1")
        archives_restantes = banc.executer(
            "-v", f"{banc.volume('wal')}:/archives", commande=["sh", "-c", "ls /archives | grep -v archtemp | wc -l"]
        ).stdout.strip()  # fmt: skip
        en_clair = banc.executer(
            "-v", f"{banc.volume('sauvegardes')}:/sauvegardes",
            commande=["sh", "-c", "grep -rlE 'convention|statuts|attestation|avant_sauvegarde' /sauvegardes | wc -l"],
        ).stdout.strip()  # fmt: skip
        _docker("stop", base)

        mauvaise_cle = banc.restaurer("pgdata-mauvaise-cle", "stockage-mauvaise-cle", cle="autre", CIBLE=cible)
        sans_fuseau = banc.restaurer("pgdata-sans-fuseau", "stockage-sans-fuseau", CIBLE="2026-11-01 10:00:00")
        retour_ligne = banc.restaurer("pgdata-retour", "stockage-retour", CIBLE="2026-11-01 10:00:00+01\nx")
        restauration = banc.restaurer("pgdata-restauree", "stockage-restaure", CIBLE=cible, FICHIERS="1")
        assert restauration.returncode == 0, restauration.stdout + restauration.stderr
        restauree = banc.demarrer_base("pgdata-restauree")
        valeurs = banc.sql(restauree, "SELECT string_agg(valeur, ',' ORDER BY valeur) FROM temoin").stdout.strip()
        fichiers = banc.dans_stockage(
            "stockage-restaure", 'cd /stockage && for f in ab/*; do echo "$f $(stat -c %u $f) $(cat $f)"; done'
        ).stdout.strip()
        _docker("stop", restauree)
        deuxieme = banc.restaurer("pgdata-restauree", "stockage-autre", CIBLE=cible)

        yield Resultats(
            sauvegarde, cycle, refus_replication, refus_connexion, archives_restantes, en_clair, restauration,
            valeurs, fichiers, deuxieme, sans_fuseau, retour_ligne, mauvaise_cle,
        )  # fmt: skip
    finally:
        banc.nettoyer()


def test_exp01_cycle_de_sauvegarde_reussi(scenario: Resultats) -> None:
    assert scenario.sauvegarde.returncode == 0, scenario.sauvegarde.stdout + scenario.sauvegarde.stderr
    assert "chiffrée" in scenario.sauvegarde.stdout
    assert scenario.cycle.returncode == 0, scenario.cycle.stdout + scenario.cycle.stderr


def test_exp01_wal_expedies_puis_retires_du_volume_d_archivage(scenario: Resultats) -> None:
    assert scenario.archives_restantes == "0"


def test_exp01_sauvegardes_chiffrees(scenario: Resultats) -> None:
    # Ni la base, ni les fichiers déposés ne se lisent en clair dans la cible des sauvegardes.
    assert scenario.en_clair == "0"


def test_exp01_restauration_a_un_instant_donne(scenario: Resultats) -> None:
    # Les écritures postérieures à la sauvegarde sont rejouées depuis les WAL expédiés, jusqu'à la cible seulement.
    assert scenario.valeurs == "apres_sauvegarde,avant_sauvegarde"


def test_exp01_fichiers_restaures_y_compris_ceux_supprimes_apres_la_sauvegarde(scenario: Resultats) -> None:
    assert scenario.fichiers.splitlines() == [
        "ab/0123 10001 convention signée",
        "ab/4567 10001 statuts",
        "ab/89ab 10001 attestation",
    ]


def test_exp01_refus_role_applicatif_sans_replication(scenario: Resultats) -> None:
    assert scenario.refus_replication.returncode != 0
    assert "replication" in (scenario.refus_replication.stdout + scenario.refus_replication.stderr).lower()


def test_exp01_refus_connexion_du_role_de_sauvegarde_a_la_base_metier(scenario: Resultats) -> None:
    assert scenario.refus_connexion.returncode != 0
    assert "pg_hba.conf rejects" in scenario.refus_connexion.stderr


def test_exp01_refus_restauration_sur_volume_non_vide(scenario: Resultats) -> None:
    assert scenario.deuxieme.returncode != 0
    assert "n'est pas vide" in scenario.deuxieme.stderr


def test_exp01_refus_instant_cible_sans_fuseau_ou_sur_plusieurs_lignes(scenario: Resultats) -> None:
    for refus in (scenario.sans_fuseau, scenario.retour_ligne):
        assert refus.returncode != 0
        assert "instant cible invalide" in refus.stderr


def test_exp01_refus_restauration_avec_une_autre_cle(scenario: Resultats) -> None:
    assert scenario.mauvaise_cle.returncode != 0
    assert "illisible" in scenario.mauvaise_cle.stderr
