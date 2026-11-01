import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "./cn";

type Variante = "principal" | "secondaire" | "danger" | "lien";

interface Proprietes extends ButtonHTMLAttributes<HTMLButtonElement> {
  variante?: Variante;
  enCours?: boolean;
  icone?: ReactNode;
}

/** Classes des boutons de la charte (DESIGN.md) : angles droits, 44 px de haut, un seul bouton principal par zone.
 * Exportées pour les liens qui ont l'apparence d'un bouton. */
export const CLASSES_BOUTON: Record<Variante, string> = {
  principal: "border-2 border-vert bg-vert text-blanc hover:border-vert-fonce hover:bg-vert-fonce",
  secondaire: "border-2 border-vert bg-carte text-vert hover:bg-info-fond hover:text-vert-fonce",
  danger: "border-2 border-danger bg-danger text-blanc hover:underline",
  lien: "min-h-0 border-0 bg-transparent px-1.5 py-1 font-medium text-vert underline underline-offset-2 hover:bg-info-fond hover:text-vert-fonce",
};
export const BASE_BOUTON =
  "inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 px-5 py-2 font-sans text-base font-semibold no-underline disabled:cursor-not-allowed disabled:opacity-60";

/** Bouton accessible : type explicite, état « en cours » annoncé, jamais désactivé sans raison visible. */
export function Bouton({ variante = "principal", enCours = false, icone, children, type = "button", disabled, className, ...autres }: Proprietes) {
  return (
    <button type={type} className={cn(BASE_BOUTON, CLASSES_BOUTON[variante], className)} disabled={disabled || enCours} aria-busy={enCours || undefined} {...autres}>
      {icone ? (
        <span className="inline-flex" aria-hidden="true">
          {icone}
        </span>
      ) : null}
      <span>{enCours ? "Traitement en cours…" : children}</span>
    </button>
  );
}
