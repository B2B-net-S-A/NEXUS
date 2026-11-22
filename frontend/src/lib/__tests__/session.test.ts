import { describe, it, expect, beforeEach } from "vitest";

import * as session from "@/lib/session";
import {
  clearSessionArtifacts,
  COOKIE_SESSION,
  getAuthenticatedRequestHeaders,
} from "@/lib/session";
import { useAuthStore, type User } from "@/store/auth";

describe("clearSessionArtifacts", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("usuwa wszystkie klucze sesji (w tym markery podgladu jako-user)", () => {
    localStorage.setItem("access_token", "T");
    localStorage.setItem("nexus_user", "{}");
    localStorage.setItem("nexus_real_user", "{}");
    localStorage.setItem("nexus_impersonate_id", "42");
    localStorage.setItem("unrelated_key", "keep");

    clearSessionArtifacts();

    expect(localStorage.getItem("access_token")).toBeNull();
    expect(localStorage.getItem("nexus_user")).toBeNull();
    expect(localStorage.getItem("nexus_real_user")).toBeNull();
    expect(localStorage.getItem("nexus_impersonate_id")).toBeNull();
    // Nie dotyka niepowiązanych kluczy.
    expect(localStorage.getItem("unrelated_key")).toBe("keep");
  });

  it("usuwa robocze wyszukiwanie Talent Radaru (sessionStorage)", () => {
    // Snapshot radaru niesie dane kandydatów — wylogowanie/martwa sesja nie
    // może zostawić go w karcie dla kolejnej zalogowanej osoby.
    sessionStorage.setItem("nexus_talent_radar_session_v1", "{}");
    for (const key of ["nexus-full-job:7:42", "nexus-full-radar:7", "nexus-radar-request:7", "nexus-radar-mode:7"]) sessionStorage.setItem(key, "saved");
    sessionStorage.setItem("unrelated_session_key", "keep");
    localStorage.setItem("nexus-full-job:7:42", "shared-run");

    clearSessionArtifacts();

    expect(sessionStorage.getItem("nexus_talent_radar_session_v1")).toBeNull();
    for (const key of ["nexus-full-job:7:42", "nexus-full-radar:7", "nexus-radar-request:7", "nexus-radar-mode:7"]) expect(sessionStorage.getItem(key)).toBeNull();
    expect(sessionStorage.getItem("unrelated_session_key")).toBe("keep");
    expect(localStorage.getItem("nexus-full-job:7:42")).toBeNull();
  });

  it("zostawia zapamiętany widok listy rekrutacji — to ustawienie osoby, nie dane sesji", () => {
    // Decyzja 13.10.2026: ostatnie filtry przeżywają ponowne logowanie; wpis
    // jest per osoba i niesie same klucze filtrów (`lib/jobs-list-memory.ts`).
    localStorage.setItem("nexus:jobs-list-filters:7", "open=1&stage=searching");

    clearSessionArtifacts();

    expect(localStorage.getItem("nexus:jobs-list-filters:7")).toBe("open=1&stage=searching");
  });

  it("usuwa szkice notatek z panelu osoby (sessionStorage)", () => {
    // Niewysłana notatka niesie dane kandydata — nie czeka na kolejną osobę.
    sessionStorage.setItem("nexus:note-draft:v1:7:10:42", "Oddzwonić po 15");
    sessionStorage.setItem("nexus:note-draft:v1:7:11:43", "Chce hybrydę");
    sessionStorage.setItem("unrelated_session_key", "keep");

    clearSessionArtifacts();

    expect(sessionStorage.getItem("nexus:note-draft:v1:7:10:42")).toBeNull();
    expect(sessionStorage.getItem("nexus:note-draft:v1:7:11:43")).toBeNull();
    expect(sessionStorage.getItem("unrelated_session_key")).toBe("keep");
  });

  it("usuwa szkice list poprawek CV z karty „CV do klienta” (sessionStorage)", () => {
    sessionStorage.setItem("nexus:cv-rewrite-draft:v1:7:21", "1. krócej\n2. więcej o Kafce");
    sessionStorage.setItem("unrelated_session_key", "keep");

    clearSessionArtifacts();

    expect(sessionStorage.getItem("nexus:cv-rewrite-draft:v1:7:21")).toBeNull();
    expect(sessionStorage.getItem("unrelated_session_key")).toBe("keep");
  });

  it("kasuje cookie nexus_access", () => {
    document.cookie = "nexus_access=abc; path=/";
    clearSessionArtifacts();
    expect(document.cookie).not.toContain("nexus_access=abc");
  });
});

describe("stara ścieżka tokenu w JS jest zamknięta (11.2026)", () => {
  // Od PR #3407 sesja przeglądarki żyje w ciasteczku HttpOnly. Bezpiecznik
  // na API sprzed ciasteczka (token w localStorage, ciasteczko pisane z JS,
  // Bearer z frontu, adopcja na /login) usunięty po tygodniu na produkcji.
  beforeEach(() => {
    clearSessionArtifacts();
  });

  it("moduł sesji nie wystawia już zapisu ani odczytu tokenu", () => {
    for (const name of [
      "writeAuthCookie",
      "hasAuthCookie",
      "getAccessToken",
      "storeLegacyAccessToken",
      "adoptLegacySession",
    ]) {
      expect(session, name).not.toHaveProperty(name);
    }
  });

  it("natywny fetch dostaje CSRF, nigdy Bearer z localStorage", () => {
    localStorage.setItem("access_token", "PLANTED");
    const headers = getAuthenticatedRequestHeaders();
    expect(headers.Authorization).toBeUndefined();
    expect(headers["X-Nexus-CSRF"]).toBe("1");
  });

  it("setAuth nie zapisuje tokenu w localStorage ani w ciasteczku z JS", () => {
    const user = { id: 1, email: "a@b2bnetwork.pl", role: "recruiter" } as unknown as User;
    useAuthStore.getState().setAuth(user);
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(document.cookie).not.toContain("nexus_access=");
    expect(useAuthStore.getState().token).toBe(COOKIE_SESSION);
  });

  it("hydrate nie bierze tokenu z localStorage", () => {
    localStorage.setItem("access_token", "PLANTED");
    useAuthStore.getState().hydrate();
    expect(useAuthStore.getState().token).toBeNull();
  });
});
