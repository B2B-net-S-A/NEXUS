import { describe, it, expect, beforeEach } from "vitest";

import { clearSessionArtifacts } from "@/lib/session";

describe("clearSessionArtifacts", () => {
  beforeEach(() => {
    localStorage.clear();
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

  it("kasuje cookie nexus_access", () => {
    document.cookie = "nexus_access=abc; path=/";
    clearSessionArtifacts();
    expect(document.cookie).not.toContain("nexus_access=abc");
  });
});
