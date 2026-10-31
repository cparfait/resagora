"""ADM-06 : amorçage des correspondances groupes AD ; SEC-02 : diagnostic de l'annuaire."""

from __future__ import annotations

import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.habilitations.models import GroupeAD
from tests.fabriques import SiteFabrique

pytestmark = pytest.mark.django_db


def test_adm06_amorcer_groupes_ad_ville_entiere_et_sites(tmp_path):
    site = SiteFabrique(code="complexe-nord")
    fichier = tmp_path / "groupes.json"
    fichier.write_text(
        json.dumps(
            [
                {"dn": "CN=Admins,DC=test", "role": "administrateur", "perimetre": "Ville entière"},
                {"dn": "CN=Nord,DC=test", "role": "gestionnaire", "perimetre": ["complexe-nord"], "nom_perimetre": "Nord"},
            ]
        ),
        encoding="utf-8",
    )
    call_command("amorcer_groupes_ad", str(fichier))
    call_command("amorcer_groupes_ad", str(fichier))
    assert GroupeAD.objects.count() == 2
    nord = GroupeAD.objects.get(dn="CN=Nord,DC=test")
    assert list(nord.perimetre.sites.all()) == [site] and nord.role.code == "gestionnaire"


def test_adm06_amorcer_refuse_un_role_inconnu(tmp_path):
    fichier = tmp_path / "groupes.json"
    fichier.write_text(json.dumps([{"dn": "CN=X", "role": "pirate", "perimetre": "Ville entière"}]), encoding="utf-8")
    with pytest.raises(CommandError):
        call_command("amorcer_groupes_ad", str(fichier))
