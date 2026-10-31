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
