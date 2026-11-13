import { describe, expect, it } from "vitest";

import type { TrainingRow, TrainingView } from "@/lib/api/trainings";
import { HANDOVER, PREVIOUS_FEES, QUOTED } from "@/app/preview/trainings/fixtures";

import {
  canReviewFile,
  compareFees,
  defaultDeliverables,
  deliverablesFromOrder,
  deliverablesPayload,
  feeTotal,
  formatAmount,
  handoverSummary,
  orderFormProblem,
  paymentBlockReason,
  previousTrainingOf,
  publishBlockReason,
  trainingSteps,
} from "../training-model";

const TODAY = "2026-12-06";
const TCM = { can_manage: true };

function view(patch: Partial<TrainingView>): TrainingView {
  return { ...HANDOVER, ...patch };
}

describe("kroki szkolenia", () => {
  it("trener z umową: etap wynika ze stanu", () => {
    const at = (patch: Partial<TrainingView>) => trainingSteps(view(patch), TODAY).current;
    expect(at({ status: "draft" })).toBe(0);
    expect(at({ status: "ordered" })).toBe(1);
    expect(at({ status: "quoted" })).toBe(1);
    expect(at({ status: "returned" })).toBe(1);
    expect(at({ status: "accepted" })).toBe(2);
    expect(at({ status: "trainer_signed" })).toBe(2);
  });

  it("po podpisie: szkolenie, przekazanie, zapłata, biblioteka", () => {
    const fresh = HANDOVER.handover.map((item) => ({ ...item, state: "missing" as const, files: [] }));
    const ahead = { ...HANDOVER.order, session_date: "2026-12-20" };
    expect(trainingSteps(view({ handover: fresh, order: ahead }), TODAY).current).toBe(3);
    expect(trainingSteps(view({}), TODAY).current).toBe(4);
    const ready = { invoice_ready_at: "2026-12-08T10:00:00Z", paid_at: null };
    expect(trainingSteps(view({ payment: ready }), TODAY).current).toBe(5);
    const paid = { invoice_ready_at: "2026-12-08T10:00:00Z", paid_at: "2026-12-20T10:00:00Z" };
    expect(trainingSteps(view({ payment: paid }), TODAY).current).toBe(6);
    const published = trainingSteps(view({ payment: paid, published_at: "2026-12-21T10:00:00Z" }), TODAY);
    expect(published.complete).toBe(true);
  });

  it("pracownik ma trzy kroki, bez wyceny i umowy", () => {
    const employee = view({ trainer_kind: "employee", status: "signed" });
    const steps = trainingSteps({ ...employee, order: { ...employee.order, session_date: "2026-12-20" } }, TODAY);
    expect(steps.labels).toEqual(["Zamówienie", "Szkolenie", "Biblioteka"]);
    expect(steps.current).toBe(1);
    expect(trainingSteps(employee, TODAY).current).toBe(2);
  });

  it("anulowane nie ma bieżącego kroku", () => {
    const steps = trainingSteps(view({ status: "cancelled" }), TODAY);
    expect(steps).toMatchObject({ current: -1, cancelled: true, complete: false });
  });
});

describe("publikacja i zapłata", () => {
  it("trener B2B bez zapłaty: przycisk wyłączony z powodem z § 8 ust. 3", () => {
    expect(publishBlockReason(view({}), TCM)).toMatch(/po zapłacie.*§ 8 ust\. 3/);
  });

  it("po zapłacie i z plikiem dla uczestników można publikować", () => {
    const paid = { invoice_ready_at: "2026-12-08T10:00:00Z", paid_at: "2026-12-20T10:00:00Z" };
    expect(publishBlockReason(view({ payment: paid, can_publish: true }), TCM)).toBeNull();
  });

  it("bez pliku dla uczestników nie ma czego publikować", () => {
    const paid = { invoice_ready_at: "x", paid_at: "y" };
    const files = HANDOVER.files.map((file) => ({ ...file, for_participants: false }));
    expect(publishBlockReason(view({ payment: paid, files, can_publish: true }), TCM)).toMatch(
      /przynajmniej jeden plik/,
    );
  });

  it("pracownik publikuje bez zapłaty, ale nie przed zatwierdzeniem", () => {
    expect(publishBlockReason(view({ trainer_kind: "employee", can_publish: true }), TCM)).toBeNull();
    expect(publishBlockReason(view({ trainer_kind: "employee", status: "draft" }), TCM)).toMatch(
      /wyślij zamówienie/,
    );
  });

  it("bez prowadzenia szkoleń nie ma publikacji", () => {
    expect(publishBlockReason(view({}), { can_manage: false })).toMatch(/Talent Community Manager/);
  });

  it("Finanse oznaczają zapłatę dopiero po przyjęciu plików", () => {
    expect(paymentBlockReason(view({}), { can_pay: true })).toMatch(/po przyjęciu/);
    const ready = { invoice_ready_at: "2026-12-08T10:00:00Z", paid_at: null };
    expect(paymentBlockReason(view({ payment: ready }), { can_pay: true })).toBeNull();
    expect(paymentBlockReason(view({ payment: ready }), { can_pay: false })).toMatch(/Finansów/);
    expect(paymentBlockReason(view({ trainer_kind: "employee" }), { can_pay: true })).toMatch(/pracownika/);
  });
});

describe("kwoty", () => {
  it("suma jak core.fee_total: null, gdy żadnej kwoty", () => {
    expect(feeTotal([{ amount: null }, { amount: null }])).toBeNull();
    expect(feeTotal([{ amount: "1600.00" }, { amount: null }, { amount: "800.50" }])).toBe(2400.5);
  });

  it("porównanie z poprzednim szkoleniem: różnice per pozycja i w sumie", () => {
    const comparison = compareFees(QUOTED.fees!, PREVIOUS_FEES);
    expect(comparison.total).toBe(4100);
    expect(comparison.previousTotal).toBe(6200);
    expect(comparison.totalDiff).toBe(-2100);
    const audio = comparison.rows.find((row) => row.key === "fee_audio")!;
    expect(audio).toMatchObject({ amount: null, previous: 900, diff: null });
    const rights = comparison.rows.find((row) => row.key === "fee_rights")!;
    expect(rights.diff).toBe(300);
  });

  it("bez poprzedniego szkolenia kolumna porównania jest pusta", () => {
    const comparison = compareFees(QUOTED.fees!, null);
    expect(comparison.previousTotal).toBeNull();
    expect(comparison.rows.every((row) => row.previous === null && row.diff === null)).toBe(true);
  });

  it("kwoty w tabeli grupują tysiące spacją", () => {
    expect(formatAmount(4100)).toBe("4 100");
    expect(formatAmount(12500)).toMatch(/^12\s500$/);
    expect(formatAmount(null)).toBe("—");
  });

  it("poprzednie szkolenie: ten sam kontrakt, wcześniejsze, z kwotą, nie anulowane", () => {
    const base: TrainingRow = {
      id: 1,
      title: "x",
      status: "signed",
      status_label: "",
      trainer_kind: "consultant",
      trainer_contract_id: QUOTED.trainer_contract_id,
      trainer_name: "Anna Przykładowa",
      session_date: "2026-10-07",
      total: "6200.00",
      invoice_ready_at: null,
      paid_at: null,
      published_at: null,
      can_publish: false,
    };
    const rows: TrainingRow[] = [
      base,
      { ...base, id: 2, session_date: "2026-11-01" },
      { ...base, id: 3, session_date: "2026-11-15", status: "cancelled" },
      { ...base, id: 4, session_date: "2026-11-10", total: null },
      // to samo nazwisko, inny kontrakt — inna osoba
      { ...base, id: 5, session_date: "2026-11-12", trainer_contract_id: 9999 },
      { ...base, id: 6, session_date: "2027-01-10" },
    ];
    expect(previousTrainingOf(rows, QUOTED)?.id).toBe(2);
    expect(previousTrainingOf(rows, { ...QUOTED, trainer_kind: "employee" })).toBeNull();
  });
});

describe("przekazanie plików", () => {
  it("podsumowanie liczy wymagane, przyjęte i do sprawdzenia", () => {
    expect(handoverSummary(HANDOVER)).toEqual({ required: 2, accepted: 0, toReview: 1, returned: 1 });
  });

  it("plik zastąpiony nie ma decyzji, przyjęty da się jeszcze zwrócić", () => {
    expect(canReviewFile("submitted", "replaced")).toEqual({ accept: false, return: false });
    expect(canReviewFile("submitted", "submitted")).toEqual({ accept: true, return: true });
    expect(canReviewFile("accepted", "accepted")).toEqual({ accept: false, return: true });
    expect(canReviewFile("returned", "returned")).toEqual({ accept: true, return: false });
  });
});

describe("zamówienie: pliki do przekazania", () => {
  it("domyślnie materiały i prezentacja z formatem i terminem, audio i inne odznaczone", () => {
    const drafts = defaultDeliverables();
    expect(drafts.map((d) => [d.key, d.checked])).toEqual([
      ["materials", true],
      ["presentation", true],
      ["audio", false],
      ["other", false],
    ]);
    expect(drafts.find((d) => d.key === "presentation")).toMatchObject({
      format: "PPTX do edycji i PDF dla uczestników",
      due_days: 2,
      required: true,
    });
    expect(drafts.find((d) => d.key === "audio")?.due_days).toBe(7);
    expect(deliverablesPayload(drafts).map((d) => d.key)).toEqual(["materials", "presentation"]);
  });

  it("zapisane pozycje wracają zaznaczone, reszta z domyślnych", () => {
    const drafts = deliverablesFromOrder([
      { key: "audio", label: "Pliki audio", required: false, format: "MP3", due_days: 10 },
    ]);
    expect(drafts.filter((d) => d.checked).map((d) => d.key)).toEqual(["audio"]);
    expect(drafts.find((d) => d.key === "audio")).toMatchObject({ format: "MP3", due_days: 10, required: false });
  });

  it("walidacja: nazwa, „Inne pliki” z nazwą, termin 0–60", () => {
    const drafts = defaultDeliverables();
    expect(orderFormProblem({ title: " " }, drafts)).toMatch(/nazwę szkolenia/);
    const other = drafts.map((d) => (d.key === "other" ? { ...d, checked: true } : d));
    expect(orderFormProblem({ title: "X" }, other)).toMatch(/Inne pliki/);
    const late = drafts.map((d) => (d.key === "materials" ? { ...d, due_days: 61 } : d));
    expect(orderFormProblem({ title: "X" }, late)).toMatch(/0–60/);
    expect(orderFormProblem({ title: "X" }, drafts)).toBeNull();
  });
});
