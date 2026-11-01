/** Tableau de données accessible : légende, en-têtes de colonnes, tri annoncé, ligne vide explicite. Charte : carte
 * plate dans un conteneur à défilement horizontal, en-têtes sur fond vert clair, lignes séparées par un filet. */
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";
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

const TETE = "border-b border-filet bg-info-fond px-3 py-1.5 text-left align-bottom font-bold whitespace-nowrap text-vert-profond";
const CELLULE = "border-b border-filet px-3 py-2 text-left align-top";

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
    <div className="overflow-x-auto border border-filet bg-carte">
      <table className="w-full border-collapse text-petit">
        <caption className="sr-only">{legende}</caption>
        <thead>
          <tr>
            {colonnes.map((c) => (
              <th
                key={c.cle}
                scope="col"
                className={TETE}
                style={c.largeur ? { width: c.largeur } : undefined}
                aria-sort={tri?.cle === c.cle ? tri.sens : undefined}
              >
                {c.valeurTri ? (
                  <button
                    type="button"
                    className="inline-flex min-h-11 cursor-pointer items-center gap-1.5 border-0 bg-transparent p-0 font-sans text-petit font-bold text-vert-profond"
                    onClick={() => setTri((t) => ({ cle: c.cle, sens: t?.cle === c.cle && t.sens === "ascending" ? "descending" : "ascending" }))}
                  >
                    {c.titre}
                    {tri?.cle === c.cle ? (
                      tri.sens === "ascending" ? (
                        <ArrowUp aria-hidden="true" size={16} strokeWidth={1.8} />
                      ) : (
                        <ArrowDown aria-hidden="true" size={16} strokeWidth={1.8} />
                      )
                    ) : (
                      <ArrowUpDown aria-hidden="true" size={16} strokeWidth={1.8} />
                    )}
                    <span className="sr-only"> (trier)</span>
                  </button>
                ) : (
                  c.titre
                )}
              </th>
            ))}
            {actions ? (
              <th scope="col" className={TETE}>
                <span className="sr-only">Actions</span>
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {triees.length === 0 ? (
            <tr>
              <td colSpan={colonnes.length + (actions ? 1 : 0)} className="p-8 text-center text-encre-douce">
                {messageVide}
              </td>
            </tr>
          ) : (
            triees.map((ligne) => (
              <tr key={cleLigne(ligne)} className="hover:bg-fond">
                {colonnes.map((c) => (
                  <td key={c.cle} className={CELLULE}>
                    {c.rendu(ligne)}
                  </td>
                ))}
                {actions ? <td className={`${CELLULE} text-right whitespace-nowrap`}>{actions(ligne)}</td> : null}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
