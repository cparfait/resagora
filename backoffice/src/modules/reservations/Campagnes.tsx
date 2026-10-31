/** Campagne annuelle des créneaux (PLA-05) : cycle de la campagne, arbitrage proposé (RG-03), décision de la commission. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ErreurApi, requete } from "../../api/http";
import type { Campagne } from "../../api/types";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { ChampSelection, ChampTexte } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { Chargement, Erreur, Vide } from "../../ui/Etats";
import { useNotifications } from "../../ui/Notifications";
import { EcranRessource, useOptions } from "../../ui/Ressource";

const STATUTS_CAMPAGNE: Record<string, { libelle: string; suivant?: string; action?: string }> = {
  preparation: { libelle: "En préparation", suivant: "ouverte", action: "Ouvrir aux demandes" },
  ouverte: { libelle: "Ouverte aux demandes", suivant: "instruction", action: "Clore les dépôts et instruire" },
  instruction: { libelle: "En instruction", suivant: "commission", action: "Transmettre à la commission" },
  commission: { libelle: "En commission", suivant: "attribuee", action: "Marquer comme attribuée" },
  attribuee: { libelle: "Attribuée", suivant: "close", action: "Clore la campagne" },
  close: { libelle: "Close" },
};

const CATEGORIES: Record<string, string> = {
  service_municipal: "Ville",
  scolaire_temps_scolaire: "Scolaire (temps scolaire)",
  association_conventionnee_locale: "Association conventionnée locale",
  association: "Autre association",
  autre: "Entreprise, particulier ou hors temps scolaire",
};

interface Candidat {
  reservation_id: number;
  dossier: string;
  usager: string;
  categorie: string;
  rang: number;
  reconduction: boolean;
  depose_le: string | null;
  proposition: "attribuer" | "refuser";
}

interface Groupe {
  espace: string;
  creneau: string;
  candidats: Candidat[];
}

function Arbitrage({ campagne, onFermer }: { campagne: Campagne; onFermer: () => void }) {
  const { peut } = useSession();
  const { annoncer } = useNotifications();
  const client = useQueryClient();
  const analyse = useQuery({ queryKey: ["arbitrage", campagne.id], queryFn: () => requete<Groupe[]>("GET", `/api/gestion/reservations/campagnes/${campagne.id}/analyse`) });
  const [decisions, setDecisions] = useState<Record<number, { decision: string; motif: string }>>({});
  const decision = (c: Candidat) => decisions[c.reservation_id] ?? { decision: c.proposition, motif: c.proposition === "refuser" ? "Créneau attribué à un demandeur prioritaire (règlement d'attribution)." : "" };
  const attribuer = useMutation({
    mutationFn: () => {
      const tout: Record<string, { decision: string; motif: string }> = {};
      for (const g of analyse.data ?? []) for (const c of g.candidats) tout[String(c.reservation_id)] = decision(c);
      return requete<{ attribuees: number; refusees: number }>("POST", `/api/gestion/reservations/campagnes/${campagne.id}/attribution`, { decisions: tout });
    },
    onSuccess: async (bilan) => {
      annoncer(`${bilan.attribuees} créneaux attribués, ${bilan.refusees} refus motivés ; les usagers sont prévenus.`);
      await client.invalidateQueries({ queryKey: ["campagnes"] });
      onFermer();
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Attribution impossible.", "erreur"),
  });
  if (analyse.isPending) return <Chargement />;
  if (analyse.isError) return <Erreur erreur={analyse.error} />;
  if (!analyse.data.length) return <Vide message="Aucune demande concurrente : toutes les demandes peuvent être attribuées depuis leurs dossiers." />;
  return (
    <>
      <p>Proposition d'arbitrage : Ville, puis scolaire en temps scolaire, associations conventionnées locales, autres associations, entreprises et particuliers ; à égalité, reconduction puis date de dépôt.</p>
      {analyse.data.map((g) => (
        <fieldset key={`${g.espace}-${g.creneau}`} className="groupe">
          <legend>
            {g.espace} — {g.creneau}
          </legend>
          <ol className="liste-arbitrage">
            {g.candidats.map((c) => {
              const d = decision(c);
              return (
                <li key={c.reservation_id}>
                  <p>
                    <strong>{c.usager}</strong> ({c.dossier}) — {CATEGORIES[c.categorie] ?? c.categorie}
                    {c.reconduction ? " — reconduction" : ""}
                  </p>
                  <ChampSelection
                    libelle={`Décision pour ${c.usager}`}
                    options={[
                      { valeur: "attribuer", libelle: "Attribuer" },
                      { valeur: "refuser", libelle: "Refuser" },
                    ]}
                    value={d.decision}
                    onChange={(e) => setDecisions({ ...decisions, [c.reservation_id]: { ...d, decision: e.target.value } })}
                  />
                  {d.decision === "refuser" ? (
                    <ChampTexte libelle="Motif du refus" obligatoire value={d.motif} onChange={(e) => setDecisions({ ...decisions, [c.reservation_id]: { ...d, motif: e.target.value } })} />
                  ) : null}
                </li>
              );
            })}
          </ol>
        </fieldset>
      ))}
      <div className="formulaire__actions">
        <Bouton variante="secondaire" onClick={onFermer}>
          Fermer
        </Bouton>
        {peut("arbitrer_campagne") && campagne.statut === "commission" ? (
          <Bouton enCours={attribuer.isPending} onClick={() => attribuer.mutate()}>
            Enregistrer la décision de la commission
          </Bouton>
        ) : (
          <p className="texte-doux">La décision se saisit par un membre de la commission quand la campagne est « en commission ».</p>
        )}
      </div>
    </>
  );
}

export default function Campagnes() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const saisons = useOptions("saisons", "/api/gestion/referentiel/saisons", (s) => String(s.nom));
  const [arbitrage, setArbitrage] = useState<Campagne | null>(null);
  const changer = useMutation({
    mutationFn: ({ campagne, statut }: { campagne: number; statut: string }) => requete("POST", `/api/gestion/reservations/campagnes/${campagne}/statut`, { statut }),
    onSuccess: async () => {
      annoncer("Campagne mise à jour.");
      await client.invalidateQueries({ queryKey: ["campagnes"] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Changement impossible.", "erreur"),
  });
  return (
    <>
      <EcranRessource<Campagne & Record<string, unknown>>
        titre="Campagnes de créneaux annuels"
        chemin="/api/gestion/reservations/campagnes"
        cleRequete="campagnes"
        actionLecture="lire_reservation"
        actionEcriture="gerer_campagne"
        libelleObjet="Campagne"
        colonnes={[
          { cle: "nom", titre: "Campagne", rendu: (c) => c.nom },
          { cle: "saison", titre: "Saison", rendu: (c) => c.saison_nom },
          { cle: "periode", titre: "Dépôt des demandes", rendu: (c) => `du ${c.ouverture} au ${c.cloture}` },
          { cle: "demandes", titre: "Demandes", rendu: (c) => c.nombre_demandes },
          { cle: "statut", titre: "Étape", rendu: (c) => <Badge libelle={STATUTS_CAMPAGNE[c.statut]?.libelle ?? c.statut} ton="info" /> },
        ]}
        actionsLigne={(c) => {
          const etape = STATUTS_CAMPAGNE[c.statut];
          return (
            <>
              <Bouton variante="lien" onClick={() => setArbitrage(c)}>
                Arbitrage
              </Bouton>
              {etape?.suivant && peut(etape.suivant === "attribuee" || etape.suivant === "close" ? "arbitrer_campagne" : "gerer_campagne") ? (
                <Bouton variante="lien" onClick={() => changer.mutate({ campagne: c.id, statut: etape.suivant ?? "" })}>
                  {etape.action}
                </Bouton>
              ) : null}
            </>
          );
        }}
        champs={[
          { nom: "nom", libelle: "Nom", type: "texte", obligatoire: true },
          { nom: "saison", libelle: "Saison", type: "selection", obligatoire: true, options: saisons },
          { nom: "ouverture", libelle: "Ouverture des dépôts", type: "date", obligatoire: true },
          { nom: "cloture", libelle: "Clôture des dépôts", type: "date", obligatoire: true },
          { nom: "date_commission", libelle: "Date de la commission", type: "date" },
        ]}
      />
      <Dialogue ouvert={arbitrage !== null} titre={`Arbitrage — ${arbitrage?.nom ?? ""}`} onFermer={() => setArbitrage(null)} large>
        {arbitrage ? <Arbitrage campagne={arbitrage} onFermer={() => setArbitrage(null)} /> : null}
      </Dialogue>
    </>
  );
}
