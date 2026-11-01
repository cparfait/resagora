"""Analyse Trivy des images et des dépendances (bloquant sur CVE critiques/hautes corrigeables) et SBOM.

Usage : python scripts/analyse_trivy.py [--sbom] [--version dev]
Rapports : docs/securite/trivy-<cible>.txt ; SBOM CycloneDX : docs/securite/sbom/<cible>.cdx.json
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "docs" / "securite"
IMAGE_TRIVY = "aquasec/trivy:0.76.1@sha256:790fd66d1697395d8693d1acaa1ea702406a20f109b6fc7bac8db623eca6c06c"
IMAGES = ["api", "facade", "backoffice", "portail", "mobile"]
SOCKET = "//var/run/docker.sock" if os.name == "nt" else "/var/run/docker.sock"


def trivy(arguments: list[str], monter_depot: bool = False) -> subprocess.CompletedProcess[str]:
    commande = ["docker", "run", "--rm", "-v", f"{SOCKET}:/var/run/docker.sock", "-v", "equipements-trivy-cache:/root/.cache/"]
    if monter_depot:
        commande += ["-v", f"{RACINE}:/depot:ro"]
    commande += [IMAGE_TRIVY, *arguments]
    environnement = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    return subprocess.run(commande, capture_output=True, text=True, encoding="utf-8", errors="replace", env=environnement, check=False)


def main() -> int:
    parseur = argparse.ArgumentParser()
    parseur.add_argument("--sbom", action="store_true")
    parseur.add_argument("--version", default=os.environ.get("VERSION", "dev"))
    parseur.add_argument("--registre", default=os.environ.get("REGISTRE", "equipements"))
    args = parseur.parse_args()
    SORTIE.mkdir(parents=True, exist_ok=True)
    (SORTIE / "sbom").mkdir(exist_ok=True)
    echecs: list[str] = []
    cibles = [(nom, ["image", f"{args.registre}/{nom}:{args.version}"], False) for nom in IMAGES]
    cibles.append(("depot", ["fs", "--scanners", "vuln,secret,misconfig", "/depot"], True))
    for nom, cible, depot in cibles:
        options = [
            "--severity", "HIGH,CRITICAL", "--ignore-unfixed", "--exit-code", "1", "--no-progress", "--format", "table",
            "--timeout", "30m",
        ]
        if depot:
            options += ["--skip-dirs", "/depot/node_modules,/depot/backend/.venv,/depot/facade/.venv,/depot/.playwright,/depot/outils/codegen/node_modules",
                        "--skip-dirs", "/depot/deploy/lan/secrets,/depot/deploy/dmz/secrets,/depot/deploy/dev/secrets",
                        "--skip-dirs", "/depot/.git,/depot/e2e/test-results,/depot/e2e/playwright-report,/depot/e2e/.etat,"
                        "/depot/docs/securite,/depot/backend/stockage,/depot/backoffice/dist,/depot/portail/dist,/depot/mobile/dist"]
        resultat = trivy([*cible[:1], *options, *cible[1:]], depot)
        rapport = (resultat.stdout or "") + (resultat.stderr or "")
        (SORTIE / f"trivy-{nom}.txt").write_text(rapport, encoding="utf-8")
        statut = "conforme" if resultat.returncode == 0 else "VULNÉRABILITÉS" if resultat.returncode == 1 else "ERREUR"
        print(f"{nom:12} {statut}")
        if resultat.returncode != 0:
            echecs.append(nom)
        if args.sbom and not depot:
            sbom = trivy(["image", "--format", "cyclonedx", "--no-progress", cible[1]])
            (SORTIE / "sbom" / f"{nom}.cdx.json").write_text(sbom.stdout, encoding="utf-8")
    if echecs:
        print("Échec de l'analyse pour : " + ", ".join(echecs) + " (voir docs/securite/trivy-*.txt)")
        return 1
    print("Aucune vulnérabilité critique ou haute corrigeable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
