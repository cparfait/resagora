import type { ButtonHTMLAttributes, ReactNode } from "react";

type Variante = "principal" | "secondaire" | "danger" | "lien";

interface Proprietes extends ButtonHTMLAttributes<HTMLButtonElement> {
  variante?: Variante;
  enCours?: boolean;
  icone?: ReactNode;
}

/** Bouton accessible : type explicite, état « en cours » annoncé, jamais désactivé sans raison visible. */
export function Bouton({ variante = "principal", enCours = false, icone, children, type = "button", disabled, className, ...autres }: Proprietes) {
  return (
    <button
      type={type}
      className={["bouton", `bouton--${variante}`, className].filter(Boolean).join(" ")}
      disabled={disabled || enCours}
      aria-busy={enCours || undefined}
      {...autres}
    >
      {icone ? (
        <span className="bouton__icone" aria-hidden="true">
          {icone}
        </span>
      ) : null}
      <span>{enCours ? "Traitement en cours…" : children}</span>
    </button>
  );
}
