import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  showError: vi.fn(),
  brandedGet: vi.fn(),
  shareCreate: vi.fn(),
  move: vi.fn(),
  setRate: vi.fn(),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: vi.fn(),
    showError: mocks.showError,
    showToast: vi.fn(),
    showActionToast: vi.fn(),
  }),
}));
vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: vi.fn(async () => true) }));
vi.mock("@/lib/api", () => ({
  candidateStageCvApi: {
    branded: { get: mocks.brandedGet },
    share: { create: mocks.shareCreate },
  },
  candidatesApi: { setRecruitmentClientRate: mocks.setRate },
  pipelineApi: { move: mocks.move },
  extractErrorMsg: (e: unknown) => {
    const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
    return typeof detail === "string" ? detail : e instanceof Error ? e.message : "";
  },
}));

import { useBulkCvHandoff } from "@/components/v2/recruitment/useBulkCvHandoff";
import { buildProcessRows } from "@/components/v2/recruitment/person-rows";
import type { ProcessPersonRow } from "@/components/v2/recruitment/types";
import type { KanbanColumn } from "@/components/v2/pages/kanban-shared";

import { item, template } from "./recruitment-fixtures";

const columns = template({
  3: [
    item(2, { name: "Marek", lastname: "Zieliński", process_state_version: 7 }),
    item(3, { name: "Katarzyna", lastname: "Wójcik" }),
  ],
});
const rows = buildProcessRows(columns, {
  scores: new Map(),
  slaDays: null,
  budgetHourly: null,
  offTemplate: null,
}).filter((r): r is ProcessPersonRow => r.kind === "process");
const stageIdOf = (candidateId: number) => rows.find((r) => r.candidateId === candidateId)!.item.id;

const onHandled = vi.fn();

function Harness({
  canWriteClientRate = true,
  cols = columns,
}: {
  canWriteClientRate?: boolean;
  cols?: KanbanColumn[];
}) {
  const bulk = useBulkCvHandoff({ jobId: 42, jobTitle: "Senior Java", columns: cols, canWriteClientRate });
  return (
    <>
      <button onClick={() => bulk.start(rows, { onHandled })}>start</button>
      {bulk.dialogs}
    </>
  );
}

function renderHarness(props: Parameters<typeof Harness>[0] = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <Harness {...props} />
    </QueryClientProvider>,
  );
  return { invalidate };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.brandedGet.mockResolvedValue({ data: { status: "finalized" } });
  mocks.shareCreate.mockImplementation(async (stageId: number) => ({
    data: { share_url_suffix: `/cv/s/${stageId}` },
  }));
  mocks.move.mockResolvedValue({ data: {} });
  mocks.setRate.mockResolvedValue({ data: {} });
});

describe("useBulkCvHandoff", () => {
  it("potwierdzenie → per osoba ruch, link na etapie SPRZED ruchu, stawka tylko tam, gdzie wpisana; tablica unieważniona RAZ", async () => {
    const { invalidate } = renderHarness();
    await userEvent.click(screen.getByRole("button", { name: "start" }));
    expect(screen.getByText("Wyślij CV do klienta — 2 osoby")).toBeInTheDocument();
    expect(screen.getByLabelText("Ważność linków (dni)")).toHaveValue("14");

    await userEvent.type(screen.getByLabelText("Stawka do klienta — Marek Zieliński"), "21000");
    await userEvent.click(screen.getByRole("button", { name: "Wyślij i utwórz linki" }));

    await waitFor(() =>
      expect(screen.getByText("Wyślij CV do klienta — wynik")).toBeInTheDocument(),
    );
    expect(mocks.move).toHaveBeenCalledTimes(2);
    expect(mocks.move).toHaveBeenNthCalledWith(1, {
      candidate_id: 2,
      job_id: 42,
      stage: "cv_sent",
      stage_def_id: 5,
      expected_state_version: 7,
      acknowledge_eligibility: undefined,
    });
    expect(mocks.brandedGet.mock.calls.map((c) => c[0])).toEqual([stageIdOf(2), stageIdOf(3)]);
    expect(mocks.shareCreate.mock.calls).toEqual([
      [stageIdOf(2), 14],
      [stageIdOf(3), 14],
    ]);
    expect(mocks.setRate).toHaveBeenCalledTimes(1);
    expect(mocks.setRate).toHaveBeenCalledWith(2, 42, {
      rate_value: 21000,
      rate_unit: "monthly",
      rate_currency: "PLN",
    });
    // Ruch przed linkiem, link przed stawką (dla tej samej osoby).
    expect(mocks.move.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.shareCreate.mock.invocationCallOrder[0],
    );
    expect(mocks.shareCreate.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.setRate.mock.invocationCallOrder[0],
    );

    const keys = invalidate.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(keys.filter((k) => k === '["kanban","42"]')).toHaveLength(1);
    expect(keys.filter((k) => k === '["kanban",42]')).toHaveLength(1);
    expect(keys.filter((k) => k === '["pipeline-scores"]')).toHaveLength(1);
    expect(onHandled).toHaveBeenCalledTimes(1);

    expect(screen.getByLabelText("Marek Zieliński")).toHaveValue(
      `${window.location.origin}/cv/s/${stageIdOf(2)}`,
    );
  });

  it("bez prawa do stawki: żadnych pól stawki i żadnego zapisu stawki", async () => {
    renderHarness({ canWriteClientRate: false });
    await userEvent.click(screen.getByRole("button", { name: "start" }));
    expect(screen.queryByLabelText(/Stawka do klienta/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Jednostka (wspólna)")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Wyślij i utwórz linki" }));
    await waitFor(() =>
      expect(screen.getByText("Wyślij CV do klienta — wynik")).toBeInTheDocument(),
    );
    expect(mocks.setRate).not.toHaveBeenCalled();
  });

  it("ważność spoza 1–90 i nieczytelna stawka blokują wysyłkę", async () => {
    renderHarness();
    await userEvent.click(screen.getByRole("button", { name: "start" }));
    const days = screen.getByLabelText("Ważność linków (dni)");
    await userEvent.clear(days);
    await userEvent.type(days, "91");
    expect(screen.getByRole("button", { name: "Wyślij i utwórz linki" })).toBeDisabled();
    await userEvent.clear(days);
    await userEvent.type(days, "30");
    expect(screen.getByRole("button", { name: "Wyślij i utwórz linki" })).toBeEnabled();
    await userEvent.type(screen.getByLabelText("Stawka do klienta — Katarzyna Wójcik"), "abc");
    expect(screen.getByRole("button", { name: "Wyślij i utwórz linki" })).toBeDisabled();
    expect(mocks.move).not.toHaveBeenCalled();
  });

  it("ostrzeżenie dopuszczalności: „Przenieś mimo to” ponawia ruch z potwierdzeniem; „Anuluj” pomija osobę", async () => {
    const warning = {
      response: { status: 409, data: { detail: { code: "ELIGIBILITY_WARNING", reason: "Weto HM", reason_code: "hm_veto", can_acknowledge: true } } },
    };
    mocks.move.mockImplementation(async (payload: { acknowledge_eligibility?: boolean }) => {
      if (!payload.acknowledge_eligibility) throw warning;
      return { data: {} };
    });
    renderHarness({ canWriteClientRate: false });
    await userEvent.click(screen.getByRole("button", { name: "start" }));
    await userEvent.click(screen.getByRole("button", { name: "Wyślij i utwórz linki" }));

    await userEvent.click(await screen.findByRole("button", { name: "Przenieś mimo to" }));
    await userEvent.click(await screen.findByRole("button", { name: "Anuluj" }));

    await waitFor(() =>
      expect(screen.getByText("Wyślij CV do klienta — wynik")).toBeInTheDocument(),
    );
    expect(mocks.move.mock.calls.map((c) => [c[0].candidate_id, c[0].acknowledge_eligibility])).toEqual([
      [2, undefined],
      [2, true],
      [3, undefined],
    ]);
    expect(mocks.shareCreate).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("bulk-cv-failure-3")).toHaveTextContent("anulowano po ostrzeżeniu");
  });

  it("„przenieś bez linku”: domyślnie osoba bez sfinalizowanego CV jest pomijana; po zaznaczeniu idzie na „CV Wysłane” bez linku", async () => {
    mocks.brandedGet.mockImplementation(async (stageId: number) => ({
      data: { status: stageId === stageIdOf(3) ? "draft" : "finalized" },
    }));
    renderHarness({ canWriteClientRate: false });
    await userEvent.click(screen.getByRole("button", { name: "start" }));
    const toggle = screen.getByRole("checkbox", {
      name: /Osoby bez sfinalizowanego CV firmowego przenieś bez linku/,
    });
    // Domyślnie wyłączone — akcja zbiorcza istnieje po to, żeby powstały linki.
    expect(toggle).not.toBeChecked();
    await userEvent.click(toggle);
    await userEvent.click(screen.getByRole("button", { name: "Wyślij i utwórz linki" }));
    await waitFor(() =>
      expect(screen.getByText("Wyślij CV do klienta — wynik")).toBeInTheDocument(),
    );
    expect(mocks.move.mock.calls.map((c) => c[0].candidate_id)).toEqual([2, 3]);
    // Link TYLKO dla osoby ze sfinalizowanym CV (plan `shareLink: null` dla drugiej).
    expect(mocks.shareCreate.mock.calls).toEqual([[stageIdOf(2), 14]]);
    expect(screen.getByTestId("bulk-cv-failure-3")).toHaveTextContent(/bez linku/);
    expect(screen.getByText(/Przeniesiono na „CV Wysłane”: 2 z 2/)).toBeInTheDocument();
  });

  it("bez zaznaczenia „przenieś bez linku” osoba bez sfinalizowanego CV nie jest ruszana", async () => {
    mocks.brandedGet.mockImplementation(async (stageId: number) => ({
      data: { status: stageId === stageIdOf(3) ? "draft" : "finalized" },
    }));
    renderHarness({ canWriteClientRate: false });
    await userEvent.click(screen.getByRole("button", { name: "start" }));
    await userEvent.click(screen.getByRole("button", { name: "Wyślij i utwórz linki" }));
    await waitFor(() =>
      expect(screen.getByText("Wyślij CV do klienta — wynik")).toBeInTheDocument(),
    );
    expect(mocks.move.mock.calls.map((c) => c[0].candidate_id)).toEqual([2]);
    expect(screen.getByTestId("bulk-cv-failure-3")).toHaveTextContent("brak CV firmowego");
  });

  it("konflikt wersji odświeża historię etapów TEJ osoby (klucz pojedynczego przepływu), a tablicę nadal RAZ", async () => {
    const conflict = {
      response: { status: 409, data: { detail: { code: "PIPELINE_VERSION_CONFLICT" } } },
    };
    mocks.move.mockImplementation(async (payload: { candidate_id: number }) => {
      if (payload.candidate_id === 2) throw conflict;
      return { data: {} };
    });
    const { invalidate } = renderHarness({ canWriteClientRate: false });
    await userEvent.click(screen.getByRole("button", { name: "start" }));
    await userEvent.click(screen.getByRole("button", { name: "Wyślij i utwórz linki" }));
    await waitFor(() =>
      expect(screen.getByText("Wyślij CV do klienta — wynik")).toBeInTheDocument(),
    );
    const keys = invalidate.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(keys).toContain('["candidate-stage-history",2,42]');
    expect(keys).not.toContain('["candidate-stage-history",3,42]');
    expect(keys.filter((k) => k === '["kanban","42"]')).toHaveLength(1);
    // Bez ponowienia ruchu po konflikcie.
    expect(mocks.move.mock.calls.filter((c) => c[0].candidate_id === 2)).toHaveLength(1);
  });

  it("szablon bez „CV Wysłane”: toast błędu, żadnego okna", async () => {
    renderHarness({ cols: columns.filter((c) => c.stage !== "cv_sent") });
    await userEvent.click(screen.getByRole("button", { name: "start" }));
    expect(mocks.showError).toHaveBeenCalledWith(expect.stringMatching(/CV Wysłane/));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
