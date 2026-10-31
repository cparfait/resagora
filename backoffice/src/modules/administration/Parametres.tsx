/** ADM-02 : paramètres fonctionnels (délais, seuils, barèmes), modifiés par l'administration et tracés. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ErreurApi, requete } from "../../api/http";
import type { Parametre } from "../../api/types";
import { useSession } from "../../auth/session";
import { Bouton } from "../../ui/Bouton";
import { CaseACocher, ChampTexte, ChampZone } from "../../ui/Champ";
import { Chargement, Erreur } from "../../ui/Etats";
import { useNotifications } from "../../ui/Notifications";
import { Page } from "../../ui/Page";

function versTexte(valeur: unknown): string {
  return typeof valeur === "string" ? valeur : JSON.stringify(valeur, null, 2);
}

export default function Parametres() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const parametres = useQuery({ queryKey: ["parametres"], queryFn: () => requete<Parametre[]>("GET", "/api/gestion/parametres") });
  const [modifies, setModifies] = useState<Record<string, string | boolean>>({});
  const [erreurs, setErreurs] = useState<Record<string, string[]>>({});
  const modifiable = peut("gerer_parametres");

  const enregistrer = useMutation({
    mutationFn: () => {
      const valeurs: Record<string, unknown> = {};
      for (const p of parametres.data ?? []) {
        if (!(p.cle in modifies)) continue;
        const brut = modifies[p.cle];
        if (typeof p.defaut === "boolean") valeurs[p.cle] = brut;
        else if (typeof p.defaut === "number") valeurs[p.cle] = Number(brut);
        else if (typeof p.defaut === "string") valeurs[p.cle] = brut;
        else valeurs[p.cle] = JSON.parse(String(brut));
      }
      return requete<Parametre[]>("PATCH", "/api/gestion/parametres", { valeurs });
    },
    onSuccess: async () => {
      annoncer("Paramètres enregistrés.");
      setModifies({});
      setErreurs({});
      await client.invalidateQueries({ queryKey: ["parametres"] });
    },
    onError: (e) => {
      if (e instanceof ErreurApi) {
        setErreurs((e.details.champs as Record<string, string[]>) ?? {});
        annoncer(e.message, "erreur");
      } else annoncer("Valeur au format JSON invalide.", "erreur");
    },
  });

  if (parametres.isPending) return <Chargement />;
  if (parametres.isError) return <Erreur erreur={parametres.error} reessayer={() => void parametres.refetch()} />;
  const groupes = [...new Set(parametres.data.map((p) => p.groupe))];

  return (
    <Page titre="Paramètres fonctionnels" description="Chaque modification est inscrite au journal d'audit et s'applique immédiatement aux règles de gestion.">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          enregistrer.mutate();
        }}
      >
        {groupes.map((groupe) => (
          <fieldset key={groupe} className="groupe">
            <legend>{groupe}</legend>
            <div className="formulaire__grille">
              {parametres.data
                .filter((p) => p.groupe === groupe)
                .map((p) => {
                  const valeur = p.cle in modifies ? modifies[p.cle] : typeof p.valeur === "boolean" ? p.valeur : versTexte(p.valeur);
                  const aide = `${p.aide ? `${p.aide}. ` : ""}Par défaut : ${versTexte(p.defaut)}.`;
                  if (typeof p.defaut === "boolean")
                    return <CaseACocher key={p.cle} libelle={p.libelle} aide={aide} disabled={!modifiable} checked={Boolean(valeur)} onChange={(e) => setModifies({ ...modifies, [p.cle]: e.target.checked })} erreur={erreurs[p.cle]} />;
                  if (typeof p.defaut === "object")
                    return <ChampZone key={p.cle} libelle={p.libelle} aide={`${aide} Format JSON.`} disabled={!modifiable} value={String(valeur)} onChange={(e) => setModifies({ ...modifies, [p.cle]: e.target.value })} erreur={erreurs[p.cle]} />;
                  return (
                    <ChampTexte
                      key={p.cle}
                      libelle={p.libelle}
                      aide={aide}
                      type={typeof p.defaut === "number" ? "number" : "text"}
                      disabled={!modifiable}
                      value={String(valeur)}
                      onChange={(e) => setModifies({ ...modifies, [p.cle]: e.target.value })}
                      erreur={erreurs[p.cle]}
                    />
                  );
                })}
            </div>
          </fieldset>
        ))}
        {modifiable ? (
          <div className="formulaire__actions">
            <Bouton type="submit" disabled={!Object.keys(modifies).length} enCours={enregistrer.isPending}>
              Enregistrer les modifications
            </Bouton>
          </div>
        ) : null}
      </form>
    </Page>
  );
}
