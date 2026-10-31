/**
 * Champs de formulaire accessibles (RGAA 11) : étiquette visible, mention « obligatoire » en texte,
 * format attendu, aide et erreur reliées au champ (aria-describedby), autocomplete renseigné.
 */
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

function Libelle({ id, libelle, obligatoire }: { id: string; libelle: string; obligatoire?: boolean }) {
  return (
    <label htmlFor={id} className="champ__libelle">
      {libelle}
      {obligatoire ? <span className="champ__obligatoire"> (obligatoire)</span> : null}
    </label>
  );
}

function Pied({ id, aide, erreur }: { id: string; aide?: ReactNode; erreur?: string }) {
  return (
    <>
      {aide ? (
        <p id={`${id}-aide`} className="champ__aide">
          {aide}
        </p>
      ) : null}
      {erreur ? (
        <p id={`${id}-erreur`} className="champ__erreur">
          <span aria-hidden="true">✕ </span>
          {erreur}
        </p>
      ) : null}
    </>
  );
}

export function Champ({ libelle, obligatoire, aide, erreur, nom, id, ...autres }: Commun & InputHTMLAttributes<HTMLInputElement> & { ref?: Ref<HTMLInputElement> }) {
  const genere = useId();
  const identifiant = id ?? (nom ? `champ-${nom}` : genere);
  return (
    <div className={`champ${erreur ? " champ--erreur" : ""}`}>
      <Libelle id={identifiant} libelle={libelle} obligatoire={obligatoire} />
      <Pied id={identifiant} aide={aide} />
      <input id={identifiant} name={nom} required={obligatoire} aria-invalid={erreur ? true : undefined} aria-describedby={decrits(identifiant, aide, erreur)} {...autres} />
      <Pied id={identifiant} erreur={erreur} />
    </div>
  );
}

export function Zone({ libelle, obligatoire, aide, erreur, nom, id, ...autres }: Commun & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const genere = useId();
  const identifiant = id ?? (nom ? `champ-${nom}` : genere);
  return (
    <div className={`champ${erreur ? " champ--erreur" : ""}`}>
      <Libelle id={identifiant} libelle={libelle} obligatoire={obligatoire} />
      <Pied id={identifiant} aide={aide} />
      <textarea id={identifiant} name={nom} required={obligatoire} rows={5} aria-invalid={erreur ? true : undefined} aria-describedby={decrits(identifiant, aide, erreur)} {...autres} />
      <Pied id={identifiant} erreur={erreur} />
    </div>
  );
}

export interface Option {
  valeur: string;
  libelle: string;
}

export function Liste({ libelle, obligatoire, aide, erreur, nom, id, options, vide = "— Choisir —", ...autres }: Commun & SelectHTMLAttributes<HTMLSelectElement> & { options: Option[]; vide?: string | null }) {
  const genere = useId();
  const identifiant = id ?? (nom ? `champ-${nom}` : genere);
  return (
    <div className={`champ${erreur ? " champ--erreur" : ""}`}>
      <Libelle id={identifiant} libelle={libelle} obligatoire={obligatoire} />
      <Pied id={identifiant} aide={aide} />
      <select id={identifiant} name={nom} required={obligatoire} aria-invalid={erreur ? true : undefined} aria-describedby={decrits(identifiant, aide, erreur)} {...autres}>
        {vide !== null ? <option value="">{vide}</option> : null}
        {options.map((o) => (
          <option key={o.valeur} value={o.valeur}>
            {o.libelle}
          </option>
        ))}
      </select>
      <Pied id={identifiant} erreur={erreur} />
    </div>
  );
}

export function Case({ libelle, aide, erreur, nom, id, obligatoire, ...reste }: Commun & InputHTMLAttributes<HTMLInputElement>) {
  const genere = useId();
  const identifiant = id ?? (nom ? `champ-${nom}` : genere);
  return (
    <div className={`champ champ--case${erreur ? " champ--erreur" : ""}`}>
      <input type="checkbox" id={identifiant} name={nom} required={obligatoire} aria-invalid={erreur ? true : undefined} aria-describedby={decrits(identifiant, aide, erreur)} {...reste} />
      <label htmlFor={identifiant}>
        {libelle}
        {obligatoire ? <span className="champ__obligatoire"> (obligatoire)</span> : null}
      </label>
      <Pied id={identifiant} aide={aide} erreur={erreur} />
    </div>
  );
}

export function Choix({ legende, nom, options, valeur, onChange, obligatoire, erreur }: { legende: string; nom: string; options: Option[]; valeur: string; onChange: (v: string) => void; obligatoire?: boolean; erreur?: string }) {
  const id = `champ-${nom.replaceAll(".", "-")}`;
  return (
    <fieldset id={id} tabIndex={-1} className={`champ champ--groupe${erreur ? " champ--erreur" : ""}`} aria-describedby={erreur ? `${id}-erreur` : undefined}>
      <legend>
        {legende}
        {obligatoire ? <span className="champ__obligatoire"> (obligatoire)</span> : null}
      </legend>
      {options.map((o) => (
        <div key={o.valeur} className="champ--case">
          <input type="radio" id={`${id}-${o.valeur}`} name={nom} value={o.valeur} checked={valeur === o.valeur} required={obligatoire} onChange={() => onChange(o.valeur)} />
          <label htmlFor={`${id}-${o.valeur}`}>{o.libelle}</label>
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
    <div className="alerte alerte--erreur" role="alert" tabIndex={-1} ref={(e) => e?.focus()}>
      <h2 className="alerte__titre">{message ?? "Le formulaire contient des erreurs."}</h2>
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
