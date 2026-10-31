# Interface unique des tâches du projet (CI et postes de développement).
# Sous Windows sans GNU Make : docker compose -f deploy/dev/compose.yaml run --rm outils make <cible> (D-005).

SHELL := /bin/bash
PYTHON ?= python3
BACK := backend
VENV_PY := $(shell if [ -x $(BACK)/.venv/bin/python ]; then echo .venv/bin/python; elif [ -x $(BACK)/.venv/Scripts/python ]; then echo .venv/Scripts/python; else echo $(PYTHON); fi)
COMPOSE_DEV := docker compose -f deploy/dev/compose.yaml
COMPOSE_LAN := docker compose -f deploy/lan/compose.yaml
COMPOSE_DMZ := docker compose -f deploy/dmz/compose.yaml
export PYTHONIOENCODING := utf-8

.PHONY: up up-dmz down certs secrets demo test test-back test-front lint lint-back lint-front motifs matrice \
        e2e a11y trivy sbom schema format-changed migrations-reversibles recette

## Piles ------------------------------------------------------------------------------------------

up: certs secrets ## Pile LAN complète (API, back-office, mobile, services de développement)
	$(COMPOSE_DEV) up -d postgres-dev valkey-dev annuaire mailpit simulateurs
	$(COMPOSE_LAN) up -d --build

up-dmz: certs secrets ## Façade et portail DMZ (relais mTLS vers la pile LAN)
	$(COMPOSE_DMZ) up -d --build

down:
	-$(COMPOSE_DMZ) down
	-$(COMPOSE_LAN) down
	-$(COMPOSE_DEV) down

certs: ## Autorité de certification et certificats de développement (mTLS, LDAPS) — jamais en production
	$(PYTHON) scripts/certificats_dev.py

secrets: ## Secrets de développement générés aléatoirement dans deploy/*/secrets (ignorés par Git)
	$(PYTHON) scripts/secrets_dev.py

demo: ## Jeu de données de démonstration (anonyme)
	$(COMPOSE_LAN) exec api python manage.py charger_demo

## Tests ------------------------------------------------------------------------------------------

test: test-back test-front

test-back:
	cd $(BACK) && $(VENV_PY) -m pytest --cov --cov-report=term --cov-report=xml
	cd facade && $(VENV_PY_FACADE) -m pytest

test-front:
	npm run test --workspaces --if-present

e2e:
	npm run e2e --workspace e2e

a11y:
	npm run a11y --workspace e2e

migrations-reversibles: ## Applique toutes les migrations puis revient à zéro, puis réapplique
	cd $(BACK) && $(VENV_PY) scripts_migrations.py

## Qualité ----------------------------------------------------------------------------------------

lint: lint-back lint-front motifs

lint-back:
	cd $(BACK) && $(VENV_PY) -m ruff check . && $(VENV_PY) -m ruff format --check . && $(VENV_PY) -m mypy .
	cd $(BACK) && DJANGO_SETTINGS_MODULE=config.settings.test $(VENV_PY) manage.py makemigrations --check --dry-run
	cd facade && $(VENV_PY_FACADE) -m ruff check . && $(VENV_PY_FACADE) -m ruff format --check . && $(VENV_PY_FACADE) -m mypy .

lint-front:
	npm run lint --workspaces --if-present
	npm run typecheck --workspaces --if-present

motifs: ## Échoue si TODO, FIXME, NotImplementedError, fonctions vides… dans le code livré
	$(PYTHON) scripts/verifier_motifs.py

matrice: ## Régénère docs/recette/matrice.csv et échoue si une exigence n'a pas son code et ses tests
	$(PYTHON) scripts/matrice.py --jusqua-lot 7

schema: ## Schéma OpenAPI et types TypeScript générés (jamais de DTO écrits à la main)
	cd $(BACK) && DJANGO_SETTINGS_MODULE=config.settings.test $(VENV_PY) manage.py exporter_schemas ../docs/api
	npm run schema --workspaces --if-present

trivy: ## Analyse des images et des dépendances ; bloquant sur CVE critiques/hautes corrigeables
	$(PYTHON) scripts/analyse_trivy.py

sbom:
	$(PYTHON) scripts/analyse_trivy.py --sbom

recette: lint test e2e a11y motifs matrice trivy

format-changed:
	@git diff --name-only --diff-filter=AM HEAD 2>/dev/null | grep -E '^(backend|facade)/.*\.py$$' | \
	  while read f; do d=$${f%%/*}; (cd $$d && $(VENV_PY) -m ruff format -q "$${f#*/}"); done || true

VENV_PY_FACADE := $(shell if [ -x facade/.venv/bin/python ]; then echo .venv/bin/python; elif [ -x facade/.venv/Scripts/python ]; then echo .venv/Scripts/python; else echo $(PYTHON); fi)
