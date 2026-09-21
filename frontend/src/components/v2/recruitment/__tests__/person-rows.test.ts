import { describe, expect, it } from "vitest";

import { NO_NEXT_ACTION_LABEL } from "@/lib/pipeline-next-action";
import {
  AUTO_GROUP_THRESHOLD,
  DEFAULT_PERSON_SORT,
  availabilityLabelFor,
  buildProcessRows,
  chipCounts,
  defaultCollapsedFor,
  defaultPanelSectionFor,
  firstVisibleRowKey,
  filterRows,
  groupRowsByOwner,
  ownerGroupOf,
  recruiterOptions,
  rowBadges,
  segmentCounts,
  shouldGroupRows,
  sortRows,
} from "@/components/v2/recruitment/person-rows";

import { item, template } from "./recruitment-fixtures";

const byId = <T extends { candidateId: number }>(rows: T[], id: number): T => {
  const row = rows.find((r) => r.candidateId === id);
  if (!row) throw new Error(`brak wiersza ${id}`);
  return row;
};

describe("buildProcessRows", () => {
  it("liczy grupę etapu nad CAŁYM szablonem — własny etap po screeningu to weryfikacja", () => {
    const rows = buildProcessRows(template({ 4: [item(1)] }));
    const row = byId(rows, 1);
    expect(row.group).toBe("verification");
    // Bez grupy z szablonu ta osoba dostałaby podpowiedź etapu wejściowego.
    expect(row.nextAction.label).toBe("Wyślij CV do klienta");
    expect(row.stageLabel).toBe("Wysłać do Cpro");
  });

  it("dopasowanie bez wyniku to null, nigdy zero zastępcze", () => {
    const rows = buildProcessRows(template({ 1: [item(1), item(2), item(3)] }), {
      scores: new Map([
        [1, 87.6],
        [3, 0],
      ]),
    });
    expect(byId(rows, 1).fitScore).toBe(88);
    expect(byId(rows, 2).fitScore).toBeNull();
    // Zero policzone przez serwer zostaje zerem — to realny wynik.
    expect(byId(rows, 3).fitScore).toBe(0);
  });

  it("klucz wiersza idzie po kandydacie, więc przeżywa ruch (nowe id etapu)", () => {
    const before = buildProcessRows(template({ 1: [item(7, { id: 1 })] }));
    const after = buildProcessRows(template({ 2: [item(7, { id: 2 })] }));
    expect(before[0].key).toBe(after[0].key);
  });

  it("odznaka „ponad budżet”: stempel serwera ALBO stawka ponad bieżący budżet", () => {
    const rows = buildProcessRows(
      template({
        3: [
          item(1, { budget_exceeded: true }),
          item(2, { expected_rate_value: "210", expected_rate_unit: "hourly", expected_rate_currency: "PLN" }),
          item(3, { expected_rate_value: "150", expected_rate_unit: "hourly", expected_rate_currency: "PLN" }),
          // Waluta obca = nie do porównania → brak odznaki, nigdy fałszywa.
          item(4, { expected_rate_value: "900", expected_rate_unit: "hourly", expected_rate_currency: "EUR" }),
        ],
      }),
      { budgetHourly: 190 },
    );
    const labels = (id: number) => rowBadges(byId(rows, id)).map((b) => b.label);
    expect(labels(1)).toContain("ponad budżet");
    expect(labels(2)).toContain("ponad budżet");
    expect(labels(3)).not.toContain("ponad budżet");
    expect(labels(4)).not.toContain("ponad budżet");
    expect(byId(rows, 2).warnings).toEqual(["budget_exceeded"]);
    expect(byId(rows, 2).rateLabel).toBe("210 PLN/h");
  });

  it("odznaki screeningu i scorecardu wymagają jawnego `false` — brak pola nie pokazuje nic", () => {
    const rows = buildProcessRows(
      template({
        3: [item(1, { screening_done: false, scorecard_done: false }), item(2)],
        1: [item(3, { screening_done: false })],
      }),
    );
    const ctx = { stagesWithScorecard: new Set([3]) };
    expect(rowBadges(byId(rows, 1), ctx).map((b) => b.key)).toEqual(["screening", "scorecard"]);
    expect(rowBadges(byId(rows, 2), ctx)).toEqual([]);
    // „Nowy" nie jest etapem z punktem screeningu.
    expect(rowBadges(byId(rows, 3), ctx)).toEqual([]);
  });

  it("„CV gotowe w tle” tylko przy jawnym `auto_cv_ready: true` i nigdy na etapie zamkniętym", () => {
    const rows = buildProcessRows(
      template({
        4: [item(1, { auto_cv_ready: true }), item(2, { auto_cv_ready: false }), item(3)],
        10: [item(4, { auto_cv_ready: true })],
      }),
    );
    const ready = byId(rows, 1);
    expect(ready.nextAction.label).toBe("Wyślij CV do klienta");
    expect(rowBadges(ready).map((b) => [b.key, b.label, b.tone])).toEqual([
      ["auto-cv", "CV gotowe w tle", "info"],
    ]);
    expect(rowBadges(byId(rows, 2))).toEqual([]);
    expect(rowBadges(byId(rows, 3))).toEqual([]);
    expect(rowBadges(byId(rows, 4))).toEqual([]);
  });

  it("weto HM: kod ostrzeżenia, odznaka i ruch po stronie rekrutera", () => {
    const veto = {
      hiring_manager_contact_id: 1,
      source_job_id: 2,
      rejected_at: "2026-09-01T10:00:00Z",
      rejection_reason_name: "Za mało Kafki",
    };
    const rows = buildProcessRows(template({ 5: [item(1, { hm_veto: veto })], 10: [item(2, { hm_veto: veto })] }));
    expect(byId(rows, 1).warnings).toEqual(["hm_veto"]);
    expect(byId(rows, 1).nextAction.tone).toBe("gate");
    expect(rowBadges(byId(rows, 1))[0].label).toBe("weto HM");
    // Odrzuconego nikt już nie rusza — żadnych odznak.
    expect(rowBadges(byId(rows, 2))).toEqual([]);
  });

  it("kubełek poza szablonem: osobny wiersz z własnym następnym krokiem", () => {
    const rows = buildProcessRows(template(), {
      offTemplate: { name: "Poza szablonem", count: 1, items: [item(9, { stage: "legacy_x" })] },
    });
    expect(rows).toHaveLength(1);
    expect(rows[0].stageLabel).toBe("Poza szablonem");
    expect(rows[0].nextAction).toMatchObject({ owner: "recruiter", tone: "due" });
    expect(filterRows(rows, { segment: "off-template" })).toHaveLength(1);
    expect(filterRows(rows, { segment: "in-process" })).toHaveLength(1);
    expect(filterRows(rows, { segment: "group:intake" })).toHaveLength(0);
  });

  it("rekruter karty: właściciel procesu, a bez niego osoba dodająca", () => {
    const rows = buildProcessRows(
      template({
        1: [
          item(1, { recruiter_id: 5, recruiter_name: "Anna Nowicka" }),
          item(2, { added_to_job_by_name: "Jan Lis" }),
        ],
      }),
    );
    expect(byId(rows, 1)).toMatchObject({ recruiterId: 5, recruiterName: "Anna Nowicka" });
    expect(byId(rows, 2)).toMatchObject({ recruiterId: null, recruiterName: "Jan Lis" });
    expect(recruiterOptions(rows)).toEqual([{ id: 5, name: "Anna Nowicka" }]);
  });
});

describe("availabilityLabelFor", () => {
  const today = new Date("2026-09-21T12:00:00");
  it("data wygrywa ze statusem; miniona znaczy „od razu”", () => {
    expect(availabilityLabelFor({ availability_date: "2026-09-01", availability_status: "not_looking" }, today)).toBe("od razu");
    expect(availabilityLabelFor({ availability_date: "2026-11-01" }, today)).toMatch(/^od /);
  });
  it("status bez daty; `unknown` i brak pól to null", () => {
    expect(availabilityLabelFor({ availability_status: "open_to_offers" }, today)).toBe("Otwarty na oferty");
    expect(availabilityLabelFor({ availability_status: "unknown" }, today)).toBeNull();
    expect(availabilityLabelFor({}, today)).toBeNull();
  });
});

describe("sortRows", () => {
  const rows = buildProcessRows(
    template({
      1: [item(1, { days_in_stage: 3, lastname: "Zając" }), item(2, { days_in_stage: 9, lastname: "Adamski" })],
      2: [item(3, { days_in_stage: 8, lastname: "Baran" })],
      // U klienta < NUDGE_DAYS → ruch po stronie klienta.
      5: [item(4, { days_in_stage: 2, lastname: "Cichy" }), item(5, { days_in_stage: 4, lastname: "Duda" })],
      // Weto HM u klienta → bramka po stronie rekrutera.
      6: [
        item(6, {
          days_in_stage: 1,
          lastname: "Ewert",
          hm_veto: { hiring_manager_contact_id: 1, source_job_id: 1, rejected_at: "2026-09-01", rejection_reason_name: "x" },
        }),
      ],
    }),
  );

  it("domyślnie: najpierw MÓJ ruch (bramka > po terminie > zwykły), potem reszta po dniach malejąco", () => {
    const order = sortRows(rows, DEFAULT_PERSON_SORT).map((r) => r.candidateId);
    // 6 = bramka; 3 = po terminie (screening, 8 d). Reszta po dniach malejąco:
    // stos wejściowy (2: 9 d, 1: 3 d) to „Do przejrzenia", nie mój ruch —
    // stoi w jednym szeregu z osobami po stronie klienta (5: 4 d, 4: 2 d).
    expect(order).toEqual([6, 3, 2, 5, 1, 4]);
  });

  it("nie mutuje wejścia", () => {
    const snapshot = rows.map((r) => r.candidateId);
    sortRows(rows, { key: "name", dir: "asc" });
    expect(rows.map((r) => r.candidateId)).toEqual(snapshot);
  });

  it("po nazwisku, bez polskich znaków w kluczu", () => {
    expect(sortRows(rows, { key: "name", dir: "asc" }).map((r) => r.item.lastname)).toEqual([
      "Adamski", "Baran", "Cichy", "Duda", "Ewert", "Zając",
    ]);
  });

  it("w etapie najdłużej = dni malejąco", () => {
    expect(sortRows(rows, { key: "days", dir: "desc" })[0].candidateId).toBe(2);
  });

  it("dopasowanie: brak wyniku ląduje na końcu w OBU kierunkach", () => {
    const scored = buildProcessRows(template({ 1: [item(1), item(2), item(3)] }), {
      scores: new Map([[1, 60], [3, 90]]),
    });
    expect(sortRows(scored, { key: "fit", dir: "desc" }).map((r) => r.candidateId)).toEqual([3, 1, 2]);
    expect(sortRows(scored, { key: "fit", dir: "asc" }).map((r) => r.candidateId)).toEqual([1, 3, 2]);
  });
});

describe("filterRows i chipy", () => {
  const rows = buildProcessRows(
    template({
      1: [item(1, { days_in_stage: 9, name: "Łukasz", lastname: "Żak" }), item(2, { days_in_stage: 0 })],
      5: [item(3, { days_in_stage: 2 }), item(4, { days_in_stage: 6 })],
      10: [item(5, { days_in_stage: 40 })],
    }),
  );

  it("liczniki chipów", () => {
    const counts = chipCounts(filterRows(rows, { segment: "in-process" }));
    expect(counts).toMatchObject({
      mine: 1, // 4 (klient milczy ≥ 5 dni → ruch wraca do rekrutera)
      review: 2, // 1 i 2 — stos wejściowy
      overdue: 1,
      "waiting-client": 1,
      stuck: 1,
      "no-action": 1,
      warnings: 0,
    });
  });

  it("„Utknęli” pomija etapy terminalne", () => {
    const stuck = filterRows(rows, { segment: "closed", chips: ["stuck"] });
    expect(stuck).toHaveLength(0);
  });

  it("chipy zawężają łącznie", () => {
    const hit = filterRows(rows, { segment: "in-process", chips: new Set(["review", "no-action"] as const) });
    expect(hit.map((r) => r.candidateId)).toEqual([1]);
    expect(hit[0].nextAction.label).toBe(NO_NEXT_ACTION_LABEL);
  });

  it("tekst: bez polskich znaków (także „ł”), AND po słowach, szuka też po etapie", () => {
    expect(filterRows(rows, { segment: "in-process", text: "lukasz zak" }).map((r) => r.candidateId)).toEqual([1]);
    expect(filterRows(rows, { segment: "in-process", text: "cv wysłane" }).map((r) => r.candidateId)).toEqual([3, 4]);
    expect(filterRows(rows, { segment: "in-process", text: "lukasz cv" })).toHaveLength(0);
  });

  it("segmenty: grupa, pojedynczy etap, zamknięci; propozycje nie są wierszami procesu", () => {
    expect(filterRows(rows, { segment: "group:client" })).toHaveLength(2);
    expect(filterRows(rows, { segment: "stage:1" })).toHaveLength(2);
    expect(filterRows(rows, { segment: "closed" }).map((r) => r.candidateId)).toEqual([5]);
    expect(filterRows(rows, { segment: "in-process" })).toHaveLength(4);
    expect(filterRows(rows, { segment: "proposals" })).toHaveLength(0);
  });

  it("filtr rekrutera", () => {
    const owned = buildProcessRows(template({ 1: [item(1, { recruiter_id: 5 }), item(2, { recruiter_id: 6 })] }));
    expect(filterRows(owned, { segment: "in-process", recruiterId: 6 }).map((r) => r.candidateId)).toEqual([2]);
  });
});

describe("groupRowsByOwner", () => {
  const rows = buildProcessRows(
    template({
      1: [item(1, { days_in_stage: 2 })],
      5: [item(2, { days_in_stage: 1 })],
      7: [item(3, { days_in_stage: 1 })],
      9: [item(4, { days_in_stage: 30 })],
      2: [item(5, { days_in_stage: 20 }), item(7, { days_in_stage: 1 })],
      10: [item(6, { days_in_stage: 3 })],
    }),
  );

  it("stała kolejność grup, tylko niepuste, polskie etykiety", () => {
    const groups = groupRowsByOwner(rows);
    expect(groups.map((g) => g.label)).toEqual([
      "Wymaga mojego ruchu",
      "Czeka na klienta",
      "Czeka na kandydata",
      "Delivery",
      "Do przejrzenia",
      "Bez ruchu ponad 14 dni",
      "Zamknięci",
    ]);
    expect(groups.map((g) => g.rowKeys)).toEqual([["c:7"], ["c:2"], ["c:3"], ["c:4"], ["c:1"], ["c:5"], ["c:6"]]);
  });

  it("zatrudniony od miesiąca to Delivery, nie „bez ruchu”", () => {
    expect(ownerGroupOf(rows.find((r) => r.candidateId === 4)!)).toBe("delivery");
  });

  it("kolejność w grupie = kolejność wejścia (sortowanie użytkownika)", () => {
    const mine = buildProcessRows(template({ 1: [item(1, { lastname: "B" }), item(2, { lastname: "A" })] }));
    const sorted = sortRows(mine, { key: "name", dir: "asc" });
    expect(groupRowsByOwner(sorted)[0].rowKeys).toEqual(["c:2", "c:1"]);
  });

  it("grupowanie: próg automatyczny, wybór użytkownika wygrywa", () => {
    expect(shouldGroupRows(AUTO_GROUP_THRESHOLD, null)).toBe(false);
    expect(shouldGroupRows(AUTO_GROUP_THRESHOLD + 1, null)).toBe(true);
    expect(shouldGroupRows(500, false)).toBe(false);
    expect(shouldGroupRows(3, true)).toBe(true);
  });
});

describe("segmentCounts", () => {
  it("w procesie = nie-terminalne + poza szablonem; grupy i etapy osobno", () => {
    const columns = template({
      1: [item(1)],
      3: [item(2)],
      4: [item(3), item(4)],
      9: [item(5)],
      10: [item(6), item(7)],
    });
    const counts = segmentCounts(columns, { count: 2, items: [item(8), item(9)] });
    expect(counts.inProcess).toBe(4 + 2);
    expect(counts.groups.verification).toBe(3);
    expect(counts.groups.contract).toBe(1);
    expect(counts.stages[4]).toBe(2);
    expect(counts.offTemplate).toBe(2);
    expect(counts.closed).toBe(2);
  });
});

describe("defaultPanelSectionFor", () => {
  it("sekcja panelu wynika z etapu", () => {
    expect(defaultPanelSectionFor("screening")).toBe("screening");
    expect(defaultPanelSectionFor("verification")).toBe("cv");
    expect(defaultPanelSectionFor("client")).toBe("interviews");
    expect(defaultPanelSectionFor("contract")).toBe("contract");
    expect(defaultPanelSectionFor("intake")).toBe("notes");
    expect(defaultPanelSectionFor("closed")).toBe("notes");
  });

  it("„CV Wysłane” i etap przed rozmową otwierają CV, nie pustą sekcję rozmów", () => {
    const cvSent = { stage: "cv_sent", category: "internal", name: "CV Wysłane" } as never;
    const interview = { stage: "client_interview", category: "external", name: "Interview Klient" } as never;
    expect(defaultPanelSectionFor("client", cvSent)).toBe("cv");
    expect(defaultPanelSectionFor("client", interview)).toBe("interviews");
  });
});

describe("defaultCollapsedFor / firstVisibleRowKey", () => {
  const g = (key: string, n: number) => ({ key, label: key, rowKeys: Array.from({ length: n }, (_, i) => `${key}:${i}`) });

  it("zwija przegląd i „bez ruchu”, gdy jest co pokazać obok", () => {
    const collapsed = defaultCollapsedFor([g("mine", 2), g("review", 400), g("stale", 5)]);
    expect([...collapsed].sort()).toEqual(["review", "stale"]);
  });

  it("nigdy nie chowa wszystkiego — rozwija „bez ruchu” przed stosem wejściowym", () => {
    const groups = [g("review", 461), g("stale", 6)];
    const collapsed = defaultCollapsedFor(groups);
    expect(collapsed.has("stale")).toBe(false);
    expect(collapsed.has("review")).toBe(true);
    expect(firstVisibleRowKey(groups, collapsed)).toBe("stale:0");
  });

  it("sam stos wejściowy zostaje rozwinięty", () => {
    const groups = [g("review", 12)];
    expect(defaultCollapsedFor(groups).has("review")).toBe(false);
  });

  it("pierwsza widoczna osoba pochodzi z rozwiniętej grupy", () => {
    const groups = [g("review", 3), g("client", 2)];
    expect(firstVisibleRowKey(groups, defaultCollapsedFor(groups))).toBe("client:0");
  });
});

