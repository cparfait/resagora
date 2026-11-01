/** Messages de confirmation et d'erreur annoncés aux lecteurs d'écran (aria-live). */
import { Check, TriangleAlert, X } from "lucide-react";
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
      <div className="notifications fixed right-4 bottom-4 z-50 flex max-w-[26rem] flex-col gap-2" aria-live="polite" role="status">
        {messages.map((m) => (
          <div
            key={m.id}
            className={`flex items-start gap-2 border border-l-[6px] border-filet bg-carte py-2 pr-1 pl-4 ${m.ton === "succes" ? "border-l-succes" : "border-l-danger"}`}
          >
            {m.ton === "succes" ? (
              <Check aria-hidden="true" size={20} strokeWidth={1.8} className="mt-2.5 shrink-0 text-succes" />
            ) : (
              <TriangleAlert aria-hidden="true" size={20} strokeWidth={1.8} className="mt-2.5 shrink-0 text-danger" />
            )}
            <span className="flex-1 py-2">{m.texte}</span>
            <button
              type="button"
              className="inline-flex size-11 shrink-0 cursor-pointer items-center justify-center border-0 bg-transparent text-encre hover:bg-fond"
              onClick={() => retirer(m.id)}
              aria-label="Masquer ce message"
            >
              <X aria-hidden="true" size={18} strokeWidth={1.8} />
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
