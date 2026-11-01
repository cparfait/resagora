/** Statut affiché par libellé + couleur + icône, jamais par la couleur seule (pastille de la charte, DESIGN.md). */
import { Check, Circle, Info, TriangleAlert, X, type LucideIcon } from "lucide-react";
import { cn } from "./cn";

export type Ton = "neutre" | "info" | "succes" | "attention" | "danger";

const TONS: Record<Ton, { icone: LucideIcon; classes: string }> = {
  neutre: { icone: Circle, classes: "bg-fond text-encre-douce" },
  info: { icone: Info, classes: "bg-info-fond text-info" },
  succes: { icone: Check, classes: "bg-succes-fond text-succes" },
  attention: { icone: TriangleAlert, classes: "bg-attention-fond text-attention" },
  danger: { icone: X, classes: "bg-danger-fond text-danger" },
};

export function Badge({ libelle, ton = "neutre" }: { libelle: string; ton?: Ton }) {
  const { icone: Icone, classes } = TONS[ton];
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[0.8rem] font-semibold whitespace-nowrap", classes)}>
      <Icone aria-hidden="true" size={14} strokeWidth={1.8} />
      {libelle}
    </span>
  );
}
