/**
 * Session de l'agent : profil et actions autorisées par périmètre (RG-14).
 * L'interface masque ce qui n'est pas permis ; l'API refuse dans tous les cas.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useMemo, type ReactNode } from "react";
import { ErreurApi, requete } from "../api/http";
import type { Moi } from "../api/types";

interface ContexteSession {
  moi: Moi | null;
  chargement: boolean;
  peut: (action: string, site?: number | null) => boolean;
  sitesAutorises: (action: string) => number[] | "tous";
  actualiser: () => Promise<void>;
}

const Contexte = createContext<ContexteSession | null>(null);

export async function chargerMoi(): Promise<Moi | null> {
  try {
    return await requete<Moi>("GET", "/api/gestion/moi");
  } catch (erreur) {
    if (erreur instanceof ErreurApi && erreur.statut === 401) return null;
    throw erreur;
  }
}

export function peutAvec(moi: Moi | null, action: string, site?: number | null): boolean {
  if (!moi) return false;
  if (moi.double_authentification_exigee && !moi.double_authentification_validee) return false;
  return moi.habilitations.some(
    (h) => h.actions.includes(action) && (site === undefined || site === null || h.tous_sites || h.sites.includes(site)),
  );
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const requeteMoi = useQuery({ queryKey: ["moi"], queryFn: chargerMoi, staleTime: 60_000, retry: false });
  const valeur = useMemo<ContexteSession>(() => {
    const moi = requeteMoi.data ?? null;
    return {
      moi,
      chargement: requeteMoi.isPending,
      peut: (action, site) => peutAvec(moi, action, site),
      sitesAutorises: (action) => {
        const habilitations = moi?.habilitations.filter((h) => h.actions.includes(action)) ?? [];
        if (habilitations.some((h) => h.tous_sites)) return "tous";
        return [...new Set(habilitations.flatMap((h) => h.sites))];
      },
      actualiser: async () => {
        await client.invalidateQueries({ queryKey: ["moi"] });
      },
    };
  }, [requeteMoi.data, requeteMoi.isPending, client]);
  return <Contexte.Provider value={valeur}>{children}</Contexte.Provider>;
}

export function useSession(): ContexteSession {
  const contexte = useContext(Contexte);
  if (!contexte) throw new Error("useSession doit être utilisé dans SessionProvider");
  return contexte;
}
