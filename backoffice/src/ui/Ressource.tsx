/**
 * Écran générique liste + formulaire pour une ressource REST de l'API de gestion
 * (référentiel, administration, tarifs, matériel…). Les droits viennent de /moi ;
 * les erreurs de validation du serveur sont affichées sous chaque champ.
 */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { useSearchParams } from "react-router";
import { construireChemin, ErreurApi, requete, type ErreursChamps, type Page as PageApi } from "../api/http";
import { useSession } from "../auth/session";
import { Bouton } from "./Bouton";
import { cn } from "./cn";
import { CaseACocher, ChampSelection, ChampTexte, ChampZone, type Option } from "./Champ";
import { Dialogue } from "./Dialogue";
import { Chargement, DroitsInsuffisants, Erreur } from "./Etats";
import { useNotifications } from "./Notifications";
import { Page } from "./Page";
import { Tableau, type Colonne } from "./Tableau";

export type TypeChamp = "texte" | "nombre" | "zone" | "booleen" | "selection" | "multiple" | "date" | "heure" | "dateheure" | "courriel" | "euros";

export interface DefinitionChamp {
  nom: string;
  libelle: string;
  type: TypeChamp;
  obligatoire?: boolean;
  aide?: string;
  options?: Option[];
  lectureSeule?: boolean;
  enCreationSeulement?: boolean;
  /** Pas des champs « nombre » (« any » pour des décimales). */
  pas?: string;
}

export interface DefinitionFiltre {
  nom: string;
  libelle: string;
  options?: Option[];
  type?: "texte" | "selection" | "booleen" | "date";
}

type Objet = Record<string, unknown> & { id: number };

interface Proprietes<T extends Objet> {
  titre: string;
  description?: ReactNode;
  chemin: string;
  cleRequete: string;
  actionLecture: string;
  actionEcriture?: string;
  colonnes: Colonne<T>[];
  champs?: DefinitionChamp[];
  filtres?: DefinitionFiltre[];
  libelleObjet: string;
  suppression?: boolean;
  actionsLigne?: (ligne: T) => ReactNode;
  actionsPage?: ReactNode;
  valeursInitiales?: Partial<T>;
  /** Filtres en pilules au-dessus de la liste (façon Mariloo) : une valeur exclusive du paramètre `nom`. */
  pilules?: { nom: string; libelle: string; options: { valeur: string; libelle: string; nombre?: number }[] };
}

function versSaisieLocale(d: Date): string {
  const deux = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${deux(d.getMonth() + 1)}-${deux(d.getDate())}T${deux(d.getHours())}:${deux(d.getMinutes())}`;
}

function versFormulaire(champs: DefinitionChamp[], objet: Partial<Objet>): Record<string, unknown> {
  const resultat: Record<string, unknown> = {};
  for (const champ of champs) {
    const valeur = objet[champ.nom];
    if (champ.type === "booleen") resultat[champ.nom] = Boolean(valeur);
    else if (champ.type === "multiple") resultat[champ.nom] = Array.isArray(valeur) ? valeur.map(String) : [];
    else if (champ.type === "euros") resultat[champ.nom] = typeof valeur === "number" ? (valeur / 100).toFixed(2).replace(".", ",") : "";
    else if (champ.type === "dateheure") resultat[champ.nom] = typeof valeur === "string" && valeur ? versSaisieLocale(new Date(valeur)) : "";
    else resultat[champ.nom] = valeur === null || valeur === undefined ? "" : String(valeur);
  }
  return resultat;
}

function versApi(champs: DefinitionChamp[], valeurs: Record<string, unknown>, creation: boolean): Record<string, unknown> {
  const corps: Record<string, unknown> = {};
  for (const champ of champs) {
    if (champ.lectureSeule || (champ.enCreationSeulement && !creation)) continue;
    const valeur = valeurs[champ.nom];
    if (champ.type === "booleen") corps[champ.nom] = Boolean(valeur);
    else if (champ.type === "multiple") corps[champ.nom] = (valeur as string[]).map((v) => (/^\d+$/.test(v) ? Number(v) : v));
    else if (champ.type === "nombre") corps[champ.nom] = valeur === "" ? null : Number(valeur);
    else if (champ.type === "euros") corps[champ.nom] = valeur === "" ? null : Math.round(Number(String(valeur).replace(/\s/g, "").replace(",", ".")) * 100);
    else if (champ.type === "selection") corps[champ.nom] = valeur === "" ? null : /^\d+$/.test(String(valeur)) ? Number(valeur) : valeur;
    else if (champ.type === "dateheure") corps[champ.nom] = valeur === "" ? null : new Date(String(valeur)).toISOString();
    else corps[champ.nom] = valeur === "" && (champ.type === "date" || champ.type === "heure") ? null : valeur;
  }
  return corps;
}

export function Formulaire({
  champs,
  valeurs,
  erreurs,
  onChange,
  creation,
}: {
  champs: DefinitionChamp[];
  valeurs: Record<string, unknown>;
  erreurs: ErreursChamps;
  onChange: (nom: string, valeur: unknown) => void;
  creation: boolean;
}) {
  return (
    <div className="formulaire__grille">
      {champs.map((champ) => {
        const commun = {
          libelle: champ.libelle,
          aide: champ.aide,
          erreur: erreurs[champ.nom],
          obligatoire: champ.obligatoire,
          disabled: champ.lectureSeule || (champ.enCreationSeulement && !creation),
          name: champ.nom,
        };
        switch (champ.type) {
          case "zone":
            return <ChampZone key={champ.nom} {...commun} value={String(valeurs[champ.nom] ?? "")} onChange={(e) => onChange(champ.nom, e.target.value)} />;
          case "booleen":
            return (
              <CaseACocher
                key={champ.nom}
                libelle={champ.libelle}
                aide={champ.aide}
                erreur={erreurs[champ.nom]}
                name={champ.nom}
                checked={Boolean(valeurs[champ.nom])}
                disabled={commun.disabled}
                onChange={(e) => onChange(champ.nom, e.target.checked)}
              />
            );
          case "selection":
            return (
              <ChampSelection
                key={champ.nom}
                {...commun}
                options={champ.options ?? []}
                value={String(valeurs[champ.nom] ?? "")}
                onChange={(e) => onChange(champ.nom, e.target.value)}
              />
            );
          case "multiple":
            return (
              <ChampSelection
                key={champ.nom}
                {...commun}
                multiple
                aide={champ.aide ?? "Maintenez Ctrl (ou Cmd) pour choisir plusieurs éléments."}
                options={champ.options ?? []}
                value={(valeurs[champ.nom] as string[]) ?? []}
                onChange={(e) => onChange(champ.nom, Array.from(e.target.selectedOptions, (o) => o.value))}
              />
            );
          default: {
            const types: Record<string, string> = { nombre: "number", date: "date", heure: "time", dateheure: "datetime-local", courriel: "email", euros: "text" };
            return (
              <ChampTexte
                key={champ.nom}
                {...commun}
                type={types[champ.type] ?? "text"}
                step={champ.type === "nombre" ? champ.pas : undefined}
                inputMode={champ.type === "euros" ? "decimal" : undefined}
                aide={champ.aide ?? (champ.type === "euros" ? "Montant en euros, par exemple 12,50." : undefined)}
                value={String(valeurs[champ.nom] ?? "")}
                onChange={(e) => onChange(champ.nom, e.target.value)}
              />
            );
          }
        }
      })}
    </div>
  );
}

export function EcranRessource<T extends Objet>(p: Proprietes<T>) {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const [page, setPage] = useState(1);
  // DSH-06 : un compteur du tableau de bord ouvre la liste déjà filtrée (paramètres de l'adresse).
  const [parametresUrl] = useSearchParams();
  const [filtres, setFiltres] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      [...(p.filtres ?? []).map((f) => f.nom), ...(p.pilules ? [p.pilules.nom] : [])].flatMap((nom) =>
        parametresUrl.get(nom) ? [[nom, parametresUrl.get(nom) ?? ""]] : [],
      ),
    ),
  );
  const [edition, setEdition] = useState<Partial<T> | null>(null);
  const [valeurs, setValeurs] = useState<Record<string, unknown>>({});
  const [erreurs, setErreurs] = useState<ErreursChamps>({});
  const [erreurGenerale, setErreurGenerale] = useState<string | null>(null);
  const [aSupprimer, setASupprimer] = useState<T | null>(null);
  const ecriture = p.actionEcriture ? peut(p.actionEcriture) : false;
  const creation = edition !== null && edition.id === undefined;

  const liste = useQuery({
    queryKey: [p.cleRequete, page, filtres],
    queryFn: async ({ signal }) => {
      const reponse = await requete<PageApi<T> | T[]>("GET", construireChemin(p.chemin, { page, ...filtres }), undefined, signal);
      // Les référentiels courts (types, modèles) ne sont pas paginés : on présente la même forme.
      return Array.isArray(reponse) ? { count: reponse.length, next: null, previous: null, results: reponse } : reponse;
    },
    placeholderData: keepPreviousData,
    enabled: peut(p.actionLecture),
  });

  const enregistrer = useMutation({
    mutationFn: (corps: Record<string, unknown>) =>
      creation ? requete<T>("POST", p.chemin, corps) : requete<T>("PATCH", `${p.chemin}/${edition?.id}`, corps),
    onSuccess: async () => {
      annoncer(creation ? `${p.libelleObjet} créé(e).` : `${p.libelleObjet} enregistré(e).`);
      setEdition(null);
      await client.invalidateQueries({ queryKey: [p.cleRequete] });
    },
    onError: (erreur) => {
      if (erreur instanceof ErreurApi) {
        setErreurs(erreur.champs);
        setErreurGenerale(erreur.message);
      } else setErreurGenerale("Une erreur inattendue est survenue.");
    },
  });

  const supprimer = useMutation({
    mutationFn: (objet: T) => requete<void>("DELETE", `${p.chemin}/${objet.id}`),
    onSuccess: async () => {
      annoncer(`${p.libelleObjet} supprimé(e).`);
      setASupprimer(null);
      await client.invalidateQueries({ queryKey: [p.cleRequete] });
    },
    onError: (erreur) => annoncer(erreur instanceof ErreurApi ? erreur.message : "Suppression impossible.", "erreur"),
  });

  if (!peut(p.actionLecture)) return <DroitsInsuffisants />;

  const ouvrir = (objet: Partial<T>) => {
    setEdition(objet);
    setValeurs(versFormulaire(p.champs ?? [], objet));
    setErreurs({});
    setErreurGenerale(null);
  };

  const soumettre = (evenement: FormEvent) => {
    evenement.preventDefault();
    setErreurs({});
    setErreurGenerale(null);
    enregistrer.mutate(versApi(p.champs ?? [], valeurs, creation));
  };

  const total = liste.data?.count ?? 0;
  const pages = Math.max(1, Math.ceil(total / 50));

  return (
    <Page
      titre={p.titre}
      description={p.description}
      actions={
        <>
          {p.actionsPage}
          {ecriture && p.champs ? (
            <Bouton onClick={() => ouvrir((p.valeursInitiales ?? {}) as Partial<T>)}>
              Ajouter {p.libelleObjet.toLowerCase()}
            </Bouton>
          ) : null}
        </>
      }
    >
      {p.pilules ? (
        <div role="group" aria-label={p.pilules.libelle} className="mb-4 flex flex-wrap gap-2">
          {p.pilules.options.map((o) => {
            const active = (filtres[p.pilules?.nom ?? ""] ?? "") === o.valeur;
            return (
              <button
                key={o.valeur || "toutes"}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  const nom = p.pilules?.nom ?? "";
                  setPage(1);
                  setFiltres({ ...filtres, [nom]: o.valeur });
                }}
                className={cn(
                  "inline-flex min-h-10 cursor-pointer items-center gap-2 rounded-full border border-filet bg-carte px-4 font-sans text-[0.9rem] font-medium text-encre transition-colors hover:border-vert hover:text-vert",
                  active && "border-encre bg-encre text-blanc hover:border-encre hover:text-blanc",
                )}
              >
                {o.libelle}
                {o.nombre ? " " : null}
                {o.nombre ? (
                  <span className={cn("min-w-5 rounded-full px-1.5 text-center text-xs leading-5 font-bold", active ? "bg-blanc text-encre" : "bg-vert text-blanc")}>{o.nombre}</span>
                ) : null}
              </button>
            );
          })}
        </div>
      ) : null}
      <div className="rounded-lg bg-carte shadow-carte">
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2 border-b border-filet px-4 pt-3 pb-1">
      {p.filtres?.length ? (
        <form className="filtres filtres--carte" role="search" aria-label={`Filtrer : ${p.titre}`} onSubmit={(e) => e.preventDefault()}>
          {p.filtres.map((f) =>
            f.options ? (
              <ChampSelection
                key={f.nom}
                libelle={f.libelle}
                options={f.options}
                videLibelle="Tous"
                value={filtres[f.nom] ?? ""}
                onChange={(e) => {
                  setPage(1);
                  setFiltres({ ...filtres, [f.nom]: e.target.value });
                }}
              />
            ) : (
              <ChampTexte
                key={f.nom}
                libelle={f.libelle}
                type={f.type === "date" ? "date" : "search"}
                value={filtres[f.nom] ?? ""}
                onChange={(e) => {
                  setPage(1);
                  setFiltres({ ...filtres, [f.nom]: e.target.value });
                }}
              />
            ),
          )}
        </form>
      ) : null}

      {liste.data ? (
        <p className="compteur compteur--pastille" aria-live="polite">
          {total} {total > 1 ? "éléments" : "élément"}
        </p>
      ) : null}
      </div>
      {liste.isPending ? (
        <Chargement />
      ) : liste.isError ? (
        <Erreur erreur={liste.error} reessayer={() => void liste.refetch()} />
      ) : (
        <>
          <Tableau
            nu
            legende={p.titre}
            colonnes={p.colonnes}
            lignes={liste.data.results}
            cleLigne={(l) => l.id}
            messageVide="Aucun élément ne correspond."
            actions={
              ecriture || p.actionsLigne
                ? (ligne) => (
                    <>
                      {p.actionsLigne?.(ligne)}
                      {ecriture && p.champs ? (
                        <Bouton variante="lien" onClick={() => ouvrir(ligne)} aria-label={`Modifier ${String(ligne.nom ?? ligne.libelle ?? ligne.id)}`}>
                          Modifier
                        </Bouton>
                      ) : null}
                      {ecriture && p.suppression ? (
                        <Bouton variante="lien" onClick={() => setASupprimer(ligne)} aria-label={`Supprimer ${String(ligne.nom ?? ligne.libelle ?? ligne.id)}`}>
                          Supprimer
                        </Bouton>
                      ) : null}
                    </>
                  )
                : undefined
            }
          />
          {pages > 1 ? (
            <nav className="pagination px-4 pb-4" aria-label="Pagination">
              <Bouton variante="secondaire" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                Page précédente
              </Bouton>
              <span>
                Page {page} sur {pages}
              </span>
              <Bouton variante="secondaire" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                Page suivante
              </Bouton>
            </nav>
          ) : null}
        </>
      )}
      </div>

      <Dialogue ouvert={edition !== null} titre={creation ? `Ajouter : ${p.libelleObjet.toLowerCase()}` : `Modifier : ${p.libelleObjet.toLowerCase()}`} onFermer={() => setEdition(null)} large>
        <form onSubmit={soumettre} noValidate>
          {erreurGenerale ? (
            <div className="alerte alerte--erreur" role="alert">
              <p>{erreurGenerale}</p>
              {Object.keys(erreurs).length ? (
                <ul>
                  {Object.entries(erreurs).map(([champ, messages]) => (
                    <li key={champ}>
                      {(p.champs ?? []).find((c) => c.nom === champ)?.libelle ?? champ} : {messages.join(" ")}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
          <Formulaire champs={p.champs ?? []} valeurs={valeurs} erreurs={erreurs} onChange={(nom, v) => setValeurs({ ...valeurs, [nom]: v })} creation={creation} />
          <div className="formulaire__actions">
            <Bouton variante="secondaire" onClick={() => setEdition(null)}>
              Annuler
            </Bouton>
            <Bouton type="submit" enCours={enregistrer.isPending}>
              Enregistrer
            </Bouton>
          </div>
        </form>
      </Dialogue>

      <Dialogue ouvert={aSupprimer !== null} titre="Confirmer la suppression" onFermer={() => setASupprimer(null)}>
        <p>Cette action est définitive et sera inscrite au journal d'audit.</p>
        <div className="formulaire__actions">
          <Bouton variante="secondaire" onClick={() => setASupprimer(null)}>
            Annuler
          </Bouton>
          <Bouton variante="danger" enCours={supprimer.isPending} onClick={() => aSupprimer && supprimer.mutate(aSupprimer)}>
            Supprimer
          </Bouton>
        </div>
      </Dialogue>
    </Page>
  );
}

/** Options d'une liste déroulante chargées depuis l'API (sites, rôles, familles…). */
export function useOptions(cle: string, chemin: string, libelle: (o: Record<string, unknown>) => string, actif = true): Option[] {
  const requeteOptions = useQuery({
    queryKey: ["options", cle],
    queryFn: () => requete<PageApi<Record<string, unknown>> | Record<string, unknown>[]>("GET", construireChemin(chemin, { taille: 500 })),
    staleTime: 5 * 60_000,
    enabled: actif,
  });
  const donnees = requeteOptions.data;
  const objets = Array.isArray(donnees) ? donnees : (donnees?.results ?? []);
  return objets.map((o) => ({ valeur: String(o.id), libelle: libelle(o) }));
}
