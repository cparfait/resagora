# Interface unique des tâches du projet (CI et postes de développement).
# Poste Windows sans GNU Make (D-005) :
#   docker compose -f deploy/dev/compose.yaml run --rm outils make preparer lint test

SHELL := /bin/bash
PYTHON ?= python3
export PYTHONIOENCODING := utf-8

# Interpréteurs : variables d'environnement BACK_PY / FACADE_PY (conteneur d'outillage), sinon venv local.
BACK_PY ?= $(shell if [ -x backend/.venv/bin/python ]; then echo $(CURDIR)/backend/.venv/bin/python; elif [ -x backend/.venv/Scripts/python.exe ]; then echo $(CURDIR)/backend/.venv/Scripts/python.exe; else echo $(PYTHON); fi)
FACADE_PY ?= $(shell if [ -x facade/.venv/bin/python ]; then echo $(CURDIR)/facade/.venv/bin/python; elif [ -x facade/.venv/Scripts/python.exe ]; then echo $(CURDIR)/facade/.venv/Scripts/python.exe; else echo $(PYTHON); fi)

COMPOSE_DEV := docker compose -f deploy/dev/compose.yaml
COMPOSE_LAN := docker compose -f deploy/lan/compose.yaml -f deploy/lan/compose.dev.yaml
COMPOSE_DMZ := docker compose -f deploy/dmz/compose.yaml -f deploy/dmz/compose.dev.yaml

.PHONY: preparer up up-dmz down certs secrets demo test test-back test-facade test-front test-integration lint lint-back \
        lint-facade lint-front motifs matrice e2e a11y trivy sbom schema format-changed migrations-reversibles recette

preparer: ## Environnements Python (uv) et dépendances npm verrouillées
	cd backend && UV_PROJECT_ENVIRONMENT=$${BACK_VENV:-.venv} uv sync --frozen --inexact
	cd facade && UV_PROJECT_ENVIRONMENT=$${FACADE_VENV:-.venv} uv sync --frozen --inexact
	npm ci --no-audit --no-fund
	npm ci --prefix outils/codegen --no-audit --no-fund

## Piles ------------------------------------------------------------------------------------------

certs: ## Autorités et certificats de développement (mTLS, LDAPS) — jamais en production
	$(BACK_PY) scripts/certificats_dev.py

secrets: ## Secrets de développement aléatoires dans deploy/*/secrets (ignorés par Git)
	$(BACK_PY) scripts/secrets_dev.py

up: certs secrets ## Services de test + pile LAN (API, tâches, back-office, mobile)
	$(COMPOSE_DEV) up -d postgres-dev valkey-dev annuaire mailpit simulateurs
	$(COMPOSE_LAN) up -d --build --wait
	$(COMPOSE_LAN) exec -T api python manage.py amorcer_groupes_ad - < deploy/dev/groupes-ad-recette.json

up-dmz: certs secrets ## Façade, portail et signature (DMZ) reliés à la pile LAN
	$(COMPOSE_DMZ) up -d --build --wait

down:
	-$(COMPOSE_DMZ) down
	-$(COMPOSE_LAN) down
	-$(COMPOSE_DEV) down

demo: ## Jeu de données de démonstration anonyme (3 sites, 40 espaces, une saison complète)
	$(COMPOSE_LAN) exec -T api python manage.py charger_demo

## Tests ------------------------------------------------------------------------------------------

test: test-back test-facade test-front

test-back:
	cd backend && $(BACK_PY) -m pytest --cov --cov-report=term --cov-report=xml

test-facade:
	cd facade && $(FACADE_PY) -m pytest

test-front:
	npm run test --workspaces --if-present

test-sauvegarde: ## EXP-01 : sauvegarde chiffrée puis restauration réelles, conteneurs jetables (Docker requis)
	cd backend && $(BACK_PY) -m pytest -o addopts="" -p no:cacheprovider --noconftest -m integration tests/test_sauvegarde_restauration.py

test-integration: ## Tests contre les conteneurs de test (annuaire, Mailpit, Gotenberg, ClamAV, DocuSeal, simulateurs)
	cd backend && $(BACK_PY) -m pytest -m integration

e2e: export PLAYWRIGHT_BROWSERS_PATH := $(CURDIR)/.playwright
e2e:
	npm run e2e --workspace e2e

a11y: export PLAYWRIGHT_BROWSERS_PATH := $(CURDIR)/.playwright
a11y:
	npm run a11y --workspace e2e

migrations-reversibles: ## Applique toutes les migrations, revient à zéro, puis réapplique (CLAUDE.md règle 7)
	cd backend && DJANGO_SETTINGS_MODULE=config.settings.test $(BACK_PY) manage.py verifier_migrations_reversibles

## Qualité ----------------------------------------------------------------------------------------

lint: lint-back lint-facade lint-front motifs

lint-back:
	cd backend && $(BACK_PY) -m ruff check . && $(BACK_PY) -m ruff format --check . && $(BACK_PY) -m mypy .
	cd backend && DJANGO_SETTINGS_MODULE=config.settings.test $(BACK_PY) manage.py makemigrations --check --dry-run

lint-facade:
	cd facade && $(FACADE_PY) -m ruff check . && $(FACADE_PY) -m ruff format --check . && $(FACADE_PY) -m mypy .

lint-front:
	npm run lint --workspaces --if-present
	npm run typecheck --workspaces --if-present

motifs: ## Échoue si TODO, FIXME, NotImplementedError, fonctions vides… dans le code livré
	$(PYTHON) scripts/verifier_motifs.py

matrice: ## Régénère docs/recette/matrice.csv et échoue si une exigence n'a pas son code et ses tests
	$(PYTHON) scripts/matrice.py --jusqua-lot 7

schema: ## Schémas OpenAPI et types TypeScript générés (jamais de DTO écrits à la main)
	cd backend && DJANGO_SETTINGS_MODULE=config.settings.test $(BACK_PY) manage.py exporter_schemas ../docs/api
	npm run schema --workspaces --if-present

trivy: ## Images et dépendances ; bloquant sur CVE critiques/hautes corrigeables
	$(PYTHON) scripts/analyse_trivy.py

sbom:
	$(PYTHON) scripts/analyse_trivy.py --sbom

recette: lint test migrations-reversibles motifs matrice trivy e2e a11y

format-changed:
	@git diff --name-only --diff-filter=AM HEAD 2>/dev/null | grep -E '^backend/.*\.py$$' | sed 's|^backend/||' | \
	  (cd backend && xargs -r $(BACK_PY) -m ruff format -q) || true
	@git diff --name-only --diff-filter=AM HEAD 2>/dev/null | grep -E '^facade/.*\.py$$' | sed 's|^facade/||' | \
	  (cd facade && xargs -r $(FACADE_PY) -m ruff format -q) || true
