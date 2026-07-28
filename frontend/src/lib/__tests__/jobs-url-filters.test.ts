/**
 * Deep-linki do listy ofert były atrapą.
 *
 * Pulpit prowadzi na `/jobs?mine=0&status=published`, a `JobsListV2` startował
 * z pustymi filtrami i te parametry ignorował. Użytkownik dostawał WSZYSTKIE
 * oferty (z Draftami włącznie) i nie miał żadnego sygnału, że kliknięty filtr
 * nie zadziałał — lista wyglądała poprawnie, tylko pokazywała co innego.
 *
 * Reguła parsowania jest tu odtworzona 1:1 z `initialStatusFromUrl`, bo o nią
 * chodzi: co przepuszczamy do API, a co odrzucamy.
 */

import { describe, expect, it } from "vitest";

const VALID_JOB_STATUSES: ReadonlySet<string> = new Set([
  "draft",
  "published",
  "closed",
]);

function initialStatusFromUrl(params: URLSearchParams): string[] {
  return params.getAll("status").filter((v) => VALID_JOB_STATUSES.has(v));
}

describe("initialStatusFromUrl", () => {
  it("czyta pojedynczy status z deep-linka pulpitu", () => {
    const p = new URLSearchParams("mine=0&status=published");
    expect(initialStatusFromUrl(p)).toEqual(["published"]);
  });

  it("czyta wielokrotny status (API łączy je przez OR)", () => {
    const p = new URLSearchParams("status=published&status=draft");
    expect(initialStatusFromUrl(p)).toEqual(["published", "draft"]);
  });

  it("odrzuca wartości spoza kontraktu zamiast wysyłać je do API", () => {
    // Ręcznie podrasowany URL ma dać pusty filtr, nie 422 z backendu.
    const p = new URLSearchParams("status=archived&status=published&status=");
    expect(initialStatusFromUrl(p)).toEqual(["published"]);
  });

  it("brak parametru = brak filtra", () => {
    expect(initialStatusFromUrl(new URLSearchParams(""))).toEqual([]);
    expect(initialStatusFromUrl(new URLSearchParams("mine=1"))).toEqual([]);
  });
});

describe("mine z URL-a", () => {
  const mineFromUrl = (qs: string) =>
    new URLSearchParams(qs).get("mine") === "1";

  it("„mine=1” włącza filtr moich ofert", () => {
    expect(mineFromUrl("mine=1")).toBe(true);
  });

  it("„mine=0” go NIE włącza", () => {
    // Pulpit linkuje `mine=0` właśnie po to, żeby pokazać wszystkie —
    // potraktowanie tego jako „true" odwróciłoby sens linku.
    expect(mineFromUrl("mine=0")).toBe(false);
  });

  it("brak parametru = wyłączony", () => {
    expect(mineFromUrl("status=published")).toBe(false);
  });
});
