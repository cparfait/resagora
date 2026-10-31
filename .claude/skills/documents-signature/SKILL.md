---
name: documents-signature
description: Génération de documents depuis des modèles (.docx avec champs de fusion, conversion PDF/A par Gotenberg) et circuit de signature électronique DocuSeal ou manuelle. À charger pour tout travail sur les modèles, les PDF, les conventions, attestations, plannings imprimés ou la signature.
---

# Documents et signature

## Modèles (DOC-01 à DOC-07)

- Modèles `.docx` éditables dans Word par l'administrateur fonctionnel, fusion avec `docxtpl` (syntaxe Jinja : `{{ usager.nom }}`, boucles `{% for o in occurrences %}`).
- Chaque modèle est **versionné** ; un document généré référence la version exacte utilisée.
- Variables exposées par un **contexte typé** (`documents/contexte.py`) : usager, contacts, espaces, créneaux, récurrence lisible (« tous les mardis de 18 h à 20 h, hors vacances scolaires »), tarifs, montants formatés en euros, caution, matériel, signataires, références de délibération. Ne jamais passer d'objet ORM brut au modèle.
- Conversion PDF via Gotenberg (LibreOffice) en **PDF/A-2b** pour l'archivage ; stockage avec empreinte SHA-256.
- Génération en lot (DOC-06) en tâche Celery, avec progression et rapport d'erreurs.
- Plannings imprimés (IMP-01 à 03) : gabarits HTML → PDF Gotenberg (Chromium), A4/A3, lisibles en noir et blanc, QR code vers la version en ligne, date d'édition.

## Circuit DocuSeal (SIG-01 à SIG-05)

1. Le document PDF est déposé par l'API métier dans DocuSeal (API `POST /api/submissions`, en-tête `X-Auth-Token`) avec les signataires **ordonnés** (usager puis élu/agent délégataire) et une date d'expiration.
2. Statut local `envoye` ; webhooks DocuSeal (`form.viewed`, `form.completed`, `submission.completed`, `submission.expired`…) reçus via la façade et relayés à l'API.
3. À réception d'un webhook : **revérifier** l'état par l'API DocuSeal (ne pas faire confiance au seul corps du webhook), mettre à jour le statut, notifier.
4. Une fois terminé : télécharger le PDF signé + journal de preuve, les rattacher au dossier, puis **purger** la soumission côté DocuSeal (la DMZ ne conserve pas les documents).
5. Relances automatiques avant expiration ; annulation possible par l'agent.

Points à valider en preuve de concept (lot 0) : périmètre exact de l'édition libre (API, webhooks, relances, ordre des signataires) face à l'offre Pro ; maintenir DocuSeal à sa dernière version (correctifs de sécurité fréquents).

## Circuit manuel (SIG-05)

Impression → signature papier → dépôt du scan par l'agent ou l'usager → statut `signe_manuellement`, avec agent et date. Même rattachement au dossier.

## Immuabilité (RG-13)

Un document signé n'est jamais régénéré ni modifié : toute modification = avenant (nouveau document lié).
