/**
 * Champs de formulaire accessibles (RGAA 11) : étiquette visible, mention « obligatoire » en texte,
 * format attendu, aide et erreur reliées au champ (aria-describedby), autocomplete renseigné.
 */
import { TriangleAlert } from "lucide-react";
import { cn } from "./cn";
import { classesAlerte } from "./Elements";
import { useId, type InputHTMLAttributes, type ReactNode, type Ref, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

interface Commun {
  libelle: string;
  obligatoire?: boolean;
  aide?: ReactNode;
  erreur?: string;
  nom?: string;
}

function decrits(id: string, aide?: ReactNode, erreur?: string): string | undefined {
  return [aide ? `${id}-aide` : "", erreur ? `${id}-erreur` : ""].filter(Boolean).join(" ") || undefined;
}

/** La classe « champ » reste un repère pour les mises en page (formulaire__ligne). Erreur au-dessus du champ
 * (charte), champ de 48 px à angles droits, contour 1 px (2 px rouge en erreur). */
const CONTENEUR = "champ mb-4 flex min-w-0 max-w-full flex-col gap-1";
const SAISIE = "min-h-12 w-full max-w-full border border-contour-champ bg-carte px-3 py-2 font-sans text-base text-encre";
const SAISIE_ERREUR = "border-2 border-danger";

function Libelle({ id, libelle, obligatoire }: { id: string; libelle: string; obligatoire?: boolean }) {
  return (
    <label htmlFor={id} className="font-semibold">
      {libelle}
      {obligatoire ? <span className="font-normal"> (obligatoire)</span> : null}
    </label>
  );
}

function Pied({ id, aide, erreur }: { id: string; aide?: ReactNode; erreur?: string }) {
  return (
    <>
      {aide ? (
        <p id={`${id}-aide`} className="m-0 text-petit text-encre-douce">
          {aide}
        </p>
      ) : null}
      {erreur ? (
        <p id={`${id}-erreur`} className="m-0 flex items-start gap-1.5 font-bold text-danger">
          <TriangleAlert aria-hidden="true" size={18} strokeWidth={1.8} className="mt-0.5 shrink-0" />
          <span>{erreur}</span>
        </p>
      ) : null}
    </>
  );
}

export function Champ({ libelle, obligatoire, aide, erreur, nom, id, className, ...autres }: Commun & InputHTMLAttributes<HTMLInputElement> & { ref?: Ref<HTMLInputElement> }) {
  const genere = useId();
  const identifiant = id ?? (nom ? `champ-${nom}` : genere);
  return (
    <div className={CONTENEUR}>
      <Libelle id={identifiant} libelle={libelle} obligatoire={obligatoire} />
      <Pied id={identifiant} aide={aide} />
      <Pied id={identifiant} erreur={erreur} />
      <input id={identifiant} name={nom} required={obligatoire} aria-invalid={erreur ? true : undefined} aria-describedby={decrits(identifiant, aide, erreur)} className={cn(SAISIE, erreur && SAISIE_ERREUR, className)} {...autres} />
    </div>
  );
}

export function Zone({ libelle, obligatoire, aide, erreur, nom, id, className, ...autres }: Commun & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const genere = useId();
  const identifiant = id ?? (nom ? `champ-${nom}` : genere);
  return (
    <div className={CONTENEUR}>
      <Libelle id={identifiant} libelle={libelle} obligatoire={obligatoire} />
      <Pied id={identifiant} aide={aide} />
      <Pied id={identifiant} erreur={erreur} />
      <textarea id={identifiant} name={nom} required={obligatoire} rows={5} aria-invalid={erreur ? true : undefined} aria-describedby={decrits(identifiant, aide, erreur)} className={cn(SAISIE, erreur && SAISIE_ERREUR, className)} {...autres} />
    </div>
  );
}

export interface Option {
  valeur: string;
  libelle: string;
}

export function Liste({ libelle, obligatoire, aide, erreur, nom, id, className, options, vide = "— Choisir —", ...autres }: Commun & SelectHTMLAttributes<HTMLSelectElement> & { options: Option[]; vide?: string | null }) {
  const genere = useId();
  const identifiant = id ?? (nom ? `champ-${nom}` : genere);
  return (
    <div className={CONTENEUR}>
      <Libelle id={identifiant} libelle={libelle} obligatoire={obligatoire} />
      <Pied id={identifiant} aide={aide} />
      <Pied id={identifiant} erreur={erreur} />
      <select id={identifiant} name={nom} required={obligatoire} aria-invalid={erreur ? true : undefined} aria-describedby={decrits(identifiant, aide, erreur)} className={cn(SAISIE, erreur && SAISIE_ERREUR, className)} {...autres}>
        {vide !== null ? <option value="">{vide}</option> : null}
        {options.map((o) => (
          <option key={o.valeur} value={o.valeur}>
            {o.libelle}
          </option>
        ))}
      </select>
    </div>
  );
}

export function Case({ libelle, aide, erreur, nom, id, obligatoire, ...reste }: Commun & InputHTMLAttributes<HTMLInputElement>) {
  const genere = useId();
  const identifiant = id ?? (nom ? `champ-${nom}` : genere);
  return (
    <div className="champ mb-4 flex flex-row flex-wrap items-start gap-x-2.5 gap-y-1">
      <input className="mt-0.5 size-5 shrink-0 cursor-pointer accent-vert" type="checkbox" id={identifiant} name={nom} required={obligatoire} aria-invalid={erreur ? true : undefined} aria-describedby={decrits(identifiant, aide, erreur)} {...reste} />
      <label htmlFor={identifiant} className="cursor-pointer">
        {libelle}
        {obligatoire ? <span className="font-normal"> (obligatoire)</span> : null}
      </label>
      <div className="basis-full">
        <Pied id={identifiant} aide={aide} erreur={erreur} />
      </div>
    </div>
  );
}

export function Choix({ legende, nom, options, valeur, onChange, obligatoire, erreur }: { legende: string; nom: string; options: Option[]; valeur: string; onChange: (v: string) => void; obligatoire?: boolean; erreur?: string }) {
  const id = `champ-${nom.replaceAll(".", "-")}`;
  return (
    <fieldset id={id} tabIndex={-1} className={cn("champ mb-4 border border-contour-champ p-4", erreur && "border-2 border-danger")} aria-describedby={erreur ? `${id}-erreur` : undefined}>
      <legend className="px-1 font-semibold">
        {legende}
        {obligatoire ? <span className="font-normal"> (obligatoire)</span> : null}
      </legend>
      {options.map((o) => (
        <div key={o.valeur} className="flex min-h-11 items-center gap-2.5">
          <input className="size-5 shrink-0 cursor-pointer accent-vert" type="radio" id={`${id}-${o.valeur}`} name={nom} value={o.valeur} checked={valeur === o.valeur} required={obligatoire} onChange={() => onChange(o.valeur)} />
          <label htmlFor={`${id}-${o.valeur}`} className="cursor-pointer">
            {o.libelle}
          </label>
        </div>
      ))}
      <Pied id={id} erreur={erreur} />
    </fieldset>
  );
}

/** Erreurs listées en haut du formulaire, avec un lien vers chaque champ ; le focus y est placé. */
export function ResumeErreurs({ message, champs, libelles }: { message: string | null; champs: Record<string, string[]>; libelles: Record<string, string> }) {
  const entrees = Object.entries(champs).filter(([, valeurs]) => valeurs.length);
  if (!message && !entrees.length) return null;
  return (
    <div className={classesAlerte("erreur")} role="alert" tabIndex={-1} ref={(e) => e?.focus()}>
      <h2 className="m-0 mb-1 text-base font-bold text-encre">{message ?? "Le formulaire contient des erreurs."}</h2>
      {entrees.length ? (
        <ul>
          {entrees.map(([champ, valeurs]) => (
            <li key={champ}>
              <a href={`#champ-${champ.replaceAll(".", "-")}`}>
                {libelles[champ] ?? champ} : {valeurs.join(" ")}
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
