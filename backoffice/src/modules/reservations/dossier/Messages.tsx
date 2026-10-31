/** COM-02 : fil de messages du dossier entre la Ville et l'usager. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { construireChemin, ErreurApi, requete, type Page as PageApi } from "../../../api/http";
import { useSession } from "../../../auth/session";
import { Bouton } from "../../../ui/Bouton";
import { ChampZone } from "../../../ui/Champ";
import { Chargement, Erreur } from "../../../ui/Etats";
import { dateHeure } from "../../../ui/metier";
import { useNotifications } from "../../../ui/Notifications";

interface Message {
  id: number;
  auteur: string;
  de_la_ville: boolean;
  corps: string;
  cree_le: string;
  lu_par_usager_le: string | null;
}

export function MessagesDossier({ dossier }: { dossier: number }) {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const [texte, setTexte] = useState("");
  const fil = useQuery({
    queryKey: ["messages", dossier],
    queryFn: () => requete<PageApi<Message>>("GET", construireChemin("/api/gestion/communication/messages", { dossier, taille: 200 })),
  });
  const envoyer = useMutation({
    mutationFn: () => requete<Message>("POST", "/api/gestion/communication/messages", { dossier, corps: texte }),
    onSuccess: async () => {
      annoncer("Message envoyé ; l'usager est prévenu par courriel.");
      setTexte("");
      await client.invalidateQueries({ queryKey: ["messages", dossier] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Envoi impossible.", "erreur"),
  });
  return (
    <section aria-labelledby="titre-messages" className="carte">
      <h2 id="titre-messages">Messages</h2>
      {fil.isPending ? <Chargement lignes={2} /> : null}
      {fil.isError ? <Erreur erreur={fil.error} /> : null}
      {fil.data ? (
        fil.data.results.length === 0 ? (
          <p>Aucun message sur ce dossier.</p>
        ) : (
          <ol className="fil-messages">
            {fil.data.results.map((m) => (
              <li key={m.id} className={m.de_la_ville ? "message message--ville" : "message message--usager"}>
                <p className="message__entete">
                  <strong>{m.de_la_ville ? `Ville (${m.auteur})` : m.auteur}</strong> — {dateHeure(m.cree_le)}
                  {m.de_la_ville ? <span className="texte-doux">{m.lu_par_usager_le ? " — lu par l'usager" : " — non lu par l'usager"}</span> : null}
                </p>
                <p className="message__corps">{m.corps}</p>
              </li>
            ))}
          </ol>
        )
      ) : null}
      {peut("envoyer_message") ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (texte.trim()) envoyer.mutate();
          }}
        >
          <ChampZone libelle="Votre réponse à l'usager" obligatoire value={texte} onChange={(e) => setTexte(e.target.value)} maxLength={5000} />
          <div className="formulaire__actions formulaire__actions--gauche">
            <Bouton type="submit" enCours={envoyer.isPending} disabled={!texte.trim()}>
              Envoyer le message
            </Bouton>
          </div>
        </form>
      ) : null}
    </section>
  );
}
