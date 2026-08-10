/**
 * Deep-linki do listy ofert były atrapą.
 *
 * Pulpit prowadzi na `/jobs?mine=0&status=published`, a `JobsListV2` startował
 * z pustymi filtrami i te parametry ignorował. Użytkownik dostawał WSZYSTKIE
 * oferty (z Draftami włącznie) i nie miał żadnego sygnału, że kliknięty filtr
 * nie zadziałał — lista wyglądała poprawnie, tylko pokazywała co innego.
 *
 * Test importuje PRAWDZIWE funkcje, których używa komponent. Wcześniejsza
 * wersja odtwarzała je inline i przez to sprawdzała własną kopię.
 */

import { describe, expect, it } from "vitest";

import {
  initialMineFromUrl,
  initialStatusFromUrl,
} from "@/lib/jobs-url-filters";

describe("initialStatusFromUrl", () => {
  it("czyta pojedynczy status z deep-linka pulpitu", () => {
    expect(
      initialStatusFromUrl(new URLSearchParams("mine=0&status=published")),
    ).toEqual(["published"]);
  });

  it("czyta wielokrotny status (API łączy je przez OR)", () => {
    expect(
      initialStatusFromUrl(new URLSearchParams("status=published&status=draft")),
    ).toEqual(["published", "draft"]);
  });

  it("odrzuca wartości spoza kontraktu zamiast wysyłać je do API", () => {
    // Ręcznie podrasowany URL ma dać pusty filtr, nie 422 z backendu.
    expect(
      initialStatusFromUrl(
        new URLSearchParams("status=archived&status=published&status="),
      ),
    ).toEqual(["published"]);
  });

  it("brak parametru = brak filtra", () => {
    expect(initialStatusFromUrl(new URLSearchParams(""))).toEqual([]);
    expect(initialStatusFromUrl(new URLSearchParams("mine=1"))).toEqual([]);
  });
});

describe("initialMineFromUrl", () => {
  it("„mine=1” włącza filtr moich rekrutacji", () => {
    expect(initialMineFromUrl(new URLSearchParams("mine=1"))).toBe(true);
  });

  it("„mine=0” go NIE włącza", () => {
    // Pulpit linkuje `mine=0` właśnie po to, żeby pokazać wszystkie —
    // potraktowanie samej obecności parametru jako `true` odwróciłoby sens linku.
    expect(initialMineFromUrl(new URLSearchParams("mine=0"))).toBe(false);
  });

  it("brak parametru = wyłączony", () => {
    expect(initialMineFromUrl(new URLSearchParams("status=published"))).toBe(false);
  });
});
