"""Jeu de démonstration : volumes attendus (tests-recette) et cohérence des réservations."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.referentiel.models import Espace, Site
from apps.reservations.models import Occurrence, Verrou
from apps.usagers.models import Usager

pytestmark = pytest.mark.django_db


def test_jeu_de_demonstration_complet_et_coherent():
    call_command("charger_demo")
    assert Site.objects.filter(code__startswith="demo-").count() == 3
    assert Espace.objects.count() == 40 and Espace.objects.filter(parent__isnull=False).count() == 5
    assert Usager.objects.filter(type="association").count() == 40 and Usager.objects.filter(type="ecole").count() == 5
    assert Usager.objects.filter(type="particulier").count() == 10
    assert Occurrence.objects.filter(statut__in=["validee", "confirmee"]).count() > 500
    assert Verrou.objects.exists()
    assert (
        Occurrence.objects.filter(
            reservation__dossier__usager__type="particulier", reservation__dossier__type_reservation__code="location"
        ).count()
        >= 5
    )
    with pytest.raises(CommandError):
        call_command("charger_demo")
