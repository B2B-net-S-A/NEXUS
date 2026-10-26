import { describe, expect, it } from "vitest";

import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import {
  MY_MOVE_LABEL,
  cardBadges,
  cardNextStep,
  cardOwner,
  claimAction,
  dlSendQueue,
  formatClientRate,
  hoursLeft,
  isReadyForDlSend,
  knownForwardGap,
  minimumOnlyGap,
  qcChip,
  type CardBadgeContext,
  compactCardBadge,
  cardShortName,
  criticalGapBadge,
  cvStateBadge,
  dlWaitingStatus,
  fillGapsText,
  requirementsSkippedBadge,
  shortStepLabel,
} from "@/lib/board-card-badges";
import { WHY_CANDIDATE_LABEL, nextActionFor } from "@/lib/pipeline-next-action";

const NOW = new Date("2026-09-23T10:00:00Z");

function item(extra: Partial<KanbanItem> = {}): KanbanItem {
  return { id: 1, candidate_id: 11, stage: "new", ...extra } as KanbanItem;
}

function ctx(extra: Partial<CardBadgeContext> = {}): CardBadgeContext {
  return { column: "new", cproEnabled: false, viewerId: 7, now: NOW, ...extra };
}

const labels = (i: KanbanItem, c: CardBadgeContext) => cardBadges(i, c).map((b) => b.label);

describe("odznaki karty — Pipeline v4", () => {
  it("osoba dodana ręcznie: „Dodałeś sam” i „Twój · 9 h” dla trzymającego blokadę", () => {
    const own = item({
      entry_source: "added_manual",
      claim_user_id: 7,
      claim_user_name: "Marta Nowak",
      claim_until: "2026-09-23T19:30:00Z",
      added_to_job_by_name: "Marta Nowak",
    });
    expect(labels(own, ctx())).toEqual(["Dodałeś sam", "Twój · 9 h"]);
    expect(claimAction(own, ctx())).toBeNull();
  });

  it("cudza blokada: imię i czas; „Przejmij” tylko gdy serwer pozwala (DL)", () => {
    const other = item({
      entry_source: "added_manual",
      claim_user_id: 3,
      claim_user_name: "Anna Kowal",
      claim_until: "2026-09-23T13:10:00Z",
      added_to_job_by_name: "Anna Kowal",
    });
    expect(labels(other, ctx())).toEqual(["Dodał(a): Anna", "Anna · 3 h"]);
    expect(claimAction(other, ctx())).toBeNull();
    expect(claimAction({ ...other, can_take: true }, ctx())).toBe("takeover");
  });

  it("wolna osoba z ogłoszenia: „Wolny” i „Biorę”", () => {
    const free = item({ entry_source: "application", can_take: true });
    expect(labels(free, ctx())).toEqual(["Z ogłoszenia", "Wolny"]);
    expect(claimAction(free, ctx())).toBe("take");
    // Poza „Nowymi” nikt niczego nie bierze.
    expect(claimAction(free, ctx({ column: "verified" }))).toBeNull();
    // Screening to ta sama część procesu co Nowi (blokada 12 h).
    expect(claimAction(free, ctx({ column: "screening" }))).toBe("take");
    expect(labels(free, ctx({ column: "screening" }))).toEqual(["Z ogłoszenia", "Wolny"]);
  });

  it("wejście z automatu niesie wynik zamiast notatki (0399)", () => {
    const auto = item({
      entry_source: "auto_match",
      entry_auto_match: { score: 67, source: "jjit", must_hit: ["Java"], must_total: 2 },
    });
    const badges = cardBadges(auto, ctx());
    expect(badges.map((b) => b.label)).toEqual(["Auto-match 67/100 · JJIT", "Wolny"]);
    expect(badges[0].title).toContain("Must-have: 1/2 (Java).");
    // Proces sprzed 0399 (bez wyniku) — dawna etykieta.
    expect(labels(item({ entry_source: "auto_match" }), ctx())[0]).toBe("Z automatu");
  });

  it("champion: złota plakietka zawsze pierwsza, pełnym napisem (D3, 15.10.2026)", () => {
    const champion = item({
      stage: "client_interview",
      is_champion: true,
      entry_source: "reassign",
      reassign_from_reference: "ZOB-1725",
    });
    const badges = cardBadges(champion, ctx({ column: "client_interview" }));
    expect(badges[0]).toEqual({
      key: "champion",
      label: "Champion",
      tone: "champion",
      title: "Champion tej rekrutacji — oznaczył Delivery Lead.",
    });
    expect(badges[1].key).toBe("reassign");
    // Nie skraca się do ikony — „Champion” ma być czytelny na karcie.
    expect(compactCardBadge(badges[0])).toBeNull();
    expect(labels(item({ stage: "client_interview" }), ctx({ column: "client_interview" }))).not.toContain(
      "Champion",
    );
  });

  it("przepięcie niesie rekrutację źródłową", () => {
    const re = item({ entry_source: "reassign", reassign_from_title: "Java · PKO BP" });
    expect(labels(re, ctx())[0]).toBe("Przepięcie · Java · PKO BP");
    const withRef = item({
      entry_source: "reassign",
      reassign_from_title: "Analityk Systemowy",
      reassign_from_reference: "ZOB-1725",
    });
    expect(labels(withRef, ctx())[0]).toBe("↻ z ZOB-1725");
  });

  it("„Czeka na DL” w QC CV (u Nordei — akceptacja do Cpro), w kolejce Cpro i w Zweryfikowanym nie", () => {
    const v = item({ stage: "interview", days_in_stage: 1, qc: { status: "passed", blocking_failed: 0 } });
    expect(labels(v, ctx({ column: "cv_qc" }))).toEqual(["Czeka na DL · 1 dzień"]);
    // Niesprawdzone QC: DL jeszcze na nic nie czeka.
    const unchecked = item({ stage: "interview", days_in_stage: 1 });
    expect(labels(unchecked, ctx({ column: "cv_qc" }))).toEqual([]);
    // Od 13.10.2026 u Nordei DL akceptuje osobę do kolejki Cpro.
    const nordea = cardBadges(v, ctx({ column: "cv_qc", cproEnabled: true }));
    expect(nordea.map((b) => b.label)).toEqual(["Czeka na DL · 1 dzień"]);
    expect(nordea[0].title).toContain("akceptuje osobę do kolejki Cpro");
    // Karta już w kolejce Cpro czeka na osobę od Cpro, nie na DL-a.
    expect(labels(v, ctx({ column: "cv_qc", cproEnabled: true, stageBadge: "cpro" }))).toEqual([]);
    expect(labels(v, ctx({ column: "verified" }))).toEqual([]);
  });

  it("stawka do klienta i cisza klienta w „CV wysłane”", () => {
    const sent = item({
      stage: "cv_sent",
      client_rate_value: "165.00",
      client_rate_unit: "hourly",
      client_rate_currency: "PLN",
      days_in_stage: 5,
    });
    expect(labels(sent, ctx({ column: "cv_sent" }))).toEqual([
      "do klienta 165 zł/h",
      "5 dni bez odpowiedzi",
    ]);
  });

  it("terminarz rozmowy i zamówienie po zatrudnieniu", () => {
    const iv = item({
      interview_badge: { kind: "call_due", label: "Zadzwoń · 18 min po rozmowie", tone: "urgent" },
    });
    expect(cardBadges(iv, ctx({ column: "client_interview" }))).toEqual([
      { key: "interview", label: "Zadzwoń · 18 min po rozmowie", tone: "urgent" },
    ]);
    // Osoba przesunięta dalej z zaległym telefonem: odznaka nie znika
    // (produkcja 24.09.2026 — karta w „Umowie” wyglądała na załatwioną).
    expect(labels(iv, ctx({ column: "contract" }))).toContain("Zadzwoń · 18 min po rozmowie");
    expect(labels(iv, ctx({ column: "cv_sent" }))).toContain("Zadzwoń · 18 min po rozmowie");
    // 20.10.2026: brak zamówienia to cudzy krok po zatrudnieniu — neutralnie.
    const missingOrder = cardBadges(item({ order_status: "missing" }), ctx({ column: "hired" }));
    expect(missingOrder.map((b) => b.label)).toEqual(["Zamówienie: u Delivery Leada"]);
    expect(missingOrder[0]).toMatchObject({ key: "order", tone: "neutral" });
    expect(missingOrder[0].title).toContain("nie jest warunkiem zatrudnienia");
    expect(labels(item({ order_status: "complete" }), ctx({ column: "hired" }))).toEqual([
      "Zamówienie ✓",
    ]);
  });

  it("„Zatrudniony” bez umowy w Kontraktach: odznaka przed zamówieniem, tylko w tej kolumnie (17.10.2026)", () => {
    const noContract = item({ missing_contract: true, order_status: "missing" });
    const badges = cardBadges(noContract, ctx({ column: "hired" }));
    expect(badges.map((b) => b.label)).toEqual([
      "Brak umowy w Kontraktach",
      "Zamówienie: u Delivery Leada",
    ]);
    expect(badges[0]).toMatchObject({ key: "contract", tone: "wait" });
    expect(badges[0].title).toContain("„Pracuje u nas” pojawi się po wpisaniu umowy");
    // Inna kolumna (karta cofnięta z „Zatrudniony”) i karta z umową — bez odznaki.
    expect(labels(noContract, ctx({ column: "contract" }))).not.toContain("Brak umowy w Kontraktach");
    expect(labels(item({ missing_contract: false }), ctx({ column: "hired" }))).toEqual([]);
  });

  it("prepy w Teams: brak prepu i słaby prep jak inne odznaki terminarza, z podpowiedzią", () => {
    const missing = item({
      interview_badge: { kind: "prep_missing", label: "Brak prepu · rozmowa jutro", tone: "urgent" },
    });
    const [badge] = cardBadges(missing, ctx({ column: "client_interview" }));
    expect(badge).toMatchObject({ key: "interview", label: "Brak prepu · rozmowa jutro", tone: "urgent" });
    expect(badge.title).toContain("brakuje prepu");
    const weak = item({
      interview_badge: { kind: "prep_weak", label: "Prep słaby · rozmowa czw 25.09", tone: "wait" },
    });
    expect(cardBadges(weak, ctx({ column: "client_interview" }))[0]).toMatchObject({
      label: "Prep słaby · rozmowa czw 25.09",
      tone: "wait",
    });
  });

  it("pomocnicze: godziny blokady i format stawki", () => {
    expect(hoursLeft("2026-09-23T10:30:00Z", NOW)).toBe("<1 h");
    expect(formatClientRate(item({ client_rate_value: "1200", client_rate_unit: "daily" }))).toBe(
      "do klienta 1200 zł/MD",
    );
    expect(formatClientRate(item({ client_rate_value: null }))).toBeNull();
  });
});

describe("Rekrutacja v5: chip QC, znany brak i „kto ma ruch”", () => {
  it("chip QC mówi wynik ostatniej kontroli; brak pola = „nie sprawdzone”", () => {
    expect(qcChip(item({})).label).toBe("QC nie sprawdzone");
    expect(qcChip(item({ qc: { status: "passed", blocking_failed: 0 } })).label).toBe("QC ✓");
    expect(qcChip(item({ qc: { status: "failed", blocking_failed: 3 } }))).toMatchObject({
      label: "QC: 3 do poprawy",
      tone: "urgent",
    });
    expect(qcChip(item({ qc: { status: "overridden", blocking_failed: 2 } })).label).toBe(
      "QC przepuszczone",
    );
  });

  it("strzałka jest szara tylko przy brakach, które karta zna", () => {
    expect(knownForwardGap(item({ screening_done: false }), "screening")).toBe("Brak arkusza screeningu");
    expect(knownForwardGap(item({ screening_done: true }), "screening")).toBeNull();
    // Brak pola (starszy serwer) to nie brak arkusza.
    expect(knownForwardGap(item({}), "screening")).toBeNull();
    // Rekrutacja bez pytań screeningowych: brakuje oceny, nie arkusza (13.10.2026).
    expect(
      knownForwardGap(item({ screening_done: false, screening_requirement: "why_candidate" }), "screening"),
    ).toBe("Brak „Dlaczego ten kandydat”");
    expect(
      knownForwardGap(item({ screening_done: true, screening_requirement: "why_candidate" }), "screening"),
    ).toBeNull();
    expect(knownForwardGap(item({ qc: { status: "failed", blocking_failed: 2 } }), "cv_qc")).toBe(
      "QC: 2 do poprawy",
    );
    expect(knownForwardGap(item({ qc: { status: "unchecked", blocking_failed: 0 } }), "cv_qc")).toBeNull();
  });

  // 22.10.2026: Delivery Lead przesuwa bez bramek pól — zna tylko brak QC.
  it("Delivery Lead: strzałka nie jest szara przez arkusz, minimum ani CV firmowe", () => {
    const dl = { skipsFillGates: true };
    expect(knownForwardGap(item({ screening_done: false }), "screening", dl)).toBeNull();
    expect(knownForwardGap(item({ screening_done: true, minimum_missing: ["location"] }), "screening", dl)).toBeNull();
    expect(knownForwardGap(item({ company_cv: false }), "verified", dl)).toBeNull();
    expect(knownForwardGap(item({ qc: { status: "failed", blocking_failed: 1 } }), "cv_qc", dl)).toBe("QC: 1 do poprawy");
  });

  it("komunikat strzałki DL-a wymienia braki", () => {
    expect(
      fillGapsText(item({ screening_done: false, minimum_missing: ["location", "work_mode"] }), "screening", "verified"),
    ).toBe("bez: arkusza screeningu, stawki kandydata, lokalizacja, tryb pracy");
    expect(
      fillGapsText(
        item({ screening_done: true, expected_rate_value: "140", minimum_missing: [] }),
        "screening",
        "verified",
      ),
    ).toBeNull();
    // Stawka z profilu kandydata spełnia bramkę na serwerze — komunikat jej nie wymienia.
    expect(
      fillGapsText(
        item({ screening_done: true, expected_rate_value: null, candidate_expected_rate_hourly: 150, minimum_missing: [] }),
        "screening",
        "verified",
      ),
    ).toBeNull();
    // Z Nowych do Screeningu nie ma bramki — komunikat nic nie wymienia.
    expect(fillGapsText(item({ screening_done: false }), "new", "screening")).toBeNull();
    expect(fillGapsText(item({ company_cv: false }), "verified", "cv_qc")).toBe("bez: CV firmowego");
  });

  it("odznaka „Przesunął DL” od „Zweryfikowanego”, nie w Nowych i Zamkniętych", () => {
    const moved = item({
      requirements_skipped: ["screening_sheet", "candidate_rate"],
      requirements_skipped_by_name: "Anna Nowak",
    });
    expect(requirementsSkippedBadge(moved, "verified")).toMatchObject({
      label: "Przesunął DL · bez arkusza i stawki",
      tone: "wait",
    });
    expect(requirementsSkippedBadge(moved, "verified")?.title).toContain("Anna Nowak");
    expect(requirementsSkippedBadge(moved, "screening")).toBeNull();
    expect(requirementsSkippedBadge(moved, "closed")).toBeNull();
    expect(requirementsSkippedBadge(item({}), "verified")).toBeNull();
    const many = item({ requirements_skipped: ["screening_sheet", "candidate_rate", "location"] });
    expect(requirementsSkippedBadge(many, "cv_sent")?.label).toBe("Przesunął DL · bez 3 pól");
  });

  // 21.10.2026: minimum dla Delivery Leada blokuje „Zweryfikowany”.
  it("brak minimum dla DL robi strzałkę szarą — dopiero po arkuszu", () => {
    const gap = item({ screening_done: true, minimum_missing: ["location", "work_mode"] });
    expect(knownForwardGap(gap, "screening")).toBe("Brak: lokalizacja, tryb pracy");
    expect(minimumOnlyGap(gap)).toBe(true);
    // Brak arkusza mówi pierwszy; okno minimum nie zastępuje formularza.
    const noSheet = item({ screening_done: false, minimum_missing: ["location"] });
    expect(knownForwardGap(noSheet, "screening")).toBe("Brak arkusza screeningu");
    expect(minimumOnlyGap(noSheet)).toBe(false);
    // Starszy serwer (brak pola) albo pusta lista = bez braku.
    expect(minimumOnlyGap(item({ screening_done: true }))).toBe(false);
    expect(knownForwardGap(item({ screening_done: true, minimum_missing: [] }), "screening")).toBeNull();
  });

  // 14.10.2026: przeciągnięcie ze „Zweryfikowanego” bez CV firmowego wkładało
  // osobę wprost do kolejki Delivery Leada w „QC CV”.
  it("ze „Zweryfikowanego” bez CV firmowego strzałka jest szara; nieznany stan CV nie jest brakiem", () => {
    expect(knownForwardGap(item({ company_cv: false }), "verified")).toBe("Brak CV firmowego");
    expect(knownForwardGap(item({ company_cv: true }), "verified")).toBeNull();
    // Starszy serwer (brak pola) albo `null` = nie wiadomo — bez blokady.
    expect(knownForwardGap(item({}), "verified")).toBeNull();
    expect(knownForwardGap(item({ company_cv: null }), "verified")).toBeNull();
    // Pole dotyczy tylko wyjścia ze „Zweryfikowanego”.
    expect(knownForwardGap(item({ company_cv: false }), "screening")).toBeNull();
  });

  it("w QC CV ruch ma rekruter (poprawki), DL (wysyłka albo akceptacja do Cpro) albo osoba od Cpro", () => {
    const action = { label: "Popraw CV / wyślij", owner: "recruiter", kind: "cv" };
    const failed = item({ qc: { status: "failed", blocking_failed: 1 } });
    expect(cardNextStep(action, failed, { column: "cv_qc", cproEnabled: false })).toMatchObject({
      who: "Twój ruch",
      mine: true,
    });
    const passed = item({ qc: { status: "passed", blocking_failed: 0 } });
    expect(cardNextStep(action, passed, { column: "cv_qc", cproEnabled: false })?.who).toBe("DL");
    // Niesprawdzone QC = ruch rekrutera, nie DL.
    expect(cardNextStep(action, item({}), { column: "cv_qc", cproEnabled: false })).toMatchObject({
      who: "Twój ruch",
      label: "Sprawdź QC CV",
    });
    expect(
      cardNextStep(action, item({}), { column: "cv_qc", cproEnabled: true, stageBadge: "cpro" })?.who,
    ).toBe("Osoba od Cpro");
    // U Nordei gotowa karta czeka na akceptację DL-a (13.10.2026).
    expect(cardNextStep(action, passed, { column: "cv_qc", cproEnabled: true })).toEqual({
      who: "DL",
      mine: false,
      label: "Przegląd CV i akceptacja do Cpro",
    });
    // Poza QC — lustro `nextActionFor`: klient to nie „Twój ruch”.
    expect(
      cardNextStep({ label: "Feedback klienta", owner: "client", kind: "client" }, item({}), {
        column: "cv_sent",
        cproEnabled: false,
      }),
    ).toEqual({ who: "Klient", mine: false, label: "Feedback klienta" });
    expect(
      cardNextStep({ label: "", owner: "none", kind: "none" }, item({}), { column: "closed", cproEnabled: false }),
    ).toBeNull();
  });

  it("„Twój ruch” tylko na własnej (albo niczyjej) karcie — cudza mówi imię rekrutera", () => {
    const action = { label: "Przygotuj CV do QC", owner: "recruiter", kind: "cv" };
    const mine = item({ recruiter_id: 7, recruiter_name: "Klaudia Urban" });
    expect(cardNextStep(action, mine, { column: "verified", cproEnabled: false, viewerId: 7 })).toEqual({
      who: "Twój ruch",
      mine: true,
      label: "Przygotuj CV do QC",
    });
    expect(cardNextStep(action, mine, { column: "verified", cproEnabled: false, viewerId: 9 })).toEqual({
      who: "Klaudia",
      mine: false,
      label: "Przygotuj CV do QC",
    });
    // Karta bez rekrutera — nikt jej nie „ma”, ruch jest po stronie patrzącego.
    expect(cardNextStep(action, item({}), { column: "verified", cproEnabled: false, viewerId: 9 })?.who).toBe(
      "Twój ruch",
    );
    // Nowi: aktywna blokada „Biorę” wygrywa z rekruterem karty.
    const claimed = item({ recruiter_id: 9, claim_user_id: 3, claim_user_name: "Ola Nowak" });
    expect(
      cardNextStep({ label: "Umów screening", owner: "review", kind: "screening" }, claimed, {
        column: "new",
        cproEnabled: false,
        viewerId: 9,
      })?.who,
    ).toBe("Ola");
    // Kandydat i Delivery to role, nie imiona.
    expect(
      cardNextStep({ label: "Reakcja kandydata na ofertę", owner: "candidate", kind: "offer" }, mine, {
        column: "contract",
        cproEnabled: false,
        viewerId: 7,
      })?.who,
    ).toBe("Kandydat");
    expect(
      cardNextStep({ label: "Przekaż do Delivery", owner: "delivery", kind: "contract" }, mine, {
        column: "hired",
        cproEnabled: false,
        viewerId: 7,
      })?.who,
    ).toBe("Delivery");
  });
});

describe("„Do wysłania do klienta” — Delivery Lead tej rekrutacji (13.10.2026)", () => {
  // NOW = 23.09.2026 12:00 w Warszawie (czas letni, UTC+2).
  const action = { label: "Popraw CV / wyślij", owner: "recruiter", kind: "cv" };
  const ready = item({ stage: "interview", days_in_stage: 1, qc: { status: "passed", blocking_failed: 0 } });
  const owner = { column: "cv_qc" as const, cproEnabled: false, viewerOwnsDlReview: true };

  it("gotowa do wysłania jest karta w „QC CV” poza Cpro, z QC zaliczonym albo przepuszczonym", () => {
    expect(isReadyForDlSend(ready, "cv_qc", false)).toBe(true);
    expect(isReadyForDlSend(item({ qc: { status: "overridden", blocking_failed: 2 } }), "cv_qc", false)).toBe(true);
    expect(isReadyForDlSend(item({ qc: { status: "failed", blocking_failed: 1 } }), "cv_qc", false)).toBe(false);
    expect(isReadyForDlSend(item({ qc: { status: "unchecked", blocking_failed: 0 } }), "cv_qc", false)).toBe(false);
    expect(isReadyForDlSend(item({}), "cv_qc", false)).toBe(false);
    // Karta w kolejce Cpro (znacznik w tej samej kolumnie) czeka na osobę od Cpro.
    expect(isReadyForDlSend(ready, "cv_qc", true)).toBe(false);
    expect(isReadyForDlSend(ready, "verified", false)).toBe(false);
    expect(isReadyForDlSend(ready, null, false)).toBe(false);
  });

  it("właściciel przeglądu ma „Twój ruch” i „Czeka na Ciebie”; pozostali dalej „DL” i „Czeka na DL”", () => {
    expect(cardNextStep(action, ready, owner)).toEqual({
      who: MY_MOVE_LABEL,
      mine: true,
      label: "Przegląd CV i wysłanie do klienta",
    });
    const mine = cardBadges(ready, ctx({ column: "cv_qc", viewerOwnsDlReview: true }));
    expect(mine).toEqual([
      {
        key: "dl_review",
        label: "Czeka na Ciebie · 1 dzień",
        tone: "wait",
        title: "Przejrzyj CV, wpisz stawkę do klienta i wyślij.",
      },
    ]);
    // Inny Delivery Lead, admin i rekruter — bez zmian.
    expect(cardNextStep(action, ready, { column: "cv_qc", cproEnabled: false })).toEqual({
      who: "DL",
      mine: false,
      label: "Przegląd CV i wysłanie do klienta",
    });
    expect(cardNextStep(action, ready, { ...owner, viewerOwnsDlReview: false })?.who).toBe("DL");
    expect(cardBadges(ready, ctx({ column: "cv_qc" }))).toEqual([
      {
        key: "dl_review",
        label: "Czeka na DL · 1 dzień",
        tone: "wait",
        title: "Delivery Lead przegląda CV i wpisuje stawkę do klienta przed wysłaniem.",
      },
    ]);
  });

  it("własność przeglądu nie zabiera ruchu rekruterowi ani kolejce Cpro", () => {
    const failed = item({ qc: { status: "failed", blocking_failed: 1 } });
    expect(cardNextStep(action, failed, owner)).toMatchObject({ who: "Twój ruch", label: "Popraw CV wg QC" });
    expect(cardNextStep(action, item({}), owner)).toMatchObject({ label: "Sprawdź QC CV" });
    expect(cardNextStep(action, ready, { ...owner, cproEnabled: true })).toEqual({
      who: MY_MOVE_LABEL,
      mine: true,
      label: "Przegląd CV i akceptacja do Cpro",
    });
    expect(
      cardNextStep(action, ready, { ...owner, cproEnabled: true, stageBadge: "cpro" })?.who,
    ).toBe("Osoba od Cpro");
    expect(labels(failed, ctx({ column: "cv_qc", viewerOwnsDlReview: true }))).toEqual([]);
    expect(
      labels(ready, ctx({ column: "cv_qc", cproEnabled: true, viewerOwnsDlReview: true, stageBadge: "cpro" })),
    ).toEqual([]);
  });

  it("dni liczą się od gotowości: późniejsze z wejścia do kolumny i zaliczenia QC", () => {
    const waited = (extra: Partial<KanbanItem>, viewerOwnsDlReview = true) =>
      labels(item({ stage: "interview", days_in_stage: 5, ...extra }), ctx({ column: "cv_qc", viewerOwnsDlReview }));
    // W kolumnie od 5 dni, QC zaliczone przedwczoraj — czeka 2 dni, nie 5.
    const lateQc = {
      moved_at: "2026-09-18T08:00:00Z",
      qc: { status: "passed" as const, blocking_failed: 0, ok_at: "2026-09-21T15:00:00Z" },
    };
    expect(waited(lateQc)).toEqual(["Czeka na Ciebie · 2 dni"]);
    expect(waited(lateQc, false)).toEqual(["Czeka na DL · 2 dni"]);
    // QC zaliczone wcześniej niż wejście do kolumny (karta wróciła po poprawkach).
    expect(
      waited({
        moved_at: "2026-09-22T08:00:00Z",
        qc: { status: "overridden", blocking_failed: 1, ok_at: "2026-09-19T08:00:00Z" },
      }),
    ).toEqual(["Czeka na Ciebie · 1 dzień"]);
    // Dni kalendarzowe w Warszawie: 22.09 23:30 to „wczoraj”, 23.09 00:30 — „dziś”
    // (oba zapisy mają w UTC datę 22.09).
    expect(
      waited({
        moved_at: "2026-09-18T08:00:00Z",
        qc: { status: "passed", blocking_failed: 0, ok_at: "2026-09-22T21:30:00Z" },
      }),
    ).toEqual(["Czeka na Ciebie · 1 dzień"]);
    expect(
      waited({
        moved_at: "2026-09-18T08:00:00Z",
        qc: { status: "passed", blocking_failed: 0, ok_at: "2026-09-22T22:30:00Z" },
      }),
    ).toEqual(["Czeka na Ciebie · dziś"]);
    // Bez którejś z dat (starszy serwer) zostają dni na etapie.
    expect(waited({ moved_at: "2026-09-18T08:00:00Z", qc: { status: "passed", blocking_failed: 0 } })).toEqual([
      "Czeka na Ciebie · 5 dni",
    ]);
    expect(
      waited({ qc: { status: "passed", blocking_failed: 0, ok_at: "2026-09-21T15:00:00Z" } }),
    ).toEqual(["Czeka na Ciebie · 5 dni"]);
    expect(
      waited({ moved_at: "2026-09-18T08:00:00Z", qc: { status: "passed", blocking_failed: 0, ok_at: null } }),
    ).toEqual(["Czeka na Ciebie · 5 dni"]);
  });

  it("kolejka „po kolei”: tylko gotowe karty, najdłużej czekające pierwsze", () => {
    const passed = (id: number, extra: Partial<KanbanItem>) =>
      item({ id, candidate_id: id, qc: { status: "passed", blocking_failed: 0 }, ...extra });
    const cards = [
      passed(1, { moved_at: "2026-09-22T08:00:00Z", qc: { status: "passed", blocking_failed: 0, ok_at: "2026-09-22T09:00:00Z" } }),
      // W kolumnie najdłużej, ale QC zaliczone dopiero dziś — idzie na koniec.
      passed(2, { moved_at: "2026-09-10T08:00:00Z", qc: { status: "passed", blocking_failed: 0, ok_at: "2026-09-23T08:00:00Z" } }),
      item({ id: 3, candidate_id: 3, qc: { status: "failed", blocking_failed: 1 } }),
      passed(4, { moved_at: "2026-09-20T08:00:00Z", qc: { status: "overridden", blocking_failed: 1, ok_at: "2026-09-20T09:00:00Z" } }),
      // Bez dat: miejsce według dni na etapie (3 dni temu).
      passed(5, { days_in_stage: 3 }),
      item({ id: 6, candidate_id: 6 }),
    ];
    const before = cards.map((c) => c.id);
    expect(dlSendQueue(cards, () => false, NOW).map((c) => c.id)).toEqual([4, 5, 1, 2]);
    // Lista z tablicy zostaje w swojej kolejności.
    expect(cards.map((c) => c.id)).toEqual(before);
    // Karty w kolejce Cpro (u Nordei ta sama kolumna) nie czekają na DL-a.
    expect(dlSendQueue(cards, (c) => c.id === 4 || c.id === 1, NOW).map((c) => c.id)).toEqual([5, 2]);
    expect(dlSendQueue(cards, () => true, NOW)).toEqual([]);
  });
});

describe("odznaka follow-upu (0372) — klient milczy, kto dzwoni do kandydata", () => {
  const badge = {
    caller_id: 3,
    caller_name: "Anna Kowalczyk",
    due_on: "2026-09-21",
    state: "overdue" as const,
    overdue_days: 2,
    process_count: 3,
  };

  it("zaległy telefon innej osoby: imię i liczba dni, czerwona odznaka", () => {
    const badges = cardBadges(item({ followup: badge }), ctx({ column: "cv_sent" }));
    const f = badges.find((b) => b.key === "followup");
    expect(f?.label).toBe("Follow-up: Anna K. · zaległy 2 dni");
    expect(f?.tone).toBe("urgent");
    expect(f?.title).toContain("w 3 procesach");
  });

  it("gdy dzwoni patrzący — „Ty”; termin za kilka dni nie zaśmieca karty", () => {
    const mine = item({ followup: { ...badge, caller_id: 7, state: "today", overdue_days: 0 } });
    expect(labels(mine, ctx({ column: "client_interview" }))).toContain("Follow-up: Ty · dziś");
    const later = item({ followup: { ...badge, state: "scheduled", overdue_days: 0 } });
    expect(cardBadges(later, ctx({ column: "cv_sent" })).some((b) => b.key === "followup")).toBe(
      false,
    );
  });

  it("poza kolumnami czekania na klienta odznaki nie ma", () => {
    expect(
      cardBadges(item({ followup: badge }), ctx({ column: "contract" })).some(
        (b) => b.key === "followup",
      ),
    ).toBe(false);
  });
});

describe("compactCardBadge — ikony zamiast napisów (PR 4, 04.10.2026)", () => {
  it("źródło to sama ikona, pełna treść w podpowiedzi", () => {
    expect(
      compactCardBadge({ key: "source", label: "Dodał(a): Anna", tone: "neutral", title: "Do rekrutacji dodał(a): Anna Nowak" }),
    ).toEqual({ short: null, full: "Dodał(a): Anna — Do rekrutacji dodał(a): Anna Nowak" });
  });

  it("moja blokada pokazuje godziny, cudza — imię i godziny, wolna — samą ikonę", () => {
    expect(compactCardBadge({ key: "claim", label: "Twój · 11 h", tone: "own" })?.short).toBe("11 h");
    expect(compactCardBadge({ key: "claim", label: "Anna · 3 h", tone: "lock" })?.short).toBe("Anna · 3 h");
    expect(compactCardBadge({ key: "claim", label: "Wolny", tone: "free" })?.short).toBeNull();
  });

  it("karta rekomendacji: liczba braków albo ✓; próby kontaktu zostają napisem", () => {
    expect(compactCardBadge({ key: "recommendation_card", label: "Screening: brakuje 3", tone: "wait" })?.short).toBe("−3");
    expect(compactCardBadge({ key: "recommendation_card", label: "Screening: komplet", tone: "ok" })?.short).toBe("✓");
    expect(compactCardBadge({ key: "recommendation_card", label: "Screening: puste pola", tone: "neutral" })?.short).toBeNull();
    expect(compactCardBadge({ key: "recommendation_card", label: "2 próby kontaktu", tone: "neutral" })).toBeNull();
  });

  it("pozostałe plakietki (np. QC, przegląd DL) zostają pełnym napisem", () => {
    expect(compactCardBadge({ key: "dl_review", label: "Czeka na DL · 2 dni", tone: "wait" })).toBeNull();
  });
});

describe("karta na laptopie (04.10.2026)", () => {
  it("krótka nazwa osoby bez dwukropka konta integracji", () => {
    expect(cardShortName("Integracje: JJIT")).toBe("Integracje");
    expect(cardShortName("  Marta Nowak ")).toBe("Marta");
    expect(cardShortName("")).toBeNull();
    expect(cardShortName(null)).toBeNull();
  });

  it("skraca długie nazwy kroków, reszta bez zmian", () => {
    expect(shortStepLabel("Przygotuj CV do QC")).toBe("CV do QC");
    expect(shortStepLabel("Umów interview / feedback klienta")).toBe("Umów rozmowę");
    expect(shortStepLabel("Feedback klienta")).toBe("Feedback klienta");
  });

  it("rekrutacja bez pytań: krok na karcie mówi o „Dlaczego ten kandydat”, nie o arkuszu (13.10.2026)", () => {
    expect(WHY_CANDIDATE_LABEL).toBe("Wpisz „Dlaczego ten kandydat”");
    expect(shortStepLabel(WHY_CANDIDATE_LABEL)).toBe("Wpisz ocenę");
    expect(shortStepLabel("Uzupełnij arkusz screeningu")).toBe("Arkusz screeningu");
  });

  it("skraca kroki cyklu rozmowy u klienta (05.10.2026)", () => {
    expect(shortStepLabel("Wybierz termin rozmowy")).toBe("Wybierz termin");
    expect(shortStepLabel("Rozmowa 08.10 — prep z kandydatem")).toBe("Prep · rozmowa 08.10");
    expect(shortStepLabel("Telefon po rozmowie i debrief")).toBe("Telefon i debrief");
  });

  it("karta w „Rozmowie u klienta” z wyborem terminu to ruch rekrutera, nie klienta", () => {
    const item = {
      id: 1,
      candidate_id: 1,
      stage: "client_interview",
      days_in_stage: 1,
      interview_badge: {
        kind: "choose_slot",
        label: "Wybierz termin · 2 propozycje",
        tone: "wait",
        phase: "awaiting_recruiter_pick",
      },
    } as KanbanItem;
    const column = {
      stage: "client_interview",
      category: "external",
      name: "Rozmowa u klienta",
      count: 1,
      items: [item],
    } as unknown as KanbanColumn;
    const step = cardNextStep(nextActionFor(item, column, { group: "client" }), item, {
      column: "client_interview",
      cproEnabled: false,
    });
    expect(step).toEqual({ who: MY_MOVE_LABEL, mine: true, label: "Wybierz termin rozmowy" });
  });
});

describe("„Nowy · N dni” — osoba świeżo w bazie (13.10.2026)", () => {
  const fresh = (extra: Partial<KanbanItem> = {}) =>
    item({
      entry_source: "application",
      can_take: true,
      candidate_added_at: "2026-09-20T08:00:00Z",
      candidate_added_exact: true,
      candidate_added_by_name: "Marta Nowak",
      ...extra,
    });

  it("w „Nowych” i „Screeningu” po źródle i blokadzie, z datą i autorem w dymku", () => {
    expect(labels(fresh(), ctx())).toEqual(["Z ogłoszenia", "Wolny", "Nowy · 3 dni"]);
    expect(labels(fresh(), ctx({ column: "screening" }))).toEqual([
      "Z ogłoszenia",
      "Wolny",
      "Nowy · 3 dni",
    ]);
    const badge = cardBadges(fresh(), ctx()).find((b) => b.key === "new_in_base");
    expect(badge).toMatchObject({ tone: "info", title: "W bazie od 20.09.2026 · dodał(a) Marta Nowak" });
    // Krótki napis — nie ikona jak źródło i blokada.
    expect(compactCardBadge(badge!)).toBeNull();
  });

  it("dalsze kolumny jej nie pokazują", () => {
    expect(labels(fresh(), ctx({ column: "verified" }))).not.toContain("Nowy · 3 dni");
  });

  it("15 dni i więcej — bez pigułki; 14 dni — jeszcze z pigułką", () => {
    expect(labels(fresh({ candidate_added_at: "2026-09-08T10:00:00Z" }), ctx())).toEqual([
      "Z ogłoszenia",
      "Wolny",
    ]);
    expect(labels(fresh({ candidate_added_at: "2026-09-09T10:00:00Z" }), ctx())).toContain("Nowy · 14 dni");
  });

  it("data niedokładna (import z Traffita bez daty u źródła) — bez pigułki", () => {
    expect(labels(fresh({ candidate_added_exact: false }), ctx())).toEqual(["Z ogłoszenia", "Wolny"]);
  });

  it("dodana dziś", () => {
    expect(labels(fresh({ candidate_added_at: "2026-09-23T06:00:00Z" }), ctx())).toContain("Nowy · dziś");
  });
});

describe("stan CV firmowego na karcie (14.10.2026)", () => {
  const label = (i: KanbanItem, column: Parameters<typeof cvStateBadge>[1] = "verified") =>
    cvStateBadge(i, column)?.label ?? null;

  it("automat pisze CV — „CV w przygotowaniu…”, nawet gdy stare CV ma wynik QC", () => {
    expect(label(item({ auto_cv_state: "processing" }))).toBe("CV w przygotowaniu…");
    expect(
      label(item({ auto_cv_state: "processing", company_cv: true, qc: { status: "passed", blocking_failed: 0 } })),
    ).toBe("CV w przygotowaniu…");
  });

  it("CV jest i QC biegło: do poprawy i uwagi osobno (jak panel osoby) albo „bez uwag”", () => {
    const withCv = (qc: KanbanItem["qc"]) => item({ company_cv: true, qc });
    // Kalwala, 789131 (18.10.2026): karta „QC: 2 do poprawy”, panel „1 rzecz” — ta sama osoba.
    expect(label(withCv({ status: "failed", blocking_failed: 1, warnings_count: 1 }))).toBe(
      "CV gotowe · QC: 1 do poprawy · 1 uwaga",
    );
    expect(label(withCv({ status: "failed", blocking_failed: 2, warnings_count: 5 }))).toBe(
      "CV gotowe · QC: 2 do poprawy · 5 uwag",
    );
    expect(label(withCv({ status: "passed", blocking_failed: 0, warnings_count: 2 }))).toBe(
      "CV gotowe · QC: 2 uwagi",
    );
    expect(cvStateBadge(withCv({ status: "passed", blocking_failed: 0, warnings_count: 2 }), "verified")?.tone).toBe(
      "info",
    );
    // Starszy serwer bez `warnings_count` — liczą się same blokujące.
    expect(label(withCv({ status: "passed", blocking_failed: 0 }))).toBe("CV gotowe · QC bez uwag");
    expect(cvStateBadge(withCv({ status: "passed", blocking_failed: 0 }), "verified")?.tone).toBe("ok");
    expect(cvStateBadge(withCv({ status: "failed", blocking_failed: 1 }), "verified")?.tone).toBe("wait");
    // Gotowe auto-CV bez pola `company_cv` (starszy serwer) też jest CV.
    expect(
      label(item({ auto_cv_ready: true, qc: { status: "passed", blocking_failed: 0, warnings_count: 0 } })),
    ).toBe("CV gotowe · QC bez uwag");
  });

  it("QC przepuszczone mimo uwag (D6) — „przepuszczone”, nie „do poprawy”", () => {
    const badge = cvStateBadge(
      item({ company_cv: true, qc: { status: "overridden", blocking_failed: 1, warnings_count: 1 } }),
      "verified",
    );
    expect(badge?.label).toBe("CV gotowe · QC przepuszczone");
    expect(badge?.tone).toBe("ok");
  });

  it("QC jeszcze nie biegło — gotowe auto-CV zostaje „CV gotowe w tle” (sprawdź przed wysyłką)", () => {
    expect(label(item({ auto_cv_ready: true }))).toBe("CV gotowe w tle");
    expect(label(item({ auto_cv_ready: true, company_cv: true, qc: { status: "unchecked", blocking_failed: 0 } }))).toBe(
      "CV gotowe w tle",
    );
    expect(cvStateBadge(item({ auto_cv_ready: true }), "verified")?.title).toMatch(/sprawdź je przed wysyłką/);
  });

  it("bez CV firmowego i bez automatu — nic; wynik QC tylko na „Zweryfikowanym”", () => {
    expect(label(item({}))).toBeNull();
    expect(label(item({ company_cv: false, qc: { status: "failed", blocking_failed: 1 } }))).toBeNull();
    // W „QC CV” wynik pokazuje chip QC — bez drugiej plakietki.
    expect(label(item({ company_cv: true, qc: { status: "failed", blocking_failed: 1 } }), "cv_qc")).toBeNull();
  });
});

describe("„Czeka u Delivery Leada” w oknie i ramce ruchu (14.10.2026)", () => {
  it("gotowa karta: od kiedy czeka (od gotowości, kalendarzowo)", () => {
    expect(
      dlWaitingStatus(
        item({
          moved_at: "2026-09-18T08:00:00Z",
          qc: { status: "passed", blocking_failed: 0, ok_at: "2026-09-20T08:00:00Z" },
        }),
        NOW,
      ),
    ).toEqual({ ready: true, text: "Czeka u Delivery Leada od 3 dni." });
    expect(
      dlWaitingStatus(
        item({ moved_at: "2026-09-22T08:00:00Z", qc: { status: "overridden", blocking_failed: 1, ok_at: "2026-09-22T09:00:00Z" } }),
        NOW,
      ).text,
    ).toBe("Czeka u Delivery Leada od 1 dnia.");
    expect(
      dlWaitingStatus(
        item({ moved_at: "2026-09-23T06:00:00Z", qc: { status: "passed", blocking_failed: 0, ok_at: "2026-09-23T07:00:00Z" } }),
        NOW,
      ).text,
    ).toBe("Czeka u Delivery Leada od dziś.");
  });

  it("QC nie przeszło albo nie biegło — co ma zrobić rekruter", () => {
    expect(dlWaitingStatus(item({ qc: { status: "failed", blocking_failed: 2 } }), NOW)).toEqual({
      ready: false,
      text: "QC: 2 do poprawy — popraw CV, zanim Delivery Lead je zobaczy.",
    });
    expect(dlWaitingStatus(item({}), NOW).text).toMatch(/^QC jeszcze nie sprawdzone/);
    expect(dlWaitingStatus(null, NOW).ready).toBe(false);
  });
});

describe("„brak: …” — krytyczne bez śladu u osoby (16.10.2026)", () => {
  it("bez braków nie ma plakietki", () => {
    expect(criticalGapBadge(undefined)).toBeNull();
    expect(criticalGapBadge([])).toBeNull();
    expect(criticalGapBadge(["  "])).toBeNull();
  });

  it("jedna krytyczna — nazwa w etykiecie, liczba pojedyncza w opisie", () => {
    const badge = criticalGapBadge(["płatności"]);
    expect(badge?.label).toBe("brak: płatności");
    expect(badge?.title).toMatch(/^Wymaganie krytyczne bez śladu w profilu, CV i notatkach: płatności\./);
  });

  it("kilka krytycznych — po przecinku, liczba mnoga", () => {
    const badge = criticalGapBadge(["płatności", "java"]);
    expect(badge?.label).toBe("brak: płatności, java");
    expect(badge?.title).toMatch(/^Wymagania krytyczne bez śladu/);
  });
});

describe("cardOwner — czyja karta (20.10.2026)", () => {
  const added = { added_to_job_by_name: "Piotr Szkicowy", verified_by_name: "Olga Weryfikująca" };

  it("od „Zweryfikowanego” w prawo pokazuje osobę, która zweryfikowała", () => {
    for (const column of ["verified", "cv_qc", "cv_sent", "client_interview", "contract", "hired", "closed"] as const) {
      expect(cardOwner(item(added), column)).toEqual({ name: "Olga Weryfikująca", role: "verified" });
    }
  });

  it("w „Nowych” i „Screeningu” zostaje osoba, która dodała", () => {
    expect(cardOwner(item(added), "new")).toEqual({ name: "Piotr Szkicowy", role: "added" });
    expect(cardOwner(item(added), "screening")).toEqual({ name: "Piotr Szkicowy", role: "added" });
  });

  it("bez zapisanej weryfikacji albo bez kolumny — dodający, a bez niego brak danych", () => {
    expect(cardOwner(item({ added_to_job_by_name: "Piotr Szkicowy", verified_by_name: "  " }), "cv_qc"))
      .toEqual({ name: "Piotr Szkicowy", role: "added" });
    expect(cardOwner(item(added), null)).toEqual({ name: "Piotr Szkicowy", role: "added" });
    expect(cardOwner(item({ added_to_job_by_name: null }), "cv_qc")).toEqual({ name: null, role: "added" });
  });

  it("osoba przypisana „Prowadzi” wygrywa w każdej kolumnie (25.10.2026)", () => {
    for (const column of ["new", "screening", "verified", "cv_sent", "closed", null] as const) {
      expect(cardOwner(item({ ...added, owner_name: "Maria Przypisana" }), column)).toEqual({
        name: "Maria Przypisana",
        role: "assigned",
      });
    }
  });
});

describe("0521: plakietka formularza CV klienta", () => {
  it("mówi o formularzu zamiast CV firmowego i tylko na „Zweryfikowanym” i „QC CV”", async () => {
    const { clientFormBadge, cvStateBadge } = await import("@/lib/board-card-badges");
    const base = { id: 1, candidate_id: 2 } as unknown as Parameters<typeof clientFormBadge>[0];
    const at = (client_form: unknown, column: Parameters<typeof clientFormBadge>[1] = "verified") =>
      clientFormBadge({ ...base, client_form } as typeof base, column);
    expect(at({ template: false, missing: null })?.label).toBe("Formularz: brak wzoru");
    expect(at({ template: true, missing: null })?.label).toBe("Formularz do wypełnienia");
    expect(at({ template: true, missing: 7 })?.label).toBe("Formularz: 7 do uzupełnienia");
    expect(at({ template: true, missing: 7 })?.tone).toBe("wait");
    expect(at({ template: true, missing: 0 }, "cv_qc")?.label).toBe("Formularz gotowy");
    expect(at({ template: true, missing: 0 }, "cv_sent")).toBeNull();
    expect(at(null)).toBeNull();
    // Formularz wygrywa z CV firmowym w tej samej plakietce.
    expect(
      cvStateBadge(
        { ...base, client_form: { template: true, missing: 2 }, company_cv: true } as typeof base,
        "verified",
      )?.label,
    ).toBe("Formularz: 2 do uzupełnienia");
  });
});
