/**
 * `usePipelineMove` BEZ tablicy kanban: te same przepływy ruchu mają działać
 * z dowolnego ekranu (widok tabeli, panel osoby). Testy pilnują kontraktu
 * z CLAUDE.md „Kanban bez bramek" i „Pipeline rekrutacji — bramka ruchu…".
 */

import * as React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const post = vi.fn();
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
    get: vi.fn(),
    post: (...a: unknown[]) => post(...a),
  },
  candidatesApi: { setRecruitmentClientRate: vi.fn() },
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
vi.mock("@/components/v2/recruitment/DebriefRequiredDialog", () => ({
  DebriefRequiredDialog: (p: { eventId: number; onSaved: () => void }) => (
    <button type="button" onClick={p.onSaved}>
      zapisz debrief {p.eventId}
    </button>
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
    job: { budgetHourly: 150, rejectionReasons: [] },
    columns,
    readOnly: options.readOnly ?? false,
    canWriteClientRate: false,
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
  render(
    <QueryClientProvider client={queryClient}>
      <Harness columns={columns} optimistic={optimistic} options={options} />
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

  it("„Zweryfikowany” przy zapisanej stawce: „Zostaw zapisaną stawkę” nie wysyła stawki", async () => {
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

    fireEvent.click(await screen.findByRole("button", { name: "Zostaw zapisaną stawkę" }));
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
      expect(screen.queryByRole("button", { name: "Zostaw zapisaną stawkę" })).toBeNull()
    );
  });

  it("bez zapisanej stawki okno jej wymaga — nie ma „Zostaw zapisaną stawkę” (D1)", async () => {
    const item = card({ id: 14, candidate_id: 104, process_state_version: 1 });
    const b = board({ fresh: [item] });
    mount(b.all, { apply: vi.fn(), confirm: vi.fn() });

    React.act(() => controls.requestMove(item, b.fresh, b.verified));
    expect(await screen.findByText(/\(wymagana\)/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Zostaw zapisaną stawkę" })).toBeNull();
    expect(screen.getByRole("button", { name: "Przesuń" })).toBeDisabled();
  });

  it("409 VERIFIED_REQUIREMENTS_MISSING: komunikat serwera i arkusz screeningu u wołającego", async () => {
    const item = card({
      id: 15,
      candidate_id: 105,
      process_state_version: 1,
      candidate_expected_rate_hourly: 120,
    });
    const b = board({ fresh: [item] });
    move.mockRejectedValueOnce({
      response: {
        status: 409,
        data: {
          detail: {
            code: "VERIFIED_REQUIREMENTS_MISSING",
            missing: ["screening_sheet"],
            screening_stage_id: 77,
            message: "Przed „Zweryfikowany” uzupełnij: arkusz screeningu.",
          },
        },
      },
    });
    const onMissing = vi.fn();
    mount(b.all, { apply: vi.fn(), confirm: vi.fn() }, { onVerifiedRequirementsMissing: onMissing });

    React.act(() => controls.requestMove(item, b.fresh, b.verified));
    fireEvent.click(await screen.findByRole("button", { name: "Zostaw zapisaną stawkę" }));
    await waitFor(() =>
      expect(showError).toHaveBeenCalledWith("Przed „Zweryfikowany” uzupełnij: arkusz screeningu."),
    );
    expect(onMissing).toHaveBeenCalledWith(
      { missing: ["screening_sheet"], screeningStageId: 77, message: expect.any(String) },
      item,
    );
  });

  it("okno stawki podpowiada stawkę z karty rekomendacji, gdy profil jej nie ma", async () => {
    const item = card({
      id: 12,
      candidate_id: 102,
      process_state_version: 1,
      card: { status: "partial", missing: 3, answers: 0, rate_hourly: 130 },
    });
    const b = board({ fresh: [item] });
    mount(b.all, { apply: vi.fn(), confirm: vi.fn() });

    React.act(() => controls.requestMove(item, b.fresh, b.verified));
    expect(await screen.findByLabelText("Kwota")).toHaveValue(130);
  });

  // 0414 (decyzja Artura 04.10.2026): okno pyta o stawkę w TEJ rekrutacji —
  // karta pary wygrywa, potem „Stawka od”, na końcu profil.
  it("stawka z karty tej rekrutacji wygrywa z profilem i „Stawką od”", async () => {
    const item = card({
      id: 13,
      candidate_id: 103,
      process_state_version: 1,
      candidate_expected_rate_hourly: 120,
      candidate_rate_from_hourly: 90,
      card: { status: "partial", missing: 3, answers: 0, rate_hourly: 130 },
    });
    const b = board({ fresh: [item] });
    mount(b.all, { apply: vi.fn(), confirm: vi.fn() });

    React.act(() => controls.requestMove(item, b.fresh, b.verified));
    expect(await screen.findByLabelText("Kwota")).toHaveValue(130);
  });

  it("bez stawki na karcie okno podpowiada „Stawkę od”", async () => {
    const item = card({
      id: 14,
      candidate_id: 104,
      process_state_version: 1,
      candidate_expected_rate_hourly: 120,
      candidate_rate_from_hourly: 90,
    });
    const b = board({ fresh: [item] });
    mount(b.all, { apply: vi.fn(), confirm: vi.fn() });

    React.act(() => controls.requestMove(item, b.fresh, b.verified));
    expect(await screen.findByLabelText("Kwota")).toHaveValue(90);
  });

  it("„Zweryfikowany”: podwójny klik w trakcie wysyłki to jeden ruch (R10-N15-7)", async () => {
    const item = card({
      id: 11,
      candidate_id: 101,
      process_state_version: 2,
      candidate_expected_rate_hourly: 110,
    });
    const b = board({ fresh: [item] });
    let resolveMove: (v: unknown) => void = () => undefined;
    move.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveMove = resolve;
        })
    );
    mount(b.all, { apply: vi.fn(), confirm: vi.fn() });

    React.act(() => controls.requestMove(item, b.fresh, b.verified));
    const input = await screen.findByLabelText("Kwota");
    fireEvent.change(input, { target: { value: "120" } });
    const submit = screen.getByRole("button", { name: "Przesuń" });
    fireEvent.click(submit);
    fireEvent.click(submit);
    fireEvent.click(screen.getByRole("button", { name: "Zostaw zapisaną stawkę" }));
    await waitFor(() => expect(move).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: "Zostaw zapisaną stawkę" })).toBeDisabled();

    await React.act(async () => {
      resolveMove({ data: { id: 503, process_state_version: 3 } });
    });
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Zostaw zapisaną stawkę" })).toBeNull()
    );
    expect(move).toHaveBeenCalledTimes(1);
  });

  it("rola bez prawa do stawek dostaje komunikat zamiast okna", () => {
    useAuthStore.setState({
      user: { id: 2, role: "user", email: "s@example.com" },
    } as never);
    const item = card({ id: 10, candidate_id: 100 });
    const b = board({ fresh: [item] });
    mount(b.all);
    React.act(() => controls.requestMove(item, b.fresh, b.verified));
    expect(showError).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Przesuń" })).toBeNull();
  });

  it.each(["talent_community_manager", "recruiter"])(
    "%s dostaje okno stawki, nie odmowę (02.10.2026)",
    async (role) => {
      useAuthStore.setState({
        user: { id: 3, role, email: "t@example.com" },
      } as never);
      const item = card({ id: 10, candidate_id: 100 });
      const b = board({ fresh: [item] });
      mount(b.all);
      React.act(() => controls.requestMove(item, b.fresh, b.verified));
      expect(showError).not.toHaveBeenCalled();
      expect(await screen.findByRole("button", { name: "Przesuń" })).toBeTruthy();
    }
  );

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
  async function rejectWith(
    checkEmail: boolean,
    response: Record<string, unknown> = {
      id: 600,
      scheduled_rejection_email_id: checkEmail ? 77 : null,
    }
  ) {
    const item = card({ id: 20, candidate_id: 200, stage: "client_interview" });
    const b = board({ client: [item] });
    post.mockResolvedValue({ data: response });
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

  it("mail zaznaczony, a serwer go nie zaplanował — okno mówi dlaczego (runda 9)", async () => {
    await rejectWith(true, {
      id: 600,
      scheduled_rejection_email_id: null,
      rejection_email_status: "no_mailbox",
    });
    await waitFor(() =>
      expect(showError).toHaveBeenCalledWith(
        expect.stringContaining("Microsoft 365")
      )
    );
    expect(showActionToast).not.toHaveBeenCalled();
  });

  it("kilka osób, mail niezaplanowany — JEDNO zdanie z liczbą (R10-V2-1)", async () => {
    const items = [1, 2].map((n) =>
      card({ id: 40 + n, candidate_id: 400 + n, stage: "client_interview" })
    );
    const b = board({ client: items });
    post.mockResolvedValue({
      data: { id: 700, scheduled_rejection_email_id: null, rejection_email_status: "no_mailbox" },
    });
    mount(b.all);

    React.act(() => controls.requestReject(items));
    const reason = await screen.findByPlaceholderText(/brak wymaganych kompetencji/);
    fireEvent.change(reason, { target: { value: "Za wysoka stawka" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(showError).toHaveBeenCalledWith(
        "Mail odrzucenia nie został zaplanowany dla 2 osób — brak podłączonej skrzynki Microsoft 365."
      )
    );
    expect(showError).toHaveBeenCalledTimes(1);
  });
});

describe("usePipelineMove — odrzucenie z notatką startową", () => {
  it("requestReject z `notes` wypełnia notatkę okna i wysyła ją z ruchem", async () => {
    const item = card({ id: 21, candidate_id: 210, stage: "client_interview" });
    const b = board({ client: [item] });
    post.mockResolvedValue({ data: { id: 601 } });
    mount(b.all);

    React.act(() => controls.requestReject(item, undefined, { notes: "Odpada, gdy: brak Javy" }));
    const reason = await screen.findByPlaceholderText(/brak wymaganych kompetencji/);
    expect(screen.getByPlaceholderText(/lepszą ofertę/)).toHaveValue("Odpada, gdy: brak Javy");
    fireEvent.change(reason, { target: { value: "Narusza deal-breaker" } });
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post.mock.calls[0][1].notes).toContain("Odpada, gdy: brak Javy");
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

  it("„Potwierdź zatrudnienie” wymaga wyboru „jak podpisano” i wysyła go (D2)", async () => {
    const item = card({ id: 42, candidate_id: 402, process_state_version: 1 });
    const b = board({ fresh: [item] });
    const hired = column("hired", 8, "Zatrudniony", "terminal", [], "hired");
    post.mockResolvedValue({ data: { id: 900, process_state_version: 2 } });
    mount([...b.all, hired], { apply: vi.fn(), confirm: vi.fn() });

    React.act(() => controls.requestMove(item, b.fresh, hired));
    const confirmButton = await screen.findByRole("button", { name: "Potwierdź zatrudnienie" });
    expect(confirmButton).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "Inna umowa" }));
    // „Inna umowa” wymaga opisu.
    expect(confirmButton).toBeDisabled();
    fireEvent.click(screen.getByRole("radio", { name: "Umowa o pracę" }));
    expect(confirmButton).toBeEnabled();
    fireEvent.click(confirmButton);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({ candidate_id: 402, hired_signed_via: "uop" }),
      ),
    );
  });

  describe("umowa z Generatora „W trakcie” (04.10.2026)", () => {
    const agreement = {
      id: 55,
      number: "1601/2026",
      contract_status: "in_progress",
      signature_status: "unsigned",
      created_at: "2026-10-01T10:00:00Z",
      signed_at: null,
      signature_requested_at: null,
      contract_id: null,
    };

    function openHire() {
      const item = card({ id: 43, candidate_id: 403, process_state_version: 1, agreement });
      const b = board({ fresh: [item] });
      const hired = column("hired", 8, "Zatrudniony", "terminal", [], "hired");
      mount([...b.all, hired], { apply: vi.fn(), confirm: vi.fn() });
      React.act(() => controls.requestMove(item, b.fresh, hired));
    }

    it("bez uprawnienia „Podpis B2B” wysyła prośbę i nie przesuwa karty", async () => {
      generatedList.mockResolvedValue([{ id: 55, contract_number: "1601/2026", can_confirm_signed: false }]);
      requestSignature.mockResolvedValue({ sent: true, requested_at: "x", recipient_names: ["Anna DL"] });
      openHire();
      fireEvent.click(
        await screen.findByRole("radio", { name: /Umowa 1601\/2026 z Generatora jest podpisana/ }),
      );
      fireEvent.click(screen.getByRole("button", { name: "Dalej: potwierdź podpis" }));
      await waitFor(() => expect(requestSignature).toHaveBeenCalledWith(55));
      expect(generatedList).toHaveBeenCalledWith(20, { jobId: JOB_ID, candidateId: 403 });
      expect(post).not.toHaveBeenCalled();
      expect(showSuccess).toHaveBeenCalledWith(expect.stringContaining("Anna DL"));
    });

    it("z uprawnieniem otwiera okno podpisu tej umowy, bez ruchu karty", async () => {
      generatedList.mockResolvedValue([{ id: 55, contract_number: "1601/2026", can_confirm_signed: true }]);
      openHire();
      fireEvent.click(
        await screen.findByRole("radio", { name: /Umowa 1601\/2026 z Generatora jest podpisana/ }),
      );
      fireEvent.click(screen.getByRole("button", { name: "Dalej: potwierdź podpis" }));
      expect(await screen.findByText("Potwierdź podpis umowy 1601/2026")).toBeInTheDocument();
      expect(requestSignature).not.toHaveBeenCalled();
      expect(post).not.toHaveBeenCalled();
    });

    it("zatrudnienie inną drogą anuluje umowę w rejestrze po udanym ruchu", async () => {
      post.mockResolvedValue({ data: { id: 901, process_state_version: 2 } });
      updateGenerated.mockResolvedValue({});
      openHire();
      fireEvent.click(await screen.findByRole("radio", { name: "Umowa o pracę" }));
      expect(screen.getByRole("checkbox", { name: /Anuluj umowę 1601\/2026/ })).toBeChecked();
      fireEvent.click(screen.getByRole("button", { name: "Potwierdź zatrudnienie" }));
      await waitFor(() =>
        expect(updateGenerated).toHaveBeenCalledWith(55, { contract_status: "cancelled" }),
      );
      expect(post).toHaveBeenCalledWith(
        "/api/pipeline/move",
        expect.objectContaining({ candidate_id: 403, hired_signed_via: "uop" }),
      );
    });

    it("odznaczone „Anuluj umowę” zostawia umowę bez zmian", async () => {
      post.mockResolvedValue({ data: { id: 902, process_state_version: 2 } });
      openHire();
      fireEvent.click(await screen.findByRole("radio", { name: "Umowa o pracę" }));
      fireEvent.click(screen.getByRole("checkbox", { name: /Anuluj umowę 1601\/2026/ }));
      fireEvent.click(screen.getByRole("button", { name: "Potwierdź zatrudnienie" }));
      await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
      expect(updateGenerated).not.toHaveBeenCalled();
    });
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

// Poza klientem z kolejką Cpro do klienta wysyła osoba z uprawnieniem
// „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta” — domyślnie
// Delivery Lead i administrator, ale rozstrzyga uprawnienie, nie rola.
describe("usePipelineMove — wysyłka CV do klienta za uprawnieniem", () => {
  const RATE_DIALOG = "Przesuń na „CV wysłane\"";

  function signIn(role: string, granted?: Permission[], realUser: unknown = null) {
    useAuthStore.setState({
      user: {
        id: 9,
        role,
        roles: [role],
        email: `${role}@example.com`,
        // Bez `granted` liczą się domyślne uprawnienia roli.
        ...(granted ? { effective_action_access: permissionSnapshot(...granted) } : {}),
      },
      realUser,
    } as never);
  }

  function sendBoard(items: KanbanItem[]) {
    const qc = column("interview", 5, "QC CV", "internal", items);
    const cvSent = column("cv_sent", 6, "CV Wysłane", "external");
    return { qc, cvSent, all: [qc, cvSent] };
  }

  function requestSend(options?: HarnessOptions) {
    const item = card({ id: 60, candidate_id: 600, process_state_version: 2 });
    const b = sendBoard([item]);
    mount(b.all, undefined, options);
    React.act(() => controls.requestMove(item, b.qc, b.cvSent));
  }

  afterEach(() => {
    useAuthStore.setState({ realUser: null } as never);
  });

  it.each(["delivery_lead", "admin"])(
    "%s ma uprawnienie domyślnie — dostaje okno stawki do klienta",
    async (role) => {
      signIn(role);
      requestSend();

      expect(await screen.findByText(RATE_DIALOG)).toBeInTheDocument();
      expect(showError).not.toHaveBeenCalled();
      // Okno można anulować — ruch idzie dopiero po wpisaniu stawki.
      expect(post).not.toHaveBeenCalled();
    },
  );

  it("rekruter z nadanym uprawnieniem dostaje okno stawki do klienta", async () => {
    signIn("recruiter", ["recruitment_manage"]);
    requestSend();

    expect(await screen.findByText(RATE_DIALOG)).toBeInTheDocument();
    expect(showError).not.toHaveBeenCalled();
  });

  it("rekruter bez uprawnienia dostaje komunikat z jego nazwą zamiast okna", () => {
    signIn("recruiter");
    requestSend();

    expect(showError).toHaveBeenCalledTimes(1);
    expect(showError).toHaveBeenCalledWith(CLIENT_SEND_DENIED_MESSAGE);
    expect(CLIENT_SEND_DENIED_MESSAGE).toContain(
      "„Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta”",
    );
    expect(CLIENT_SEND_DENIED_MESSAGE).not.toMatch(/Delivery Lead/);
    expect(screen.queryByText(RATE_DIALOG)).toBeNull();
    expect(post).not.toHaveBeenCalled();
  });

  it("Delivery Lead z wyłączonym uprawnieniem nie wysyła do klienta mimo roli", () => {
    signIn("delivery_lead", ["delivery_view", "clients_edit"]);
    requestSend();

    expect(showError).toHaveBeenCalledWith(CLIENT_SEND_DENIED_MESSAGE);
    expect(screen.queryByText(RATE_DIALOG)).toBeNull();
    expect(post).not.toHaveBeenCalled();
  });

  it("ruch zbiorczy na „CV wysłane” bez uprawnienia nie wysyła nikogo", async () => {
    signIn("recruiter");
    const items = [1, 2].map((n) => card({ id: 60 + n, candidate_id: 600 + n }));
    const b = sendBoard(items);
    const onHandled = vi.fn();
    mount(b.all);

    await React.act(async () => {
      await controls.requestBulkMove(items, b.cvSent, { onHandled });
    });

    expect(showError).toHaveBeenCalledWith(CLIENT_SEND_DENIED_MESSAGE);
    expect(post).not.toHaveBeenCalled();
    expect(onHandled).not.toHaveBeenCalled();
  });

  it("u klienta z kolejką Cpro ruch nie pyta o to uprawnienie", async () => {
    signIn("recruiter");
    post.mockResolvedValue({ data: { id: 801, process_state_version: 3 } });
    requestSend({ cproEnabled: true });

    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect(post).toHaveBeenCalledWith(
      "/api/pipeline/move",
      expect.objectContaining({ candidate_id: 600, stage: "cv_sent" }),
    );
    expect(showError).not.toHaveBeenCalled();
  });

  it("w podglądzie jako inny użytkownik (tablica tylko do odczytu) ruch nie startuje", () => {
    signIn("delivery_lead", undefined, { id: 1, role: "admin", roles: ["admin"] });
    requestSend({ readOnly: true });

    expect(screen.queryByText(RATE_DIALOG)).toBeNull();
    expect(showError).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });
});
