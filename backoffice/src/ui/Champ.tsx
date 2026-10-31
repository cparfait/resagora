/**
 * Champ de formulaire : libellé visible associé, aide et erreur liées par aria-describedby,
 * caractère obligatoire indiqué en texte.
 */
import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";

interface Commun {
  libelle: string;
  aide?: ReactNode;
  erreur?: string | string[] | undefined;
  obligatoire?: boolean;
}

function useIdentifiants(erreur: Commun["erreur"], aide: Commun["aide"]) {
  const base = useId();
  const idAide = aide ? `${base}-aide` : undefined;
  const idErreur = erreur && (Array.isArray(erreur) ? erreur.length : true) ? `${base}-erreur` : undefined;
  return { id: base, idAide, idErreur, decrit: [idAide, idErreur].filter(Boolean).join(" ") || undefined };
}

function Libelle({ id, libelle, obligatoire }: { id: string; libelle: string; obligatoire?: boolean | undefined }) {
  return (
    <label htmlFor={id} className="champ__libelle">
      {libelle}
      {obligatoire ? <span className="champ__obligatoire"> (obligatoire)</span> : null}
    </label>
  );
}

function Pied({ idAide, idErreur, aide, erreur }: { idAide?: string | undefined; idErreur?: string | undefined; aide?: ReactNode; erreur?: Commun["erreur"] }) {
  return (
    <>
      {idAide ? (
        <p id={idAide} className="champ__aide">
          {aide}
        </p>
      ) : null}
      {idErreur ? (
        <p id={idErreur} className="champ__erreur">
          <span aria-hidden="true">⚠ </span>
          {Array.isArray(erreur) ? erreur.join(" ") : erreur}
        </p>
      ) : null}
    </>
  );
}

export function ChampTexte({ libelle, aide, erreur, obligatoire, ...autres }: Commun & InputHTMLAttributes<HTMLInputElement>) {
  const { id, idAide, idErreur, decrit } = useIdentifiants(erreur, aide);
  return (
    <div className={`champ${idErreur ? " champ--erreur" : ""}`}>
      <Libelle id={id} libelle={libelle} obligatoire={obligatoire} />
      <input id={id} required={obligatoire} aria-invalid={idErreur ? true : undefined} aria-describedby={decrit} {...autres} />
      <Pied idAide={idAide} idErreur={idErreur} aide={aide} erreur={erreur} />
    </div>
  );
}

export function ChampZone({ libelle, aide, erreur, obligatoire, ...autres }: Commun & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const { id, idAide, idErreur, decrit } = useIdentifiants(erreur, aide);
  return (
    <div className={`champ${idErreur ? " champ--erreur" : ""}`}>
      <Libelle id={id} libelle={libelle} obligatoire={obligatoire} />
      <textarea id={id} required={obligatoire} aria-invalid={idErreur ? true : undefined} aria-describedby={decrit} rows={4} {...autres} />
      <Pied idAide={idAide} idErreur={idErreur} aide={aide} erreur={erreur} />
    </div>
  );
}

export interface Option {
  valeur: string;
  libelle: string;
}

export function ChampSelection({
  libelle,
  aide,
  erreur,
  obligatoire,
  options,
  videLibelle,
  ...autres
}: Commun & SelectHTMLAttributes<HTMLSelectElement> & { options: Option[]; videLibelle?: string }) {
  const { id, idAide, idErreur, decrit } = useIdentifiants(erreur, aide);
  return (
    <div className={`champ${idErreur ? " champ--erreur" : ""}`}>
      <Libelle id={id} libelle={libelle} obligatoire={obligatoire} />
      <select id={id} required={obligatoire} aria-invalid={idErreur ? true : undefined} aria-describedby={decrit} {...autres}>
        {autres.multiple ? null : <option value="">{videLibelle ?? "— Choisir —"}</option>}
        {options.map((o) => (
          <option key={o.valeur} value={o.valeur}>
            {o.libelle}
          </option>
        ))}
      </select>
      <Pied idAide={idAide} idErreur={idErreur} aide={aide} erreur={erreur} />
    </div>
  );
}

export function CaseACocher({ libelle, aide, erreur, ...autres }: Omit<Commun, "obligatoire"> & InputHTMLAttributes<HTMLInputElement>) {
  const { id, idAide, idErreur, decrit } = useIdentifiants(erreur, aide);
  return (
    <div className="champ champ--case">
      <input id={id} type="checkbox" aria-describedby={decrit} {...autres} />
      <label htmlFor={id}>{libelle}</label>
      <Pied idAide={idAide} idErreur={idErreur} aide={aide} erreur={erreur} />
    </div>
  );
}
