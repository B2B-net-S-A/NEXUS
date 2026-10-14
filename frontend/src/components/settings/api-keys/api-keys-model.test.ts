import { describe, expect, it } from "vitest";

import {
  EXPIRY_WARNING_DAYS,
  activeKeysLabel,
  expiryWarning,
  expiryWarningLabel,
  groupScopeCatalog,
  groupScopes,
  keyStatus,
  lastUsedLabel,
  parseTtlDays,
  shortScopeLabel,
  slugError,
  sortKeys,
  writeStateLabel,
} from "./api-keys-model";

const NOW = new Date("2026-10-14T10:00:00Z");
const DAY = 24 * 60 * 60 * 1000;
const at = (days: number) => new Date(NOW.getTime() + days * DAY).toISOString();

const CATALOG = [
  { value: "traffit:sync", label: "Uruchamianie synchronizacji Traffit" },
  { value: "clients:read", label: "Klienci: odczyt (nazwa, NIP, Delivery Lead)" },
  { value: "md:read", label: "Zużycie MD: odczyt (salda, importy)" },
  { value: "md:write", label: "Zużycie MD: zapis (import, przypisanie wiersza, korekta miesiąca)" },
  { value: "amounts:read", label: "Stawki i kwoty: podgląd w zamówieniach i kontraktach" },
  { value: "reports:read", label: "Raporty: odczyt" },
];

describe("groupScopes — grupy uprawnień na ekranie", () => {
  it("dzieli scope'y na stałe grupy w ich kolejności, bez pustych grup", () => {
    const groups = groupScopes(["md:write", "clients:read", "traffit:sync", "md:read"], CATALOG);
    expect(groups.map((g) => g.title)).toEqual([
      "Rozliczenia — odczyt",
      "Rozliczenia — zapis",
      "Operacyjne",
    ]);
    // W grupie kolejność definicji, nie kolejność w koncie.
    expect(groups[0].scopes.map((s) => s.value)).toEqual(["clients:read", "md:read"]);
    expect(groups[1].scopes).toEqual([
      { value: "md:write", label: "Zużycie MD: zapis (import, przypisanie wiersza, korekta miesiąca)" },
    ]);
  });

  it("scope spoza grup trafia do „Inne” — znany z etykietą, nieznany z samą wartością", () => {
    const groups = groupScopes(["zzz:legacy", "reports:read", "amounts:read"], CATALOG);
    expect(groups.map((g) => g.title)).toEqual(["Kwoty", "Inne"]);
    // Najpierw w kolejności słownika z serwera, potem nieznane.
    expect(groups[1].scopes).toEqual([
      { value: "reports:read", label: "Raporty: odczyt" },
      { value: "zzz:legacy", label: "zzz:legacy" },
    ]);
  });

  it("konto bez uprawnień nie ma żadnej grupy, a powtórzony scope liczy się raz", () => {
    expect(groupScopes([], CATALOG)).toEqual([]);
    expect(groupScopes(["md:read", "md:read"], CATALOG)[0].scopes).toHaveLength(1);
  });

  it("formularz dostaje cały słownik z serwera i nie wymyśla scope'ów, których serwer nie zna", () => {
    const groups = groupScopeCatalog(CATALOG);
    const values = groups.flatMap((g) => g.scopes.map((s) => s.value));
    expect(values.sort()).toEqual(CATALOG.map((s) => s.value).sort());
    expect(values).not.toContain("invoices:write");
  });

  it("chip pokazuje etykietę bez dopisku w nawiasie", () => {
    expect(shortScopeLabel("Zużycie MD: zapis (import, przypisanie wiersza)")).toBe("Zużycie MD: zapis");
    expect(shortScopeLabel("Raporty: odczyt")).toBe("Raporty: odczyt");
    expect(shortScopeLabel("(tylko nawias)")).toBe("(tylko nawias)");
  });
});

describe("stan klucza i ostrzeżenie o wygaśnięciu", () => {
  const key = (expiresInDays: number, revoked = false) => ({
    expires_at: at(expiresInDays),
    revoked_at: revoked ? at(-1) : null,
  });

  it("aktywny, wygasły, odwołany — odwołanie wygrywa z wygaśnięciem", () => {
    expect(keyStatus(key(30), NOW)).toBe("active");
    expect(keyStatus(key(-1), NOW)).toBe("expired");
    expect(keyStatus({ expires_at: NOW.toISOString(), revoked_at: null }, NOW)).toBe("expired");
    expect(keyStatus(key(-1, true), NOW)).toBe("revoked");
    expect(keyStatus(key(30, true), NOW)).toBe("revoked");
  });

  it(`ostrzega na ${EXPIRY_WARNING_DAYS} dni przed terminem, nie wcześniej`, () => {
    expect(expiryWarning(key(15), NOW)).toBeNull();
    expect(expiryWarning(key(14), NOW)).toEqual({ kind: "soon", days: 14 });
    expect(expiryWarning(key(5), NOW)).toEqual({ kind: "soon", days: 5 });
    expect(expiryWarningLabel({ kind: "soon", days: 5 })).toBe("Wygasa za 5 dni");
  });

  it("ostatnia doba i po terminie", () => {
    const fewHours = { expires_at: new Date(NOW.getTime() + 3 * 3600 * 1000).toISOString(), revoked_at: null };
    expect(expiryWarning(fewHours, NOW)).toEqual({ kind: "soon", days: 1 });
    expect(expiryWarningLabel({ kind: "soon", days: 1 })).toBe("Wygasa w ciągu doby");
    expect(expiryWarning(key(-2), NOW)).toEqual({ kind: "expired" });
    expect(expiryWarningLabel({ kind: "expired" })).toBe("Wygasł");
  });

  it("odwołany klucz nie straszy terminem", () => {
    expect(expiryWarning(key(3, true), NOW)).toBeNull();
    expect(expiryWarning(key(-3, true), NOW)).toBeNull();
  });

  it("aktywne klucze na górze, potem wygasłe i odwołane; w grupie najnowsze", () => {
    const keys = [
      { key_id: "revoked", created_at: at(-1), ...key(30, true) },
      { key_id: "old", created_at: at(-60), ...key(30) },
      { key_id: "expired", created_at: at(-2), ...key(-1) },
      { key_id: "new", created_at: at(-5), ...key(30) },
    ];
    expect(sortKeys(keys, NOW).map((k) => k.key_id)).toEqual(["new", "old", "expired", "revoked"]);
    expect(keys[0].key_id).toBe("revoked");
  });

  it("liczba aktywnych kluczy po polsku", () => {
    expect(activeKeysLabel(0)).toBe("Brak aktywnego klucza");
    expect(activeKeysLabel(1)).toBe("1 aktywny klucz");
    expect(activeKeysLabel(3)).toBe("3 aktywne klucze");
    expect(activeKeysLabel(5)).toBe("5 aktywnych kluczy");
    expect(activeKeysLabel(12)).toBe("12 aktywnych kluczy");
    expect(activeKeysLabel(22)).toBe("22 aktywne klucze");
  });

  it("ostatnie użycie: czas względny i IP, albo „Nigdy”", () => {
    expect(lastUsedLabel({ last_used_at: null, last_used_ip: null }, NOW)).toBe("Nigdy");
    const minutesAgo = new Date(NOW.getTime() - 12 * 60 * 1000).toISOString();
    expect(lastUsedLabel({ last_used_at: minutesAgo, last_used_ip: "192.0.2.10" }, NOW)).toBe(
      "12 min temu · 192.0.2.10",
    );
    expect(lastUsedLabel({ last_used_at: at(-3), last_used_ip: null }, NOW)).toBe("3 dni temu");
    expect(lastUsedLabel({ last_used_at: at(-1), last_used_ip: null }, NOW)).toBe("wczoraj");
  });
});

describe("walidacja formularzy", () => {
  it("slug jak w backendzie: małe litery, cyfry, myślniki, 3–64 znaki", () => {
    expect(slugError("rozliczenia-n8n")).toBeNull();
    // Wielkie litery i spacje na brzegach backend sam normalizuje.
    expect(slugError("  Rozliczenia-N8N ")).toBeNull();
    expect(slugError("")).toBe("Podaj identyfikator konta.");
    for (const bad of ["ab", "-rozliczenia", "rozliczenia-", "rozliczenia n8n", "rozliczenia_n8n", "a".repeat(65)]) {
      expect(slugError(bad), bad).toMatch(/^Identyfikator:/);
    }
  });

  it("ważność klucza: liczba całkowita od 1 do sufitu z konfiguracji", () => {
    expect(parseTtlDays("90", 365)).toEqual({ days: 90, error: null });
    expect(parseTtlDays(" 365 ", 365)).toEqual({ days: 365, error: null });
    expect(parseTtlDays("366", 365)).toEqual({ days: null, error: "Najdłuższa ważność to 365 dni." });
    expect(parseTtlDays("0", 365).error).toBe("Ważność to co najmniej 1 dzień.");
    expect(parseTtlDays("", 365).error).toBe("Podaj ważność klucza w dniach.");
    expect(parseTtlDays("30.5", 365).error).toMatch(/liczba całkowita/);
    expect(parseTtlDays("-5", 365).error).toMatch(/liczba całkowita/);
  });

  it("stan zapisu przez API po polsku, nieznany bez zmian", () => {
    expect(writeStateLabel("done")).toBe("Zapisano");
    expect(writeStateLabel("pending")).toBe("W toku");
    expect(writeStateLabel("other")).toBe("other");
  });
});
