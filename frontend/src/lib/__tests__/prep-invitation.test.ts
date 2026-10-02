/**
 * Podgląd zaproszenia na prep: treść składa serwer, okno podstawia tylko
 * dopisek, podpis i (gdy prep nie jest przed rozmową) zdejmuje termin rozmowy.
 */
import { describe, expect, it } from "vitest";

import { renderInvitationPreview, type PrepInvitation } from "@/lib/prep-invitation";

const LINE = "Termin rozmowy z Klientem: 05.10.2031, godz. 14:00";
const INVITATION: PrepInvitation = {
  title: "Przygotowanie do spotkania z Klientem Bank Omega - Jan Przykładowy",
  body: [
    "Dzień dobry,",
    "Zapraszam na spotkanie przygotowujące do rozmowy z Klientem Bank Omega na stanowisko Java Developer.",
    LINE,
    "{note}",
    "W razie pytań pozostaję do dyspozycji.",
    "Pozdrawiam\n{organizer}",
  ].join("\n\n"),
  interview_line: LINE,
};

describe("renderInvitationPreview", () => {
  it("bez dopisku nie zostawia pustego akapitu ani pola", () => {
    const text = renderInvitationPreview(INVITATION, {
      note: "  ",
      organizer: "Kasia Lead",
      beforeInterview: true,
    });
    expect(text).not.toContain("{note}");
    expect(text).not.toContain("\n\n\n");
    expect(text).toContain(LINE);
    expect(text.endsWith("Pozdrawiam\nKasia Lead")).toBe(true);
  });

  it("dopisek trafia między termin rozmowy a zakończenie", () => {
    const text = renderInvitationPreview(INVITATION, {
      note: "Link do opisu stanowiska: https://example.com/opis",
      organizer: "Kasia Lead",
      beforeInterview: true,
    });
    expect(text).toContain(
      `${LINE}\n\nLink do opisu stanowiska: https://example.com/opis\n\nW razie pytań`,
    );
  });

  it("prep po rozmowie nie zapowiada jej terminu — jak serwer przy zapisie", () => {
    const text = renderInvitationPreview(INVITATION, {
      note: "",
      organizer: "Kasia Lead",
      beforeInterview: false,
    });
    expect(text).not.toContain("Termin rozmowy");
  });

  it("znaki specjalne zamiany w dopisku zostają dosłowne", () => {
    const text = renderInvitationPreview(INVITATION, {
      note: "Stawka $& i $1",
      organizer: "A $& B",
      beforeInterview: true,
    });
    expect(text).toContain("Stawka $& i $1");
    expect(text).toContain("A $& B");
  });
});
