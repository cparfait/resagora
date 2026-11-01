/** POR-05 : lien d'abonnement à l'agenda des séances d'une structure (Outlook, Google Agenda, Thunderbird…). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { messageErreur, requete } from "../api/http";
import type { AbonnementAgenda } from "../api/types";
import { Bouton } from "../ui/Bouton";
import { Champ } from "../ui/Champs";
import { Alerte, date, dateHeure } from "../ui/Elements";

export function AgendaStructure({ usager }: { usager: string | number }) {
  const client = useQueryClient();
  const cle = ["agenda", String(usager)];
  const chemin = `/api/portail/usagers/${usager}/agenda`;
  const etat = useQuery({ queryKey: cle, queryFn: () => requete<AbonnementAgenda>("GET", chemin) });
  // Le lien n'est connu qu'au moment de sa création : il n'est pas conservé par la Ville.
  const [lien, setLien] = useState<string | null>(null);
  const [annonce, setAnnonce] = useState<{ ton: "succes" | "erreur"; texte: string } | null>(null);
  const creer = useMutation({
    mutationFn: () => requete<AbonnementAgenda & { url: string }>("POST", chemin),
    onSuccess: async (reponse) => {
      setLien(reponse.url);
      setAnnonce({ ton: "succes", texte: "Lien d'abonnement créé. Copiez-le maintenant : il ne sera plus affiché." });
      await client.invalidateQueries({ queryKey: cle });
    },
    onError: (e) => setAnnonce({ ton: "erreur", texte: messageErreur(e) }),
  });
  const revoquer = useMutation({
    mutationFn: () => requete("DELETE", chemin),
    onSuccess: async () => {
      setLien(null);
      setAnnonce({ ton: "succes", texte: "Lien désactivé : les agendas abonnés ne recevront plus vos séances." });
      await client.invalidateQueries({ queryKey: cle });
    },
    onError: (e) => setAnnonce({ ton: "erreur", texte: messageErreur(e) }),
  });
  const copier = async () => {
    if (!lien) return;
    try {
      await navigator.clipboard.writeText(lien);
      setAnnonce({ ton: "succes", texte: "Lien copié." });
    } catch {
      setAnnonce({ ton: "erreur", texte: "La copie automatique n'a pas fonctionné : sélectionnez le lien et copiez-le." });
    }
  };
  const actif = etat.data?.actif ?? false;
  return (
    <section aria-labelledby="titre-agenda" className="carte">
      <h2 id="titre-agenda">Agenda des séances</h2>
      <p>
        Abonnez l'agenda de votre structure (Outlook, Google Agenda, Thunderbird, téléphone) à vos séances : réservations validées ou confirmées, demandes en
        cours (marquées « Provisoire »), annulations et refus, avec l'adresse et les consignes d'accès. L'agenda se met à jour de lui-même, environ toutes les heures.
      </p>
      <p>
        Ce lien donne accès à vos séances sans mot de passe : ne le transmettez qu'aux membres de la structure. Il est valable un an. Vous pouvez le
        remplacer ou le désactiver à tout moment.
      </p>
      {annonce ? <Alerte ton={annonce.ton}>{annonce.texte}</Alerte> : null}
      {etat.data && actif ? (
        <p>
          Lien actif depuis le {date(etat.data.cree_le)}, valable jusqu'au {date(etat.data.expire_le)}.
          {etat.data.dernier_acces ? ` Dernière lecture par un agenda : ${dateHeure(etat.data.dernier_acces)}.` : " Aucun agenda ne l'a encore lu."}
        </p>
      ) : null}
      {lien ? (
        <>
          <Champ
            libelle="Lien d'abonnement"
            aide="Dans Outlook : Ajouter un calendrier, puis S'abonner à partir du web. Dans Google Agenda : Autres agendas, puis À partir de l'URL."
            value={lien}
            readOnly
            onFocus={(e) => e.currentTarget.select()}
          />
          <Bouton variante="secondaire" onClick={() => void copier()}>
            Copier le lien
          </Bouton>
        </>
      ) : null}
      <p className="actions">
        <Bouton variante={actif ? "secondaire" : "principal"} enCours={creer.isPending} onClick={() => creer.mutate()}>
          {actif ? "Remplacer le lien (l'ancien cesse de fonctionner)" : "Créer un lien d'abonnement"}
        </Bouton>
        {actif ? (
          <Bouton variante="lien" enCours={revoquer.isPending} onClick={() => revoquer.mutate()}>
            Désactiver le lien
          </Bouton>
        ) : null}
      </p>
    </section>
  );
}
