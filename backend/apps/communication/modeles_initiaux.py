"""Modèles de messages fournis à l'installation (modifiables ensuite dans « Modèles de messages », ADM-04)."""

SIGNATURE = "\n\nService des équipements sportifs et associatifs\nVille de Châtillon\n{{ portail_url }}"

MODELES: dict[str, tuple[str, str, str]] = {
    "demande_recue": (
        "Accusé de réception d'une demande",
        "Votre demande {{ dossier.numero }} a bien été reçue",
        "Bonjour {{ contact.prenom }},\n\nNous avons bien reçu votre demande « {{ dossier.objet }} » (dossier {{ dossier.numero }}). "
        "Elle sera instruite dans les meilleurs délais ; vous pouvez suivre son avancement sur le portail." + SIGNATURE,
    ),
    "reservation_validee": (
        "Réservation validée",
        "Votre réservation {{ dossier.numero }} est validée",
        "Bonjour {{ contact.prenom }},\n\nVotre demande « {{ dossier.objet }} » est validée pour {{ reservation.espace.nom }} : "
        "{{ reservation.description }}.\n{% if conditions %}Pour la confirmer, il reste à : {{ conditions }}.{% endif %}"
        + SIGNATURE,
    ),
    "reservation_confirmee": (
        "Réservation confirmée",
        "Votre réservation {{ dossier.numero }} est confirmée",
        "Bonjour {{ contact.prenom }},\n\nVotre réservation de {{ reservation.espace.nom }} ({{ reservation.description }}) est confirmée."
        + SIGNATURE,
    ),
    "reservation_refusee": (
        "Demande refusée",
        "Votre demande {{ dossier.numero }} n'a pas pu être acceptée",
        "Bonjour {{ contact.prenom }},\n\nNous ne pouvons pas donner suite à votre demande « {{ dossier.objet }} ».\nMotif : {{ motif }}"
        "{% if alternatives %}\n\nCréneaux proposés : {{ alternatives }}{% endif %}" + SIGNATURE,
    ),
    "option_relance": (
        "Relance avant expiration d'une option",
        "Votre option {{ dossier.numero }} expire le {{ expire_le }}",
        "Bonjour {{ contact.prenom }},\n\nL'option posée pour {{ reservation.espace.nom }} ({{ reservation.description }}) expire le "
        "{{ expire_le }}. Sans réponse de votre part, le créneau sera libéré." + SIGNATURE,
    ),
    "option_expiree": (
        "Option expirée",
        "Votre option {{ dossier.numero }} a expiré",
        "Bonjour {{ contact.prenom }},\n\nL'option posée pour {{ reservation.espace.nom }} ({{ reservation.description }}) a expiré "
        "et le créneau a été libéré." + SIGNATURE,
    ),
    "occurrence_annulee": (
        "Annulation d'une séance",
        "Annulation : {{ espace }} le {{ date }}",
        "Bonjour {{ contact.prenom }},\n\nLa séance du {{ date }} ({{ espace }}) est annulée.\nMotif : {{ motif }}"
        "{% if frais %}\nFrais d'annulation : {{ frais }}{% endif %}" + SIGNATURE,
    ),
    "fermeture_exceptionnelle": (
        "Fermeture exceptionnelle",
        "Fermeture de {{ lieu }} du {{ debut }} au {{ fin }}",
        "Bonjour {{ contact.prenom }},\n\n{{ lieu }} sera fermé du {{ debut }} au {{ fin }} ({{ motif }}). Vos créneaux concernés :\n"
        "{{ seances }}\nLe service des équipements vous contactera pour vous proposer une solution." + SIGNATURE,
    ),
    "priorite_municipale": (
        "Déplacement pour une manifestation municipale",
        "Modification de votre créneau du {{ date }}",
        "Bonjour {{ contact.prenom }},\n\nPour permettre « {{ manifestation }} », votre créneau du {{ date }} ({{ espace }}) "
        "{% if nouveau %}est déplacé : {{ nouveau }}.{% else %}est annulé, sans frais.{% endif %}\nMotif : {{ motif }}"
        + SIGNATURE,
    ),
    "liste_attente_place": (
        "Créneau libéré (liste d'attente)",
        "Un créneau s'est libéré : {{ espace }} le {{ date }}",
        "Bonjour {{ contact.prenom }},\n\nLe créneau {{ espace }} du {{ date }} s'est libéré. Vous étiez inscrit(e) en liste d'attente : "
        "répondez rapidement pour le réserver." + SIGNATURE,
    ),
    "campagne_attribution": (
        "Attribution des créneaux annuels",
        "Créneaux {{ saison }} : décision de la commission",
        "Bonjour {{ contact.prenom }},\n\nLa commission d'attribution des créneaux {{ saison }} a rendu sa décision.\n"
        "Créneaux attribués :\n{{ attribues }}{% if refuses %}\n\nDemandes non retenues :\n{{ refuses }}{% endif %}" + SIGNATURE,
    ),
    "piece_expiree": (
        "Pièce justificative bientôt expirée",
        "Pièce à renouveler : {{ piece }}",
        "Bonjour {{ contact.prenom }},\n\nLa pièce « {{ piece }} » de {{ usager.nom }} expire le {{ fin }}. "
        "Merci de déposer la nouvelle version sur le portail." + SIGNATURE,
    ),
}


# Lot 2 — portail, messagerie, documents et signature : (libellé, sujet, corps, texte SMS éventuel).
MODELES_LOT2: dict[str, tuple[str, str, str, str]] = {
    "compte_confirmation": (
        "Confirmation de l'adresse électronique",
        "Confirmez votre adresse pour le portail des équipements",
        "Bonjour {{ contact.prenom }},\n\nPour confirmer votre adresse et finaliser votre demande de compte, ouvrez ce lien :\n"
        "{{ lien }}\n\nCe lien est personnel et utilisable une seule fois. Si vous n'êtes pas à l'origine de cette demande, "
        "ignorez ce message." + SIGNATURE,
        "",
    ),
    "compte_deja_existant": (
        "Tentative d'inscription avec une adresse déjà utilisée",
        "Votre compte sur le portail des équipements",
        "Bonjour {{ contact.prenom }},\n\nUne demande de création de compte vient d'être faite avec votre adresse, qui a déjà "
        "un compte. Si vous avez oublié votre mot de passe, utilisez « Mot de passe oublié » : {{ lien }}\n\n"
        "Si vous n'êtes pas à l'origine de cette demande, aucune action n'est nécessaire." + SIGNATURE,
        "",
    ),
    "compte_a_valider": (
        "Nouveau compte à valider (service)",
        "Nouveau compte du portail à valider : {{ usagers }}",
        "Un compte du portail attend votre validation.\n\nContact : {{ compte.contact }}\nStructure : {{ usagers }}\n\n"
        "Valider ou refuser : {{ lien }}",
        "",
    ),
    "compte_valide": (
        "Compte validé",
        "Votre compte sur le portail des équipements est ouvert",
        "Bonjour {{ contact.prenom }},\n\nVotre compte est validé par la Ville. Vous pouvez désormais déposer vos demandes "
        "de réservation et suivre vos dossiers : {{ lien }}" + SIGNATURE,
        "",
    ),
    "compte_refuse": (
        "Compte refusé",
        "Votre demande de compte sur le portail des équipements",
        "Bonjour {{ contact.prenom }},\n\nNous ne pouvons pas donner suite à votre demande de compte.\nMotif : {{ motif }}\n\n"
        "Pour toute question, répondez à ce message." + SIGNATURE,
        "",
    ),
    "contact_invitation": (
        "Invitation d'un contact",
        "Vous êtes invité sur le portail des équipements de la Ville",
        "Bonjour {{ contact.prenom }},\n\n{{ invite_par }} vous a ajouté comme contact sur le portail des équipements de la "
        "Ville de Châtillon. Pour choisir votre mot de passe, ouvrez ce lien (valable 7 jours) :\n{{ lien }}" + SIGNATURE,
        "",
    ),
    "mot_de_passe_reinitialisation": (
        "Réinitialisation du mot de passe",
        "Réinitialisation de votre mot de passe",
        "Bonjour {{ contact.prenom }},\n\nPour choisir un nouveau mot de passe, ouvrez ce lien (valable {{ minutes }} minutes, "
        "une seule fois) :\n{{ lien }}\n\nSi vous n'avez rien demandé, ignorez ce message : votre mot de passe reste inchangé."
        + SIGNATURE,
        "",
    ),
    "mot_de_passe_modifie": (
        "Mot de passe modifié",
        "Votre mot de passe a été modifié",
        "Bonjour {{ contact.prenom }},\n\nLe mot de passe de votre compte vient d'être modifié. Si vous n'êtes pas à l'origine "
        "de cette modification, contactez immédiatement le service des équipements." + SIGNATURE,
        "",
    ),
    "totp_desactive": (
        "Double authentification désactivée",
        "La double authentification de votre compte est désactivée",
        "Bonjour {{ contact.prenom }},\n\nLa double authentification de votre compte vient d'être désactivée. Si vous n'êtes "
        "pas à l'origine de cette action, contactez immédiatement le service des équipements." + SIGNATURE,
        "",
    ),
    "message_ville": (
        "Nouveau message de la Ville sur un dossier",
        "Nouveau message sur votre dossier {{ dossier.numero }}",
        "Bonjour {{ contact.prenom }},\n\nLe service des équipements vous a écrit au sujet de votre dossier "
        "{{ dossier.numero }} (« {{ dossier.objet }} »). Lisez et répondez sur le portail : {{ portail_url }}/dossiers/"
        "{{ dossier.pk }}" + SIGNATURE,
        "",
    ),
    "message_usager": (
        "Nouveau message d'un usager (service)",
        "Message de {{ usager.nom }} — dossier {{ dossier.numero }}",
        "{{ auteur }} a écrit au sujet du dossier {{ dossier.numero }} (« {{ dossier.objet }} ») :\n\n{{ extrait }}\n\n"
        "Répondre : {{ lien }}",
        "",
    ),
    "document_disponible": (
        "Document disponible",
        "Un document est disponible pour votre dossier {{ dossier.numero }}",
        "Bonjour {{ contact.prenom }},\n\nLe document « {{ document.titre }} » est disponible dans votre dossier "
        "{{ dossier.numero }} sur le portail : {{ portail_url }}/dossiers/{{ dossier.pk }}" + SIGNATURE,
        "",
    ),
    "signature_demandee": (
        "Signature demandée",
        "Document à signer : {{ document.titre }}",
        "Bonjour {{ contact.prenom }},\n\nLe document « {{ document.titre }} » (dossier {{ dossier.numero }}) attend votre "
        "signature avant le {{ expire_le }}. Signez-le depuis le portail : {{ portail_url }}/dossiers/{{ dossier.pk }}"
        + SIGNATURE,
        "Ville de Châtillon : le document {{ document.titre }} attend votre signature avant le {{ expire_le }}.",
    ),
    "signature_relance": (
        "Relance de signature",
        "Rappel : document à signer avant le {{ expire_le }}",
        "Bonjour {{ contact.prenom }},\n\nLe document « {{ document.titre }} » (dossier {{ dossier.numero }}) n'est pas encore "
        "signé. Il expire le {{ expire_le }}. Signez-le depuis le portail : {{ portail_url }}/dossiers/{{ dossier.pk }}"
        + SIGNATURE,
        "Rappel Ville de Châtillon : signez {{ document.titre }} avant le {{ expire_le }}.",
    ),
    "signature_terminee": (
        "Document signé",
        "Le document {{ document.titre }} est signé",
        "Bonjour {{ contact.prenom }},\n\nLe document « {{ document.titre }} » est signé par toutes les parties. L'exemplaire "
        "signé est disponible dans votre dossier : {{ portail_url }}/dossiers/{{ dossier.pk }}" + SIGNATURE,
        "",
    ),
    "signature_expiree": (
        "Signature expirée",
        "Le délai de signature de {{ document.titre }} est dépassé",
        "Bonjour {{ contact.prenom }},\n\nLe délai de signature du document « {{ document.titre }} » est dépassé. Le service "
        "des équipements va vous recontacter." + SIGNATURE,
        "",
    ),
    "rappel_seance": (
        "Rappel de séance la veille",
        "Rappel : {{ espace }} demain à {{ heure }}",
        "Bonjour {{ contact.prenom }},\n\nNous vous rappelons votre réservation de {{ espace }} demain {{ jour }} à {{ heure }}."
        + SIGNATURE,
        "Rappel Ville de Châtillon : {{ espace }} demain à {{ heure }}.",
    ),
    "seance_deplacee": (
        "Séance déplacée",
        "Modification de votre séance du {{ date }}",
        "Bonjour {{ contact.prenom }},\n\nVotre séance du {{ date }} ({{ espace }}) est déplacée : {{ nouveau }}.\n"
        "En cas de difficulté, répondez à ce message." + SIGNATURE,
        "Ville de Châtillon : séance du {{ date }} déplacée : {{ nouveau }}.",
    ),
    "information_generale": (
        "Information aux usagers (envoi groupé)",
        "{{ titre }}",
        "Bonjour {{ contact.prenom }},\n\n{{ texte }}" + SIGNATURE,
        "Ville de Châtillon : {{ titre }}. Détails par courriel.",
    ),
    "usager_anonymise": (
        "Données personnelles effacées",
        "Effacement de vos données personnelles",
        "Bonjour,\n\nConformément à la durée de conservation annoncée, les données personnelles liées à votre compte ont été "
        "effacées. Les pièces comptables restent conservées par la Ville selon les règles de la comptabilité publique."
        + SIGNATURE,
        "",
    ),
}


# Lot 3 — finances et cautions : (libellé, sujet, corps, texte SMS éventuel).
MODELES_LOT3: dict[str, tuple[str, str, str, str]] = {
    "facture_emise": (
        "Facture émise",
        "Facture {{ piece.numero }} — {{ dossier.numero }}",
        "Bonjour {{ contact.prenom }},\n\nLa facture {{ piece.numero }} relative à votre dossier {{ dossier.numero }} est "
        "disponible sur le portail. Montant à régler : {{ montant }}, avant le {{ piece.echeance }}.\nUn titre de recettes "
        "vous sera adressé par le comptable public ; réglez par virement en indiquant la référence {{ piece.reference_virement }}."
        + SIGNATURE,
        "",
    ),
    "devis_emis": (
        "Devis disponible",
        "Votre devis {{ piece.numero }} est disponible",
        "Bonjour {{ contact.prenom }},\n\nLe devis {{ piece.numero }} pour votre dossier {{ dossier.numero }} est disponible "
        "sur le portail ({{ montant }}). Il est valable jusqu'au {{ piece.validite }} ; vous pouvez l'accepter en ligne."
        + SIGNATURE,
        "",
    ),
    "caution_restituee": (
        "Caution restituée",
        "Restitution de votre caution — {{ dossier.numero }}",
        "Bonjour {{ contact.prenom }},\n\nL'état des lieux de sortie est conforme : votre caution de {{ montant }} vous est "
        "restituée." + SIGNATURE,
        "",
    ),
    "caution_retenue": (
        "Retenue sur caution",
        "Retenue sur votre caution — {{ dossier.numero }}",
        "Bonjour {{ contact.prenom }},\n\nÀ la suite de l'état des lieux de sortie, une retenue de {{ montant_retenu }} est "
        "appliquée sur votre caution (montant restitué : {{ montant_restitue }}).\nMotif : {{ motif }}\n\nLes photos du constat "
        "sont à votre disposition auprès du service. Vous pouvez contester cette retenue en répondant à ce message." + SIGNATURE,
        "",
    ),
}


# Corrections du lot 2 (revues) : invitation de chaque signataire, signature manuscrite contrôlée, annulations,
# invitations sans énumération, double authentification, vérification du numéro de SMS.
MODELES_SIGNATURE_ET_COMPTES: dict[str, tuple[str, str, str, str]] = {
    "signature_demandee_externe": (
        "Signature demandée (élu ou agent)",
        "Document à signer : {{ document.titre }}",
        "Bonjour,\n\nLe document « {{ document.titre }} » (dossier {{ dossier.numero }}) attend votre signature avant le "
        "{{ expire_le }}. Les signataires précédents ont signé.\n\nSigner : {{ lien }}\n\nCe lien vous est personnel."
        + SIGNATURE,
        "",
    ),
    "signature_relance_externe": (
        "Relance de signature (élu ou agent)",
        "Rappel : document à signer avant le {{ expire_le }}",
        "Bonjour,\n\nLe document « {{ document.titre }} » (dossier {{ dossier.numero }}) attend toujours votre signature. "
        "Il expire le {{ expire_le }}.\n\nSigner : {{ lien }}" + SIGNATURE,
        "",
    ),
    "signature_refusee": (
        "Signature refusée",
        "Le document {{ document.titre }} n'a pas été signé",
        "Bonjour {{ contact.prenom }},\n\nLa signature du document « {{ document.titre }} » a été refusée"
        "{% if refuse_par %} ({{ refuse_par }}){% endif %}. Le service des équipements va vous recontacter." + SIGNATURE,
        "",
    ),
    "signature_manuelle_demandee": (
        "Signature manuscrite demandée",
        "Document à signer et à renvoyer : {{ document.titre }}",
        "Bonjour {{ contact.prenom }},\n\nLe document « {{ document.titre }} » (dossier {{ dossier.numero }}) est à imprimer, "
        "signer et déposer en PDF sur le portail avant le {{ expire_le }} : {{ portail_url }}/dossiers/{{ dossier.pk }}\n"
        "Le service vérifiera le document avant de le contresigner." + SIGNATURE,
        "",
    ),
    "scan_a_controler": (
        "Scan signé à contrôler (service)",
        "Scan signé déposé : {{ document.titre }}",
        "{{ depose_par }} a déposé l'exemplaire signé du document « {{ document.titre }} » (dossier {{ dossier.numero }}).\n"
        "Vérifiez qu'il est complet et signé avant de le constater : {{ lien }}",
        "",
    ),
    "scan_refuse": (
        "Scan signé refusé",
        "Votre document signé {{ document.titre }} n'a pas pu être accepté",
        "Bonjour {{ contact.prenom }},\n\nLe document signé que vous avez déposé (« {{ document.titre }} ») n'a pas pu être "
        "accepté.\nMotif : {{ motif }}\n\nMerci de déposer un nouvel exemplaire sur le portail : {{ portail_url }}/dossiers/"
        "{{ dossier.pk }}" + SIGNATURE,
        "",
    ),
    "annulation_usager": (
        "Annulation par un usager (service)",
        "Annulation par {{ usager.nom }} — dossier {{ dossier.numero }}",
        "{{ auteur }} a annulé depuis le portail :\n{{ seances }}\n{% if tardives %}\nAnnulation tardive (moins de "
        "{{ delai }} heures avant) pour : {{ tardives }}{% endif %}\n\nDossier : {{ lien }}",
        "",
    ),
    "contact_deja_inscrit": (
        "Ajout comme contact d'une structure (compte existant)",
        "Vous avez été ajouté comme contact de {{ structure }}",
        "Bonjour {{ contact.prenom }},\n\n{{ invite_par }} vous a ajouté comme contact de « {{ structure }} » sur le portail "
        "des équipements. Votre compte existant n'est pas modifié. Pour représenter cette structure depuis votre compte, "
        "demandez au service des équipements de rattacher votre compte à la structure.\n\nSi vous ne connaissez pas cette "
        "structure, ignorez ce message." + SIGNATURE,
        "",
    ),
    "totp_active": (
        "Double authentification activée",
        "La double authentification de votre compte est activée",
        "Bonjour {{ contact.prenom }},\n\nLa double authentification de votre compte vient d'être activée. Si vous n'êtes pas "
        "à l'origine de cette action, contactez immédiatement le service des équipements." + SIGNATURE,
        "",
    ),
    "telephone_sms_code": (
        "Vérification du numéro de SMS",
        "Code de vérification",
        "Code de vérification : {{ code }}",
        "Ville de Châtillon : votre code de vérification est {{ code }} (valable 15 minutes).",
    ),
    "courriel_changement_confirmation": (
        "Confirmation d'une nouvelle adresse",
        "Confirmez votre nouvelle adresse pour le portail des équipements",
        "Bonjour {{ contact.prenom }},\n\nPour utiliser désormais cette adresse ({{ nouvelle }}) sur le portail des "
        "équipements, ouvrez ce lien (valable 24 heures, une seule fois) :\n{{ lien }}\n\nSi vous n'êtes pas à l'origine de "
        "cette demande, ignorez ce message." + SIGNATURE,
        "",
    ),
    "courriel_contact_modifie": (
        "Adresse d'un contact modifiée",
        "L'adresse de votre compte sur le portail a été modifiée",
        "Bonjour {{ contact.prenom }},\n\nL'adresse électronique associée à votre compte vient d'être remplacée par "
        "{{ nouvelle }}. Si vous n'êtes pas à l'origine de cette demande, contactez immédiatement le service des "
        "équipements." + SIGNATURE,
        "",
    ),
}

# COM-05 : textes SMS des messages de service courts (fermetures, annulations).
SMS_COMPLEMENTS: dict[str, str] = {
    "fermeture_exceptionnelle": "Ville de Châtillon : {{ lieu }} fermé du {{ debut }} au {{ fin }}. Détails par courriel.",
    "occurrence_annulee": "Ville de Châtillon : séance du {{ date }} ({{ espace }}) annulée. Détails par courriel.",
    "priorite_municipale": "Ville de Châtillon : votre créneau du {{ date }} ({{ espace }}) est modifié. Détails par courriel.",
}


# Lot 4 — personnel et application mobile : (libellé, sujet, corps, texte SMS éventuel).
MODELES_LOT4: dict[str, tuple[str, str, str, str]] = {
    "vacation_affectee": (
        "Vacation affectée (agent)",
        "Nouvelle vacation : {{ site }} le {{ debut }}",
        "Bonjour {{ agent }},\n\nUne vacation vous est affectée : {{ site }}, du {{ debut }} au {{ fin }}. Elle figure dans "
        "l'application mobile à la prochaine synchronisation.",
        "Ville de Châtillon : vacation {{ site }} le {{ debut }}.",
    ),
    "vacation_a_revoir": (
        "Vacation à revoir (agent)",
        "Votre vacation du {{ debut }} est modifiée",
        "Bonjour {{ agent }},\n\nVotre vacation {{ site }} du {{ debut }} au {{ fin }} est à revoir : {{ motif }}.\n"
        "Le planificateur vous confirmera la nouvelle organisation.",
        "Ville de Châtillon : vacation {{ site }} du {{ debut }} à revoir.",
    ),
    "incident_signale": (
        "Incident signalé (service)",
        "Incident {{ gravite }} — {{ site }}",
        "Incident « {{ nature }} » ({{ gravite }}) signalé sur {{ site }}{% if seance %}, séance {{ seance }}{% endif %}"
        "{% if usager_nom %}, usager {{ usager_nom }}{% endif %} :\n\n{{ description }}\n\nSuivi : {{ lien }}",
        "",
    ),
    "saisie_mobile_conflit": (
        "Saisie mobile à vérifier (service)",
        "Saisie de {{ agent }} à vérifier",
        "Une saisie de l'application mobile ({{ type }}, {{ horodatage }}) de {{ agent }} est conservée mais à vérifier :\n"
        "{{ message }}\n\nSaisies : {{ lien }}",
        "",
    ),
}


# Corrections du lot 3 (revues) : tout changement de paramètre financier est signalé au service.
MODELES_CORRECTIONS_LOT3: dict[str, tuple[str, str, str, str]] = {
    "parametre_financier_modifie": (
        "Paramètre financier modifié (service)",
        "Paramètre financier modifié : {{ parametres }}",
        "Bonjour,\n\n{{ agent }} vient de modifier les paramètres financiers suivants : {{ parametres }}.\nLe détail "
        "(valeurs avant et après) figure dans le journal d'audit. Si ce changement n'était pas prévu, prévenez la DSI.",
        "",
    ),
}


# Corrections du lot 4 (revues) : dégâts relevés par un gardien, à examiner par le régisseur.
MODELES_CORRECTIONS_LOT4: dict[str, tuple[str, str, str, str]] = {
    "etat_des_lieux_degats": (
        "Dégâts constatés à la sortie (service)",
        "Dégâts constatés — {{ espace }}, {{ debut }}",
        "Bonjour,\n\nL'état des lieux de sortie de la séance du {{ debut }} ({{ espace }}, {{ usager }}, dossier {{ dossier }}) "
        "relève des dégâts :\n{{ observations }}\n\nLa caution reste bloquée : statuez sur une retenue depuis le back-office : "
        "{{ lien }}",
        "",
    ),
}


# Lot 5 — matériel : signalements au service.
MODELES_LOT5: dict[str, tuple[str, str, str, str]] = {
    "materiel_manquant": (
        "Matériel manquant au retour (service)",
        "Matériel manquant — {{ dossier }}",
        "Bonjour,\n\n{{ manquants }} « {{ materiel }} » manquent au retour du prêt du dossier {{ dossier }} ({{ usager }}). "
        "Ils sont retirés du stock ; s'ils sont rapportés, enregistrez-les depuis le prêt. Une retenue sur la caution peut "
        "être proposée.\n\nPrêts : {{ lien }}",
        "",
    ),
    "materiel_indisponible": (
        "Prêts de matériel à revoir (service)",
        "Matériel indisponible : {{ materiel }}",
        "Bonjour,\n\nLe stock de « {{ materiel }} » ({{ lieu }}) ne couvre plus les prêts suivants : {{ prets }}.\n"
        "Proposez un autre matériel, un transfert ou prévenez l'usager.\n\nPrêts : {{ lien }}",
        "",
    ),
    "materiel_alertes": (
        "Contrôles et stocks du matériel (service)",
        "Matériel : {{ nombre }} point(s) à traiter",
        "Bonjour,\n\nContrôles périodiques dépassés et consommables sous le seuil :\n{{ lignes }}\n\nDétail : {{ lien }}",
        "",
    ),
}


# Lot 6 — pilotage : attestation de valorisation sur le portail (VAL-04), planning programmé (IMP-04).
MODELES_LOT6: dict[str, tuple[str, str, str, str]] = {
    "attestation_valorisation_disponible": (
        "Attestation de valorisation disponible",
        "Votre attestation de valorisation {{ exercice }} est disponible",
        "Bonjour {{ contact.prenom }},\n\nL'attestation des avantages en nature accordés par la Ville à {{ usager }} pour "
        "l'exercice {{ exercice }} ({{ montant }}) est disponible dans votre espace, rubrique « Attestations ». Elle vous permet "
        "de valoriser ces contributions dans vos comptes (comptes 86 et 87)." + SIGNATURE,
        "",
    ),
    "planning_hebdomadaire": (
        "Planning de la semaine (envoi programmé)",
        "{{ cible }} — semaine du {{ semaine }}",
        "Bonjour,\n\nVeuillez trouver ci-joint le planning de la semaine du {{ semaine }} : {{ cible }}.\nLa version en ligne fait foi.",
        "",
    ),
}
