# ADR 0007 — Règles de calcul et de restitution de la valorisation des avantages en nature

- Date : 2026-10-31
- Statut : accepté (à confirmer par la direction des finances et le service juridique avant la première clôture)
- Exigences : VAL-01 à VAL-08, RG-04, RG-05, RG-12, RG-13 ; revues sécurité et métier du lot 6

## Contexte

Le cahier des charges étant absent (D-001), le skill `valorisation-subventions` et la réglementation fixent le cadre :

- loi 2000-321, article 10 ;
- CGCT L. 2313-1 ;
- CGPPP L. 2125-1 ;
- règlement ANC 2018-06.

Les revues du lot 6 ont relevé cinq points où la règle n'était pas écrite et où le code faisait un choix implicite.

## Décisions

1. **Montant valorisé d'une séance** = (valeur de référence − montant payé) × part d'occupation.
   - **Valeur de référence** : prix du devis accepté (RG-04), sinon tarif voté en vigueur (RG-05) ; ou bien, selon la méthode de la famille, coût de revient ou valeur locative.
   - **Montant payé** : ce qui est facturé pour la séance (occupation et majorations), chaque ligne étant diminuée de ses avoirs, plus les frais d'annulation tardive. Une séance pas encore facturée compte son dû calculé ; une séance annulée hors délai ne compte que ses frais.
   - **Espace partagé** : chaque usager est facturé du créneau entier (tarification) ; seule sa part de l'écart est valorisée. Exemple : une gratuité partagée par deux clubs vaut 50 % du créneau pour chacun ; à 50 % de réduction, chacun reçoit 25 % du créneau.
2. **Paramètres de calcul figés par exercice.** À la création d'un exercice, le coût horaire chargé du personnel dédié et la prise en compte des absences non signalées sont repris des paramètres généraux. Ils restent modifiables tant que l'exercice est ouvert, puis sont figés à la clôture : un recalcul tracé d'un exercice clos réutilise ses propres valeurs. La méthode d'une famille est fixée par exercice (VAL-01).
3. **Bénéficiaires.**
   - **Ne sont ni valorisés ni nommés** : les services municipaux (la Ville elle-même) et les particuliers (pas de concours à une personne physique, aucun nom dans une annexe publique).
   - **Écoles** : valorisées pour les statistiques, sans attestation, et absentes de l'annexe du compte administratif.
   - **Annexe** : associations, entreprises et autres collectivités ayant reçu un concours non nul.
4. **Seuils.**
   - **23 000 €** (nature + numéraire) : convention d'objectifs obligatoire (loi 2000-321, art. 10).
   - **153 000 €** : seuil repris du skill pour le compte rendu financier renforcé. Selon la revue métier, ce seuil relève plutôt de l'obligation de publier les comptes (C. com. L. 612-4, décret 2009-540), le compte rendu financier valant pour toute subvention affectée.
   - Les deux seuils sont des paramètres ; leur libellé et leur fondement sont à confirmer par le service juridique (docs/a-brancher.md).
5. **Attestation.**
   - Elle ne s'édite qu'une fois l'exercice clôturé : les montants sont alors définitifs. La clôture recalcule chaque bénéficiaire sur l'état final des séances et des pièces.
   - Elle cite l'article L. 2125-1 du CGPPP et est **signée par l'élu délégataire** par le circuit de signature existant (DocuSeal ou signature manuscrite constatée). Elle n'est déposée sur le portail qu'une fois signée, et l'association en est alors avertie.
   - Un recalcul tracé après clôture réédite l'attestation déjà déposée et la renvoie en signature.

## Conséquences

- La valorisation est un objet de la Ville entière : la calculer, la clôturer, importer le numéraire ou changer une méthode exige un périmètre « tous sites » (RG-14). Un agent d'un site ne lit que les lignes de ses sites.
- **Contrôles en base** :
  - un exercice clos ne rouvre pas et ne change ni d'année ni de paramètres ;
  - ses méthodes et ses subventions sont figées ;
  - les versions de valorisation figées sont immuables ;
  - aucune de ces tables ne se vide.
- Le jeu de démonstration, dont l'exercice est en cours, n'a pas d'attestation déposée. Le parcours complet (clôture, signature, dépôt) est couvert par les tests de l'API.
