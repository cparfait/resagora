/**
 * Champ de formulaire : libellé visible associé, aide et erreur liées par aria-describedby,
 * caractère obligatoire indiqué en texte. Charte (DESIGN.md) : libellé au-dessus, aide sous le libellé, erreur
 * (icône + message) au-dessus du champ, champ de 44 px à angles droits, contour 1 px (2 px rouge en erreur).
 */
import { TriangleAlert } from "lucide-react";
import { useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { cn } from "./cn";

interface Commun {
  libelle: string;
  aide?: ReactNode;
  erreur?: string | string[] | undefined;
  obligatoire?: boolean;
}

/** La classe « champ » reste un repère pour les mises en page de formulaires (filtres, lignes de formulaire). */
const CONTENEUR = "champ mb-4 flex flex-col gap-1";
const SAISIE = "min-h-11 w-full border border-contour-champ bg-carte px-3 py-2 font-sans text-base text-encre";
const SAISIE_ERREUR = "border-2 border-danger";

function useIdentifiants(erreur: Commun["erreur"], aide: Commun["aide"]) {
  const base = useId();
  const idAide = aide ? `${base}-aide` : undefined;
  const idErreur = erreur && (Array.isArray(erreur) ? erreur.length : true) ? `${base}-erreur` : undefined;
  return { id: base, idAide, idErreur, decrit: [idAide, idErreur].filter(Boolean).join(" ") || undefined };
}

function Libelle({ id, libelle, obligatoire }: { id: string; libelle: string; obligatoire?: boolean | undefined }) {
  return (
    <label htmlFor={id} className="font-semibold">
      {libelle}
      {obligatoire ? <span className="font-normal text-encre-douce"> (obligatoire)</span> : null}
    </label>
  );
}

function Aide({ idAide, aide }: { idAide?: string | undefined; aide?: ReactNode }) {
  return idAide ? (
    <p id={idAide} className="m-0 text-petit text-encre-douce">
      {aide}
    </p>
  ) : null;
}

function MessageErreur({ idErreur, erreur }: { idErreur?: string | undefined; erreur?: Commun["erreur"] }) {
  return idErreur ? (
    <p id={idErreur} className="m-0 flex items-start gap-1.5 font-semibold text-danger">
      <TriangleAlert aria-hidden="true" size={18} strokeWidth={1.8} className="mt-0.5 shrink-0" />
      <span>{Array.isArray(erreur) ? erreur.join(" ") : erreur}</span>
    </p>
  ) : null;
}

export function ChampTexte({ libelle, aide, erreur, obligatoire, className, ...autres }: Commun & InputHTMLAttributes<HTMLInputElement>) {
  const { id, idAide, idErreur, decrit } = useIdentifiants(erreur, aide);
  return (
    <div className={CONTENEUR}>
      <Libelle id={id} libelle={libelle} obligatoire={obligatoire} />
      <Aide idAide={idAide} aide={aide} />
      <MessageErreur idErreur={idErreur} erreur={erreur} />
      <input
        id={id}
        required={obligatoire}
        aria-invalid={idErreur ? true : undefined}
        aria-describedby={decrit}
        className={cn(SAISIE, idErreur && SAISIE_ERREUR, className)}
        {...autres}
      />
    </div>
  );
}

export function ChampZone({ libelle, aide, erreur, obligatoire, className, ...autres }: Commun & TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const { id, idAide, idErreur, decrit } = useIdentifiants(erreur, aide);
  return (
    <div className={CONTENEUR}>
      <Libelle id={id} libelle={libelle} obligatoire={obligatoire} />
      <Aide idAide={idAide} aide={aide} />
      <MessageErreur idErreur={idErreur} erreur={erreur} />
      <textarea
        id={id}
        required={obligatoire}
        aria-invalid={idErreur ? true : undefined}
        aria-describedby={decrit}
        rows={4}
        className={cn(SAISIE, idErreur && SAISIE_ERREUR, className)}
        {...autres}
      />
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
  className,
  ...autres
}: Commun & SelectHTMLAttributes<HTMLSelectElement> & { options: Option[]; videLibelle?: string }) {
  const { id, idAide, idErreur, decrit } = useIdentifiants(erreur, aide);
  return (
    <div className={CONTENEUR}>
      <Libelle id={id} libelle={libelle} obligatoire={obligatoire} />
      <Aide idAide={idAide} aide={aide} />
      <MessageErreur idErreur={idErreur} erreur={erreur} />
      <select
        id={id}
        required={obligatoire}
        aria-invalid={idErreur ? true : undefined}
        aria-describedby={decrit}
        className={cn(SAISIE, autres.multiple && "min-h-32", idErreur && SAISIE_ERREUR, className)}
        {...autres}
      >
        {autres.multiple ? null : <option value="">{videLibelle ?? "— Choisir —"}</option>}
        {options.map((o) => (
          <option key={o.valeur} value={o.valeur}>
            {o.libelle}
          </option>
        ))}
      </select>
    </div>
  );
}

export function CaseACocher({ libelle, aide, erreur, className, ...autres }: Omit<Commun, "obligatoire"> & InputHTMLAttributes<HTMLInputElement>) {
  const { id, idAide, idErreur, decrit } = useIdentifiants(erreur, aide);
  return (
    <div className="champ mb-4 flex min-h-11 flex-row flex-wrap items-center gap-x-2.5 gap-y-1">
      <input id={id} type="checkbox" aria-describedby={decrit} className={cn("size-5 shrink-0 cursor-pointer accent-vert", className)} {...autres} />
      <label htmlFor={id} className="cursor-pointer">
        {libelle}
      </label>
      <div className="basis-full">
        <Aide idAide={idAide} aide={aide} />
        <MessageErreur idErreur={idErreur} erreur={erreur} />
      </div>
    </div>
  );
}
