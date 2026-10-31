/** POR-01 : comptes du portail créés par les usagers, à valider par la Ville (rattachement à un usager connu possible). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { construireChemin, ErreurApi, requete, type Page as PageApi } from "../../api/http";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { ChampSelection, ChampTexte } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { Chargement, Erreur } from "../../ui/Etats";
import { dateHeure } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { Page } from "../../ui/Page";
import { Tableau } from "../../ui/Tableau";

interface Compte {
  id: number;
  identifiant: string;
  contact_nom: string;
  telephone: string;
  statut: string;
  courriel_confirme_le: string | null;
  derniere_connexion: string | null;
  cree_le: string;
  motif_suspension: string;
  structures: { id: number; nom: string; type: string; statut: string; siret: string; rna: string }[];
}

const STATUTS: Record<string, { libelle: string; ton: "neutre" | "info" | "succes" | "attention" | "danger" }> = {
  a_confirmer: { libelle: "Courriel à confirmer", ton: "neutre" },
  a_valider: { libelle: "À valider", ton: "attention" },
  actif: { libelle: "Actif", ton: "succes" },
  suspendu: { libelle: "Suspendu", ton: "danger" },
  ferme: { libelle: "Fermé", ton: "neutre" },
};

type Decision = { compte: Compte; type: "valider" | "refuser" | "suspendre" } | null;

export default function Comptes() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const [statut, setStatut] = useState("a_valider");
  const [recherche, setRecherche] = useState("");
  const [decision, setDecision] = useState<Decision>(null);
  const [motif, setMotif] = useState("");
  const [rattacher, setRattacher] = useState("");
  const [rechercheUsager, setRechercheUsager] = useState("");
  const comptes = useQuery({
    queryKey: ["comptes-portail", statut, recherche],
    queryFn: () => requete<PageApi<Compte>>("GET", construireChemin("/api/gestion/usagers/comptes", { statut, recherche, taille: 100 })),
  });
  const candidats = useQuery({
    queryKey: ["usagers-rattachement", rechercheUsager],
    queryFn: () => requete<PageApi<{ id: number; nom: string; commune: string }>>("GET", construireChemin("/api/gestion/usagers/usagers", { recherche: rechercheUsager, statut: "valide", taille: 20 })),
    enabled: decision?.type === "valider" && rechercheUsager.length >= 2,
  });
  const action = useMutation({
    mutationFn: ({ compte, verbe, corps }: { compte: Compte; verbe: string; corps?: unknown }) => requete<Compte>("POST", `/api/gestion/usagers/comptes/${compte.id}/${verbe}`, corps),
    onSuccess: async (c) => {
      annoncer(`Compte ${c.identifiant} : ${STATUTS[c.statut]?.libelle ?? c.statut}. L'usager est prévenu par courriel.`);
      setDecision(null);
      setMotif("");
      setRattacher("");
      await client.invalidateQueries({ queryKey: ["comptes-portail"] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Action impossible.", "erreur"),
  });
  const gerer = peut("valider_compte_usager");

  return (
    <Page titre="Comptes du portail" description="Les structures inscrites sur le portail ne peuvent déposer de demande qu'une fois leur compte validé par la Ville.">
      <form className="filtres" role="search" aria-label="Filtrer les comptes" onSubmit={(e) => e.preventDefault()}>
        <ChampSelection libelle="État" options={Object.entries(STATUTS).map(([valeur, s]) => ({ valeur, libelle: s.libelle }))} videLibelle="Tous" value={statut} onChange={(e) => setStatut(e.target.value)} />
        <ChampTexte libelle="Courriel, nom ou structure" type="search" value={recherche} onChange={(e) => setRecherche(e.target.value)} />
      </form>
      {comptes.isPending ? <Chargement /> : null}
      {comptes.isError ? <Erreur erreur={comptes.error} reessayer={() => void comptes.refetch()} /> : null}
      {comptes.data ? (
        <Tableau<Compte>
          legende="Comptes du portail"
          lignes={comptes.data.results}
          cleLigne={(c) => c.id}
          messageVide="Aucun compte dans cet état."
          colonnes={[
            { cle: "contact", titre: "Contact", rendu: (c) => `${c.contact_nom} — ${c.identifiant}${c.telephone ? ` — ${c.telephone}` : ""}` },
            { cle: "structures", titre: "Structure(s)", rendu: (c) => c.structures.map((s) => `${s.nom} (${s.type}${s.rna ? `, ${s.rna}` : ""}${s.siret ? `, SIRET ${s.siret}` : ""})`).join(" ; ") },
            { cle: "statut", titre: "État", rendu: (c) => <Badge libelle={STATUTS[c.statut]?.libelle ?? c.statut} ton={STATUTS[c.statut]?.ton ?? "neutre"} /> },
            { cle: "cree", titre: "Inscrit le", rendu: (c) => dateHeure(c.cree_le), valeurTri: (c) => c.cree_le },
          ]}
          actions={
            gerer
              ? (c) => (
                  <>
                    {["a_valider", "a_confirmer"].includes(c.statut) ? (
                      <>
                        <Bouton variante="lien" onClick={() => setDecision({ compte: c, type: "valider" })} aria-label={`Valider le compte de ${c.contact_nom}`}>
                          Valider
                        </Bouton>
                        <Bouton variante="lien" onClick={() => setDecision({ compte: c, type: "refuser" })} aria-label={`Refuser le compte de ${c.contact_nom}`}>
                          Refuser
                        </Bouton>
                      </>
                    ) : null}
                    {c.statut === "actif" ? (
                      <Bouton variante="lien" onClick={() => setDecision({ compte: c, type: "suspendre" })} aria-label={`Suspendre le compte de ${c.contact_nom}`}>
                        Suspendre
                      </Bouton>
                    ) : null}
                    {c.statut === "suspendu" ? (
                      <Bouton variante="lien" onClick={() => action.mutate({ compte: c, verbe: "reactiver" })} aria-label={`Réactiver le compte de ${c.contact_nom}`}>
                        Réactiver
                      </Bouton>
                    ) : null}
                  </>
                )
              : undefined
          }
        />
      ) : null}
      <Dialogue ouvert={decision !== null} titre={decision?.type === "valider" ? "Valider le compte" : decision?.type === "refuser" ? "Refuser le compte" : "Suspendre le compte"} onFermer={() => setDecision(null)}>
        {decision ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (decision.type === "valider") action.mutate({ compte: decision.compte, verbe: "valider", corps: rattacher ? { usager_existant: Number(rattacher) } : {} });
              else action.mutate({ compte: decision.compte, verbe: decision.type, corps: { motif } });
            }}
          >
            <p>
              {decision.compte.contact_nom} — {decision.compte.structures.map((s) => s.nom).join(", ")}
            </p>
            {decision.type === "valider" ? (
              <>
                <p>Si la structure est déjà connue de la Ville, rattachez le contact à sa fiche plutôt que de créer un doublon.</p>
                <ChampTexte libelle="Rechercher un usager existant (facultatif)" type="search" value={rechercheUsager} onChange={(e) => setRechercheUsager(e.target.value)} />
                {candidats.data ? (
                  <ChampSelection
                    libelle="Rattacher à"
                    videLibelle="Nouvelle structure (pas de rattachement)"
                    options={candidats.data.results.map((u) => ({ valeur: String(u.id), libelle: `${u.nom}${u.commune ? ` (${u.commune})` : ""}` }))}
                    value={rattacher}
                    onChange={(e) => setRattacher(e.target.value)}
                  />
                ) : null}
              </>
            ) : (
              <ChampTexte libelle="Motif (communiqué à l'usager)" obligatoire value={motif} onChange={(e) => setMotif(e.target.value)} />
            )}
            <div className="formulaire__actions">
              <Bouton variante="secondaire" onClick={() => setDecision(null)}>
                Retour
              </Bouton>
              <Bouton type="submit" variante={decision.type === "valider" ? "principal" : "danger"} enCours={action.isPending}>
                {decision.type === "valider" ? "Valider le compte" : decision.type === "refuser" ? "Refuser" : "Suspendre"}
              </Bouton>
            </div>
          </form>
        ) : null}
      </Dialogue>
    </Page>
  );
}
