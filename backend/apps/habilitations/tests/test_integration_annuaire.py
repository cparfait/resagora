"""SEC-02 / ADM-06 contre le vrai annuaire de test (OpenLDAP en LDAPS, conteneur `annuaire`).

Lancer avec : pytest -m integration (les secrets de développement doivent exister, `make secrets certs`).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from apps.habilitations.ldap import Annuaire, AnnuaireIndisponible

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

SECRETS = Path(__file__).resolve().parents[4] / "deploy" / "dev" / "secrets"
URI = os.environ.get("ANNUAIRE_TEST_URI", "ldaps://localhost:50636")


def _conf(**surcharges: object) -> dict[str, object]:
    if not (SECRETS / "ldap_mot_de_passe").exists():
        pytest.skip("Secrets de développement absents")
    conf: dict[str, object] = {
        "URI": URI,
        "STARTTLS": False,
        "FICHIER_AC": str(SECRETS / "ac_interne.crt"),
        "VERIFIER_CERTIFICAT": True,
        "COMPTE_SERVICE_DN": "cn=svc-equipements,ou=services,dc=chatillon,dc=test",
        "COMPTE_SERVICE_MOT_DE_PASSE": (SECRETS / "ldap_mot_de_passe").read_text().strip(),
        "BASE_UTILISATEURS": "ou=agents,dc=chatillon,dc=test",
        "BASE_GROUPES": "ou=groupes,dc=chatillon,dc=test",
        "FILTRE_UTILISATEUR": "(&(objectClass=inetOrgPerson)(uid={identifiant}))",
        "MODE_GROUPES": "memberof",
        "ATTRIBUT_IDENTIFIANT": "uid",
        "ATTRIBUT_PRENOM": "givenName",
        "ATTRIBUT_NOM": "sn",
        "ATTRIBUT_COURRIEL": "mail",
        "ATTRIBUT_GROUPES": "memberOf",
        "DELAI_SECONDES": 5,
    }
    conf.update(surcharges)
    return conf


def _mdp_agents() -> str:
    return (SECRETS / "mdp_agents_demo").read_text().strip()


def test_sec02_ldaps_reel_authentifie_et_lit_les_groupes():
    entree = Annuaire(_conf()).authentifier("gest.ville", _mdp_agents())
    assert entree is not None and entree.courriel == "gest.ville@chatillon.test"
    assert "cn=GG-Equipements-Gestionnaires,ou=groupes,dc=chatillon,dc=test" in entree.groupes


def test_adm06_ldaps_reel_mode_recherche_des_groupes():
    entree = Annuaire(_conf(MODE_GROUPES="recherche")).authentifier("gardien03", _mdp_agents())
    assert entree is not None and entree.groupes == ["cn=GG-Equipements-Gardiens,ou=groupes,dc=chatillon,dc=test"]


def test_sec02_ldaps_reel_mot_de_passe_faux():
    assert Annuaire(_conf()).authentifier("gest.ville", "mauvais") is None


def test_sec02_ldaps_certificat_non_reconnu_refuse(tmp_path):
    autre_ac = tmp_path / "autre.crt"
    autre_ac.write_text(
        (SECRETS / "annuaire.crt").read_text().split("-----END CERTIFICATE-----")[0] + "-----END CERTIFICATE-----\n"
    )
    with pytest.raises(AnnuaireIndisponible):
        Annuaire(_conf(FICHIER_AC=str(autre_ac))).authentifier("gest.ville", _mdp_agents())
