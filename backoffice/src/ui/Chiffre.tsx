/** Carte chiffre-clé (tableau de bord, planning du personnel) : pastille d'icône teintée, libellé, valeur, détail. */
import type { LucideIcon } from "lucide-react";

export function Chiffre({ icone: Icone, libelle, valeur, detail }: { icone: LucideIcon; libelle: string; valeur: string; detail?: string }) {
  return (
    <div className="rounded-lg bg-carte p-4 shadow-carte">
      <span aria-hidden="true" className="inline-flex size-9 items-center justify-center rounded-md bg-vert-pale text-vert">
        <Icone size={18} strokeWidth={1.8} />
      </span>
      <p className="mt-3 mb-0 text-[0.85rem] text-encre-douce">{libelle}</p>
      <p className="m-0 text-[1.75rem] leading-tight font-semibold text-encre">{valeur}</p>
      {detail ? <p className="m-0 text-[0.8rem] text-encre-douce">{detail}</p> : null}
    </div>
  );
}
