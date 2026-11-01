# Charte graphique — Ville de Châtillon (dérivée de la direction B « Larkfield Civic »)

Référence : identité du site public **ville-chatillon.fr** (relevée le 01/11/2026 dans ses variables CSS),
appliquée selon les principes de la direction B : surfaces plates, cartes blanches sur fond gris clair, un seul
bloc prioritaire par écran, accessibilité RGAA 4.1.2 / WCAG 2.2 AA.

Ce qui change par rapport à la direction B : le citron, le lavande et l'indigo sont remplacés par le **vert sapin**,
le **vert anis** et le **vert clair** de la Ville ; la police Inter Tight par **Montserrat** ; les pilules et grands
rayons par les **angles droits** du site de la Ville. Ce qui ne change pas : design plat, règles d'accessibilité,
un seul bloc prioritaire par écran, statuts toujours écrits.

## Couleurs (jetons)

Contrastes calculés (WCAG 2.x) pour chaque association autorisée.

| Nom | Valeur | Jeton | Rôle |
|---|---|---|---|
| Fond | `#F7F7F7` | `--fond` | Fond de page derrière les cartes |
| Carte | `#FFFFFF` | `--carte` | Toutes les surfaces de contenu |
| Encre | `#111311` | `--encre` | Texte courant (17,4:1 sur fond) |
| Encre douce | `#5A5A5A` | `--encre-douce` | Texte secondaire, aides de champ (6,9:1 sur carte, 6,4:1 sur fond) |
| Vert sapin | `#1A5D36` | `--vert` | Boutons principaux, navigation active, liens, titres H2 (7,9:1 sur carte) |
| Vert sapin foncé | `#154B2C` | `--vert-fonce` | Survol des boutons et liens (10,1:1) |
| Vert profond | `#124126` | `--vert-profond` | Anneau de focus, carte « information » foncée (11,6:1 sur carte) |
| Vert clair | `#BBCFC3` | `--vert-clair` | Pastilles d'icône, étiquettes, en-têtes de tableau (texte encre 11,4:1, vert 4,8:1) |
| Anis | `#ABBC00` | `--anis` | **Jamais en texte sur clair** (2,1:1). Filet décoratif sous les titres, fond de bouton avec texte encre (8,8:1) |
| Anis foncé | `#788300` | `--anis-fonce` | Filet ou trait épais uniquement (4,2:1 : insuffisant pour du texte courant) |
| Anis clair | `#EBEBB3` | `--anis-clair` | Fond du **bloc prioritaire** unique de l'écran (texte encre 15,2:1, vert 6,4:1) |
| Orange | `#FE872B` | `--orange` | Fond seulement, texte encre (7,8:1). Jamais en texte (2,4:1). Usage rare : mise en avant événementielle |
| Orange clair | `#FFE0C7` | `--orange-clair` | Fond de séance du planning (option, particulier), texte encre |
| Brun | `#5C300F` | `--brun` | Texte sur orange clair si besoin (11,1:1 sur carte) |
| Filet | `#E4E4DE` | `--filet` | Séparateurs et contours de cartes (décoratifs, 1,3:1) |
| Contour de champ | `#5A5A5A` | `--contour-champ` | Bordure des champs et cases (6,9:1, ≥ 3:1 exigé) |
| Succès | `#1E7A3E` sur `#E3F3E8` | `--succes` / `--succes-fond` | « Validée », « Payée » (4,7:1) |
| Attention | `#8A5300` sur `#FDF1D8` | `--attention` / `--attention-fond` | « En instruction », avertissements (5,7:1) |
| Information | `#1A5D36` sur `#E8EFE9` | `--info` / `--info-fond` | Messages d'information, survol de navigation, en-têtes de grille (6,7:1) |
| Erreur | `#C81C1E` sur `#FDE8E6` | `--danger` / `--danger-fond` | Erreurs, « Refusée » (4,9:1 ; 5,8:1 sur carte) — rouge du site de la Ville |

## Typographie

Police : **Montserrat** (licence SIL OFL), **hébergée par l'application** (fichiers woff2 servis par nos serveurs) :
la politique de sécurité (`font-src 'self'`) interdit Google Fonts, et un appel à Google depuis le portail
transmettrait l'adresse IP des usagers (RGPD). Repli : `Arial, Tahoma, sans-serif` (celui du site de la Ville).

| Style | Taille / interligne | Graisse | Jeton |
|---|---|---|---|
| H1 | 36 / 1.15 (clamp 28–36) | 700 | `--texte-h1` |
| H2 (titre de section, vert) | 26 / 1.25 | 800 | `--texte-h2` |
| H3 (titre de carte) | 20 / 1.3 | 700 | `--texte-h3` |
| Surtitre (catégorie) | 13 / 1.4, capitales, interlettrage 0.12em, vert | 600 | `--texte-surtitre` |
| Grand chiffre | 40 / 1.0 | 700 | `--texte-chiffre` |
| Corps | 17 / 1.55 | 400 | `--texte-corps` |
| Petit | 15 / 1.5 | 400–600 | `--texte-petit` |

Le corps de texte ne descend jamais sous 16 px, **sauf à l'intérieur de la grille du planning** (voir plus bas).

## Espacements et formes

- Échelle : 4, 8, 12, 16, 24, 32, 48, 72. Écart entre cartes : 16. Marge interne des cartes : 24 (16 sur mobile).
- **Angles droits** partout (cartes, boutons, champs, étiquettes), comme le site de la Ville. Seules exceptions :
  pastilles de statut et boutons-icônes ronds (rayon 999).
- Largeur de contenu : 1280 max (portail), pleine largeur pour le back-office. Marge de page 16.
- Grilles de cartes : `repeat(auto-fit, minmax(min(340px, 100%), 1fr))`.

## Composants

- **Barre d'en-tête** : bande blanche, logo de la Ville à gauche (fichier SVG officiel à fournir par le service
  communication ; à défaut, logotype texte « Ville de Châtillon » en Montserrat 700 vert), navigation au centre
  (élément actif souligné d'un filet anis 4 px + `aria-current`), à droite un bouton-icône recherche vert plein et un
  bouton secondaire « Mon espace » (contour vert, capitales), comme « Mon Châtillon » sur le site de la Ville.
- **Bouton principal** : fond vert sapin, texte blanc 600, hauteur 44 (48 sur mobile), marge 0 20, angles droits.
  Survol : vert sapin foncé. Un seul par zone.
- **Bouton secondaire** : fond blanc, contour 2 px vert, texte vert. **Bouton anis** : fond anis, texte encre,
  réservé aux cartes foncées et au bouton de menu.
- **Bouton-icône** : 44 × 44, toujours un `aria-label`.
- **Titre de section** : H2 vert suivi d'un **filet anis** de 40 × 4 px (signature du site de la Ville).
- **Bloc prioritaire** : un seul par écran (recherche de salle, montant à régler, demandes à instruire). Fond anis
  clair, filet anis de 6 px à gauche, marge interne 28.
- **Carte information** (foncée) : fond vert profond, texte blanc, libellés vert clair (7,1:1). Une ou deux par page au plus.
- **Carte de contenu** : fond blanc, contour filet, surtitre en capitales vertes, titre H3, filet anis sous le titre.
- **Pastille de statut** : fond teinté, texte foncé de même teinte, 14/600, rayon 999. Le statut est toujours écrit.
- **Onglets** : piste blanche, segment actif fond vert texte blanc, `role="tablist"` et flèches du clavier.
- **Champ** : libellé au-dessus (600), aide sous le libellé, champ de 48 px, contour 1 px `#5A5A5A`, angles droits.
  Erreur : contour 2 px rouge, icône et message au-dessus du champ, `aria-invalid` et `aria-describedby`.
- **Bandeau d'information** : fond attention, texte foncé, lien.
- **Pied de page** : bande vert profond, texte blanc, trois colonnes de liens (accessibilité, données personnelles,
  mentions légales).

## Back-office : ergonomie inspirée de Mariloo (décision DSI du 01/11/2026)

Le back-office reprend l'ergonomie et les formes de l'outil Mariloo, **aux couleurs de la Ville** (vert sapin, anis ;
ni le rose ni le dégradé de Mariloo, marque d'un produit tiers). Elles remplacent, pour le back-office seulement, les
angles droits et le « design plat » de la direction B ; le portail public garde sa présentation actuelle.

- **Surfaces** : fond `#F6F7F5`, cartes blanches arrondies (16 px, `rounded-lg`), grands blocs 24 px ; deux ombres
  douces seulement (`shadow-carte`, `shadow-flottant` pour les fenêtres et menus) ; toujours aucun dégradé.
- **Boutons et filtres en pilule** (`rounded-full`) : principal vert plein, secondaire blanc à contour fin, boutons
  d'action ronds (icône seule, avec `aria-label`).
- **Champs** arrondis (12 px) ; recherche en pilule avec loupe.
- **Menu** : élément actif sur fond vert pâle `#EEF4F0`, texte vert (7,1:1) ; pastilles de comptage.
- **Listes** : carte titrée avec compteur de résultats, vignette (photo ou pictogramme) devant chaque espace ou usager,
  filtres en pilules avec compteur (« Toutes / À traiter 2 / … »).
- **Tableau de bord** : cartes chiffres-clés avec pastille d'icône teintée, graphiques sobres (barres triées d'une seule
  teinte, barre empilée à 100 %) et leur tableau de données en alternative. Les séries des graphiques ont leur propre
  palette validée (`--color-serie-1` à `7`, ordre fixe, réservée aux marques de données) : les couleurs de la charte
  échouent aux contrôles de daltonisme en palette catégorielle.
- **Planning par espace** : une ligne par espace (vignette, capacité), séances en cartes arrondies avec filet de
  couleur, pastilles de statut et initiales de l'usager.
- **Fiche réservation** : retour, numéro, statut en pastille ; actions principales en gros boutons ; échanges façon
  messagerie ; sections repliables.

## Planning du back-office : sans défilement

Exigence de la DSI : **la vue semaine du planning tient dans la fenêtre sans défilement vertical** (écran
1280 × 720 et plus).

- La hauteur d'une heure se calcule à partir de la hauteur disponible (`calc((100dvh - en-tête) / nombre d'heures)`),
  et non plus d'une valeur fixe de 48 px ; la plage horaire suit les séances affichées (8 h – 22 h par défaut).
- À l'intérieur de la grille seulement : texte 13–14 px, séances sans marge interne superflue. Les cibles restent
  cliquables en entier et la liste accessible (vue « Liste ») reste disponible pour le clavier et les lecteurs d'écran.
- Les couleurs des séances (statuts, types d'usagers) utilisent les teintes de la charte avec un motif ou un libellé :
  la couleur n'est jamais seule porteuse d'information.

## À faire / à éviter

**À faire** : un seul bloc prioritaire par écran ; statuts écrits en toutes lettres ; libellé visible sur chaque
contrôle ; éléments natifs (`<a>`, `<button>`, `<input>`, `<label>`) ; focus visible 3 px vert profond, décalage 3 ;
tableau en alternative de chaque graphique ; `prefers-reduced-motion` respecté (transitions ≤ 200 ms).

**À éviter** : ombres, dégradés, effets de verre, halos, parallaxe, particules, 3D ; anis ou orange en texte ; menus
au seul survol ; carrousels pour un contenu essentiel ; animation automatique ; émojis en guise d'icônes ; navigation
par icônes sans libellé.

## Images et icônes

Icônes au trait 1,6–1,8 sur une grille de 24 (type Lucide). Photographies facultatives, toujours avec une
alternative textuelle.

## Accessibilité

WCAG 2.2 AA / RGAA 4.1.2. Lien d'évitement, régions (`header`, `nav[aria-label]`, `main`, `footer`), cibles de
44 × 44 au moins (sauf dans la grille du planning, qui offre la vue Liste en alternative), affichage correct à 320 px
et au zoom 400 %.

## Écarts avec la direction B, à valider

- Pas de sélecteur de langue, de fil d'Ariane généralisé ni de « Cette page vous a-t-elle été utile ? » : ces
  fonctions n'existent pas dans l'application et ne seront pas inventées (règle 2 du prompt de refonte).
- Pas d'Aceternity UI ni de 21st.dev : animations et dépendances supplémentaires sans apport pour une application
  interne ; à revoir si besoin.

## Démarrage rapide (variables CSS)

```css
:root {
  --fond: #F7F7F7;
  --carte: #FFFFFF;
  --encre: #111311;
  --encre-douce: #5A5A5A;
  --vert: #1A5D36;
  --vert-fonce: #154B2C;
  --vert-profond: #124126;
  --vert-clair: #BBCFC3;
  --anis: #ABBC00;
  --anis-fonce: #788300;
  --anis-clair: #EBEBB3;
  --orange: #FE872B;
  --brun: #5C300F;
  --filet: #E4E4DE;
  --contour-champ: #5A5A5A;
  --succes: #1E7A3E;
  --succes-fond: #E3F3E8;
  --attention: #8A5300;
  --attention-fond: #FDF1D8;
  --danger: #C81C1E;
  --danger-fond: #FDE8E6;
  --lien: var(--vert);
  --anneau: var(--vert-profond);
  --police: "Montserrat", Arial, Tahoma, sans-serif;
}

:focus-visible { outline: 3px solid var(--anneau); outline-offset: 3px; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; scroll-behavior: auto !important; }
}
```
