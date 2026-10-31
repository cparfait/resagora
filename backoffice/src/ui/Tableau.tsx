/** Tableau de données accessible : légende, en-têtes de colonnes, tri annoncé, ligne vide explicite. */
import { useMemo, useState, type ReactNode } from "react";

export interface Colonne<T> {
  cle: string;
  titre: string;
  rendu: (ligne: T) => ReactNode;
  valeurTri?: (ligne: T) => string | number;
  largeur?: string;
}

interface Proprietes<T> {
  legende: string;
  colonnes: Colonne<T>[];
  lignes: T[];
  cleLigne: (ligne: T) => string | number;
  actions?: (ligne: T) => ReactNode;
  messageVide?: string;
}

export function Tableau<T>({ legende, colonnes, lignes, cleLigne, actions, messageVide = "Aucun élément." }: Proprietes<T>) {
  const [tri, setTri] = useState<{ cle: string; sens: "ascending" | "descending" } | null>(null);
  const triees = useMemo(() => {
    const colonne = colonnes.find((c) => c.cle === tri?.cle);
    if (!tri || !colonne?.valeurTri) return lignes;
    const facteur = tri.sens === "ascending" ? 1 : -1;
    const valeur = colonne.valeurTri;
    return lignes.toSorted((a, b) => {
      const va = valeur(a);
      const vb = valeur(b);
      return (typeof va === "number" && typeof vb === "number" ? va - vb : String(va).localeCompare(String(vb), "fr")) * facteur;
    });
  }, [lignes, tri, colonnes]);

  return (
    <div className="tableau-conteneur">
      <table className="tableau">
        <caption className="visuellement-masque">{legende}</caption>
        <thead>
          <tr>
            {colonnes.map((c) => (
              <th key={c.cle} scope="col" style={c.largeur ? { width: c.largeur } : undefined} aria-sort={tri?.cle === c.cle ? tri.sens : undefined}>
                {c.valeurTri ? (
                  <button
                    type="button"
                    className="tableau__tri"
                    onClick={() => setTri((t) => ({ cle: c.cle, sens: t?.cle === c.cle && t.sens === "ascending" ? "descending" : "ascending" }))}
                  >
                    {c.titre}
                    <span aria-hidden="true">{tri?.cle === c.cle ? (tri.sens === "ascending" ? " ▲" : " ▼") : " ↕"}</span>
                    <span className="visuellement-masque"> (trier)</span>
                  </button>
                ) : (
                  c.titre
                )}
              </th>
            ))}
            {actions ? (
              <th scope="col">
                <span className="visuellement-masque">Actions</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {triees.length === 0 ? (
            <tr>
              <td colSpan={colonnes.length + (actions ? 1 : 0)} className="tableau__vide">
                {messageVide}
              </td>
            </tr>
          ) : (
            triees.map((ligne) => (
              <tr key={cleLigne(ligne)}>
                {colonnes.map((c) => (
                  <td key={c.cle}>{c.rendu(ligne)}</td>
                ))}
                {actions ? <td className="tableau__actions">{actions(ligne)}</td> : null}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
