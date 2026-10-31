"""Génère les autorités et certificats de DÉVELOPPEMENT / RECETTE (jamais pour la production).

- AC interne : certificats serveur (api-portail mTLS 8443, annuaire LDAPS, proxys LAN et DMZ) ;
- AC façade : certificat client de la façade, seul accepté par api-portail (SEC-01) ;
- AC appareils : certificats des smartphones pour l'option B de l'accès mobile (SEC-10).
Les fichiers sont écrits dans deploy/*/secrets (ignorés par Git). Idempotent.
"""

from __future__ import annotations

import datetime
import ipaddress
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

RACINE = Path(__file__).resolve().parent.parent
LAN, DMZ, DEV = (RACINE / "deploy" / z / "secrets" for z in ("lan", "dmz", "dev"))
DUREE_JOURS = 825


def nom(cn: str) -> x509.Name:
    return x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "FR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Ville de Châtillon (développement)"),
        x509.NameAttribute(NameOID.COMMON_NAME, cn),
    ])


def ecrire(chemin: Path, contenu: bytes, prive: bool = False) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_bytes(contenu)
    if prive:
        chemin.chmod(0o600)


def pem_cle(cle: ec.EllipticCurvePrivateKey) -> bytes:
    return cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())


def pem(certificat: x509.Certificate) -> bytes:
    return certificat.public_bytes(serialization.Encoding.PEM)


def autorite(cn: str) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    cle = ec.generate_private_key(ec.SECP384R1())
    maintenant = datetime.datetime.now(datetime.UTC)
    certificat = (
        x509.CertificateBuilder()
        .subject_name(nom(cn)).issuer_name(nom(cn)).public_key(cle.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(maintenant - datetime.timedelta(minutes=5))
        .not_valid_after(maintenant + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(cle.public_key()), critical=False)
        .sign(cle, hashes.SHA384())
    )
    return cle, certificat


def certificat(
    ac: tuple[ec.EllipticCurvePrivateKey, x509.Certificate], cn: str, noms: list[str], client: bool = False
) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    cle = ec.generate_private_key(ec.SECP256R1())
    maintenant = datetime.datetime.now(datetime.UTC)
    alternatifs: list[x509.GeneralName] = []
    for n in noms:
        try:
            alternatifs.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            alternatifs.append(x509.DNSName(n))
    constructeur = (
        x509.CertificateBuilder()
        .subject_name(nom(cn)).issuer_name(ac[1].subject).public_key(cle.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(maintenant - datetime.timedelta(minutes=5))
        .not_valid_after(maintenant + datetime.timedelta(days=DUREE_JOURS))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(True, False, True, False, False, False, False, False, False), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH if client else ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ac[0].public_key()), critical=False)
    )
    if alternatifs:
        constructeur = constructeur.add_extension(x509.SubjectAlternativeName(alternatifs), critical=False)
    return cle, constructeur.sign(ac[0], hashes.SHA256())


def main() -> int:
    if (LAN / "ac_interne.crt").exists() and "--forcer" not in sys.argv:
        print("Certificats de développement déjà présents (utiliser --forcer pour régénérer).")
        return 0
    ac_interne, ac_facade, ac_appareils = autorite("AC interne (dev)"), autorite("AC façade (dev)"), autorite("AC appareils (dev)")
    for dossier in (LAN, DMZ, DEV):
        ecrire(dossier / "ac_interne.crt", pem(ac_interne[1]))
    ecrire(LAN / "ac_facade.crt", pem(ac_facade[1]))
    ecrire(LAN / "ac_appareils.crt", pem(ac_appareils[1]))
    ecrire(DMZ / "ac_appareils.crt", pem(ac_appareils[1]))

    serveurs = {
        (LAN, "api_portail"): ("api-portail", ["api-portail", "localhost", "127.0.0.1"]),
        (LAN, "lan_tls"): ("equipements.chatillon.local", ["equipements.chatillon.local", "gardiens.chatillon.local", "localhost", "127.0.0.1"]),
        (DMZ, "dmz_tls"): ("equipements.chatillon.test", ["equipements.chatillon.test", "signature.chatillon.test", "gardiens.chatillon.test", "localhost", "127.0.0.1"]),
        (DEV, "annuaire"): ("annuaire", ["annuaire", "localhost", "127.0.0.1"]),
    }
    for (dossier, fichier), (cn, noms) in serveurs.items():
        cle, cert = certificat(ac_interne, cn, noms)
        ecrire(dossier / f"{fichier}.crt", pem(cert) + pem(ac_interne[1]))
        ecrire(dossier / f"{fichier}.key", pem_cle(cle), prive=True)

    cle, cert = certificat(ac_facade, "facade-portail", [], client=True)
    ecrire(DMZ / "facade_client.crt", pem(cert))
    ecrire(DMZ / "facade_client.key", pem_cle(cle), prive=True)

    cle, cert = certificat(ac_appareils, "appareil-demo-01", [], client=True)
    ecrire(DEV / "appareil-demo-01.crt", pem(cert))
    ecrire(DEV / "appareil-demo-01.key", pem_cle(cle), prive=True)
    ecrire(DEV / "appareil-demo-01.p12", pkcs12.serialize_key_and_certificates(
        b"appareil-demo-01", cle, cert, [ac_appareils[1]], serialization.NoEncryption()
    ), prive=True)
    print("Certificats de développement générés dans deploy/lan/secrets, deploy/dmz/secrets et deploy/dev/secrets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
