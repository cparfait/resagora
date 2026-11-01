/** Liste des dossiers de réservation (PLA-06) et accès à la nouvelle demande. */
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { requete } from "../../api/http";
import type { Dossier } from "../../api/types";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { dateSimple, STATUTS, TYPES_USAGER } from "../../ui/metier";
import { EcranRessource, useOptions } from "../../ui/Ressource";
import type { Compteur } from "../accueil/Accueil";

/** Avatar à initiales de l'usager (listes façon Mariloo). */
function Usager({ nom, type }: { nom: string; type: string }) {
  const initiales = nom
    .split(/[\s-]+/)
    .filter((mot) => /^[A-ZÀ-Ý]/u.test(mot))
    .slice(0, 2)
    .map((mot) => mot[0])
    .join("");
  return (
    <span className="flex min-w-[14rem] items-center gap-3">
      <span aria-hidden="true" className="inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-vert-pale text-[0.75rem] font-bold text-vert">
        {initiales || "?"}
      </span>
      <span className="flex flex-col">
        <span className="font-medium text-encre">{nom}</span>
        <span className="text-[0.8rem] text-encre-douce">{type}</span>
      </span>
    </span>
  );
}

export default function Dossiers() {
  const { peut } = useSession();
  const naviguer = useNavigate();
  const types = useOptions("types-reservation", "/api/gestion/reservations/types", (t) => String(t.libelle));
  const sites = useOptions("sites", "/api/gestion/referentiel/sites", (s) => String(s.nom));
  // Compteur « à traiter » du tableau de bord (cache partagé) pour la pilule « À traiter ».
  const aTraiter = useQuery({ queryKey: ["a-traiter"], queryFn: () => requete<{ compteurs: Compteur[] }>("GET", "/api/gestion/pilotage/a-traiter"), retry: false });
  const demandes = aTraiter.data?.compteurs.find((c) => c.code === "demandes")?.nombre;
  return (
    <EcranRessource<Dossier & Record<string, unknown>>
      titre="Dossiers de réservation"
      chemin="/api/gestion/reservations/dossiers"
      cleRequete="dossiers"
      actionLecture="lire_reservation"
      libelleObjet="Dossier"
      actionsPage={
        peut("creer_reservation") ? (
          <Bouton onClick={() => void naviguer("/reservations/nouvelle")}>
            Nouvelle demande
          </Bouton>
        ) : null
      }
      colonnes={[
        { cle: "numero", titre: "Numéro", rendu: (d) => <span className="font-medium whitespace-nowrap text-encre">{d.numero}</span>, valeurTri: (d) => d.numero },
        { cle: "usager", titre: "Usager", rendu: (d) => <Usager nom={d.usager_nom} type={TYPES_USAGER[d.usager_type] ?? d.usager_type} />, valeurTri: (d) => d.usager_nom },
        { cle: "objet", titre: "Objet", rendu: (d) => d.objet },
        { cle: "type", titre: "Type", rendu: (d) => d.type_reservation_libelle },
        { cle: "statut", titre: "Statut", rendu: (d) => <Badge libelle={STATUTS[d.statut]?.libelle ?? d.statut} ton={STATUTS[d.statut]?.ton ?? "neutre"} /> },
        { cle: "cree_le", titre: "Créé le", rendu: (d) => <span className="whitespace-nowrap">{dateSimple(d.cree_le)}</span>, valeurTri: (d) => d.cree_le },
      ]}
      actionsLigne={(d) => (
        <Bouton variante="lien" onClick={() => void naviguer(`/reservations/dossiers/${d.id}`)} aria-label={`Ouvrir le dossier ${d.numero}`}>
          Ouvrir
        </Bouton>
      )}
      pilules={{
        nom: "statut",
        libelle: "Filtrer par statut",
        options: [
          { valeur: "", libelle: "Toutes" },
          { valeur: "demande,en_instruction", libelle: "À traiter", nombre: demandes },
          { valeur: "option", libelle: "En option" },
          { valeur: "validee,confirmee", libelle: "Validées" },
          { valeur: "realisee,cloturee", libelle: "Terminées" },
          { valeur: "refusee,annulee", libelle: "Refusées ou annulées" },
        ],
      }}
      filtres={[
        { nom: "recherche", libelle: "Numéro, objet ou usager" },
        { nom: "options_expirant_heures", libelle: "Options expirant sous", options: [{ valeur: "48", libelle: "48 heures" }, { valeur: "168", libelle: "7 jours" }] },
        { nom: "type_reservation", libelle: "Type", options: types },
        { nom: "site", libelle: "Site", options: sites },
      ]}
    />
  );
}
