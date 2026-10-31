/** ADM-05 / SEC-08 : journal d'audit filtrable, exportable, avec vérification d'intégrité de la chaîne. */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { ErreurApi, requete, telecharger } from "../../api/http";
import type { EntreeJournal, Verification } from "../../api/types";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { useNotifications } from "../../ui/Notifications";
import { EcranRessource } from "../../ui/Ressource";

const dateHeure = new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "medium", timeZone: "Europe/Paris" });

export default function Journal() {
  const { annoncer } = useNotifications();
  const [verification, setVerification] = useState<Verification | null>(null);
  const verifier = useMutation({
    mutationFn: () => requete<Verification>("GET", "/api/gestion/audit/journal/verification"),
    onSuccess: setVerification,
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Vérification impossible.", "erreur"),
  });

  return (
    <>
      {verification ? (
        <div className={`alerte ${verification.integre ? "alerte--succes" : "alerte--erreur"}`} role="status">
          {verification.integre
            ? `Chaîne intègre : ${verification.entrees_verifiees} entrées vérifiées.`
            : `Intégrité rompue : ${verification.anomalies.join(" ")}`}
        </div>
      ) : null}
      <EcranRessource<EntreeJournal & Record<string, unknown>>
        titre="Journal d'audit"
        description="Toutes les écritures sont tracées et chaînées par empreinte ; aucune entrée ne peut être modifiée."
        chemin="/api/gestion/audit/journal"
        cleRequete="journal"
        actionLecture="lire_audit"
        libelleObjet="Entrée"
        actionsPage={
          <>
            <Bouton variante="secondaire" enCours={verifier.isPending} onClick={() => verifier.mutate()}>
              Vérifier l'intégrité
            </Bouton>
            <Bouton variante="secondaire" onClick={() => void telecharger("/api/gestion/audit/journal/export", "journal-audit.csv")}>
              Exporter (CSV)
            </Bouton>
          </>
        }
        colonnes={[
          { cle: "horodatage", titre: "Date", rendu: (e) => dateHeure.format(new Date(e.horodatage)) },
          { cle: "acteur", titre: "Acteur", rendu: (e) => e.acteur_libelle || "Système" },
          { cle: "action", titre: "Action", rendu: (e) => <Badge libelle={e.action} /> },
          { cle: "objet", titre: "Objet", rendu: (e) => (e.objet_type ? `${e.objet_libelle || e.objet_type} (n° ${e.objet_id})` : "—") },
          { cle: "ip", titre: "Adresse", rendu: (e) => e.adresse_ip ?? "—" },
        ]}
        filtres={[
          { nom: "acteur_libelle", libelle: "Acteur contient" },
          { nom: "action", libelle: "Action contient" },
          { nom: "du", libelle: "Depuis le", type: "date" },
          { nom: "au", libelle: "Jusqu'au", type: "date" },
        ]}
      />
    </>
  );
}
