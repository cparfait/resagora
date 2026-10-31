/**
 * Session de l'usager tenue par la façade : état de connexion, jeton CSRF, durée restante.
 * Deux minutes avant l'expiration, un dialogue propose de prolonger (RGAA 13.1 : temps limité).
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, use, useEffect, useState, type ReactNode } from "react";
import { definirCsrf, quandSessionExpire, requete } from "./api/http";
import type { EtatSession } from "./api/types";
import { Bouton } from "./ui/Bouton";
import { Dialogue } from "./ui/Dialogue";

interface ValeurSession {
  pret: boolean;
  connecte: boolean;
  contact: EtatSession["contact"];
  expiree: boolean;
  ouvrir: (reponse: { csrf: string; expire_dans: number; contact: EtatSession["contact"] }) => void;
  deconnecter: () => Promise<void>;
}

const ContexteSession = createContext<ValeurSession | null>(null);
const AVERTISSEMENT_S = 120;
const CLE = ["session"];
const DECONNECTE: EtatSession = { connecte: false, csrf: "", expire_dans: 0, contact: null };

async function lireSession(): Promise<EtatSession> {
  try {
    const etat = await requete<EtatSession>("GET", "/api/portail/session");
    definirCsrf(etat.csrf);
    return etat;
  } catch {
    return DECONNECTE;
  }
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const session = useQuery({ queryKey: CLE, queryFn: lireSession, staleTime: Number.POSITIVE_INFINITY });
  const [expiree, setExpiree] = useState(false);
  const [avertir, setAvertir] = useState(false);
  const etat = session.data;

  useEffect(() => {
    quandSessionExpire(() => {
      setExpiree(true);
      client.setQueryData<EtatSession>(CLE, (e) => (e ? { ...e, connecte: false, contact: null } : e));
    });
  }, [client]);

  useEffect(() => {
    if (!etat?.connecte || etat.expire_dans <= 0) return;
    const avertissement = window.setTimeout(() => setAvertir(true), Math.max(0, etat.expire_dans - AVERTISSEMENT_S) * 1000);
    const fin = window.setTimeout(() => {
      setAvertir(false);
      setExpiree(true);
      client.setQueryData<EtatSession>(CLE, (e) => (e ? { ...e, connecte: false, contact: null } : e));
    }, etat.expire_dans * 1000);
    return () => {
      window.clearTimeout(avertissement);
      window.clearTimeout(fin);
    };
  }, [etat, client]);

  const ouvrir = (reponse: { csrf: string; expire_dans: number; contact: EtatSession["contact"] }) => {
    definirCsrf(reponse.csrf);
    setExpiree(false);
    client.setQueryData<EtatSession>(CLE, { connecte: true, csrf: reponse.csrf, expire_dans: reponse.expire_dans, contact: reponse.contact });
  };

  const deconnecter = async () => {
    try {
      await requete("POST", "/api/portail/auth/deconnexion");
    } finally {
      client.removeQueries({ predicate: (q) => q.queryKey[0] !== "session" });
      await client.invalidateQueries({ queryKey: CLE });
    }
  };

  const prolonger = async () => {
    const reponse = await requete<EtatSession>("POST", "/api/portail/session/prolonger");
    ouvrir(reponse);
    setAvertir(false);
  };

  const valeur: ValeurSession = {
    pret: etat !== undefined,
    connecte: Boolean(etat?.connecte),
    contact: etat?.contact ?? null,
    expiree,
    ouvrir,
    deconnecter,
  };

  return (
    <ContexteSession value={valeur}>
      {children}
      <Dialogue ouvert={avertir} titre="Votre session va expirer" onFermer={() => setAvertir(false)}>
        <p>Par sécurité, votre session se termine dans deux minutes. Les informations non enregistrées seront perdues.</p>
        <div className="actions">
          <Bouton onClick={() => void prolonger()}>Rester connecté</Bouton>
          <Bouton variante="secondaire" onClick={() => void deconnecter().then(() => setAvertir(false))}>
            Me déconnecter
          </Bouton>
        </div>
      </Dialogue>
    </ContexteSession>
  );
}

export function useSession(): ValeurSession {
  const valeur = use(ContexteSession);
  if (!valeur) throw new Error("useSession doit être utilisé dans SessionProvider");
  return valeur;
}
