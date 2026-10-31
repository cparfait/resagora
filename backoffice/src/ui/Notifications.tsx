/** Messages de confirmation et d'erreur annoncés aux lecteurs d'écran (aria-live). */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { definirSignalementTelechargement } from "../api/http";

interface Message {
  id: number;
  texte: string;
  ton: "succes" | "erreur";
}

interface Contexte {
  annoncer: (texte: string, ton?: Message["ton"]) => void;
}

const ContexteNotifications = createContext<Contexte>({ annoncer: () => undefined });

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const retirer = useCallback((id: number) => setMessages((liste) => liste.filter((m) => m.id !== id)), []);
  const annoncer = useCallback(
    (texte: string, ton: Message["ton"] = "succes") => {
      const id = Date.now() + Math.random();
      setMessages((liste) => [...liste.slice(-3), { id, texte, ton }]);
      window.setTimeout(() => retirer(id), 8000);
    },
    [retirer],
  );
  const valeur = useMemo(() => ({ annoncer }), [annoncer]);
  useEffect(() => definirSignalementTelechargement((message) => annoncer(message, "erreur")), [annoncer]);
  return (
    <ContexteNotifications.Provider value={valeur}>
      {children}
      <div className="notifications" aria-live="polite" role="status">
        {messages.map((m) => (
          <div key={m.id} className={`notification notification--${m.ton}`}>
            <span aria-hidden="true">{m.ton === "succes" ? "✓ " : "⚠ "}</span>
            {m.texte}
            <button type="button" className="notification__fermer" onClick={() => retirer(m.id)} aria-label="Masquer ce message">
              ×
            </button>
          </div>
        ))}
      </div>
    </ContexteNotifications.Provider>
  );
}

export function useNotifications(): Contexte {
  return useContext(ContexteNotifications);
}
