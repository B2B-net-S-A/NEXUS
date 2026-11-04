import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", () => ({ api: {} }));

import {
  EMPTY_LISTING_OPTIONS,
  isJobBoard,
  listingProblemsFromError,
  pendingActionLabel,
  readyPortals,
  validateListingOptions,
  type PortalListingOptions,
} from "@/lib/api/jobPortals";

const OK: PortalListingOptions = {
  ...EMPTY_LISTING_OPTIONS,
  category: "java",
  experience_level: "senior",
  working_time: "full_time",
  city: "Warszawa",
  workplace_type: "remote",
};

describe("validateListingOptions", () => {
  it("kompletne ogłoszenie bez widełek nie ma braków", () => {
    expect(validateListingOptions(OK, { board: "rocketjobs" })).toEqual([]);
  });

  it("brak kategorii i miasta — dwa braki po polsku", () => {
    const problems = validateListingOptions(
      { ...OK, category: null, city: "  " },
      { board: "justjoinit" },
    );
    expect(problems).toEqual([
      "Wybierz kategorię ogłoszenia.",
      "Wpisz miasto — portal wymaga lokalizacji.",
    ]);
  });

  it("kategorii nie wymaga portal bez słownika dostawcy", () => {
    expect(validateListingOptions({ ...OK, category: null }, { board: "pracuj_pl" })).toEqual([]);
  });

  it.each([
    [null, false], // puste = elastyczny podział (portal to dopuszcza)
    [0, true],
    [5, true],
    [1.5, true],
    [1, false],
    [4, false],
  ])("hybryda z %s dniami w biurze → brak: %s", (days, hasProblem) => {
    const problems = validateListingOptions(
      { ...OK, workplace_type: "hybrid", office_days: days },
      { board: "rocketjobs" },
    );
    expect(problems.some((p) => p.includes("od 1 do 4 dni"))).toBe(hasProblem);
  });

  it("dni w biurze przy pracy zdalnej to błąd", () => {
    expect(
      validateListingOptions({ ...OK, workplace_type: "remote", office_days: 2 }, { board: "rocketjobs" }),
    ).toEqual(["Dni w biurze podaje się tylko przy pracy hybrydowej."]);
  });

  it.each([
    [{ from: 0, to: 100 }, "większa od zera"],
    [{ from: 150, to: 120 }, "nie może być niższa"],
    [{ from: 100, to: 301 }, "trzy razy"],
  ])("widełki %j → %s", (range, fragment) => {
    const problems = validateListingOptions(
      { ...OK, salary: { ...range, unit: "hour" } },
      { board: "rocketjobs" },
    );
    expect(problems).toHaveLength(1);
    expect(problems[0]).toContain(fragment);
  });

  it("widełki na granicy 3× i równe są poprawne", () => {
    for (const range of [{ from: 100, to: 300 }, { from: 150, to: 150 }]) {
      expect(
        validateListingOptions({ ...OK, salary: { ...range, unit: "month" } }, { board: "justjoinit" }),
      ).toEqual([]);
    }
  });
});

describe("pomocniki portali", () => {
  it("etykieta kolejki tylko dla aktualizacji i zamykania", () => {
    expect(pendingActionLabel("update")).toBe("Aktualizacja w kolejce");
    expect(pendingActionLabel("close")).toBe("Zamykanie w kolejce");
    expect(pendingActionLabel("publish")).toBeNull();
    expect(pendingActionLabel(null)).toBeNull();
    expect(pendingActionLabel(undefined)).toBeNull();
  });

  it("portale dostawcy 1EP i gotowe portale", () => {
    expect(isJobBoard("rocketjobs")).toBe(true);
    expect(isJobBoard("justjoinit")).toBe(true);
    expect(isJobBoard("pracuj_pl")).toBe(false);
    expect(
      readyPortals({
        any_ready: true,
        portals: [
          { portal: "rocketjobs", label: "RocketJobs", state: "ready", enabled: true },
          { portal: "justjoinit", label: "JustJoin.IT", state: "not_connected", enabled: true },
        ],
      }).map((p) => p.portal),
    ).toEqual(["rocketjobs"]);
    expect(readyPortals(undefined)).toEqual([]);
  });

  it("braki z odmowy serwera — w `detail` albo na wierzchu, tylko 422 listing_invalid", () => {
    const problems = ["Wybierz kategorię."];
    expect(
      listingProblemsFromError({
        response: { status: 422, data: { detail: { code: "listing_invalid", message: "x", problems } } },
      }),
    ).toEqual(problems);
    expect(
      listingProblemsFromError({ response: { status: 422, data: { code: "listing_invalid", problems } } }),
    ).toEqual(problems);
    expect(
      listingProblemsFromError({ response: { status: 409, data: { detail: { code: "listing_invalid", problems } } } }),
    ).toBeNull();
    expect(listingProblemsFromError({ response: { status: 422, data: { detail: "zły" } } })).toBeNull();
    expect(listingProblemsFromError(null)).toBeNull();
  });
});
