/**
 * Podgląd zaproszenia na prep: treść składa serwer, okno podstawia tylko
 * dopisek, podpis i (gdy prep nie jest przed rozmową) zdejmuje termin rozmowy.
 */
import { describe, expect, it } from "vitest";

import {
  looksLikeRoleCode,
  renderInvitationPreview,
  roleSectionHeading,
  type PrepInvitation,
} from "@/lib/prep-invitation";

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

describe("stanowisko i opis roli (26.10.2026)", () => {
  const ROLE_INVITATION: PrepInvitation = {
    title: "Przygotowanie do spotkania z Klientem Bank Omega - Jan Przykładowy",
    body: [
      "Dzień dobry,",
      "Zapraszam na spotkanie przygotowujące do rozmowy z Klientem Bank Omega na stanowisko {role}.",
      "{role_hint}",
      "{note}",
      "Pozdrawiam\n{organizer}",
    ].join("\n\n"),
    role_hint: "Przed spotkaniem przejrzyj, proszę, opis roli poniżej.",
  };
  const base = { note: "", organizer: "Kasia Lead", beforeInterview: true };

  it("podstawia stanowisko i zdanie o opisie tylko z opisem", () => {
    const withRole = renderInvitationPreview(ROLE_INVITATION, {
      ...base,
      role: "  Data   Engineer ",
      withRole: true,
    });
    expect(withRole).toContain("na stanowisko Data Engineer.\n\nPrzed spotkaniem przejrzyj");
    const without = renderInvitationPreview(ROLE_INVITATION, { ...base, role: "Data Engineer" });
    expect(without).not.toContain("opis roli");
    expect(without).not.toContain("{role_hint}");
    expect(without).not.toContain("\n\n\n");
  });

  it("puste stanowisko = zdanie bez „na stanowisko”, jak serwer", () => {
    const text = renderInvitationPreview(ROLE_INVITATION, { ...base, role: " " });
    expect(text).toContain("z Klientem Bank Omega.");
    expect(text).not.toContain("stanowisko");
  });

  it("nagłówek sekcji i wykrywanie kodu — lustro serwera", () => {
    expect(roleSectionHeading("Data Engineer")).toBe("O roli: Data Engineer");
    expect(roleSectionHeading("")).toBe("O roli");
    for (const code of ["PL_IT_Developer_expert_TP#40379", "Dev RITM0867849", "(43020)", "Replacement for Jan"]) {
      expect(looksLikeRoleCode(code)).toBe(true);
    }
    for (const role of ["Senior ETL / Snowflake Engineer", "SQL Server 2019 Administrator"]) {
      expect(looksLikeRoleCode(role)).toBe(false);
    }
  });
});
