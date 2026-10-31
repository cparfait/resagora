"""RG-13 renforcé (revue sécurité du lot 3, M4) : sur une pièce émise, seules évoluent la situation de paiement
(statut selon des transitions permises, montants réglés et avoirs croissants) et les références écrites une fois
(document, numéro de titre, acceptation). Les lignes ne changent jamais de pièce ; aucune ligne n'est ajoutée à une
pièce émise. Un état des lieux ne change plus ; une caution garde son montant et ses rattachements."""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION finances_proteger_piece() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.numero IS NOT NULL THEN
            RAISE EXCEPTION 'Pièce comptable émise (RG-13) : suppression interdite.' USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.numero IS NULL THEN
        RETURN NEW;
    END IF;
    IF NEW.numero IS DISTINCT FROM OLD.numero OR NEW.nature IS DISTINCT FROM OLD.nature
        OR NEW.exercice IS DISTINCT FROM OLD.exercice OR NEW.dossier_id IS DISTINCT FROM OLD.dossier_id
        OR NEW.usager_id IS DISTINCT FROM OLD.usager_id OR NEW.origine_id IS DISTINCT FROM OLD.origine_id
        OR NEW.objet IS DISTINCT FROM OLD.objet OR NEW.emise_le IS DISTINCT FROM OLD.emise_le
        OR NEW.echeance IS DISTINCT FROM OLD.echeance OR NEW.validite IS DISTINCT FROM OLD.validite
        OR NEW.total_reference IS DISTINCT FROM OLD.total_reference OR NEW.total_du IS DISTINCT FROM OLD.total_du
        OR NEW.acompte_deduit IS DISTINCT FROM OLD.acompte_deduit OR NEW.motif IS DISTINCT FROM OLD.motif
        OR NEW.reference_virement IS DISTINCT FROM OLD.reference_virement OR NEW.reglement IS DISTINCT FROM OLD.reglement
        OR NEW.emise_par_id IS DISTINCT FROM OLD.emise_par_id THEN
        RAISE EXCEPTION 'Pièce comptable émise (RG-13) : contenu non modifiable, émettre un avoir.' USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.montant_regle < OLD.montant_regle OR NEW.montant_avoirs < OLD.montant_avoirs THEN
        RAISE EXCEPTION 'Pièce émise (RG-13) : règlements et avoirs ne font que croître.' USING ERRCODE = 'restrict_violation';
    END IF;
    IF (OLD.document_id IS NOT NULL AND NEW.document_id IS DISTINCT FROM OLD.document_id)
        OR (OLD.titre_numero <> '' AND NEW.titre_numero IS DISTINCT FROM OLD.titre_numero)
        OR (OLD.accepte_le IS NOT NULL AND NEW.accepte_le IS DISTINCT FROM OLD.accepte_le)
        OR (OLD.accepte_par <> '' AND NEW.accepte_par IS DISTINCT FROM OLD.accepte_par) THEN
        RAISE EXCEPTION 'Pièce émise (RG-13) : document, titre et acceptation s''écrivent une seule fois.' USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.statut IS DISTINCT FROM OLD.statut AND NOT (
        (OLD.statut = 'emis' AND NEW.statut IN ('accepte', 'refuse', 'expire', 'remplace'))
        OR (OLD.statut = 'accepte' AND NEW.statut = 'remplace')
        OR (OLD.statut = 'a_titrer' AND NEW.statut IN ('titre_emis', 'solde_partiel', 'solde', 'annulee', 'en_recouvrement'))
        OR (OLD.statut = 'titre_emis' AND NEW.statut IN ('solde_partiel', 'solde', 'annulee', 'en_recouvrement'))
        OR (OLD.statut = 'solde_partiel' AND NEW.statut IN ('solde', 'annulee', 'en_recouvrement'))
        OR (OLD.statut = 'en_recouvrement' AND NEW.statut IN ('solde_partiel', 'solde', 'annulee'))
        OR (OLD.statut = 'solde' AND NEW.statut = 'annulee')
    ) THEN
        RAISE EXCEPTION 'Pièce émise (RG-13) : passage de « % » à « % » interdit.', OLD.statut, NEW.statut USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION finances_proteger_ligne() RETURNS trigger AS $$
DECLARE
    emise boolean;
BEGIN
    IF TG_OP = 'UPDATE' AND NEW.piece_id IS DISTINCT FROM OLD.piece_id THEN
        RAISE EXCEPTION 'Une ligne ne change jamais de pièce (RG-13).' USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT numero IS NOT NULL INTO emise FROM finances_piececomptable WHERE id = OLD.piece_id FOR SHARE;
        IF emise THEN
            RAISE EXCEPTION 'Ligne d''une pièce émise (RG-13) : % interdit.', TG_OP USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    IF TG_OP = 'INSERT' THEN
        SELECT numero IS NOT NULL INTO emise FROM finances_piececomptable WHERE id = NEW.piece_id FOR SHARE;
        IF emise THEN
            RAISE EXCEPTION 'Aucune ligne n''est ajoutée à une pièce émise (RG-13).' USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    RETURN COALESCE(NEW, OLD);
END
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION finances_proteger_etat_des_lieux() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'État des lieux conservé : suppression interdite.' USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.occurrence_id IS DISTINCT FROM OLD.occurrence_id OR NEW.moment IS DISTINCT FROM OLD.moment
        OR NEW.constat IS DISTINCT FROM OLD.constat OR NEW.observations IS DISTINCT FROM OLD.observations
        OR NEW.constate_le IS DISTINCT FROM OLD.constate_le OR NEW.source IS DISTINCT FROM OLD.source
        OR (OLD.signature_usager_id IS NOT NULL AND NEW.signature_usager_id IS DISTINCT FROM OLD.signature_usager_id) THEN
        RAISE EXCEPTION 'État des lieux établi : non modifiable (il fonde la restitution ou la retenue).' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION finances_proteger_caution() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Caution conservée : suppression interdite.' USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.montant IS DISTINCT FROM OLD.montant OR NEW.dossier_id IS DISTINCT FROM OLD.dossier_id
        OR NEW.reservation_id IS DISTINCT FROM OLD.reservation_id OR NEW.usager_id IS DISTINCT FROM OLD.usager_id THEN
        RAISE EXCEPTION 'Caution : montant et rattachements non modifiables.' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.statut IN ('restituee', 'encaissee') AND NEW.statut IS DISTINCT FROM OLD.statut THEN
        RAISE EXCEPTION 'Caution soldée : état définitif.' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER etat_des_lieux_immuable BEFORE UPDATE OR DELETE ON finances_etatdeslieux
    FOR EACH ROW EXECUTE FUNCTION finances_proteger_etat_des_lieux();
CREATE TRIGGER caution_protegee BEFORE UPDATE OR DELETE ON finances_caution
    FOR EACH ROW EXECUTE FUNCTION finances_proteger_caution();
"""

RETOUR = """
DROP TRIGGER IF EXISTS etat_des_lieux_immuable ON finances_etatdeslieux;
DROP TRIGGER IF EXISTS caution_protegee ON finances_caution;
DROP FUNCTION IF EXISTS finances_proteger_etat_des_lieux();
DROP FUNCTION IF EXISTS finances_proteger_caution();
CREATE OR REPLACE FUNCTION finances_proteger_ligne() RETURNS trigger AS $$
DECLARE
    piece_emise boolean;
BEGIN
    SELECT numero IS NOT NULL INTO piece_emise FROM finances_piececomptable
        WHERE id = COALESCE(NEW.piece_id, OLD.piece_id);
    IF piece_emise THEN
        RAISE EXCEPTION 'Ligne d''une pièce émise (RG-13) : % interdit.', TG_OP USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN COALESCE(NEW, OLD);
END
$$ LANGUAGE plpgsql;
CREATE OR REPLACE FUNCTION finances_proteger_piece() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.numero IS NOT NULL THEN
            RAISE EXCEPTION 'Pièce comptable émise (RG-13) : suppression interdite.' USING ERRCODE = 'restrict_violation';
        END IF;
        RETURN OLD;
    END IF;
    IF OLD.numero IS NOT NULL AND (
        NEW.numero IS DISTINCT FROM OLD.numero OR NEW.nature IS DISTINCT FROM OLD.nature
        OR NEW.exercice IS DISTINCT FROM OLD.exercice OR NEW.dossier_id IS DISTINCT FROM OLD.dossier_id
        OR NEW.usager_id IS DISTINCT FROM OLD.usager_id OR NEW.origine_id IS DISTINCT FROM OLD.origine_id
        OR NEW.objet IS DISTINCT FROM OLD.objet OR NEW.emise_le IS DISTINCT FROM OLD.emise_le
        OR NEW.echeance IS DISTINCT FROM OLD.echeance OR NEW.validite IS DISTINCT FROM OLD.validite
        OR NEW.total_reference IS DISTINCT FROM OLD.total_reference OR NEW.total_du IS DISTINCT FROM OLD.total_du
        OR NEW.acompte_deduit IS DISTINCT FROM OLD.acompte_deduit OR NEW.motif IS DISTINCT FROM OLD.motif
        OR NEW.reference_virement IS DISTINCT FROM OLD.reference_virement) THEN
        RAISE EXCEPTION 'Pièce comptable émise (RG-13) : contenu non modifiable, émettre un avoir.' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [("finances", "0003_corrections_revues_lot3")]
    operations = [migrations.RunSQL(SQL, reverse_sql=RETOUR)]
