import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router";
import { Cadre } from "./Cadre";
import { Demande } from "./espace/Demande";
import { FicheDossier, MesDossiers, TableauDeBord } from "./espace/Dossiers";
import { MesAttestations } from "./espace/Attestations";
import { MesFinances } from "./espace/Finances";
import { Campagnes, MaStructure, MonCompte } from "./espace/Profil";
import { Confirmation, ConfirmationNouvelleAdresse, Connexion, Inscription, Invitation, MotDePasseOublie, Reinitialisation } from "./pages/Comptes";
import { Accueil, Catalogue, DisponibilitesPage, FicheEquipement } from "./pages/Publiques";
import { Accessibilite, DonneesPersonnelles, MentionsLegales, PageIntrouvable, PlanDuSite } from "./pages/Reglementaires";
import { useSession } from "./session";
import { Chargement } from "./ui/Elements";

function Protege({ children }: { children: ReactNode }) {
  const { pret, connecte } = useSession();
  const lieu = useLocation();
  if (!pret) return <Chargement />;
  if (!connecte) return <Navigate to={`/connexion?retour=${encodeURIComponent(lieu.pathname + lieu.search)}`} replace />;
  return children;
}

export function Routage() {
  return (
    <Cadre>
      <Routes>
        <Route path="/" element={<Accueil />} />
        <Route path="/equipements" element={<Catalogue />} />
        <Route path="/equipements/:id" element={<FicheEquipement />} />
        <Route path="/disponibilites" element={<DisponibilitesPage />} />
        <Route path="/connexion" element={<Connexion />} />
        <Route path="/inscription" element={<Inscription />} />
        <Route path="/confirmation" element={<Confirmation />} />
        <Route path="/confirmer-adresse" element={<ConfirmationNouvelleAdresse />} />
        <Route path="/mot-de-passe-oublie" element={<MotDePasseOublie />} />
        <Route path="/reinitialisation" element={<Reinitialisation />} />
        <Route path="/invitation" element={<Invitation />} />
        <Route path="/accessibilite" element={<Accessibilite />} />
        <Route path="/donnees-personnelles" element={<DonneesPersonnelles />} />
        <Route path="/mentions-legales" element={<MentionsLegales />} />
        <Route path="/plan-du-site" element={<PlanDuSite />} />
        <Route path="/espace" element={<Protege><TableauDeBord /></Protege>} />
        <Route path="/espace/dossiers" element={<Protege><MesDossiers /></Protege>} />
        <Route path="/espace/dossiers/:id" element={<Protege><FicheDossier /></Protege>} />
        <Route path="/dossiers/:id" element={<Protege><FicheDossier /></Protege>} />
        <Route path="/espace/demande" element={<Protege><Demande /></Protege>} />
        <Route path="/espace/demande/:id" element={<Protege><Demande key="brouillon" /></Protege>} />
        <Route path="/espace/campagnes" element={<Protege><Campagnes /></Protege>} />
        <Route path="/espace/structures/:id" element={<Protege><MaStructure /></Protege>} />
        <Route path="/espace/compte" element={<Protege><MonCompte /></Protege>} />
        <Route path="/espace/factures" element={<Protege><MesFinances /></Protege>} />
        <Route path="/espace/attestations" element={<Protege><MesAttestations /></Protege>} />
        <Route path="*" element={<PageIntrouvable />} />
      </Routes>
    </Cadre>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <Routage />
    </BrowserRouter>
  );
}
