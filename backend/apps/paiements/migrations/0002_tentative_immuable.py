"""TAR-07, RG-13 : une tentative de paiement ne se supprime pas ; ses références et son montant ne changent jamais ; un
résultat définitif (payée, refusée, abandonnée, close) ne change plus — seuls avancent le compteur des notifications
et l'effacement de l'adresse à l'anonymisation ; une tentative « à contrôler » ne se clôt que par un agent. Les
remboursements de trop-perçus sont en ajout seul. Aucune table ne se vide."""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION paiements_proteger_tentative() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Tentative de paiement : suppression interdite (TAR-07).' USING ERRCODE = 'restrict_violation';
    END IF;
    IF NEW.uuid IS DISTINCT FROM OLD.uuid OR NEW.piece_id IS DISTINCT FROM OLD.piece_id
        OR NEW.montant IS DISTINCT FROM OLD.montant OR NEW.refdet IS DISTINCT FROM OLD.refdet
        OR NEW.exer IS DISTINCT FROM OLD.exer OR NEW.numcli IS DISTINCT FROM OLD.numcli
        OR NEW.mode IS DISTINCT FROM OLD.mode OR NEW.saisie IS DISTINCT FROM OLD.saisie
        OR NEW.cree_le IS DISTINCT FROM OLD.cree_le
        OR (OLD.id_op IS NOT NULL AND NEW.id_op IS DISTINCT FROM OLD.id_op)
        OR (OLD.encaissement_id IS NOT NULL AND NEW.encaissement_id IS DISTINCT FROM OLD.encaissement_id) THEN
        RAISE EXCEPTION 'Tentative de paiement : références et montant immuables (TAR-07).' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.statut IN ('payee', 'refusee', 'abandonnee', 'erreur') AND (
        NEW.statut IS DISTINCT FROM OLD.statut OR NEW.resultrans IS DISTINCT FROM OLD.resultrans
        OR NEW.numauto IS DISTINCT FROM OLD.numauto OR NEW.paye_le IS DISTINCT FROM OLD.paye_le
        OR NEW.trop_percu IS DISTINCT FROM OLD.trop_percu OR NEW.controle IS DISTINCT FROM OLD.controle
        OR NEW.encaissement_id IS DISTINCT FROM OLD.encaissement_id OR NEW.motif_cloture IS DISTINCT FROM OLD.motif_cloture) THEN
        RAISE EXCEPTION 'Tentative de paiement : résultat définitif (TAR-07).' USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.statut = 'a_controler' AND (
        NEW.statut NOT IN ('a_controler', 'erreur') OR NEW.resultrans IS DISTINCT FROM OLD.resultrans
        OR NEW.numauto IS DISTINCT FROM OLD.numauto OR NEW.trop_percu IS DISTINCT FROM OLD.trop_percu
        OR NEW.encaissement_id IS DISTINCT FROM OLD.encaissement_id) THEN
        RAISE EXCEPTION 'Tentative à contrôler : clôture par un agent seulement (TAR-07).' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER paiements_tentative_immuable
    BEFORE UPDATE OR DELETE ON paiements_tentativepaiement
    FOR EACH ROW EXECUTE FUNCTION paiements_proteger_tentative();
CREATE TRIGGER paiements_tentative_sans_vidage BEFORE TRUNCATE ON paiements_tentativepaiement
    FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
CREATE TRIGGER paiements_remboursement_immuable BEFORE UPDATE OR DELETE ON paiements_remboursementtroppercu
    FOR EACH ROW EXECUTE FUNCTION interdire_modification();
CREATE TRIGGER paiements_remboursement_sans_vidage BEFORE TRUNCATE ON paiements_remboursementtroppercu
    FOR EACH STATEMENT EXECUTE FUNCTION interdire_vidage();
"""

INVERSE = """
DROP TRIGGER IF EXISTS paiements_remboursement_sans_vidage ON paiements_remboursementtroppercu;
DROP TRIGGER IF EXISTS paiements_remboursement_immuable ON paiements_remboursementtroppercu;
DROP TRIGGER IF EXISTS paiements_tentative_sans_vidage ON paiements_tentativepaiement;
DROP TRIGGER IF EXISTS paiements_tentative_immuable ON paiements_tentativepaiement;
DROP FUNCTION IF EXISTS paiements_proteger_tentative();
"""


class Migration(migrations.Migration):
    dependencies = [("paiements", "0001_initial"), ("audit", "0005_immuabilite_renforcee")]
    operations = [migrations.RunSQL(SQL, INVERSE)]
