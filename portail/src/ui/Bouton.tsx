import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variante = "principal" | "secondaire" | "danger" | "lien";

interface Proprietes extends ButtonHTMLAttributes<HTMLButtonElement> {
  variante?: Variante;
  enCours?: boolean;
  children: ReactNode;
}

/** Bouton : libellé explicite, état « en cours » annoncé et bouton désactivé pendant l'envoi. */
export function Bouton({ variante = "principal", enCours = false, children, type = "button", disabled, className, ...autres }: Proprietes) {
  return (
    <button
      type={type}
      className={["bouton", `bouton--${variante}`, className].filter(Boolean).join(" ")}
      disabled={disabled || enCours}
      aria-busy={enCours || undefined}
      {...autres}
    >
      {children}
      {enCours ? <span className="visuellement-masque"> (en cours)</span> : null}
    </button>
  );
}
