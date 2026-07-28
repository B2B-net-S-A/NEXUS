/**
 * Stored XSS przez pole z publicznego formularza.
 *
 * `submitted_linkedin` przychodzi z NIEUWIERZYTELNIONEGO `/apply/{token}` i jest
 * walidowany wyłącznie po długości. Wyrenderowany wprost w `<a href>` daje XSS
 * w sesji rekrutera, który kliknie link w kolejce zgłoszeń — React escapuje
 * treść tekstową, ale nie waliduje schematów URL w atrybutach.
 */

import { describe, expect, it } from "vitest";

import { safeExternalHref } from "@/lib/safe-href";

describe("safeExternalHref", () => {
  it("przepuszcza zwykłe adresy http/https", () => {
    expect(safeExternalHref("https://linkedin.com/in/jan-kowalski")).toBe(
      "https://linkedin.com/in/jan-kowalski",
    );
    expect(safeExternalHref("http://example.com/x")).toBe("http://example.com/x");
  });

  it.each([
    ["javascript:alert(document.cookie)"],
    ["JavaScript:alert(1)"],
    ["  javascript:alert(1)  "],
    ["data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg=="],
    ["vbscript:msgbox(1)"],
    ["file:///etc/passwd"],
  ])("odrzuca %s", (raw) => {
    expect(safeExternalHref(raw)).toBeNull();
  });

  it("odrzuca adresy względne i protocol-relative", () => {
    // `//evil.example` dziedziczy schemat strony i prowadzi poza aplikację,
    // wyglądając w kodzie jak ścieżka lokalna.
    expect(safeExternalHref("//evil.example/x")).toBeNull();
    expect(safeExternalHref("/candidates/1")).toBeNull();
    expect(safeExternalHref("linkedin.com/in/x")).toBeNull();
  });

  it("traktuje puste wartości jako brak linku", () => {
    expect(safeExternalHref(null)).toBeNull();
    expect(safeExternalHref(undefined)).toBeNull();
    expect(safeExternalHref("")).toBeNull();
    expect(safeExternalHref("   ")).toBeNull();
  });
});
