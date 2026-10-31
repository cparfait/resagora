/** TAR-04, TAR-08, TAR-09 : devis, acompte et facture du dossier (montants calculés par l'API). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { construireChemin, ErreurApi, requete, type Page as PageApi } from "../../../api/http";
import { useSession } from "../../../auth/session";
import { Bouton } from "../../../ui/Bouton";
import { Chargement, Erreur } from "../../../ui/Etats";
import { useNotifications } from "../../../ui/Notifications";
import { NATURES, TableauPieces, type Piece } from "../../finances/Pieces";

export function FinancesDossier({ dossier }: { dossier: number }) {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const pieces = useQuery({
    queryKey: ["pieces", "dossier", dossier],
    queryFn: () => requete<PageApi<Piece>>("GET", construireChemin("/api/gestion/finances/pieces", { dossier, taille: 100 })),
  });
  const rafraichir = async () => {
    await client.invalidateQueries({ queryKey: ["pieces"] });
    await client.invalidateQueries({ queryKey: ["dossier"] });
  };
  const emettre = useMutation({
    mutationFn: (verbe: "devis" | "acompte" | "facturer") => requete<Piece>("POST", `/api/gestion/finances/pieces/${verbe}`, { dossier }),
    onSuccess: async (p) => {
      annoncer(`${NATURES[p.nature] ?? "Pièce"} ${p.numero ?? ""} émise.`);
      await rafraichir();
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Émission impossible.", "erreur"),
  });
  return (
    <section aria-labelledby="titre-finances" className="carte">
      <h2 id="titre-finances">Devis et factures</h2>
      {peut("emettre_facture") ? (
        <p className="actions">
          <Bouton variante="secondaire" onClick={() => emettre.mutate("devis")} enCours={emettre.isPending}>
            Établir le devis
          </Bouton>
          <Bouton variante="secondaire" onClick={() => emettre.mutate("acompte")} enCours={emettre.isPending}>
            Facture d'acompte
          </Bouton>
          <Bouton variante="secondaire" onClick={() => emettre.mutate("facturer")} enCours={emettre.isPending}>
            Facturer les séances et frais
          </Bouton>
        </p>
      ) : null}
      {pieces.isPending ? <Chargement lignes={2} /> : null}
      {pieces.isError ? <Erreur erreur={pieces.error} /> : null}
      {pieces.data ? <TableauPieces pieces={pieces.data.results} legende="Pièces du dossier" rafraichir={rafraichir} /> : null}
    </section>
  );
}
