/** ADM-03 : agents, habilitations manuelles et réinitialisation de la double authentification (SEC-03). */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ErreurApi, requete } from "../../api/http";
import type { Agent } from "../../api/types";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { ChampSelection, ChampTexte } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { useNotifications } from "../../ui/Notifications";
import { EcranRessource, useOptions } from "../../ui/Ressource";

export default function Agents() {
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const roles = useOptions("roles", "/api/gestion/admin/roles", (r) => String(r.libelle));
  const perimetres = useOptions("perimetres", "/api/gestion/admin/perimetres", (p) => String(p.nom));
  const [agent, setAgent] = useState<Agent | null>(null);
  const [role, setRole] = useState("");
  const [perimetre, setPerimetre] = useState("");
  const [fin, setFin] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [reactivation, setReactivation] = useState<{ agent: string; jeton: string; expire: string } | null>(null);

  const actualiser = () => client.invalidateQueries({ queryKey: ["agents"] });

  const ajouter = useMutation({
    mutationFn: () => requete("POST", "/api/gestion/admin/habilitations", { utilisateur: agent?.id, role: Number(role), perimetre: Number(perimetre), fin: fin || null }),
    onSuccess: async () => {
      annoncer("Habilitation ajoutée.");
      setAgent(null);
      await actualiser();
    },
    onError: (e) => setErreur(e instanceof ErreurApi ? e.message : "Ajout impossible."),
  });

  const retirer = useMutation({
    mutationFn: (id: number) => requete<void>("DELETE", `/api/gestion/admin/habilitations/${id}`),
    onSuccess: async () => {
      annoncer("Habilitation retirée.");
      await actualiser();
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Retrait impossible.", "erreur"),
  });

  const reinitialiser = useMutation({
    mutationFn: (a: Agent) =>
      requete<{ jeton_enrolement: string; expire_le: string }>("POST", `/api/gestion/admin/agents/${a.id}/reinitialiser-totp`).then((r) => ({ ...r, agent: a.nom_affiche ?? a.username })),
    onSuccess: async (resultat) => {
      setReactivation({ agent: resultat.agent, jeton: resultat.jeton_enrolement, expire: new Date(resultat.expire_le).toLocaleString("fr-FR") });
      await actualiser();
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Réinitialisation impossible.", "erreur"),
  });

  const basculer = useMutation({
    mutationFn: (a: Agent) => requete("PATCH", `/api/gestion/admin/agents/${a.id}`, { is_active: !a.is_active }),
    onSuccess: async () => {
      annoncer("Compte mis à jour.");
      await actualiser();
    },
  });

  const soumettre = (evenement: FormEvent) => {
    evenement.preventDefault();
    setErreur(null);
    ajouter.mutate();
  };

  return (
    <>
      <EcranRessource<Agent & Record<string, unknown>>
        titre="Agents et habilitations"
        description="Les agents apparaissent à leur première connexion par l'annuaire. Les habilitations issues d'un groupe AD se gèrent dans l'annuaire."
        chemin="/api/gestion/admin/agents"
        cleRequete="agents"
        actionLecture="administrer"
        libelleObjet="Agent"
        colonnes={[
          { cle: "nom", titre: "Agent", rendu: (a) => `${a.nom_affiche} (${a.username})`, valeurTri: (a) => a.nom_affiche ?? "" },
          {
            cle: "habilitations",
            titre: "Habilitations",
            rendu: (a) => (
              <ul className="liste-compacte">
                {a.habilitations.map((h) => (
                  <li key={h.id}>
                    {h.role_libelle} — {h.perimetre_nom} {h.source === "ad" ? <Badge libelle="AD" ton="info" /> : null}
                    {h.source === "manuel" ? (
                      <Bouton variante="lien" onClick={() => retirer.mutate(h.id)} aria-label={`Retirer ${h.role_libelle} à ${a.nom_affiche}`}>
                        Retirer
                      </Bouton>
                    ) : null}
                  </li>
                ))}
              </ul>
            ),
          },
          { cle: "totp", titre: "Double authentification", rendu: (a) => (a.totp_actif ? <Badge libelle="Activée" ton="succes" /> : <Badge libelle="Non activée" />) },
          { cle: "actif", titre: "Compte", rendu: (a) => (a.is_active ? <Badge libelle="Actif" ton="succes" /> : <Badge libelle="Désactivé" ton="danger" />) },
        ]}
        filtres={[{ nom: "is_active", libelle: "Compte", options: [{ valeur: "true", libelle: "Actifs" }, { valeur: "false", libelle: "Désactivés" }] }]}
        actionsLigne={(a) => (
          <>
            <Bouton variante="lien" onClick={() => setAgent(a)} aria-label={`Ajouter une habilitation à ${a.nom_affiche}`}>
              Ajouter une habilitation
            </Bouton>
            {a.totp_actif ? (
              <Bouton variante="lien" onClick={() => reinitialiser.mutate(a)} aria-label={`Réinitialiser la double authentification de ${a.nom_affiche}`}>
                Réinitialiser le TOTP
              </Bouton>
            ) : null}
            <Bouton variante="lien" onClick={() => basculer.mutate(a)}>
              {a.is_active ? "Désactiver" : "Réactiver"}
            </Bouton>
          </>
        )}
      />
      <Dialogue ouvert={reactivation !== null} titre="Code de réactivation à transmettre" onFermer={() => setReactivation(null)}>
        <p>
          La double authentification de <strong>{reactivation?.agent}</strong> est réinitialisée et ses sessions sont fermées. Transmettez-lui ce code par
          téléphone ou en main propre ; il ne sera plus affiché.
        </p>
        <p className="code-reactivation" aria-label="Code de réactivation">
          {reactivation?.jeton}
        </p>
        <p>Valable jusqu'au {reactivation?.expire}.</p>
        <div className="formulaire__actions">
          <Bouton onClick={() => setReactivation(null)}>J'ai transmis le code</Bouton>
        </div>
      </Dialogue>
      <Dialogue ouvert={agent !== null} titre={`Habilitation pour ${agent?.nom_affiche ?? ""}`} onFermer={() => setAgent(null)}>
        <form onSubmit={soumettre}>
          {erreur ? (
            <div className="alerte alerte--erreur" role="alert">
              {erreur}
            </div>
          ) : null}
          <ChampSelection libelle="Rôle" obligatoire options={roles} value={role} onChange={(e) => setRole(e.target.value)} />
          <ChampSelection libelle="Périmètre" obligatoire options={perimetres} value={perimetre} onChange={(e) => setPerimetre(e.target.value)} />
          <ChampTexte libelle="Fin de validité" type="date" aide="Laisser vide pour une habilitation sans échéance." value={fin} onChange={(e) => setFin(e.target.value)} />
          <div className="formulaire__actions">
            <Bouton variante="secondaire" onClick={() => setAgent(null)}>
              Annuler
            </Bouton>
            <Bouton type="submit" enCours={ajouter.isPending}>
              Ajouter
            </Bouton>
          </div>
        </form>
      </Dialogue>
    </>
  );
}
