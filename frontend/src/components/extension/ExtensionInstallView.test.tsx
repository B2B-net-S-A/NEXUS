/**
 * Strona /wtyczka (29.10.2026): ZIP zespołu i instrukcja instalacji bez Web Store.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EXTENSION_VERSION, EXTENSION_ZIP_URL, ExtensionInstallView } from "./ExtensionInstallView";

const REPO = resolve(__dirname, "../../../..");

describe("ExtensionInstallView", () => {
  it("link pobiera ZIP zespołu, który leży w public/", () => {
    render(<ExtensionInstallView />);
    const link = screen.getByRole("link", { name: /Pobierz wtyczkę/ });
    expect(link.getAttribute("href")).toBe(EXTENSION_ZIP_URL);
    expect(() => readFileSync(resolve(REPO, "frontend/public", EXTENSION_ZIP_URL.slice(1)))).not.toThrow();
  });

  it("wersja na stronie = wersja z extension/manifest.json", () => {
    const manifest = JSON.parse(readFileSync(resolve(REPO, "extension/manifest.json"), "utf8"));
    expect(EXTENSION_VERSION).toBe(manifest.version);
    render(<ExtensionInstallView />);
    expect(screen.getByRole("link", { name: new RegExp(`wersja ${EXTENSION_VERSION}`) })).toBeTruthy();
  });

  it("prowadzi przez tryb dewelopera, „Wczytaj rozpakowane” i połączenie", () => {
    render(<ExtensionInstallView />);
    expect(screen.getAllByRole("listitem").length).toBeGreaterThanOrEqual(5);
    expect(screen.getByText(/Wczytaj rozpakowane/)).toBeTruthy();
    expect(screen.getByText(/Zaloguj przez NEXUS/)).toBeTruthy();
  });
});
