import { describe, expect, it } from "vitest";

import {
  LEAGUE_DL_BEYOND_TEN,
  LEAGUE_DL_NO_CLOSED,
  LEAGUE_DL_OUTSIDE,
  LEAGUE_DL_SECOND,
  LEAGUE_RECRUITER_FOURTH,
  LEAGUE_RECRUITER_LEADER,
  LEAGUE_RECRUITER_SECOND,
  LEAGUE_RECRUITER_TIED,
  LEAGUE_RECRUITER_UNQUALIFIED,
  LEAGUE_RECRUITER_ZERO,
  LEAGUE_SPECTATOR,
} from "@/components/v2/league/league-fixtures";
import {
  buildLeagueTopbarModel,
  leagueErrorModel,
  shortName,
  workToClose,
} from "@/components/v2/league/league-topbar-model";

const FORMULA = { placement: 150, interview: 15, recommendation: 5 };

function texts(model: ReturnType<typeof buildLeagueTopbarModel>): string[] {
  return model?.panel.sentences.map((s) => s.text) ?? [];
}

describe("buildLeagueTopbarModel — rekruter", () => {
  it("4. miejsce: numer w kółku, punkty w pasku, dystans dla czytnika ekranu", () => {
    const model = buildLeagueTopbarModel(LEAGUE_RECRUITER_FOURTH);
    expect(model?.medal).toEqual({ text: "4", tone: "neutral" });
    expect(model?.label).toBe("Liga · Q4");
    expect(model?.value).toBe("385 pkt");
    expect(model?.up).toBeNull();
    expect(model?.spoken).toBe(
      "Liga Mistrzów, Q4 2026: 4. miejsce, 385 punktów. Do podium brakuje 85 punktów.",
    );
  });

  it("panel mówi, ile brakuje i czym to nadrobić", () => {
    const panel = buildLeagueTopbarModel(LEAGUE_RECRUITER_FOURTH)!.panel;
    expect(panel.title).toBe("Liga Mistrzów · Q4 2026");
    expect(panel.aside).toBe("do końca 80 dni");
    expect(panel.headline).toBe("4. miejsce");
    expect(panel.headlineValue).toBe("385 pkt");
    expect(panel.sub).toBe("14 osób w lidze · podium: 5000 / 3000 / 2000 zł");
    expect(panel.sentences.map((s) => s.text)).toEqual([
      "Do podium brakuje 85 pkt.",
      "To 1 placement albo 6 rozmów u klienta.",
    ]);
    expect(panel.breakdown).toEqual({
      rows: [
        { label: "Placementy", detail: "2 × 150", points: "300" },
        { label: "Rozmowy u klienta", detail: "4 × 15", points: "60" },
        { label: "CV wysłane do klienta", detail: "5 × 5", points: "25" },
      ],
      total: "385",
    });
    expect(panel.condition).toEqual({
      met: true,
      text: "Warunek spełniony. Próg w kolejnych miesiącach kwartału: 1, 2 i 3 placementy.",
    });
    expect(panel.rowsTitle).toBe("Obok Ciebie");
    expect(panel.rows.map((r) => [r.rank, r.name, r.value, r.prize, r.me])).toEqual([
      ["2.", "Kamil Sadowski", "515", "3000 zł", false],
      ["3.", "Anna Kowalczyk", "470", "2000 zł", false],
      ["4.", "Ty", "385", null, true],
      ["5.", "Ola Pietrzak", "340", null, false],
      ["6.", "Bartek Nowicki", "290", null, false],
    ]);
    expect(panel.link).toEqual({ href: "/insights?tab=rywalizacja", label: "Cała liga" });
    expect(panel.failed).toBe(false);
  });

  it("lider: złote kółko i przewaga, bez dystansu", () => {
    const model = buildLeagueTopbarModel(LEAGUE_RECRUITER_LEADER);
    expect(model?.medal).toEqual({ text: "1", tone: "gold" });
    expect(model?.label).toBe("Liga · Q4");
    expect(texts(model)).toEqual(["Prowadzisz. Przewaga nad 2. miejscem: 125 pkt."]);
    expect(model?.spoken).toBe("Liga Mistrzów, Q4 2026: 1. miejsce, 640 punktów.");
  });

  it("2. miejsce: srebro, dystans do miejsca wyżej i przewaga nad następnym", () => {
    const model = buildLeagueTopbarModel(LEAGUE_RECRUITER_SECOND);
    expect(model?.medal.tone).toBe("silver");
    expect(model?.spoken).toBe(
      "Liga Mistrzów, Q4 2026: 2. miejsce, 515 punktów. Do 1. miejsca brakuje 125 punktów.",
    );
    expect(texts(model)).toEqual([
      "Do 1. miejsca brakuje 125 pkt.",
      "To 1 placement albo 9 rozmów u klienta.",
      "Przewaga nad 3. miejscem: 45 pkt.",
    ]);
  });

  it("remis o płatne miejsce: brąz, „remis” w podpisie i zdanie o rozstrzygnięciu", () => {
    const model = buildLeagueTopbarModel(LEAGUE_RECRUITER_TIED);
    expect(model?.medal.tone).toBe("bronze");
    expect(model?.label).toBe("Liga · remis");
    expect(texts(model)[0]).toBe(
      "Remis o 3. miejsce. Jeśli zostanie do końca kwartału, rozstrzygnie admin.",
    );
    expect(model?.panel.rows.find((r) => r.rank === "4.")?.prize).toBeNull();
    expect(model?.panel.rows.find((r) => r.me)?.prize).toBe("remis");
  });

  it("remis bierze miejsce z grupy remisu: 2. miejsce walczy o 1., 4. o 3.", () => {
    const second = buildLeagueTopbarModel({
      ...LEAGUE_RECRUITER_SECOND,
      standing: { ...LEAGUE_RECRUITER_SECOND.standing!, tie_for: 1 },
    });
    expect(second?.label).toBe("Liga · remis");
    expect(texts(second)[0]).toBe("Remis o 1. miejsce. Jeśli zostanie do końca kwartału, rozstrzygnie admin.");
    const fourth = buildLeagueTopbarModel({
      ...LEAGUE_RECRUITER_FOURTH,
      standing: { ...LEAGUE_RECRUITER_FOURTH.standing!, tie_for: 3 },
    });
    expect(fourth?.label).toBe("Liga · remis");
    expect(texts(fourth)[0]).toBe("Remis o 3. miejsce. Jeśli zostanie do końca kwartału, rozstrzygnie admin.");
    // Bez remisu w grupie — bez „remisu”, nawet gdy wiersz miałby flagę z innego źródła.
    expect(buildLeagueTopbarModel(LEAGUE_RECRUITER_FOURTH)?.label).toBe("Liga · Q4");
  });

  it("bez miejsca: punkty widać, numeru nie, panel mówi o warunku i pozycji po punktach", () => {
    const model = buildLeagueTopbarModel(LEAGUE_RECRUITER_UNQUALIFIED);
    expect(model?.medal).toEqual({ text: "–", tone: "warn" });
    expect(model?.label).toBe("Liga · bez miejsca");
    expect(model?.value).toBe("210 pkt");
    expect(model?.panel.headline).toBe("Bez miejsca");
    expect(texts(model)).toEqual([
      "Punkty się liczą. Miejsce w klasyfikacji dostaniesz, gdy będziesz mieć 1 placement w kwartale.",
      "Po punktach to 7. pozycja.",
    ]);
    expect(model?.panel.condition).toEqual({
      met: false,
      text: "Do warunku brakuje 1 placementu w kwartale. Próg w kolejnych miesiącach kwartału: 1, 2 i 3 placementy.",
    });
    expect(model?.spoken).toBe("Liga Mistrzów, Q4 2026: 210 punktów, bez miejsca w klasyfikacji.");
  });

  it("zero punktów to „0 pkt” i podpowiedź, skąd biorą się punkty", () => {
    const model = buildLeagueTopbarModel(LEAGUE_RECRUITER_ZERO);
    expect(model?.medal).toEqual({ text: "–", tone: "off" });
    expect(model?.value).toBe("0 pkt");
    expect(model?.panel.breakdown).toBeNull();
    expect(model?.panel.rows).toEqual([]);
    expect(model?.panel.rowsTitle).toBeNull();
    expect(texts(model)).toEqual([
      "Pierwsze punkty: CV wysłane do klienta 5, rozmowa u klienta 15, placement 150.",
    ]);
  });

  it("awans od rana: strzałka „z 6.” w pasku i zdanie w panelu", () => {
    const model = buildLeagueTopbarModel(LEAGUE_RECRUITER_FOURTH, { baselineRank: 6 });
    expect(model?.up).toBe("z 6.");
    expect(texts(model)[0]).toBe("Dziś awans z 6. na 4. miejsce.");
    expect(model?.spoken).toMatch(/Dziś awans z 6\. miejsca\.$/);
  });

  it("spadek i to samo miejsce nie mają strzałki", () => {
    expect(buildLeagueTopbarModel(LEAGUE_RECRUITER_FOURTH, { baselineRank: 3 })?.up).toBeNull();
    expect(buildLeagueTopbarModel(LEAGUE_RECRUITER_FOURTH, { baselineRank: 4 })?.up).toBeNull();
    expect(buildLeagueTopbarModel(LEAGUE_RECRUITER_FOURTH, { baselineRank: null })?.up).toBeNull();
  });

  it("ostatni dzień kwartału", () => {
    const model = buildLeagueTopbarModel({ ...LEAGUE_RECRUITER_FOURTH, days_remaining: 0 });
    expect(model?.panel.aside).toBe("ostatni dzień kwartału");
    expect(buildLeagueTopbarModel({ ...LEAGUE_RECRUITER_FOURTH, days_remaining: 1 })?.panel.aside).toBe(
      "do końca 1 dzień",
    );
  });

  it("bez odpowiedzi o pozycji (starsza odpowiedź) — nic do pokazania", () => {
    expect(buildLeagueTopbarModel({ ...LEAGUE_RECRUITER_FOURTH, standing: undefined })).toBeNull();
  });
});

describe("buildLeagueTopbarModel — Delivery Lead", () => {
  it("w lidze: placementy zamiast punktów i hit ratio w panelu", () => {
    const model = buildLeagueTopbarModel(LEAGUE_DL_SECOND);
    expect(model?.medal).toEqual({ text: "2", tone: "silver" });
    expect(model?.label).toBe("Liga DL · Q4");
    expect(model?.value).toBe("4 placementy");
    expect(texts(model)).toEqual([
      "Do 1. miejsca brakuje 1 placementu.",
      "Hit ratio 36,4% (4 z 11 zamkniętych rekrutacji).",
    ]);
    expect(model?.panel.breakdown).toBeNull();
    expect(model?.panel.rowsUnit).toBe("placementy");
    expect(model?.spoken).toBe("Liga Mistrzów DL, Q4 2026: 2. miejsce, 4 placementy.");
  });

  it("zamknięcia „nie liczy się” dopisane do zdania o hit ratio (21.10.2026)", () => {
    const one = buildLeagueTopbarModel({ ...LEAGUE_DL_SECOND, dl: { ...LEAGUE_DL_SECOND.dl!, closed_neutral: 1 } });
    expect(texts(one)[1]).toBe(
      "Hit ratio 36,4% (4 z 11 zamkniętych rekrutacji). Jedna zamknięta nie liczy się (duplikat, anulowana, wewnętrzna…).",
    );
    const three = buildLeagueTopbarModel({ ...LEAGUE_DL_SECOND, dl: { ...LEAGUE_DL_SECOND.dl!, closed_neutral: 3 } });
    expect(texts(three)[1]).toContain("3 zamknięte nie liczą się");
    const five = buildLeagueTopbarModel({ ...LEAGUE_DL_SECOND, dl: { ...LEAGUE_DL_SECOND.dl!, closed_neutral: 5 } });
    expect(texts(five)[1]).toContain("5 zamkniętych nie liczy się");
  });

  it("poza ligą: droga do progu", () => {
    const model = buildLeagueTopbarModel(LEAGUE_DL_OUTSIDE);
    expect(model?.medal).toEqual({ text: "–", tone: "warn" });
    expect(model?.label).toBe("Liga DL · poza ligą");
    expect(model?.value).toBe("2 placementy");
    expect(texts(model)).toEqual([
      "Do ligi potrzeba co najmniej 3 placementów i hit ratio 30%.",
      "Hit ratio 25% (2 z 8 zamkniętych rekrutacji).",
      "Brakuje 1 placementu.",
    ]);
  });

  it("bez zamkniętych rekrutacji hit ratio jest niepoliczone, nie zerowe", () => {
    const model = buildLeagueTopbarModel(LEAGUE_DL_NO_CLOSED);
    expect(model?.value).toBe("0 placementów");
    expect(texts(model)).toContain("Hit ratio liczy się od pierwszej rekrutacji zamkniętej w kwartale.");
    expect(texts(model)).toContain("Brakuje 3 placementów.");
  });

  it("hit ratio z jedną zamkniętą rekrutacją w liczbie pojedynczej", () => {
    const model = buildLeagueTopbarModel({
      ...LEAGUE_DL_OUTSIDE,
      dl: { ...LEAGUE_DL_OUTSIDE.dl!, placements: 1, closed_requests: 1, hit_ratio: 100, missing_placements: 2 },
    });
    expect(texts(model)).toContain("Hit ratio 100% (1 z 1 zamkniętej rekrutacji).");
  });

  it("próg spełniony, ale poza pierwszą dziesiątką rankingu — to nie „poza ligą”", () => {
    const model = buildLeagueTopbarModel(LEAGUE_DL_BEYOND_TEN);
    expect(model?.panel.sub).toBe("ponad 2 osoby w lidze · podium: 5000 / 3000 / 2000 zł");
    expect(model?.label).toBe("Liga DL · poza 10.");
    expect(model?.panel.headline).toBe("W lidze");
    expect(model?.medal.tone).toBe("neutral");
  });
});

describe("buildLeagueTopbarModel — kto nie gra", () => {
  it("lider ligi rekruterów z inicjałem nazwiska i piątka w panelu", () => {
    const model = buildLeagueTopbarModel(LEAGUE_SPECTATOR);
    expect(model?.medal).toEqual({ text: "1", tone: "gold" });
    expect(model?.label).toBe("Liga · prowadzi");
    expect(model?.value).toBe("Marta W.");
    expect(model?.spoken).toBe("Liga Mistrzów, Q4 2026: prowadzi Marta Wiśniewska, 640 punktów.");
    expect(model?.panel.rowsTitle).toBe("Pierwsza piątka");
    expect(model?.panel.rows).toHaveLength(5);
    expect(model?.panel.rows.some((r) => r.me)).toBe(false);
  });

  it("bez nikogo z miejscem — przycisku nie ma", () => {
    expect(buildLeagueTopbarModel({ ...LEAGUE_SPECTATOR, leaders: [] })).toBeNull();
  });
});

describe("pomocniki", () => {
  it("workToClose: najwyżej dwie drogi, rozmowy powyżej 20 pomijane", () => {
    expect(workToClose(85, FORMULA)).toBe("To 1 placement albo 6 rozmów u klienta.");
    expect(workToClose(30, FORMULA)).toBe("To 1 placement albo 2 rozmowy u klienta.");
    expect(workToClose(15, FORMULA)).toBe("To 1 placement albo 1 rozmowa u klienta.");
    expect(workToClose(320, FORMULA)).toBe("To 3 placementy.");
    expect(workToClose(0, FORMULA)).toBeNull();
    expect(workToClose(85, undefined)).toBeNull();
  });

  it("shortName: imię i inicjał nazwiska", () => {
    expect(shortName("Marta Wiśniewska")).toBe("Marta W.");
    expect(shortName("Anna Maria Kowalska")).toBe("Anna K.");
    expect(shortName("  Ola  ")).toBe("Ola");
  });

  it("awaria to „—”, nigdy „0 pkt”", () => {
    const model = leagueErrorModel();
    expect(model.value).toBe("—");
    expect(model.medal).toEqual({ text: null, tone: "error" });
    expect(model.panel.failed).toBe(true);
  });
});
