import { render, screen } from "@testing-library/react";
import { Ban, Check, ChevronLeft, Download, Pencil } from "lucide-react";
import { describe, expect, it } from "vitest";
import { Bouton } from "./Bouton";
import { iconeAction } from "./iconeAction";

describe("Icônes des boutons d'action (comme dans CityResa)", () => {
  it("déduit l'icône du verbe du libellé, accents et majuscules compris", () => {
    expect(iconeAction("Valider")).toBe(Check);
    expect(iconeAction("Refuser la demande")).toBe(Ban);
    expect(iconeAction("Télécharger le PDF")).toBe(Download);
    expect(iconeAction("Modifier")).toBe(Pencil);
    expect(iconeAction("Semaine précédente")).toBe(ChevronLeft);
    expect(iconeAction("Ne pas annuler")).toBeUndefined();
    expect(iconeAction("Statistiques")).toBeUndefined();
  });

  it("l'icône est décorative : le nom accessible reste le libellé ; un bouton peut la refuser", () => {
    const { container } = render(
      <>
        <Bouton>Valider</Bouton>
        <Bouton icone={null}>Exporter</Bouton>
      </>,
    );
    expect(screen.getByRole("button", { name: "Valider" }).querySelector("svg")?.closest("[aria-hidden='true']")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Exporter" }).querySelector("svg")).toBeNull();
    expect(container.querySelectorAll("svg")).toHaveLength(1);
  });
});
