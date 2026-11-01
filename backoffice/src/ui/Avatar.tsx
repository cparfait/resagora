/** Vignette à initiales (ergonomie Mariloo) : décorative, le nom est toujours écrit à côté. */
import { cn } from "./cn";

/** « Association Sportive Châtillonnaise » → « AS » ; mots en minuscules (de, du…) ignorés. */
export function initiales(nom: string): string {
  return (
    nom
      .split(/[\s-]+/)
      .filter((mot) => /^[A-ZÀ-Ý0-9]/u.test(mot))
      .slice(0, 2)
      .map((mot) => mot[0])
      .join("") || "?"
  );
}

export function Avatar({ nom, className }: { nom: string; className?: string }) {
  return (
    <span aria-hidden="true" className={cn("inline-flex size-9 shrink-0 items-center justify-center rounded-full bg-vert-pale text-[0.75rem] font-bold text-vert", className)}>
      {initiales(nom)}
    </span>
  );
}
