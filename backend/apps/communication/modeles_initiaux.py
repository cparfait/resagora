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
    "usager_anonymise": (
        "Données personnelles effacées",
        "Effacement de vos données personnelles",
        "Bonjour,\n\nConformément à la durée de conservation annoncée, les données personnelles liées à votre compte ont été "
        "effacées. Les pièces comptables restent conservées par la Ville selon les règles de la comptabilité publique."
        + SIGNATURE,
        "",
    ),
}
