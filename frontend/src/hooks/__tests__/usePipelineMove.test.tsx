/**
 * `usePipelineMove` BEZ tablicy kanban: te same przepływy ruchu mają działać
 * z dowolnego ekranu (widok tabeli, panel osoby). Testy pilnują kontraktu
 * z CLAUDE.md „Kanban bez bramek" i „Pipeline rekrutacji — bramka ruchu…".
 */

import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
const move = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();
const showActionToast = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: vi.fn(),
    post: (...a: unknown[]) => post(...a),
  },
  candidatesApi: { setRecruitmentClientRate: vi.fn() },
  pipelineApi: { move: (...a: unknown[]) => move(...a) },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showActionToast, showSuccess, showError }),
}));

vi.mock("@/lib/celebrate", () => ({ celebrate: vi.fn() }));
// Okno debriefu ma własne testy — tu liczy się tylko, że hook je otwiera
// i po zapisie powtarza TEN SAM ruch.
vi.mock("@/components/v2/recruitment/DebriefRequiredDialog", () => ({
  DebriefRequiredDialog: (p: { eventId: number; onSaved: () => void }) => (
    <button type="button" onClick={p.onSaved}>
      zapisz debrief {p.eventId}
    </button>
  ),
}));

import {
  usePipelineMove,
  type PipelineMoveControls,
  type PipelineMoveOptimisticAdapter,
} from "@/hooks/usePipelineMove";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { useAuthStore } from "@/store/auth";

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

function Harness({
  columns,
  optimistic,
}: {
  columns: KanbanColumn[];
  optimistic?: PipelineMoveOptimisticAdapter;
}) {
  controls = usePipelineMove({
    jobId: JOB_ID,
    job: { budgetHourly: 150, rejectionReasons: [] },
    columns,
    readOnly: false,
    canWriteClientRate: false,
    optimistic,
  });
  return <>{controls.dialogs}</>;
}

function mount(columns: KanbanColumn[], optimistic?: PipelineMoveOptimisticAdapter) {
  const queryClient = new QueryClient();
  const invalidate = vi.spyOn(queryClient, "invalidateQueries");
  render(
    <QueryClientProvider client={queryClient}>
      <Harness columns={columns} optimistic={optimistic} />
    </QueryClientProvider>
  );
  return { invalidate };
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

describe("usePipelineMove — ruch pojedynczy", () => {
  it("wysyła expected_state_version tylko, gdy karta niesie liczbę", async () => {
    const withVersion = card({ id: 10, candidate_id: 100, process_state_version: 4 });
    const withoutVersion = card({ id: 11, candidate_id: 101 });
    const b = board({ fresh: [withVersion, withoutVersion] });
    post.mockResolvedValue({ data: { id: 500, process_state_version: 5 } });
    const { invalidate } = mount(b.all);

    React.act(() => controls.requestMove(withVersion, b.fresh, b.screening));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][0]).toBe("/api/pipeline/move");
    expect(post.mock.calls[0][1]).toMatchObject({
      candidate_id: 100,
      job_id: JOB_ID,
      stage: "screening",
      stage_def_id: 2,
      expected_state_version: 4,
    });
    expect(post.mock.calls[0][1].acknowledge_eligibility).toBeUndefined();

    React.act(() => controls.requestMove(withoutVersion, "def:1", b.screening));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect("expected_state_version" in post.mock.calls[1][1]).toBe(true);
    expect(post.mock.calls[1][1].expected_state_version).toBeUndefined();

    // Bez adaptera hook i tak unieważnia OBA klucze tablicy.
    await waitFor(() =>
      expect(kanbanKeys(invalidate)).toEqual(
        expect.arrayContaining([
          ["kanban", String(JOB_ID)],
          ["kanban", JOB_ID],
        ])
      )
    );
  });

  it("adapter: apply przed odpowiedzią, confirm z nowym id etapu i wersją", async () => {
    const item = card({ id: 10, candidate_id: 100, process_state_version: 1 });
    const b = board({ fresh: [item] });
    post.mockResolvedValue({ data: { id: 501, process_state_version: 2 } });
    const apply = vi.fn();
    const confirm = vi.fn();
    mount(b.all, { apply, confirm });

    React.act(() => controls.requestMove(item, b.fresh, b.screening));
    expect(apply).toHaveBeenCalledWith(item, "def:1", b.screening);
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(confirm.mock.calls[0][0]).toMatchObject({
      item,
      fromColId: null,
      toColumn: b.screening,
      patch: {
        id: 501,
        process_state_version: 2,
        screening_done: false,
        scorecard_done: false,
      },
    });
  });

  it("„Zweryfikowany” otwiera okno stawki, a „Pomiń stawkę” nie wysyła stawki", async () => {
    const item = card({
      id: 10,
      candidate_id: 100,
      process_state_version: 3,
      candidate_expected_rate_hourly: 120,
    });
    const b = board({ fresh: [item] });
    move.mockResolvedValue({ data: { id: 502, process_state_version: 4 } });
    const confirm = vi.fn();
    const apply = vi.fn();
    mount(b.all, { apply, confirm });

    React.act(() => controls.requestMove(item, b.fresh, b.verified));
    // Okno można anulować — żadnego ruchu ani optymistycznego przeniesienia.
    expect(apply).not.toHaveBeenCalled();
    expect(move).not.toHaveBeenCalled();

    fireEvent.click(await screen.findByRole("button", { name: "Pomiń stawkę" }));
    await waitFor(() => expect(move).toHaveBeenCalledTimes(1));
    const payload = move.mock.calls[0][0];
    expect(payload).toMatchObject({
      candidate_id: 100,
      job_id: JOB_ID,
      stage: "verified",
      stage_def_id: 3,
      expected_state_version: 3,
    });
    expect(payload).not.toHaveProperty("expected_rate_value");
    expect(payload).not.toHaveProperty("expected_rate_unit");
    expect(payload).not.toHaveProperty("expected_rate_currency");
    await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
    expect(confirm.mock.calls[0][0]).toMatchObject({
      fromColId: "def:1",
      toColumn: b.verified,
      patch: { id: 502, verification_status: "active", process_state_version: 4 },
    });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Pomiń stawkę" })).toBeNull()
    );
  });

  it("rola bez prawa do stawek dostaje komunikat zamiast okna", () => {
    useAuthStore.setState({
      user: { id: 2, role: "sourcer", email: "s@example.com" },
    } as never);
    const item = card({ id: 10, candidate_id: 100 });
    const b = board({ fresh: [item] });
    mount(b.all);
    React.act(() => controls.requestMove(item, b.fresh, b.verified));
    expect(showError).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Pomiń stawkę" })).toBeNull();
  });

  it("409 ELIGIBILITY_WARNING → „Przenieś mimo to” → ten sam ruch z acknowledge_eligibility", async () => {
    const item = card({ id: 10, candidate_id: 100, process_state_version: 2 });
    const b = board({ fresh: [item] });
    post
      .mockRejectedValueOnce(
        conflict("ELIGIBILITY_WARNING", {
          reason_code: "client_nda",
          reason: "Kandydat ma NDA z tym klientem.",
          can_acknowledge: true,
        })
      )
      .mockResolvedValueOnce({ data: { id: 503 } });
    mount(b.all);

    React.act(() => controls.requestMove(item, b.fresh, b.screening));
    expect(await screen.findByText("Kandydat ma NDA z tym klientem.")).toBeInTheDocument();
    expect(showError).not.toHaveBeenCalled();
    expect(post).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Przenieś mimo to" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(post.mock.calls[1][1]).toMatchObject({
      candidate_id: 100,
      stage: "screening",
      expected_state_version: 2,
      acknowledge_eligibility: true,
    });
    await waitFor(() =>
      expect(screen.queryByText("Kandydat ma NDA z tym klientem.")).toBeNull()
    );
  });

  it("409 DEBRIEF_REQUIRED → okno debriefu, po zapisie ten sam ruch", async () => {
    const item = card({ id: 11, candidate_id: 110, process_state_version: 3 });
    const b = board({ fresh: [item] });
    post
      .mockRejectedValueOnce(conflict("DEBRIEF_REQUIRED", { event_id: 77 }))
      .mockResolvedValueOnce({ data: { id: 504 } });
    mount(b.all);

    React.act(() => controls.requestMove(item, b.fresh, b.screening));
    const save = await screen.findByRole("button", { name: "zapisz debrief 77" });
    expect(showError).not.toHaveBeenCalled();
    fireEvent.click(save);
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    expect(post.mock.calls[1][1]).toMatchObject({ candidate_id: 110, stage: "screening" });
  });

  it("409 PIPELINE_VERSION_CONFLICT → toast, sync, oba klucze, BEZ ponowienia", async () => {
    const item = card({ id: 10, candidate_id: 100, process_state_version: 2 });
    const b = board({ fresh: [item] });
    post.mockRejectedValue(conflict("PIPELINE_VERSION_CONFLICT"));
    const sync = vi.fn().mockResolvedValue(undefined);
    const { invalidate } = mount(b.all, { apply: vi.fn(), sync });

    React.act(() => controls.requestMove(item, b.fresh, b.screening));
    await waitFor(() => expect(showError).toHaveBeenCalledTimes(1));
    expect(showError.mock.calls[0][0]).toMatch(/przesunięty przez kogoś innego/);
    await waitFor(() => expect(sync).toHaveBeenCalledTimes(1));
    const keys = kanbanKeys(invalidate);
    expect(keys).toEqual(
      expect.arrayContaining([
        ["kanban", String(JOB_ID)],
        ["kanban", JOB_ID],
      ])
    );
    expect(
      invalidate.mock.calls.some(
        (c) =>
          JSON.stringify((c[0] as { queryKey: unknown[] }).queryKey) ===
          JSON.stringify(["candidate-stage-history", 100, JOB_ID])
      )
    ).toBe(true);
    // Żadnego ponowienia i żadnego okna „Przenieś mimo to".
    expect(post).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Przenieś mimo to" })).toBeNull();
  });
});

describe("usePipelineMove — odrzucenie", () => {
  async function rejectWith(checkEmail: boolean) {
    const item = card({ id: 20, candidate_id: 200, stage: "client_interview" });
    const b = board({ client: [item] });
    post.mockResolvedValue({
      data: { id: 600, scheduled_rejection_email_id: checkEmail ? 77 : null },
    });
    mount(b.all);

    React.act(() => controls.requestReject(item));
    const reason = await screen.findByPlaceholderText(/brak wymaganych kompetencji/);
    fireEvent.change(reason, { target: { value: "Za wysoka stawka" } });
    if (checkEmail) fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    return post.mock.calls[0][1];
  }

  it("bez zaznaczenia nie prosi o mail odrzucenia", async () => {
    const payload = await rejectWith(false);
    expect(payload).toMatchObject({
      candidate_id: 200,
      stage: "rejected",
      stage_def_id: 9,
      rejection_reason: "Za wysoka stawka",
    });
    expect(payload.send_rejection_email).not.toBe(true);
    expect(showActionToast).not.toHaveBeenCalled();
  });

  it("zaznaczony checkbox wysyła send_rejection_email: true i daje toast „Cofnij wysyłkę”", async () => {
    const payload = await rejectWith(true);
    expect(payload.send_rejection_email).toBe(true);
    await waitFor(() => expect(showActionToast).toHaveBeenCalledTimes(1));
    const [, options] = showActionToast.mock.calls[0];
    expect(options.actionLabel).toBe("Cofnij wysyłkę");
    post.mockResolvedValueOnce({ data: {} });
    await options.onAction();
    expect(post).toHaveBeenLastCalledWith("/api/rejection-emails/77/cancel");
  });
});

describe("usePipelineMove — ruch zbiorczy", () => {
  it("pętla pojedynczych ruchów bez wersji; unieważnienie RAZ, po pętli", async () => {
    const items = [1, 2, 3].map((n) =>
      card({ id: 30 + n, candidate_id: 300 + n, process_state_version: n })
    );
    const b = board({ fresh: items });
    const resolvers: Array<() => void> = [];
    post.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvers.push(() => resolve({ data: { id: 700 + resolvers.length } }));
        })
    );
    const onHandled = vi.fn();
    const { invalidate } = mount(b.all);

    let done: Promise<void>;
    React.act(() => {
      done = controls.requestBulkMove(items, b.screening, { onHandled });
    });
    await waitFor(() => expect(controls.isMoving).toBe(true));

    for (let i = 0; i < 3; i += 1) {
      await waitFor(() => expect(post).toHaveBeenCalledTimes(i + 1));
      // W środku pętli — ani jednego unieważnienia tablicy.
      expect(kanbanKeys(invalidate)).toHaveLength(0);
      await React.act(async () => {
        resolvers[i]();
      });
    }
    await React.act(async () => {
      await done!;
    });

    expect(post).toHaveBeenCalledTimes(3);
    for (const call of post.mock.calls) {
      expect(call[0]).toBe("/api/pipeline/move");
      expect(call[1].expected_state_version).toBeUndefined();
    }
    expect(kanbanKeys(invalidate)).toEqual([
      ["kanban", String(JOB_ID)],
      ["kanban", JOB_ID],
    ]);
    expect(onHandled).toHaveBeenCalledTimes(1);
    expect(showSuccess).toHaveBeenCalledWith("Przeniesiono 3 kandydatów.");
    expect(controls.isMoving).toBe(false);
  });

  it("ruch zbiorczy mówi, kogo nie przeniesiono i dlaczego (REC-06)", async () => {
    const items = [1, 2].map((n) => card({ id: 50 + n, candidate_id: 500 + n }));
    const b = board({ fresh: items });
    post
      .mockRejectedValueOnce(
        conflict("ELIGIBILITY_WARNING", {
          reason_code: "rejected_by_hiring_manager",
          reason: "Odrzucony przez Annę Nowak 12.08.2026.",
          can_acknowledge: true,
        }),
      )
      .mockResolvedValueOnce({ data: { id: 702 } });
    mount(b.all);
    await React.act(async () => {
      await controls.requestBulkMove(items, b.screening);
    });
    expect(showError).toHaveBeenCalledWith(
      "Nie udało się przenieść 1 z 2 kandydatów: Jan Kowalski501 — Odrzucony przez Annę Nowak 12.08.2026.",
    );
    // Bez okna „Przenieś mimo to" w ruchu zbiorczym.
    expect(screen.queryByRole("button", { name: "Przenieś mimo to" })).toBeNull();
  });

  it("„Zatrudniony” zbiorczo jest odmawiany bez żadnego ruchu", async () => {
    const items = [card({ id: 41, candidate_id: 401 })];
    const b = board({ fresh: items });
    const hired = column("hired", 8, "Zatrudniony", "terminal", [], "hired");
    const onHandled = vi.fn();
    mount([...b.all, hired]);
    await React.act(async () => {
      await controls.requestBulkMove(items, hired, { onHandled });
    });
    expect(post).not.toHaveBeenCalled();
    expect(onHandled).not.toHaveBeenCalled();
    expect(showError).toHaveBeenCalledWith(
      "Zatrudnienie oznaczaj pojedynczo — przeciągnij kartę kandydata."
    );
  });
});
