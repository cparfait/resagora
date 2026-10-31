/** Statut affiché par libellé + couleur + icône, jamais par la couleur seule. */
export type Ton = "neutre" | "info" | "succes" | "attention" | "danger";

const ICONES: Record<Ton, string> = { neutre: "•", info: "ℹ", succes: "✓", attention: "!", danger: "✕" };

export function Badge({ libelle, ton = "neutre" }: { libelle: string; ton?: Ton }) {
  return (
    <span className={`badge badge--${ton}`}>
      <span aria-hidden="true" className="badge__icone">
        {ICONES[ton]}
      </span>
      {libelle}
    </span>
  );
}
