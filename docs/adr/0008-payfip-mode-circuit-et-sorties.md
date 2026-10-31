# ADR 0008 — PayFiP : mode, circuit comptable, sorties réseau et cycle d'une tentative

- Date : 2026-11-01
- Statut : accepté (mode et calendrier d'ouverture à arrêter avec le comptable public lors de l'adhésion à PayFiP)
- Exigences : TAR-07, POR-07, TAR-06, TAR-13, RG-13, SEC-01 ; revues sécurité et métier du lot 7

## Contexte

PayFiP (DGFiP) existe en deux variantes :

- **Titres et Rôles** : l'usager paie une dette prise en charge par le comptable public, sur un avis des sommes à payer.
- **Régie** : l'usager paie à la régie de recettes de la Ville avant toute prise en charge.

Le circuit documenté de la Ville (skill `finances-ciril`, TAR-06, TAR-12) est : facture, puis titre exporté vers CIVIL Finances Publiques, puis recouvrement par le comptable.

Les revues du lot 7 ont relevé six risques :

- **Double recouvrement en Régie** : une facture payée en ligne serait quand même exportée comme titre à recouvrer.
- **Paiement réel perdu** : une tentative close localement sans résultat de PayFiP ferait perdre un paiement effectué plus tard.
- **Notification inopérante** : la façade ne transmettait pas l'adresse signée de la notification.
- **Clé de signature** : le secret `payfip_secret` manquait à l'API du portail.
- **Sortie réseau non prévue** : l'API du portail, exposée à la DMZ, appelait elle-même PayFiP.
- **Saturation** : des appels SOAP synchrones étaient déclenchés depuis Internet.

## Décisions

1. **Mode.**
   - Par défaut, PayFiP **Titres et Rôles** (`PAYFIP_MODE=titres`) : seule une facture titrée se paie en ligne. La référence est le numéro de titre, l'exercice celui de la pièce.
   - La **Régie** (`regie`) se choisit par configuration, si l'acte constitutif de la régie le prévoit. Une facture se paie alors en ligne seulement avant sa transmission au comptable : pas de titre, pas de lot d'export actif. La référence est celle du virement, sans séparateur.
   - En Régie, une facture déjà encaissée en ligne part à l'export des titres avec `mode_encaissement=REGIE` et le montant encaissé. Le comptable émet un titre de régularisation et ne recouvre pas une seconde fois.
   - Le recouvrement contentieux (`en_recouvrement`) relève du comptable : pas de paiement en ligne.
2. **Sorties réseau.**
   - L'API du portail n'appelle jamais PayFiP : elle enregistre la tentative et vérifie la signature des notifications.
   - Les appels SOAP (création de l'opération, lecture du résultat) partent du **worker**, seul conteneur relié à `sortie_lan`, par le proxy de la Ville (`PAYFIP_PROXY`, liste blanche `www.payfip.gouv.fr`).
   - Le portail suit l'état de la tentative et redirige l'usager vers PayFiP dès que l'opération existe. Il vérifie que l'adresse est en HTTPS (ou le simulateur local en recette).
3. **Cycle d'une tentative.**
   - La tentative est créée avant toute redirection. Il y a une seule tentative « en cours » par facture. Celle du même contact est reprise pendant 20 minutes.
   - Une tentative d'un autre contact, ou plus ancienne, est **remplacée** mais reste relue. Si l'usager la paie quand même, le paiement est encaissé. Un second paiement sur la même facture devient un trop-perçu signalé.
   - Seul PayFiP clôt une tentative : payée (P, ou V par prélèvement), refusée (R) ou abandonnée (A).
   - Sans résultat après 24 h, la tentative est « expirée » mais reste relue 7 jours.
   - Un résultat incohérent (idOp, numcli, refdet, exercice, montant, saisie), un résultat inconnu, ou un paiement de test reçu hors recette passe « à contrôler ». Le service financier est prévenu et le paiement en ligne de la facture est suspendu jusqu'à la clôture motivée par un agent.
4. **Preuve et idempotence.**
   - Le retour du navigateur ne prouve rien : il demande une relecture, au plus toutes les 30 secondes.
   - La notification (adresses filtrées par la façade, `ref` UUID et `sig` HMAC transmis seuls) déclenche la même relecture par le worker.
   - Un seul encaissement par tentative : verrou, relation un-à-un et déclencheur d'immuabilité.
5. **Trop-perçus et état du comptable.**
   - Un paiement arrivé sur une facture déjà réglée est encaissé à hauteur du reste dû.
   - L'excédent est « à rembourser ». Il devient « à vérifier » si un règlement de même montant est déjà enregistré à 7 jours près, ce qui évite de rembourser à tort un paiement déjà importé de Ciril.
   - Le remboursement est tracé en ajout seul, qu'il soit fait par la régie ou par le comptable.
   - À l'import de l'état Ciril, une ligne qui correspond à un paiement PayFiP déjà enregistré compte comme « confirmée par le comptable », sans doublon.
6. **Rapprochement.** Chaque heure, le worker :
   - relit les tentatives en suspens ;
   - contrôle chaque paiement accepté (encaissement + trop-perçu = montant payé) ;
   - prévient le service financier de ce qui demande une action.

## Conséquences

- La recette se joue sur le simulateur (`simulateurs/payfip.py`), en mode Régie, saisie T, sans filtre d'adresse : réglage refusé hors recette (D-038).
- **`verifier_deploiement` refuse en production** :
  - une saisie T ;
  - un numéro de client vide ;
  - une clé de signature absente ;
  - des adresses PayFiP en HTTP ou vers le simulateur ;
  - une vérification TLS désactivée.
- **À vérifier dans le guide PayFiP en vigueur** (docs/a-brancher.md, section 12) :
  - valeurs de `resultrans` (V) ;
  - format de `refdet` et `objet` ;
  - montant minimal (paramètre `PAYFIP_MONTANT_MINIMUM_CENTIMES`, 1 € par défaut) ;
  - durée de validité d'un idOp ;
  - politique de nouvelle tentative des notifications.
