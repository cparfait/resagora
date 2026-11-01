/** Fusion de classes Tailwind (clsx + tailwind-merge) instruite des jetons de la charte (charte/charte.css) : sans
 * cela, « text-h1 » (taille) et « text-encre » (couleur) seraient vues comme deux couleurs et l'une effacerait l'autre. */
import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

const fusionner = extendTailwindMerge({
  extend: {
    theme: {
      text: ["h1", "h2", "h3", "surtitre", "chiffre", "corps", "petit"],
      color: [
        "blanc",
        "fond",
        "carte",
        "encre",
        "encre-douce",
        "vert",
        "vert-fonce",
        "vert-profond",
        "vert-clair",
        "anis",
        "anis-fonce",
        "anis-clair",
        "orange",
        "brun",
        "filet",
        "contour-champ",
        "succes",
        "succes-fond",
        "attention",
        "attention-fond",
        "danger",
        "danger-fond",
        "info",
        "info-fond",
      ],
    },
  },
});

export function cn(...classes: ClassValue[]): string {
  return fusionner(clsx(classes));
}
