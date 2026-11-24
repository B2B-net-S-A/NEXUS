/**
 * `usePipelineMove.deferReject` — odrzucenie jednym kliknięciem z panelu osoby
 * (decyzja Artura 23.11.2026). Te same pola ruchu co „Potwierdź” w oknie przy
 * „Odrzucamy my”, a wysyłka i „Cofnij” jak strzałka „→” (D7): 10 s, potem
 * żądanie; „Cofnij” przed wysłaniem = bez żadnego żądania (bez maila
 * i dzwonka). Mocki i harness jak w `usePipelineMove.test.tsx`.
 * Zasady: docs/claude/rekrutacja-tablica/odrzucenie-jednym-kliknieciem.md.
 */
import * as React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
const get = vi.fn();
// Podgląd maila w oknie odrzucenia (13.10.2026) ma własny mock — `post` liczy
// tylko ruchy i inne zapisy. Domyślnie mail może wyjść do każdej osoby.
const previewPost = vi.fn((_url: string, body: { candidate_ids: number[] }) =>
  Promise.resolve({
    data: {
      subject: "Informacja zwrotna — Rola",
      body: "Cześć,\n\ndziękujemy.",
      people: body.candidate_ids.map((id) => ({
        candidate_id: id,
        to_email: `c${id}@example.com`,
        skip_reason: null,
      })),
    },
  }),
);
const move = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();
const showActionToast = vi.fn();
const generatedList = vi.fn();
const requestSignature = vi.fn();
const updateGenerated = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) =>
      a[0] === "/api/rejection-emails/preview"
        ? previewPost(a[0] as string, a[1] as { candidate_ids: number[] })
        : post(...a),
  },
  // `interviewCycleApi` (wniosek o terminy po ruchu, 23.11.2026) woła nazwany `api`.
  api: { get: vi.fn(), post: (...a: unknown[]) => post(...a) },
  candidatesApi: { setRecruitmentClientRate: vi.fn() },
  extractErrorMsg: (e: { response?: { data?: { detail?: string } } }) =>
    e?.response?.data?.detail ?? "Błąd",
  pipelineApi: { move: (...a: unknown[]) => move(...a) },
  b2bGeneratorApi: {
    generated: (...a: unknown[]) => generatedList(...a),
    requestSignature: (...a: unknown[]) => requestSignature(...a),
    updateGenerated: (...a: unknown[]) => updateGenerated(...a),
  },
}));

// Okno podpisu żyje w module Generatora i ma własne testy — tu liczy się, że
// hook je otwiera dla właściwej umowy.
vi.mock("@/components/v2/pages/B2BContractGeneratorV2", () => ({
  ConfirmFullySignedDialog: (p: { row: { contract_number: string } }) => (
    <div role="dialog" aria-label="okno podpisu">
      Potwierdź podpis umowy {p.row.contract_number}
    </div>
  ),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showActionToast, showSuccess, showError }),
}));

vi.mock("@/lib/celebrate", () => ({ celebrate: vi.fn() }));
// Okno debriefu ma własne testy — tu liczy się tylko, że hook je otwiera
// i po zapisie powtarza TEN SAM ruch.
// Kolejność jak w `DebriefDialog`: po zapisie najpierw `onSaved`, potem
// zamknięcie okna (`onOpenChange(false)`).
vi.mock("@/components/v2/recruitment/DebriefRequiredDialog", () => ({
  DebriefRequiredDialog: (p: {
    eventId: number;
    onSaved: () => void;
    onOpenChange: (open: boolean) => void;
  }) => (
    <div>
      <button
        type="button"
        onClick={() => {
          p.onSaved();
          p.onOpenChange(false);
        }}
      >
        zapisz debrief {p.eventId}
      </button>
      <button type="button" onClick={() => p.onOpenChange(false)}>
        anuluj debrief
      </button>
    </div>
  ),
}));

import {
  CLIENT_SEND_DENIED_MESSAGE,
  usePipelineMove,
  type PipelineMoveControls,
  type PipelineMoveOptimisticAdapter,
  type UsePipelineMoveOptions,
} from "@/hooks/usePipelineMove";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { interviewCycleApi } from "@/lib/api/interviewCycle";
import type { Permission } from "@/lib/permissions";
import { useAuthStore } from "@/store/auth";
import { permissionSnapshot } from "@/__tests__/fixtures/permission-snapshot";

const JOB_ID = 7;

const card = (over: Partial<KanbanItem> & { id: number; candidate_id: number }): KanbanItem => ({
  stage: "new",
  name: "Jan",
  lastname: `Kowalski${over.candidate_id}`,
  ...over,
});

const column = (
  stage: string,
  stageDefId: number,
  name: string,
  category: "internal" | "external" | "terminal",
  items: KanbanItem[] = [],
  terminal_type: "hired" | "rejected" | "withdrawn" | null = null
): KanbanColumn =>
  ({
    stage,
    stage_def_id: stageDefId,
    name,
    category,
    terminal_type,
    count: items.length,
    items,
  }) as KanbanColumn;

function board(items: { fresh?: KanbanItem[]; client?: KanbanItem[] } = {}) {
  const fresh = column("new", 1, "Nowy", "internal", items.fresh ?? []);
  const screening = column("screening", 2, "Screening", "internal");
  const verified = column("verified", 3, "Zweryfikowany", "internal");
  const clientInterview = column(
    "client_interview",
    4,
    "Rozmowa z klientem",
    "external",
    items.client ?? []
  );
  const rejected = column("rejected", 9, "Odrzucony", "terminal", [], "rejected");
  return {
    fresh,
    screening,
    verified,
    clientInterview,
    rejected,
    all: [fresh, screening, verified, clientInterview, rejected],
  };
}

let controls: PipelineMoveControls;

interface HarnessOptions {
  /** Klient z kolejką Cpro — tam wysyłka nie pyta o uprawnienie. */
  cproEnabled?: boolean;
  /** Tablica tylko do odczytu, m.in. w podglądzie jako inny użytkownik. */
  readOnly?: boolean;
  onVerifiedRequirementsMissing?: UsePipelineMoveOptions["onVerifiedRequirementsMissing"];
  /** Słownik powodów okna odrzucenia — domyślnie pusty (wolny tekst). */
  rejectionReasons?: UsePipelineMoveOptions["job"]["rejectionReasons"];
  /** DL/HoR/admin: okno „Kiedy rozmowa?” wysyła terminy rekruterowi (23.11.2026). */
  canSendClientSlots?: boolean;
}

function Harness({
  columns,
  optimistic,
  options = {},
}: {
  columns: KanbanColumn[];
  optimistic?: PipelineMoveOptimisticAdapter;
  options?: HarnessOptions;
}) {
  controls = usePipelineMove({
    jobId: JOB_ID,
    job: { budgetHourly: 150, rejectionReasons: options.rejectionReasons ?? [] },
    columns,
    readOnly: options.readOnly ?? false,
    canWriteClientRate: false,
    canSendClientSlots: options.canSendClientSlots ?? false,
    optimistic,
    cproEnabled: options.cproEnabled,
    onVerifiedRequirementsMissing: options.onVerifiedRequirementsMissing,
  });
  return <>{controls.dialogs}</>;
}

function mount(
  columns: KanbanColumn[],
  optimistic?: PipelineMoveOptimisticAdapter,
  options?: HarnessOptions,
) {
  const queryClient = new QueryClient();
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  const { unmount } = render(
    <QueryClientProvider client={queryClient}>
      <Harness columns={columns} optimistic={optimistic} options={options} />
    </QueryClientProvider>
  );
  return { invalidate, unmount };
}

const kanbanKeys = (invalidate: { mock: { calls: unknown[][] } }) =>
  invalidate.mock.calls
    .map((c: unknown[]) => (c[0] as { queryKey: unknown[] }).queryKey)
    .filter((k: unknown[]) => k[0] === "kanban");

const conflict = (code: string, extra: Record<string, unknown> = {}) => ({
  response: { status: 409, data: { detail: { code, ...extra } } },
});

beforeEach(() => {
  post.mockReset();
  move.mockReset();
  showError.mockReset();
  showSuccess.mockReset();
  showActionToast.mockReset();
  useAuthStore.setState({
    user: { id: 1, role: "recruiter", email: "r@example.com" },
  } as never);
});


const REASONS = [
  { id: "11", label: "Nie spełnia wymagań technicznych", name: "Nie spełnia wymagań technicznych", applies_to: ["rejected" as const] },
  { id: "12", label: "Brak doświadczenia", name: "Brak doświadczenia", applies_to: ["rejected" as const] },
  { id: "13", label: "Za wysokie oczekiwania finansowe", name: "Za wysokie oczekiwania finansowe", applies_to: ["rejected" as const] },
  { id: "14", label: "Nie szuka pracy", name: "not_looking_for_work", applies_to: ["rejected" as const] },
  { id: "19", label: "Inne", name: "Inne (rejected)", applies_to: ["rejected" as const] },
];

const moveCalls = () => post.mock.calls.filter((c) => c[0] === "/api/pipeline/move");
const lastToast = () => showActionToast.mock.calls[showActionToast.mock.calls.length - 1];

describe("usePipelineMove — „Odrzuć:” jednym kliknięciem (23.11.2026)", () => {
  beforeEach(() => {
    get.mockReset();
    get.mockResolvedValue({ data: [] });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("karta idzie na „Odrzucony” od razu, żądanie po 10 s z powodem i „Odrzucamy my”, bez maila", async () => {
    vi.useFakeTimers();
    const item = card({ id: 60, candidate_id: 600, process_state_version: 3 });
    const b = board({ fresh: [item] });
    post.mockResolvedValue({ data: { id: 960, process_state_version: 4 } });
    const apply = vi.fn();
    mount(b.all, { apply }, { rejectionReasons: REASONS });

    let outcome: string | undefined;
    React.act(() => {
      outcome = controls.deferReject(item, b.fresh, "too_junior", {
        message: "Odrzucono: Jan Kowalski600 · Za mało doświadczenia · otwarta: Anna",
      });
    });
    expect(outcome).toBe("deferred");
    expect(apply).toHaveBeenCalledWith(item, "def:1", b.rejected);
    expect(lastToast()[0]).toBe("Odrzucono: Jan Kowalski600 · Za mało doświadczenia · otwarta: Anna");
    expect(lastToast()[1]).toMatchObject({ actionLabel: "Cofnij", durationMs: 10_000 });
    expect(controls.pendingMoves()).toEqual([{ candidateId: 600, toColumn: b.rejected }]);

    await React.act(async () => {
      await vi.advanceTimersByTimeAsync(9_999);
    });
    expect(moveCalls()).toHaveLength(0);
    await React.act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(moveCalls()).toHaveLength(1);
    const body = moveCalls()[0][1];
    expect(body).toMatchObject({
      candidate_id: 600,
      job_id: JOB_ID,
      stage: "rejected",
      rejection_reason_id: "12",
      ended_by: "recruiter",
      send_rejection_email: false,
      expected_state_version: 3,
      notes: "",
    });
    expect(body.autofill_reason).toBeUndefined();
    expect(body.not_looking_until).toBeUndefined();
    // Spotkania pary sprawdzone po zapisie, jak domyślnie w oknie.
    await React.act(async () => {
      await vi.runAllTimersAsync();
    });
    expect(get).toHaveBeenCalledWith(`/api/interview-cycle/pairs/${JOB_ID}/600/meetings`);
  });

  it("„Cofnij” przed wysłaniem: karta wraca, żadnego żądania (bez maila i dzwonka), panel wraca do osoby", async () => {
    vi.useFakeTimers();
    const item = card({ id: 61, candidate_id: 601 });
    const b = board({ fresh: [item] });
    const rollback = vi.fn();
    const onUndo = vi.fn();
    mount(b.all, { apply: vi.fn(() => rollback) }, { rejectionReasons: REASONS });

    React.act(() => {
      controls.deferReject(item, b.fresh, "missing_skill", { message: "Odrzucono", onUndo });
    });
    React.act(() => {
      void lastToast()[1].onAction();
    });
    expect(rollback).toHaveBeenCalledTimes(1);
    expect(onUndo).toHaveBeenCalledTimes(1);
    await React.act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(post).not.toHaveBeenCalled();
    expect(get).not.toHaveBeenCalled();
    expect(controls.pendingMoves()).toEqual([]);
  });

  it("„Za droga” nie odrzuca od razu — wołający otwiera okno z pytaniem o stawkę", () => {
    const item = card({ id: 62, candidate_id: 602 });
    const b = board({ fresh: [item] });
    const apply = vi.fn();
    mount(b.all, { apply }, { rejectionReasons: REASONS });

    let outcome: string | undefined;
    React.act(() => {
      outcome = controls.deferReject(item, b.fresh, "too_expensive", { message: "x" });
    });
    expect(outcome).toBe("needs_window");
    expect(apply).not.toHaveBeenCalled();
    expect(showActionToast).not.toHaveBeenCalled();
  });

  it("okno otwarte z chipa ma zaznaczony powód", async () => {
    const item = card({ id: 63, candidate_id: 603 });
    const b = board({ fresh: [item] });
    mount(b.all, undefined, { rejectionReasons: REASONS });

    React.act(() => controls.requestReject(item, b.rejected, { reasonKey: "too_expensive" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("radio", { name: /Za droga/ })).toBeChecked();
  });

  it("osoba od systemu w „Nowych”: powód dla systemu z „Skąd wiesz” = profil; w „Screeningu” = rozmowa", async () => {
    vi.useFakeTimers();
    const fresh = card({ id: 64, candidate_id: 604, entry_source: "system" });
    const called = card({ id: 65, candidate_id: 605, stage: "screening", entry_source: "system" });
    const b = board({ fresh: [fresh] });
    b.screening.items = [called];
    post.mockResolvedValue({ data: {} });
    mount(b.all, { apply: vi.fn() }, { rejectionReasons: REASONS });

    React.act(() => {
      controls.deferReject(fresh, b.fresh, "missing_skill", { message: "a" });
      controls.deferReject(called, b.screening, "not_looking", { message: "b" });
    });
    await React.act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    const [first, second] = moveCalls().map((c) => c[1]);
    expect(first).toMatchObject({
      candidate_id: 604,
      rejection_reason_id: "11",
      autofill_reason: "missing_skill",
      autofill_learned_from: "profile",
    });
    expect(second).toMatchObject({
      candidate_id: 605,
      rejection_reason_id: "14",
      autofill_reason: "not_looking",
      autofill_learned_from: "call",
    });
    expect(second.autofill_not_looking_until).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(second.not_looking_until).toBeUndefined();
  });

  it("„Nie szuka pracy” przy karcie ręcznej niesie datę na 3 miesiące, jak domyślnie okno", async () => {
    vi.useFakeTimers();
    const item = card({ id: 66, candidate_id: 606 });
    const b = board({ fresh: [item] });
    post.mockResolvedValue({ data: {} });
    mount(b.all, { apply: vi.fn() }, { rejectionReasons: REASONS });

    React.act(() => {
      controls.deferReject(item, b.fresh, "not_looking", { message: "a" });
    });
    await React.act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(moveCalls()[0][1]).toMatchObject({ rejection_reason_id: "14" });
    expect(moveCalls()[0][1].not_looking_until).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });

  it("szablon bez wiersza powodu → „Inne” z nazwą powodu w opisie, jak okno", async () => {
    vi.useFakeTimers();
    const item = card({ id: 67, candidate_id: 607 });
    const b = board({ fresh: [item] });
    post.mockResolvedValue({ data: {} });
    mount(b.all, { apply: vi.fn() }, { rejectionReasons: REASONS });

    React.act(() => {
      controls.deferReject(item, b.fresh, "weak_english", { message: "a" });
    });
    await React.act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(moveCalls()[0][1]).toMatchObject({ rejection_reason_id: "19", notes: "Angielski za słaby" });
  });

  it("odmowa serwera: komunikat z nazwiskiem i prawda serwera na Tablicy", async () => {
    vi.useFakeTimers();
    const item = card({ id: 68, candidate_id: 608 });
    const b = board({ fresh: [item] });
    post.mockRejectedValue({ response: { status: 403, data: { detail: "Brak uprawnień" } } });
    const sync = vi.fn();
    mount(b.all, { apply: vi.fn(), sync }, { rejectionReasons: REASONS });

    React.act(() => {
      controls.deferReject(item, b.fresh, "too_junior", { message: "a" });
    });
    await React.act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(showError).toHaveBeenCalledWith(expect.stringMatching(/^Nie odrzucono: Jan Kowalski608 — /));
    expect(sync).toHaveBeenCalled();
    expect(get).not.toHaveBeenCalled();
  });

  it("tablica tylko do odczytu: nic się nie dzieje", () => {
    const item = card({ id: 69, candidate_id: 609 });
    const b = board({ fresh: [item] });
    const apply = vi.fn();
    mount(b.all, { apply }, { rejectionReasons: REASONS, readOnly: true });

    let outcome: string | undefined;
    React.act(() => {
      outcome = controls.deferReject(item, b.fresh, "too_junior", { message: "a" });
    });
    expect(outcome).toBe("blocked");
    expect(apply).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });
});
