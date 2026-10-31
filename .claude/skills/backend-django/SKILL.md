---
name: backend-django
description: Conventions du backend Django/DRF/Celery de la plateforme (structure des apps, services, permissions rôle × périmètre, migrations, tests pytest). À charger pour tout code dans backend/.
---

# Backend Django

Versions de référence (oct. 2026, voir §6.6 du cahier des charges) : Python 3.14, Django 6.1
puis 6.2 LTS dès avril 2027, Django REST Framework 3.18, Celery 5.6, psycopg 3, PostgreSQL 18
puis 19, Valkey 9 (compatible avec le client `redis-py`). Python 3.15 seulement quand Django le
prend officiellement en charge.

## Structure

```
backend/
├── config/                 # settings (base, dev, recette, prod), urls, celery
├── apps/
│   ├── referentiel/        # Site, Batiment, Espace, Saison, Calendrier
│   ├── usagers/            # Usager, Contact, PieceJustificative
│   ├── reservations/       # Dossier, Reservation, Occurrence
│   ├── finances/           # GrilleTarifaire, Tarif, Facture, Titre, Caution
│   ├── documents/          # Modele, Document, Signature
│   ├── communication/      # Message, Notification
│   ├── personnel/          # Agent, Habilitation, Vacation, Absence
│   ├── materiel/           # Materiel, Stock, Mouvement
│   ├── valorisation/       # Valorisation
│   ├── habilitations/      # Role, Perimetre, Habilitation agent
│   └── audit/              # JournalAudit
└── tests/
```

Chaque app : `models.py`, `services.py` (logique métier), `selectors.py` (lectures filtrées par périmètre), `api/` (serializers, views, urls), `tasks.py` (Celery), `tests/`.

## Règles

- **Vues fines, services épais.** Une vue DRF valide l'entrée, appelle un service, sérialise la sortie. Toute règle de gestion est dans `services.py` et testée sans HTTP.
- **Lectures par sélecteur** : `selectors.reservations_visibles(agent)` applique le périmètre. Jamais `Model.objects.all()` dans une vue.
- **Permissions** : classe DRF `PerimetrePermission` + `has_object_permission` qui délègue à `habilitations.peut(agent, action, objet)`. Une action = un verbe (`creer`, `valider`, `encaisser`, …) listé dans `habilitations/actions.py`.
- **Deux espaces d'API** : `/api/gestion/*` (agents, auth AD/session) et `/api/portail/*` (usagers, jetons portail). Aucune vue n'est montée dans les deux.
- **Transactions** : toute transition de statut dans `transaction.atomic()` + `select_for_update()` sur l'objet.
- **Audit** : décorateur `@audite("action")` sur les services qui écrivent ; il enregistre acteur, objet, avant/après.
- **Montants** : `PositiveBigIntegerField` en centimes. Helper `euros(cents)` pour l'affichage.
- **Dates** : `USE_TZ=True`, `TIME_ZONE="Europe/Paris"`, plages en `DateTimeRangeField`.
- **Anti-chevauchement** : `ExclusionConstraint` (extension `btree_gist`) sur `(espace, plage)` filtrée par statut bloquant.
- **Tâches Celery** idempotentes (clé d'idempotence), réessais avec backoff, jamais de logique métier dupliquée : elles appellent les services.
- **Auth AD** : `django-auth-ldap` en LDAPS, mapping groupes AD → rôles ; le périmètre est en base.
- **OpenAPI** : `drf-spectacular`, schéma publié et versionné.

## Migrations

- Une migration par changement logique, nommée explicitement.
- Toujours réversible ; migrations de données avec `RunPython(forward, backward)`.
- Pas de suppression de colonne dans la même version que l'arrêt de son usage (déploiement sans interruption).

## Tests

- `pytest`, `pytest-django`, `factory_boy` ; fixtures sans données personnelles réelles (Faker `fr_FR`).
- Par endpoint : succès, validation, **accès hors périmètre refusé (403/404)**, non authentifié (401).
- Par règle de gestion : test unitaire du service nommé avec l'ID (`test_rg01_chevauchement_refuse`).
- `freezegun` pour les dates ; tester les changements d'heure.
