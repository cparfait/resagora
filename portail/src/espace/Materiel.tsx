/** MAT-02, POR-04 : matériel proposé par la Ville sur le site de l'équipement (tables, chaises, sonorisation…),
 * demandé à l'étape 2 ou ensuite sur le dossier. La Ville valide chaque demande ; la disponibilité est vérifiée. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { chemin, messageErreur, requete } from "../api/http";
import type { Dossier, MaterielDemande, MaterielPropose } from "../api/types";
import { Bouton } from "../ui/Bouton";
import { Champ, Liste } from "../ui/Champs";
import { Alerte, Chargement, Etiquette, dateHeure } from "../ui/Elements";

const TONS: Record<string, "neutre" | "info" | "succes" | "attention" | "danger"> = {
  demandee: "attention",
  validee: "succes",
  sortie: "info",
  rendue: "neutre",
  refusee: "danger",
  annulee: "neutre",
};

function useCatalogue(espace: number | null) {
  return useQuery({
    queryKey: ["materiel-propose", espace],
    queryFn: () => requete<MaterielPropose[]>("GET", chemin("/api/portail/materiel", { espace: espace ?? 0 })),
    enabled: espace !== null,
  });
}

/** Étape 2 de la demande : quantités souhaitées (0 = aucune). */
export function ChoixMateriel({ espace, valeurs, onChange }: { espace: number | null; valeurs: MaterielDemande[]; onChange: (v: MaterielDemande[]) => void }) {
  const catalogue = useCatalogue(espace);
  const idAide = useId();
  if (espace === null) return null;
  if (catalogue.isPending) return <Chargement texte="Recherche du matériel disponible…" />;
  if (!catalogue.data?.length) return null;
  const quantite = (id: number) => valeurs.find((v) => v.materiel === id)?.quantite ?? 0;
  const changer = (id: number, brut: string) => {
    const nombre = Math.max(0, Math.floor(Number(brut) || 0));
    const autres = valeurs.filter((v) => v.materiel !== id);
    onChange(nombre ? [...autres, { materiel: id, quantite: nombre }] : autres);
  };
  return (
    <fieldset className="groupe-champs" aria-describedby={idAide}>
      <legend>Matériel souhaité (facultatif)</legend>
      <p id={idAide} className="aide">
        La Ville peut prêter ce matériel sur place. Votre demande est examinée avec la réservation ; la quantité accordée dépend de ce qui est disponible à vos dates.
      </p>
      {catalogue.data.map((m) => (
        <Champ
          key={m.id}
          libelle={`${m.libelle} (nombre de ${m.unite}s, ${m.maximum} au plus)`}
          nom={`materiel-${m.id}`}
          type="number"
          inputMode="numeric"
          min={0}
          max={m.maximum}
          value={quantite(m.id) ? String(quantite(m.id)) : ""}
          onChange={(e) => changer(m.id, e.target.value)}
          aide={m.description || undefined}
        />
      ))}
    </fieldset>
  );
}

/** Fiche dossier : matériel demandé ou prêté, et nouvelle demande pour une réservation en cours. */
export function MaterielDuDossier({ dossier }: { dossier: Dossier }) {
  const client = useQueryClient();
  const enCours = (dossier.reservations ?? []).filter((r) => ["demande", "en_instruction", "option", "validee", "confirmee"].includes(r.statut));
  const [saisie, setSaisie] = useState({ reservation: enCours[0] ? String(enCours[0].id) : "", materiel: "", quantite: "" });
  const [annonce, setAnnonce] = useState<{ ton: "succes" | "erreur"; texte: string } | null>(null);
  const reservation = enCours.find((r) => String(r.id) === saisie.reservation);
  const catalogue = useCatalogue(reservation ? reservation.espace : null);
  const demander = useMutation({
    mutationFn: () =>
      requete("POST", `/api/portail/dossiers/${dossier.id}/materiel`, { reservation: Number(saisie.reservation), materiel: Number(saisie.materiel), quantite: Number(saisie.quantite) }),
    onSuccess: async () => {
      setAnnonce({ ton: "succes", texte: "Votre demande de matériel est transmise à la Ville." });
      setSaisie({ ...saisie, materiel: "", quantite: "" });
      await client.invalidateQueries({ queryKey: ["dossier", String(dossier.id)] });
    },
    onError: (e) => setAnnonce({ ton: "erreur", texte: messageErreur(e) }),
  });
  const prets = dossier.materiel ?? [];
  if (!prets.length && !enCours.length) return null;
  return (
    <section aria-labelledby="titre-materiel">
      <h2 id="titre-materiel">Matériel</h2>
      {annonce ? <Alerte ton={annonce.ton}>{annonce.texte}</Alerte> : null}
      {prets.length ? (
        <ul className="liste-simple">
          {prets.map((p) => (
            <li key={p.id}>
              {p.quantite} × {p.materiel}, du {dateHeure(p.debut)} au {dateHeure(p.fin)} — <Etiquette texte={p.statut_libelle} ton={TONS[p.statut] ?? "neutre"} />
              {p.motif ? ` (${p.motif})` : ""}
            </li>
          ))}
        </ul>
      ) : (
        <p>Aucun matériel demandé.</p>
      )}
      {enCours.length && catalogue.data?.length ? (
        <form
          className="formulaire"
          onSubmit={(e) => {
            e.preventDefault();
            setAnnonce(null);
            demander.mutate();
          }}
        >
          <h3>Demander du matériel</h3>
          {enCours.length > 1 ? (
            <Liste
              libelle="Réservation concernée"
              nom="reservation"
              obligatoire
              options={enCours.map((r) => ({ valeur: String(r.id), libelle: `${r.espace_nom} — ${r.description}` }))}
              value={saisie.reservation}
              onChange={(e) => setSaisie({ ...saisie, reservation: e.target.value, materiel: "" })}
            />
          ) : null}
          <Liste
            libelle="Matériel"
            nom="materiel"
            obligatoire
            options={catalogue.data.map((m) => ({ valeur: String(m.id), libelle: `${m.libelle} (${m.maximum} au plus)` }))}
            value={saisie.materiel}
            onChange={(e) => setSaisie({ ...saisie, materiel: e.target.value })}
          />
          <Champ libelle="Quantité" nom="quantite-materiel" type="number" inputMode="numeric" min={1} obligatoire value={saisie.quantite} onChange={(e) => setSaisie({ ...saisie, quantite: e.target.value })} />
          <Bouton type="submit" enCours={demander.isPending}>
            Demander ce matériel
          </Bouton>
        </form>
      ) : null}
    </section>
  );
}
