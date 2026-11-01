import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "./cn";

type Variante = "principal" | "secondaire" | "danger" | "lien";

interface Proprietes extends ButtonHTMLAttributes<HTMLButtonElement> {
  variante?: Variante;
  enCours?: boolean;
  children: ReactNode;
}

const VARIANTES: Record<Variante, string> = {
  principal: "border-2 border-vert bg-vert text-blanc hover:border-vert-fonce hover:bg-vert-fonce hover:text-blanc",
  secondaire: "border-2 border-vert bg-carte text-vert hover:bg-info-fond hover:text-vert-fonce",
  danger: "border-2 border-danger bg-danger text-blanc hover:text-blanc hover:underline",
  lien: "min-h-0 border-0 bg-transparent p-0 font-normal text-vert underline underline-offset-[0.15em] hover:decoration-2 sm:min-h-0",
};

/** Classes d'un bouton de la charte (DESIGN.md) : angles droits, 48 px de haut sur mobile et 44 px au-delà, texte
 * 600. Servent aussi aux liens qui ont l'apparence d'un bouton. */
export function classesBouton(variante: Variante = "principal", ...autres: (string | false | undefined)[]): string {
  return cn(
    "inline-flex min-h-12 cursor-pointer items-center justify-center gap-1 px-5 py-2 font-sans text-base font-semibold no-underline disabled:cursor-not-allowed disabled:opacity-70 sm:min-h-11",
    VARIANTES[variante],
    ...autres,
  );
}

/** Bouton : libellé explicite, état « en cours » annoncé et bouton désactivé pendant l'envoi. */
export function Bouton({ variante = "principal", enCours = false, children, type = "button", disabled, className, ...autres }: Proprietes) {
  return (
    <button type={type} className={classesBouton(variante, className)} disabled={disabled || enCours} aria-busy={enCours || undefined} {...autres}>
      {children}
      {enCours ? <span className="sr-only"> (en cours)</span> : null}
    </button>
  );
}
