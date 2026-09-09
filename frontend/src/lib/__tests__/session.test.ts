import { describe, it, expect, beforeEach } from "vitest";

import {
  clearSessionArtifacts,
  hasAuthCookie,
  writeAuthCookie,
} from "@/lib/session";

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

    clearSessionArtifacts();

    expect(sessionStorage.getItem("nexus_talent_radar_session_v1")).toBeNull();
    for (const key of ["nexus-full-job:7:42", "nexus-full-radar:7", "nexus-radar-request:7", "nexus-radar-mode:7"]) expect(sessionStorage.getItem(key)).toBeNull();
    expect(sessionStorage.getItem("unrelated_session_key")).toBe("keep");
  });

  it("kasuje cookie nexus_access", () => {
    document.cookie = "nexus_access=abc; path=/";
    clearSessionArtifacts();
    expect(document.cookie).not.toContain("nexus_access=abc");
  });
});

describe("writeAuthCookie / hasAuthCookie", () => {
  beforeEach(() => {
    clearSessionArtifacts();
  });

  it("zapisuje cookie i potwierdza zapis", () => {
    expect(hasAuthCookie()).toBe(false);
    expect(writeAuthCookie("token-abc")).toBe(true);
    expect(hasAuthCookie()).toBe(true);
    expect(document.cookie).toContain("nexus_access=token-abc");
  });

  it("zwraca false, gdy przeglądarka blokuje cookies (cichy no-op)", () => {
    // Bez tego sygnału warstwa kliencka uznaje sesję za kompletną, a middleware
    // widzi brak cookie — i mamy nieskończoną pętlę /login ↔ chroniona trasa.
    const descriptor = Object.getOwnPropertyDescriptor(Document.prototype, "cookie");
    Object.defineProperty(document, "cookie", {
      configurable: true,
      get: () => "",
      set: () => {},
    });
    try {
      expect(writeAuthCookie("token-abc")).toBe(false);
      expect(hasAuthCookie()).toBe(false);
    } finally {
      delete (document as unknown as Record<string, unknown>).cookie;
      if (descriptor) Object.defineProperty(Document.prototype, "cookie", descriptor);
    }
  });

  it("nie myli cookie o nazwie będącej sufiksem", () => {
    document.cookie = "other_nexus_access=x; path=/";
    expect(hasAuthCookie()).toBe(false);
  });
});
