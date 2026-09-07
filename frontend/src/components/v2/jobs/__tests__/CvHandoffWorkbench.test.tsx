/**
 * CvHandoffWorkbench — stanowisko „CV do klienta" (krok 06, program „flow
 * w języku C2", PR 6/7).
 *
 * Zakres: kolejka zweryfikowanych, bramka wysyłki widoczna z powodem oraz
 * SEKWENCJA „Wyślij klientowi" — kolejność `client-rate → share-token → move`
 * i to, że porażka któregokolwiek kroku przerywa resztę i mówi, co się udało.
 * Generator CV, reguły klienta i modale snapshotów są zamockowane: mają własne
 * zapytania do innych endpointów, niepowiązane z tym, co testujemy.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const calls: string[] = [];
const setRecruitmentClientRate = vi.fn(async (...a: unknown[]) => {
  calls.push("client_rate");
  return { data: {} };
});
const shareCreate = vi.fn(async (...a: unknown[]) => {
  calls.push("share_link");
  return { data: { share_url_suffix: "abc123" } };
});
const move = vi.fn(async (...a: unknown[]) => {
  calls.push("move");
  return { data: { id: 99 } };
});
const originalGet = vi.fn();
const brandedGet = vi.fn();

vi.mock("next/dynamic", () => ({ default: () => () => null }));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: vi.fn(), post: vi.fn() },
  pipelineApi: { move: (...a: unknown[]) => move(...a) },
  candidatesApi: {
    setRecruitmentClientRate: (...a: unknown[]) =>
      setRecruitmentClientRate(...a),
  },
  candidateStageCvApi: {
    original: { get: (...a: unknown[]) => originalGet(...a) },
    branded: { get: (...a: unknown[]) => brandedGet(...a) },
    share: { create: (...a: unknown[]) => shareCreate(...a) },
  },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
}));

const showSuccess = vi.fn();
const showError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError }),
}));

// Generator to 1800-linijkowy komponent z własnymi zapytaniami — dla tego testu
// liczy się wyłącznie, że dostaje prefill.
vi.mock("@/components/v2/pages/CVGeneratorStandaloneV2", () => ({
  CVGeneratorStandaloneV2: (p: {
    prefillCandidateId?: number;
    prefillJobId?: number;
  }) => (
    <div data-testid="cv-generator-stub">
      {`prefill:${p.prefillCandidateId}/${p.prefillJobId}`}
    </div>
  ),
}));
vi.mock("@/components/v2/cv-generator/ClientCvRuleBanner", () => ({
  ClientCvRuleBanner: () => <div data-testid="cv-rule-banner" />,
  useClientCvRule: () => ({ data: undefined, isLoading: false, isError: false }),
}));
vi.mock("@/lib/client-playbooks", () => ({
  useClientPlaybook: () => ({
    data: { cv_limit_per_process: 3 },
    isLoading: false,
  }),
}));
vi.mock("@/components/v2/modals/CVOriginalPreviewModal", () => ({
  CVOriginalPreviewModal: () => null,
}));

import { CvHandoffWorkbench } from "@/components/v2/jobs/CvHandoffWorkbench";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";

function item(overrides: Partial<KanbanItem> = {}): KanbanItem {
  return {
    id: 21,
    candidate_id: 121,
    stage: "verified",
    name: "Grzegorz",
    lastname: "Żebrowski",
    expected_rate_value: 118,
    expected_rate_unit: "hourly",
    ...overrides,
  };
}

function columns(verified: KanbanItem[]): KanbanColumn[] {
  return [
    {
      stage: "verified",
      name: "Zweryfikowany",
      category: "internal",
      stage_def_id: 4,
      count: verified.length,
      items: verified,
    },
    {
      stage: "cv_sent",
      name: "CV Wysłane",
      category: "internal",
      stage_def_id: 5,
      count: 1,
      items: [item({ id: 31, candidate_id: 131, stage: "cv_sent" })],
    },
  ];
}

function renderWorkbench(
  overrides: Partial<React.ComponentProps<typeof CvHandoffWorkbench>> = {},
) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const onMoved = vi.fn();
  const onRetry = vi.fn();
  const utils = render(
    <QueryClientProvider client={client}>
      <CvHandoffWorkbench
        jobId={7}
        jobTitle="Programista Python"
        clientId={4}
        columns={columns([item()])}
        isLoading={false}
        isError={false}
        error={null}
        isSuccess
        onRetry={onRetry}
        onMoved={onMoved}
        readOnly={false}
        {...overrides}
      />
    </QueryClientProvider>,
  );
  return { ...utils, onMoved, onRetry };
}

async function sendButton() {
  return screen.findByRole("button", {
    name: /Wyślij klientowi i przenieś na „CV Wysłane”/,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  calls.length = 0;
  originalGet.mockResolvedValue({ data: { has_snapshot: true } });
  brandedGet.mockResolvedValue({ data: { status: "finalized" } });
});

describe("CvHandoffWorkbench", () => {
  it("kolejka pokazuje zweryfikowanych ze stawką kandydata", () => {
    renderWorkbench();
    const queue = screen.getByRole("list", { name: "Zweryfikowani kandydaci" });
    expect(within(queue).getByText("Grzegorz Żebrowski")).toBeTruthy();
    expect(within(queue).getByText(/118/)).toBeTruthy();
  });

  it("generator dostaje prefill kandydata i rekrutacji", async () => {
    renderWorkbench();
    expect(
      (await screen.findByTestId("cv-generator-stub")).textContent,
    ).toContain("prefill:121/7");
  });

  it("limit CV klienta jest liczony z tablicy, nie zmyślony", () => {
    renderWorkbench();
    // Jedna karta na „CV Wysłane" przy limicie 3 z karty klienta.
    expect(screen.getByText("1 z 3")).toBeTruthy();
  });

  it("pusta kolejka to pusty stan, a 403 to brak uprawnień", () => {
    const { unmount } = renderWorkbench({ columns: columns([]) });
    expect(screen.getByText(/Nikt nie czeka na wysyłkę CV/)).toBeTruthy();
    unmount();

    renderWorkbench({
      columns: [],
      isError: true,
      isSuccess: false,
      error: { response: { status: 403 } },
    });
    expect(screen.getByText("Brak uprawnień")).toBeTruthy();
    expect(screen.queryByText(/Nikt nie czeka na wysyłkę CV/)).toBeNull();
  });

  it("sekwencja idzie: stawka → link → ruch", async () => {
    const { onMoved } = renderWorkbench();
    await waitFor(() => expect(brandedGet).toHaveBeenCalled());

    await userEvent.type(screen.getByLabelText("Kwota"), "25000");
    await userEvent.click(await sendButton());

    await waitFor(() => expect(move).toHaveBeenCalledOnce());
    expect(calls).toEqual(["client_rate", "share_link", "move"]);
    expect(setRecruitmentClientRate).toHaveBeenCalledWith(121, 7, {
      rate_value: 25000,
      rate_unit: "monthly",
      rate_currency: "PLN",
    });
    expect(shareCreate).toHaveBeenCalledWith(21, 14);
    expect(move).toHaveBeenCalledWith({
      candidate_id: 121,
      job_id: 7,
      stage: "cv_sent",
      stage_def_id: 5,
    });
    expect(onMoved).toHaveBeenCalled();
  });

  it("puste pole stawki = świadome pominięcie, a komunikat to mówi", async () => {
    renderWorkbench();
    await waitFor(() => expect(brandedGet).toHaveBeenCalled());

    await userEvent.click(await sendButton());

    await waitFor(() => expect(move).toHaveBeenCalledOnce());
    expect(calls).toEqual(["share_link", "move"]);
    expect(setRecruitmentClientRate).not.toHaveBeenCalled();
    expect(showSuccess).toHaveBeenCalledWith(
      expect.stringContaining("Bez stawki do klienta"),
    );
  });

  it("bez sfinalizowanego CV brandowanego link nie powstaje, a powód jest widoczny", async () => {
    brandedGet.mockResolvedValue({ data: { status: "draft" } });
    renderWorkbench();
    await waitFor(() => expect(brandedGet).toHaveBeenCalled());
    expect(
      await screen.findByText(/wymaga sfinalizowanego CV brandowanego/),
    ).toBeTruthy();

    await userEvent.click(await sendButton());

    await waitFor(() => expect(move).toHaveBeenCalledOnce());
    expect(shareCreate).not.toHaveBeenCalled();
    expect(calls).toEqual(["move"]);
  });

  it("porażka linku ZATRZYMUJE ruch i mówi, że stawka została zapisana", async () => {
    shareCreate.mockRejectedValueOnce(new Error("409 brak finalizacji"));
    renderWorkbench();
    await waitFor(() => expect(brandedGet).toHaveBeenCalled());

    await userEvent.type(screen.getByLabelText("Kwota"), "25000");
    await userEvent.click(await sendButton());

    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(move).not.toHaveBeenCalled();
    const msg = showError.mock.calls[0][0] as string;
    expect(msg).toContain("utworzenie linku dla klienta");
    expect(msg).toContain("409 brak finalizacji");
    expect(msg).toContain("zapis stawki do klienta");
  });

  it("porażka ruchu mówi, że stawka i link już istnieją", async () => {
    move.mockRejectedValueOnce(new Error("409 weto hiring managera"));
    renderWorkbench();
    await waitFor(() => expect(brandedGet).toHaveBeenCalled());

    await userEvent.type(screen.getByLabelText("Kwota"), "25000");
    await userEvent.click(await sendButton());

    await waitFor(() => expect(showError).toHaveBeenCalled());
    const msg = showError.mock.calls[0][0] as string;
    expect(msg).toContain("przeniesienie na „CV Wysłane”");
    expect(msg).toContain("powtórzenie akcji je powtórzy");
  });

  it("porażka stawki nie tworzy linku ani nie rusza etapu", async () => {
    setRecruitmentClientRate.mockRejectedValueOnce(new Error("422"));
    renderWorkbench();
    await waitFor(() => expect(brandedGet).toHaveBeenCalled());

    await userEvent.type(screen.getByLabelText("Kwota"), "25000");
    await userEvent.click(await sendButton());

    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(shareCreate).not.toHaveBeenCalled();
    expect(move).not.toHaveBeenCalled();
    expect(showError.mock.calls[0][0]).toContain("Nic nie zostało zmienione");
  });

  it("karta czekająca na akceptację stawki ma wysyłkę zablokowaną z powodem", async () => {
    renderWorkbench({
      columns: columns([item({ verification_status: "pending" })]),
    });
    const button = await sendButton();
    expect(button).toBeDisabled();
    expect(button.getAttribute("title")).toContain("czeka na akceptację");
  });

  it("weto hiring managera blokuje wysyłkę", async () => {
    renderWorkbench({
      columns: columns([
        item({
          hm_veto: {
            hiring_manager_contact_id: 5,
            source_job_id: 2,
            rejected_at: "2026-01-01",
            rejection_reason_name: "Brak bankowości",
          },
        }),
      ]),
    });
    const button = await sendButton();
    expect(button).toBeDisabled();
    expect(button.getAttribute("title")).toContain("Brak bankowości");
  });

  it("tryb tylko do odczytu nie pokazuje wysyłki", () => {
    renderWorkbench({ readOnly: true });
    expect(
      screen.queryByRole("button", {
        name: /Wyślij klientowi i przenieś/,
      }),
    ).toBeNull();
  });
});
