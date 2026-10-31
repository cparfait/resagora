import type { ReactNode } from "react";
import { createBrowserRouter, RouterProvider } from "react-router";
import { Connexion } from "./auth/Connexion";
import { useSession } from "./auth/session";
import { Cadre } from "./cadre/Cadre";
import { MODULES } from "./cadre/modules";
import { Chargement, DroitsInsuffisants } from "./ui/Etats";
import { Page } from "./ui/Page";

function Garde({ action, children }: { action: string; children: ReactNode }) {
  const { peut } = useSession();
  return peut(action) ? <>{children}</> : <DroitsInsuffisants />;
}

function Introuvable() {
  return (
    <Page titre="Page introuvable">
      <p>L'adresse demandée ne correspond à aucun écran. Utilisez le menu de navigation.</p>
    </Page>
  );
}

const routeur = createBrowserRouter([
  {
    path: "/",
    element: <Cadre />,
    children: [
      ...MODULES.map((m) => ({
        path: m.chemin === "/" ? undefined : m.chemin.slice(1),
        index: m.chemin === "/",
        element: (
          <Garde action={m.action}>
            <m.composant />
          </Garde>
        ),
      })),
      { path: "*", element: <Introuvable /> },
    ],
  },
]);

export function App() {
  const { moi, chargement } = useSession();
  if (chargement) return <Chargement libelle="Ouverture de votre session…" />;
  if (!moi || (moi.double_authentification_exigee && !moi.double_authentification_validee)) return <Connexion />;
  return <RouterProvider router={routeur} />;
}
