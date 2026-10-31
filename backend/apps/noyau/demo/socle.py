"""Jeu de démonstration (anonyme, déterministe) : référentiel, usagers, saison, réservations.

Aucune donnée personnelle réelle : noms et coordonnées générés par Faker (fr_FR, graine fixe).
Chaque lot ajoute sa partie (finances, personnel, matériel, valorisation) dans ce paquet.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from pathlib import Path
from typing import Any

from django.utils import timezone

from apps.noyau import fichiers
from apps.noyau.exceptions import ErreurMetier
from apps.referentiel.calendrier import feries_calcules, periodes_depuis_open_data
from apps.referentiel.models import Batiment, Espace, FamilleEspace, HoraireOuverture, PeriodeCalendrier, Saison, Site
from apps.reservations import services
from apps.reservations.models import Campagne, Dossier, Reservation, TypeReservation
from apps.usagers.models import Contact, PieceJustificative, Rattachement, TypePiece, Usager

PRENOMS = [
    "Camille",
    "Dominique",
    "Claude",
    "Alix",
    "Sacha",
    "Lou",
    "Noa",
    "Eden",
    "Maxime",
    "Charlie",
    "Andrea",
    "Jordan",
    "Morgan",
    "Alexis",
    "Lilou",
    "Hugo",
    "Inès",
    "Léo",
    "Manon",
    "Nathan",
    "Chloé",
    "Louis",
    "Emma",
    "Jules",
    "Léa",
    "Gabriel",
    "Sarah",
    "Adam",
]
NOMS = [
    "Martin",
    "Bernard",
    "Thomas",
    "Petit",
    "Robert",
    "Richard",
    "Durand",
    "Dubois",
    "Moreau",
    "Laurent",
    "Simon",
    "Michel",
    "Lefebvre",
    "Leroy",
    "Roux",
    "David",
    "Bertrand",
    "Morel",
    "Fournier",
    "Girard",
    "Bonnet",
    "Dupont",
    "Lambert",
    "Fontaine",
    "Rousseau",
    "Vincent",
]
VOIES = [
    "rue des Tilleuls",
    "avenue des Peupliers",
    "rue du Moulin",
    "allée des Acacias",
    "rue de la Fontaine",
    "boulevard des Sports",
    "rue des Écoles",
]


class Generateur:
    """Coordonnées fictives reproductibles (aucune donnée réelle)."""

    def __init__(self, graine: int):
        self.alea = random.Random(graine)

    def first_name(self) -> str:
        return self.alea.choice(PRENOMS)

    def last_name(self) -> str:
        return self.alea.choice(NOMS)

    def street_address(self) -> str:
        return f"{self.alea.randint(1, 120)} {self.alea.choice(VOIES)}"

    def phone_number(self) -> str:
        return "01 99 " + " ".join(f"{self.alea.randint(0, 99):02d}" for _ in range(3))


SYSTEME = services.SYSTEME
#: Parties du jeu ajoutées par les lots suivants (finances, personnel, matériel, valorisation).
EXTENSIONS: list[Callable[[dict[str, Any]], dict[str, int]]] = []
PDF_DEMO = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"

# (site, bâtiment, code, nom, famille, capacité, surface, gardiennage, partage, parent)
ESPACES: list[tuple[str, str, str, str, str, int, int, bool, int, str | None]] = [
    ("parc", "Gymnase Colette-Besson", "parc-gym-a", "Gymnase A (terrain entier)", "gymnase", 400, 1300, True, 1, None),
    ("parc", "Gymnase Colette-Besson", "parc-gym-a-t1", "Gymnase A — tiers 1", "gymnase", 120, 430, True, 1, "parc-gym-a"),
    ("parc", "Gymnase Colette-Besson", "parc-gym-a-t2", "Gymnase A — tiers 2", "gymnase", 120, 430, True, 1, "parc-gym-a"),
    ("parc", "Gymnase Colette-Besson", "parc-gym-a-t3", "Gymnase A — tiers 3", "gymnase", 120, 430, True, 1, "parc-gym-a"),
    ("parc", "Gymnase Colette-Besson", "parc-gym-b", "Gymnase B", "gymnase", 250, 900, True, 1, None),
    ("parc", "Pavillon des arts martiaux", "parc-dojo", "Dojo", "dojo", 60, 300, True, 1, None),
    ("parc", "Pavillon des arts martiaux", "parc-danse", "Salle de danse", "salle-sport", 40, 180, True, 1, None),
    ("parc", "Pavillon des arts martiaux", "parc-muscu", "Salle de musculation", "salle-sport", 25, 150, True, 1, None),
    ("parc", "Stade", "parc-synth", "Terrain synthétique (entier)", "terrain-exterieur", 300, 7000, True, 1, None),
    (
        "parc",
        "Stade",
        "parc-synth-m1",
        "Terrain synthétique — moitié nord",
        "terrain-exterieur",
        150,
        3500,
        True,
        1,
        "parc-synth",
    ),
    ("parc", "Stade", "parc-synth-m2", "Terrain synthétique — moitié sud", "terrain-exterieur", 150, 3500, True, 1, "parc-synth"),
    ("parc", "Stade", "parc-piste", "Piste d'athlétisme", "piste-athletisme", 80, 4000, True, 4, None),
    ("parc", "Tennis couverts", "parc-tennis-1", "Court de tennis couvert 1", "salle-sport", 4, 650, False, 1, None),
    ("parc", "Tennis couverts", "parc-tennis-2", "Court de tennis couvert 2", "salle-sport", 4, 650, False, 1, None),
    ("parc", "Club-house", "parc-reunion", "Salle de réunion du club-house", "salle-reunion", 30, 60, False, 1, None),
    ("centre", "Gymnase Jean-Jaurès", "centre-gym", "Gymnase Jean-Jaurès", "gymnase", 300, 1000, True, 1, None),
    ("centre", "Gymnase Jean-Jaurès", "centre-ttable", "Salle de tennis de table", "salle-sport", 40, 250, True, 1, None),
    ("centre", "Gymnase Jean-Jaurès", "centre-gymdouce", "Salle de gymnastique douce", "salle-sport", 25, 120, True, 1, None),
    ("centre", "Gymnase Jean-Jaurès", "centre-escalade", "Mur d'escalade", "salle-sport", 20, 200, True, 1, None),
    ("centre", "Halle des sports", "centre-halle", "Halle des sports", "gymnase", 500, 1600, True, 1, None),
    ("centre", "Halle des sports", "centre-boxe", "Salle de boxe", "salle-sport", 30, 160, True, 1, None),
    ("centre", "Halle des sports", "centre-polyvalente", "Salle polyvalente", "salle-associative", 80, 200, False, 1, None),
    ("centre", "Espace Mairie", "centre-reunion-1", "Salle de réunion 1", "salle-reunion", 20, 40, False, 1, None),
    ("centre", "Espace Mairie", "centre-reunion-2", "Salle de réunion 2", "salle-reunion", 20, 40, False, 1, None),
    ("centre", "Espace Mairie", "centre-reunion-3", "Salle de réunion 3", "salle-reunion", 40, 70, False, 1, None),
    ("maison", "Maison des associations", "maison-asso-1", "Salle associative 1", "salle-associative", 25, 50, False, 1, None),
    ("maison", "Maison des associations", "maison-asso-2", "Salle associative 2", "salle-associative", 25, 50, False, 1, None),
    ("maison", "Maison des associations", "maison-asso-3", "Salle associative 3", "salle-associative", 25, 50, False, 1, None),
    ("maison", "Maison des associations", "maison-asso-4", "Salle associative 4", "salle-associative", 40, 70, False, 1, None),
    ("maison", "Maison des associations", "maison-asso-5", "Salle associative 5", "salle-associative", 40, 70, False, 1, None),
    (
        "maison",
        "Maison des associations",
        "maison-atelier",
        "Atelier d'arts plastiques",
        "salle-associative",
        20,
        60,
        False,
        1,
        None,
    ),
    ("maison", "Maison des associations", "maison-musique", "Studio de musique", "salle-associative", 10, 35, False, 1, None),
    ("maison", "Maison des associations", "maison-cuisine", "Cuisine pédagogique", "salle-associative", 15, 45, False, 1, None),
    ("maison", "Salle des fêtes", "maison-fetes", "Grande salle des fêtes", "salle-fetes", 350, 500, True, 1, None),
    ("maison", "Salle des fêtes", "maison-fetes-petite", "Petite salle des fêtes", "salle-fetes", 120, 180, True, 1, None),
    ("maison", "Salle des fêtes", "maison-office", "Office traiteur", "salle-associative", 10, 40, False, 1, None),
    ("maison", "Théâtre", "maison-theatre", "Salle de spectacle", "salle-spectacle", 280, 400, True, 1, None),
    ("maison", "Théâtre", "maison-repet", "Salle de répétition", "salle-spectacle", 30, 90, False, 1, None),
    ("maison", "Théâtre", "maison-loges", "Loges", "salle-associative", 15, 40, False, 1, None),
    ("maison", "Maison des associations", "maison-numerique", "Espace numérique", "salle-associative", 16, 60, False, 1, None),
]
SITES = {
    "parc": ("Complexe sportif du Parc", "12 allée des Sports"),
    "centre": ("Pôle sportif du Centre", "3 rue de la Halle"),
    "maison": ("Maison des associations et salle des fêtes", "25 avenue de la Vie associative"),
}
ACTIVITES = [
    "basket-ball",
    "handball",
    "volley-ball",
    "badminton",
    "judo",
    "karaté",
    "danse",
    "gymnastique",
    "tennis de table",
    "escalade",
    "boxe",
    "futsal",
    "football",
    "athlétisme",
    "yoga",
    "théâtre",
    "chorale",
    "échecs",
    "arts plastiques",
    "tennis",
]


@dataclass
class Bilan:
    compteurs: dict[str, int] = field(default_factory=dict)

    def ajouter(self, cle: str, nombre: int = 1) -> None:
        self.compteurs[cle] = self.compteurs.get(cle, 0) + nombre


def deja_charge() -> bool:
    return Site.objects.filter(code__startswith="demo-").exists()


def referentiel(bilan: Bilan) -> dict[str, Espace]:
    sites = {}
    for code, (nom, adresse) in SITES.items():
        sites[code] = Site.objects.create(code=f"demo-{code}", nom=nom, adresse=adresse)
    familles = {f.code: f for f in FamilleEspace.objects.all()}
    batiments: dict[tuple[str, str], Batiment] = {}
    espaces: dict[str, Espace] = {}
    for site, batiment, code, nom, famille, capacite, surface, garde, partage, parent in ESPACES:
        cle = (site, batiment)
        if cle not in batiments:
            batiments[cle] = Batiment.objects.create(
                site=sites[site],
                nom=batiment,
                erp_type="X" if famille in {"gymnase", "dojo", "salle-sport"} else "L",
                erp_categorie="3",
            )
        espaces[code] = Espace.objects.create(
            batiment=batiments[cle],
            code=code,
            nom=nom,
            famille=familles[famille],
            capacite=capacite,
            surface_m2=surface,
            gardiennage_requis=garde,
            partageable=partage > 1,
            capacite_simultanee=partage,
            accessible_pmr=True,
            parent=espaces.get(parent) if parent else None,
            description=f"{nom} — {sites[site].nom}.",
            equipements="Vestiaires, douches" if garde else "Tables et chaises",
            activites=", ".join(random.sample(ACTIVITES, 3)),
            reservable_portail=famille != "salle-reunion" or code.endswith("3"),
        )
        soiree = famille in {"salle-fetes", "salle-spectacle"}
        for jour in range(7):
            fin = time(23, 59) if soiree else (time(23, 0) if jour < 5 else time(22, 0))
            HoraireOuverture.objects.create(espace=espaces[code], jour_semaine=jour, debut=time(8, 0), fin=fin)
    bilan.ajouter("sites", len(sites))
    bilan.ajouter("espaces", len(espaces))
    return espaces


def _luhn_valide(numero: str) -> bool:
    total = 0
    for rang, chiffre in enumerate(reversed(numero)):
        valeur = int(chiffre) * (2 if rang % 2 else 1)
        total += valeur - 9 if valeur > 9 else valeur
    return total % 10 == 0


def siret_fictif() -> str:
    """SIRET de démonstration volontairement invalide (clé de Luhn fausse) : jamais celui d'une entreprise réelle."""
    while True:
        numero = f"99{random.randint(10**11, 10**12 - 1)}"
        if not _luhn_valide(numero):
            return numero


def saison(bilan: Bilan) -> Saison:
    s = Saison.objects.create(nom="2026-2027", debut=date(2026, 9, 1), fin=date(2027, 7, 3), active=True)
    donnees = json.loads((Path(__file__).parent / "calendrier-zone-c-2026-2027.json").read_text(encoding="utf-8"))
    for p in periodes_depuis_open_data(donnees["results"]):
        if p.fin >= s.debut and p.debut <= s.fin:
            PeriodeCalendrier.objects.create(
                saison=s, nature="vacances", libelle=p.libelle, debut=p.debut, fin=p.fin, source="import", zone="Zone C"
            )
    for annee in (2026, 2027):
        for jour, libelle in feries_calcules(annee).items():
            if s.debut <= jour <= s.fin:
                PeriodeCalendrier.objects.create(saison=s, nature="ferie", libelle=libelle, debut=jour, fin=jour, source="calcul")
    Saison.objects.create(nom="2027-2028", debut=date(2027, 9, 1), fin=date(2028, 7, 1), active=False)
    bilan.ajouter("periodes_calendrier", s.periodes.count())
    return s


def _contact(faux: Generateur, domaine: str) -> Contact:
    prenom, nom = faux.first_name(), faux.last_name()
    identifiant = f"{prenom}.{nom}".lower().replace(" ", "-").replace("'", "")
    return Contact.objects.create(prenom=prenom, nom=nom, courriel=f"{identifiant}@{domaine}", telephone=faux.phone_number())


def _pieces_valides(usager: Usager) -> None:
    for type_piece in TypePiece.objects.filter(types_usager__contains=[usager.type], obligatoire=True):
        fichier = fichiers.enregistrer_genere(
            f"{type_piece.code}.pdf", PDF_DEMO, "application/pdf", depose_par="jeu de démonstration"
        )
        fin = date(2027, 9, 30) if type_piece.validite_mois else None
        PieceJustificative.objects.create(
            usager=usager, type_piece=type_piece, fichier=fichier, statut="valide", valide_jusqu_au=fin, verifie_le=timezone.now()
        )


def usagers(bilan: Bilan, faux: Generateur) -> dict[str, list[Usager]]:
    resultat: dict[str, list[Usager]] = {
        "association": [],
        "ecole": [],
        "entreprise": [],
        "particulier": [],
        "service_municipal": [],
    }
    for i in range(40):
        activite = ACTIVITES[i % len(ACTIVITES)]
        u = Usager.objects.create(
            type="association",
            nom=f"{random.choice(['Union sportive', 'Club', 'Amicale', 'Cercle', 'Association'])} {activite} {faux.last_name()}",
            rna=f"W92{i:07d}",
            adresse=faux.street_address(),
            code_postal="92320" if i % 5 else "92220",
            commune="Châtillon" if i % 5 else "Bagneux",
            local=i % 5 != 0,
            conventionne=i % 3 == 0,
            convention_reference=f"CONV-2026-{i:03d}" if i % 3 == 0 else "",
            convention_fin=date(2027, 8, 31) if i % 3 == 0 else None,
        )
        resultat["association"].append(u)
    for nom in (
        "École élémentaire des Tilleuls",
        "École élémentaire du Parc",
        "Collège de la Vallée",
        "Lycée des Métiers",
        "École maternelle des Lilas",
    ):
        resultat["ecole"].append(
            Usager.objects.create(type="ecole", nom=nom, adresse=faux.street_address(), code_postal="92320", commune="Châtillon")
        )
    for nom in ("CSE Société d'études techniques", "CSE Laboratoires de la Plaine", "Entreprise de services numériques"):
        resultat["entreprise"].append(
            Usager.objects.create(
                type="entreprise",
                nom=nom,
                siret=siret_fictif(),
                commune="Montrouge",
                code_postal="92120",
            )
        )
    for i in range(10):
        nom_complet = f"{faux.first_name()} {faux.last_name()}"
        resultat["particulier"].append(
            Usager.objects.create(
                type="particulier",
                nom=nom_complet,
                commune="Châtillon" if i % 2 else "Clamart",
                code_postal="92320" if i % 2 else "92140",
            )
        )
    for nom in ("Service des sports", "Service de la vie associative", "Service enfance et jeunesse"):
        resultat["service_municipal"].append(Usager.objects.create(type="service_municipal", nom=nom, commune="Châtillon"))
    for groupe in resultat.values():
        for u in groupe:
            contact = _contact(faux, "exemple.test")
            Rattachement.objects.create(
                usager=u,
                contact=contact,
                role="president" if u.type == "association" else "responsable",
                principal=True,
                peut_signer=True,
            )
            if u.type == "association":
                Rattachement.objects.create(usager=u, contact=_contact(faux, "exemple.test"), role="tresorier")
            if u.type != "service_municipal" and random.random() < 0.9:
                _pieces_valides(u)
            bilan.ajouter(f"usagers_{u.type}")
    return resultat


def _reserver(
    usager: Usager,
    type_code: str,
    espace: Espace,
    jour: date,
    debut: time,
    fin: time,
    recurrence: str = "",
    date_fin: date | None = None,
    saison_obj: Saison | None = None,
    statut: str = "confirmee",
    objet: str = "",
) -> Reservation | None:
    rattachement = usager.rattachements.first()
    dossier = services.creer_dossier(
        acteur=SYSTEME,
        usager=usager,
        type_reservation=TypeReservation.objects.get(code=type_code),
        objet=objet or f"Activité de {usager.nom}",
        saison=saison_obj,
        contact=rattachement.contact if rattachement else None,
    )
    try:
        reservation = services.ajouter_reservation(
            dossier,
            acteur=SYSTEME,
            espace=espace,
            date_debut=jour,
            date_fin=date_fin or jour,
            heure_debut=debut,
            heure_fin=fin,
            recurrence=recurrence,
        )
        if statut in {"validee", "confirmee"}:
            services._changer_statut(reservation, "validee", SYSTEME, valide_le=timezone.now())
            feuilles = espace.feuilles()
            for occurrence in reservation.occurrences.filter(statut="validee"):
                services.poser_verrous(occurrence, feuilles)
            if statut == "confirmee":
                services._changer_statut(reservation, "confirmee", SYSTEME, confirme_le=timezone.now())
        elif statut == "option":
            services._changer_statut(reservation, "option", SYSTEME, option_expire_le=timezone.now() + timedelta(days=5))
        elif statut == "en_instruction":
            services._changer_statut(reservation, "en_instruction", SYSTEME)
        return reservation
    except ErreurMetier:
        Dossier.objects.filter(pk=dossier.pk).delete()
        return None


def reservations(bilan: Bilan, espaces: dict[str, Espace], par_type: dict[str, list[Usager]], s: Saison) -> None:
    sportifs = [e for code, e in espaces.items() if e.famille.code in {"gymnase", "dojo", "salle-sport", "terrain-exterieur"}]
    jours = ["MO", "TU", "WE", "TH", "FR"]
    for i, association in enumerate(par_type["association"]):
        for k in range(1 + i % 3):
            espace = sportifs[(i * 3 + k) % len(sportifs)]
            jour_code = jours[(i + k) % 5]
            heure_debut = time(17 + (i + k) % 4, 0 if k % 2 else 30)
            premier = s.debut + timedelta(days=(jours.index(jour_code) - s.debut.weekday()) % 7)
            r = _reserver(
                association,
                "creneau_annuel",
                espace,
                premier,
                heure_debut,
                time(min(23, heure_debut.hour + 2), heure_debut.minute),
                f"FREQ=WEEKLY;BYDAY={jour_code}",
                date(2027, 6, 30),
                s,
                statut="confirmee" if (i + k) % 4 else "validee",
            )
            if r:
                bilan.ajouter("creneaux_annuels")
    for i, ecole in enumerate(par_type["ecole"]):
        espace = espaces["centre-gym" if i % 2 else "parc-gym-b"]
        premier = s.debut + timedelta(days=(i % 4 - s.debut.weekday()) % 7)
        if _reserver(
            ecole,
            "scolaire",
            espace,
            premier,
            time(9 + i, 0),
            time(10 + i, 30),
            f"FREQ=WEEKLY;BYDAY={jours[i % 4]}",
            date(2027, 6, 30),
            s,
        ):
            bilan.ajouter("occupations_scolaires")
    aujourd_hui = timezone.localdate()
    for i, particulier in enumerate(par_type["particulier"]):
        samedi = aujourd_hui + timedelta(days=(5 - aujourd_hui.weekday()) % 7 + 7 * (i + 1))
        salle = espaces["maison-fetes" if i % 2 else "maison-fetes-petite"]
        statut = ["confirmee", "validee", "option", "en_instruction", "demande"][i % 5]
        if _reserver(particulier, "location", salle, samedi, time(14, 0), time(23, 30), statut=statut, objet="Fête familiale"):
            bilan.ajouter("locations")
    for i, entreprise in enumerate(par_type["entreprise"]):
        jeudi = aujourd_hui + timedelta(days=(3 - aujourd_hui.weekday()) % 7 + 14)
        if _reserver(
            entreprise,
            "ponctuelle",
            espaces["centre-halle"],
            jeudi + timedelta(days=7 * i),
            time(12, 0),
            time(14, 0),
            statut="validee",
            objet="Tournoi inter-entreprises",
        ):
            bilan.ajouter("reservations_entreprises")
    ville = par_type["service_municipal"][0]
    samedi = aujourd_hui + timedelta(days=(5 - aujourd_hui.weekday()) % 7 + 21)
    if _reserver(
        ville, "municipal", espaces["centre-halle"], samedi, time(9, 0), time(18, 0), statut="confirmee", objet="Forum des sports"
    ):
        bilan.ajouter("evenements_municipaux")
    for i, association in enumerate(par_type["association"][:6]):
        mercredi = aujourd_hui + timedelta(days=(2 - aujourd_hui.weekday()) % 7 + 7 * (i + 2))
        if _reserver(
            association,
            "ponctuelle",
            espaces["parc-gym-a-t1"],
            mercredi,
            time(14, 0),
            time(16, 0),
            statut="demande",
            objet="Stage de vacances",
        ):
            bilan.ajouter("demandes_a_instruire")
    Campagne.objects.create(
        saison=Saison.objects.get(nom="2027-2028"),
        nom="Créneaux annuels 2027-2028",
        ouverture=aujourd_hui,
        cloture=aujourd_hui + timedelta(days=60),
        statut="ouverte",
    )


def charger(graine: int = 92320) -> dict[str, Any]:
    random.seed(graine)
    faux = Generateur(graine)
    bilan = Bilan()
    espaces = referentiel(bilan)
    s = saison(bilan)
    par_type = usagers(bilan, faux)
    reservations(bilan, espaces, par_type, s)
    return {"bilan": bilan.compteurs, "espaces": espaces, "usagers": par_type, "saison": s}
