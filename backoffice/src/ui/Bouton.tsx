import { createElement, type ButtonHTMLAttributes, type ReactNode } from "react";
import { cn } from "./cn";
import { iconeAction } from "./iconeAction";

type Variante = "principal" | "secondaire" | "danger" | "lien";

interface Proprietes extends ButtonHTMLAttributes<HTMLButtonElement> {
  variante?: Variante;
  enCours?: boolean;
  /** Icône imposée ; par défaut, déduite du verbe du libellé (iconeAction) ; `null` : aucune. */
  icone?: ReactNode;
}

/** Classes des boutons (DESIGN.md, ergonomie Mariloo aux couleurs de la Ville) : pilules de 44 px, principal vert
 * plein, secondaire blanc à contour fin, un seul bouton principal par zone. Exportées pour les liens-boutons. */
export const CLASSES_BOUTON: Record<Variante, string> = {
  principal: "border border-vert bg-vert text-blanc hover:border-vert-fonce hover:bg-vert-fonce",
  secondaire: "border border-contour-champ/40 bg-carte text-encre hover:border-vert hover:bg-vert-pale hover:text-vert-fonce",
  danger: "border border-danger bg-danger text-blanc hover:underline",
  lien: "min-h-0 rounded-md border-0 bg-transparent px-2 py-1 font-medium text-vert underline-offset-2 hover:bg-vert-pale hover:underline",
};
export const BASE_BOUTON =
  "inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 rounded-full px-5 py-2 font-sans text-[0.95rem] font-semibold no-underline transition-colors disabled:cursor-not-allowed disabled:opacity-60";

/** Texte d'un libellé fait de chaînes (les libellés composés d'éléments n'ont pas d'icône déduite). */
export function texteDe(contenu: ReactNode): string | undefined {
  if (typeof contenu === "string" || typeof contenu === "number") return String(contenu);
  if (Array.isArray(contenu) && contenu.every((c) => typeof c === "string" || typeof c === "number" || c === null || c === false)) {
    return contenu.filter((c) => c !== null && c !== false).join("");
  }
  return undefined;
}

/** Bouton accessible : type explicite, état « en cours » annoncé, jamais désactivé sans raison visible. Icône au trait
 * devant le libellé, comme dans CityResa (décorative : le libellé reste le nom du bouton). */
export function Bouton({ variante = "principal", enCours = false, icone, children, type = "button", disabled, className, ...autres }: Proprietes) {
  const texte = texteDe(children);
  const Deduite = icone === undefined && texte ? iconeAction(texte) : undefined;
  // Icônes Lucide : composants fixes du module, choisis d'après le libellé (pas créés au rendu).
  const pictogramme = icone !== undefined ? icone : Deduite ? createElement(Deduite, { size: variante === "lien" ? 16 : 18, strokeWidth: 1.8 }) : null;
  return (
    <button type={type} className={cn(BASE_BOUTON, CLASSES_BOUTON[variante], className)} disabled={disabled || enCours} aria-busy={enCours || undefined} {...autres}>
      {pictogramme ? (
        <span className="inline-flex shrink-0" aria-hidden="true">
          {pictogramme}
        </span>
      ) : null}
      <span>{enCours ? "Traitement en cours…" : children}</span>
    </button>
  );
}
