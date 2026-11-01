/** Cadre des écrans : lien d'évitement, en-tête, menu filtré par les droits, onglets de la rubrique, contenu.
 * Menu sur le modèle de CityResa (navigation.ts) : une douzaine de rubriques à plat avec icône et pastille « à
 * traiter », section « Administration » repliable ; les écrans d'une rubrique sont proposés en onglets au-dessus de
 * la page. Charte (DESIGN.md) : en-tête blanc, élément actif en vert plein ; sur petit écran, bouton « Menu ». */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, LogOut, Menu, Plus, X } from "lucide-react";
import { Suspense, useEffect, useRef, useState } from "react";
import { Link, Outlet, useLocation } from "react-router";
import { requete } from "../api/http";
import { useSession } from "../auth/session";
import { BASE_BOUTON, CLASSES_BOUTON } from "../ui/Bouton";
import { cn } from "../ui/cn";
import { Chargement } from "../ui/Etats";
import type { Compteur } from "../modules/accueil/Accueil";
import { MODULES, type Module } from "./modules";
import { ecransPermis, RUBRIQUES, rubriqueDe, rubriqueDuLien, type Rubrique } from "./navigation";

const LIEN_MENU =
  "flex min-h-11 items-center gap-3 px-3 py-1.5 text-petit leading-snug text-encre no-underline hover:bg-info-fond hover:text-vert-fonce";
const LIEN_ACTIF = "bg-vert font-semibold text-blanc hover:bg-vert-fonce hover:text-blanc";

function EntreeMenu({ rubrique, cible, active, nombre, onChoisir }: { rubrique: Rubrique; cible: Module; active: boolean; nombre: number; onChoisir: () => void }) {
  const Icone = rubrique.icone;
  return (
    <li>
      <Link to={cible.chemin} aria-current={active ? "page" : undefined} onClick={onChoisir} className={cn(LIEN_MENU, active && LIEN_ACTIF)}>
        <Icone aria-hidden="true" size={18} strokeWidth={1.8} className="shrink-0" />
        <span className="flex-1">{rubrique.libelle}</span>
        {nombre > 0 ? (
          <>
            <span aria-hidden="true" className={cn("min-w-6 rounded-full px-1.5 text-center text-xs font-bold", active ? "bg-blanc text-vert" : "bg-anis text-encre")}>
              {nombre}
            </span>
            <span className="sr-only">, {nombre} à traiter</span>
          </>
        ) : null}
      </Link>
    </li>
  );
}

/** Onglets de la rubrique courante (liens, pas un tablist : chaque onglet est une page). */
function Onglets({ rubrique, ecrans, chemin }: { rubrique: Rubrique; ecrans: Module[]; chemin: string }) {
  if (ecrans.length < 2) return null;
  const actif = ecrans.find((m) => m.chemin === chemin) ?? ecrans.find((m) => rubrique.prefixes?.some((p) => chemin.startsWith(p) && m.chemin === p.replace(/\/$/, "")));
  return (
    <nav aria-label={`Écrans de la rubrique ${rubrique.libelle}`} className="mb-4 border-b border-filet print:hidden">
      <ul className="m-0 flex list-none flex-wrap gap-x-1 p-0">
        {ecrans.map((m) => (
          <li key={m.chemin}>
            <Link
              to={m.chemin}
              aria-current={m === actif ? "page" : undefined}
              className={cn(
                "-mb-px inline-flex min-h-11 items-center border-b-4 border-transparent px-3 text-petit font-semibold text-encre no-underline hover:text-vert",
                m === actif && "border-anis text-vert",
              )}
            >
              {m.libelle}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function Cadre() {
  const { moi, peut } = useSession();
  const client = useQueryClient();
  const emplacement = useLocation();
  const principal = useRef<HTMLElement>(null);
  const [menuOuvert, setMenuOuvert] = useState(false);
  // Pastilles du menu : mêmes compteurs que le tableau de bord (cache partagé), sans bloquer le menu en cas d'erreur.
  const aTraiter = useQuery({
    queryKey: ["a-traiter"],
    queryFn: () => requete<{ compteurs: Compteur[] }>("GET", "/api/gestion/pilotage/a-traiter"),
    refetchInterval: 5 * 60_000,
    retry: false,
  });

  // Le focus revient au titre de l'écran à chaque changement de page (navigation au clavier et lecteurs d'écran).
  const chemin = emplacement.pathname;
  useEffect(() => {
    if (chemin) principal.current?.querySelector<HTMLElement>("h1")?.focus();
  }, [chemin]);

  const deconnecter = async () => {
    await requete<void>("POST", "/api/gestion/auth/deconnexion");
    client.clear();
    await client.invalidateQueries({ queryKey: ["moi"] });
  };

  const courante = rubriqueDe(chemin);
  const nombres = new Map<string, number>();
  for (const c of aTraiter.data?.compteurs ?? []) {
    const r = rubriqueDuLien(c.lien);
    if (r && c.groupe === "a_traiter") nombres.set(r.id, (nombres.get(r.id) ?? 0) + c.nombre);
  }
  const entrees = (section: Rubrique["section"]) =>
    RUBRIQUES.filter((r) => r.section === section).flatMap((r) => {
      const ecrans = ecransPermis(r, MODULES, peut);
      const cible = ecrans[0];
      return cible ? [{ rubrique: r, cible }] : [];
    });
  const generales = entrees("general");
  const administration = entrees("administration");
  const fermer = () => setMenuOuvert(false);

  return (
    <div className="min-h-dvh bg-fond">
      <a
        className="sr-only z-50 bg-vert-profond px-4 py-3 text-blanc focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
        href="#contenu"
      >
        Aller au contenu
      </a>
      <header className="sticky top-0 z-40 flex h-16 items-center justify-between gap-4 border-b border-filet bg-carte px-4 print:hidden lg:px-6">
        <div className="flex items-center gap-3">
          <button
            type="button"
            className={cn(BASE_BOUTON, CLASSES_BOUTON.secondaire, "px-3 lg:hidden")}
            aria-expanded={menuOuvert}
            aria-controls="navigation-principale"
            onClick={() => setMenuOuvert((ouvert) => !ouvert)}
          >
            {menuOuvert ? <X aria-hidden="true" size={20} strokeWidth={1.8} /> : <Menu aria-hidden="true" size={20} strokeWidth={1.8} />}
            Menu
          </button>
          <Link to="/" className="m-0 flex min-w-0 flex-col leading-tight no-underline">
            <span className="text-surtitre font-semibold tracking-[0.12em] text-vert uppercase">Ville de Châtillon</span>
            <span className="text-lg font-bold text-encre">Équipements</span>
          </Link>
        </div>
        <div className="flex items-center gap-3">
          {peut("creer_reservation") ? (
            <Link to="/reservations/nouvelle" className={cn(BASE_BOUTON, CLASSES_BOUTON.principal, "px-3 sm:px-5")}>
              <Plus aria-hidden="true" size={18} strokeWidth={1.8} />
              <span className="sr-only md:not-sr-only">Nouvelle demande</span>
            </Link>
          ) : null}
          <span className="hidden text-petit text-encre-douce xl:inline">{moi?.nom_affiche}</span>
          <button type="button" className={cn(BASE_BOUTON, CLASSES_BOUTON.secondaire, "px-3 sm:px-5")} onClick={() => void deconnecter()}>
            <LogOut aria-hidden="true" size={18} strokeWidth={1.8} />
            <span className="sr-only sm:not-sr-only">Se déconnecter</span>
          </button>
        </div>
      </header>
      <div className="lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
        <nav
          id="navigation-principale"
          className={cn(
            "border-b border-filet bg-carte px-3 py-4 print:hidden lg:sticky lg:top-16 lg:block lg:h-[calc(100dvh-4rem)] lg:overflow-y-auto lg:border-r lg:border-b-0",
            menuOuvert ? "block" : "hidden",
          )}
          aria-label="Navigation principale"
        >
          <h2 className="mx-3 mt-1 mb-2 text-surtitre font-semibold tracking-[0.12em] text-vert uppercase">Général</h2>
          <ul className="m-0 list-none p-0">
            {generales.map(({ rubrique, cible }) => (
              <EntreeMenu
                key={rubrique.id}
                rubrique={rubrique}
                cible={cible}
                active={courante?.id === rubrique.id}
                nombre={nombres.get(rubrique.id) ?? 0}
                onChoisir={fermer}
              />
            ))}
          </ul>
          {administration.length ? (
            <details className="group mt-4" open={courante?.section === "administration" || undefined}>
              <summary className="mx-0 flex min-h-11 cursor-pointer list-none items-center justify-between px-3 text-surtitre font-semibold tracking-[0.12em] text-vert uppercase hover:bg-info-fond [&::-webkit-details-marker]:hidden">
                Administration
                <ChevronRight aria-hidden="true" size={16} strokeWidth={1.8} className="transition-transform group-open:rotate-90" />
              </summary>
              <ul className="m-0 mt-1 list-none p-0">
                {administration.map(({ rubrique, cible }) => (
                  <EntreeMenu key={rubrique.id} rubrique={rubrique} cible={cible} active={courante?.id === rubrique.id} nombre={0} onChoisir={fermer} />
                ))}
              </ul>
            </details>
          ) : null}
        </nav>
        <main id="contenu" className="min-w-0 px-4 py-6 focus:outline-none lg:px-8" ref={principal} tabIndex={-1}>
          {courante ? <Onglets rubrique={courante} ecrans={ecransPermis(courante, MODULES, peut)} chemin={chemin} /> : null}
          <Suspense fallback={<Chargement libelle="Chargement de l'écran…" />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}
