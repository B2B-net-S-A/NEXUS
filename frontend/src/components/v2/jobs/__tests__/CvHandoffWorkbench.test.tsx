/**
 * CvHandoffWorkbench — stanowisko „CV do klienta" (krok 06, program „flow
 * w języku C2", PR 6/7).
 *
 * Zakres: kolejka zweryfikowanych, bramka wysyłki widoczna z powodem oraz
 * SEKWENCJA „Wyślij klientowi" — kolejność `share-token → move → client-rate`
 * (link przed ruchem, bo ruch tworzy nowy etap bez CV; stawka po ruchu, bo
 * zapisuje się na najnowszym etapie), porażka PRZED ruchem przerywa resztę,
 * porażka stawki PO ruchu jest ostrzeżeniem. Stawkę do klienta zapisuje
 * wyłącznie admin (`CandidateFinanceAccess`) — inne role nie widzą pola.
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

// Rola steruje polem stawki (admin-only) — ustawiana per test.
const authState: { user: { role: string; roles: string[] } | null } = {
  user: { role: "admin", roles: ["admin"] },
};
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (s: { user: unknown; realUser: null }) => unknown) =>
    selector({ user: authState.user, realUser: null }),
  hasRole: (user: { roles?: string[]; role?: string } | null, ...roles: string[]) =>
    !!user && roles.some((r) => (user.roles ?? [user.role]).includes(r)),
}));
let canManageCvRules = true;
vi.mock("@/hooks/useCapability", () => ({
  useCapability: () => canManageCvRules,
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

/** Przycisk jest zablokowany, dopóki stan CV brandowanego się nie wczyta. */
async function readySendButton() {
  const button = await sendButton();
  await waitFor(() => expect(button).not.toBeDisabled());
  return button;
}

beforeEach(() => {
  vi.clearAllMocks();
  calls.length = 0;
  authState.user = { role: "admin", roles: ["admin"] };
  canManageCvRules = true;
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

  it("sekwencja idzie: link → ruch → stawka (stawka na NOWYM etapie, jak na tablicy)", async () => {
    const { onMoved } = renderWorkbench();
    await readySendButton();

    await userEvent.type(screen.getByLabelText("Kwota"), "25000");
    await userEvent.click(await sendButton());

    await waitFor(() => expect(setRecruitmentClientRate).toHaveBeenCalledOnce());
    expect(calls).toEqual(["share_link", "move", "client_rate"]);
    expect(shareCreate).toHaveBeenCalledWith(21, 14);
    expect(move).toHaveBeenCalledWith({
      candidate_id: 121,
      job_id: 7,
      stage: "cv_sent",
      stage_def_id: 5,
    });
    expect(setRecruitmentClientRate).toHaveBeenCalledWith(121, 7, {
      rate_value: 25000,
      rate_unit: "monthly",
      rate_currency: "PLN",
    });
    expect(onMoved).toHaveBeenCalled();
    expect(showSuccess).toHaveBeenCalledWith(
      expect.stringContaining("Stawka do klienta zapisana"),
    );
  });

  it("puste pole stawki = świadome pominięcie, komunikat nie sugeruje braku", async () => {
    renderWorkbench();
    await readySendButton();

    await userEvent.click(await sendButton());

    await waitFor(() => expect(move).toHaveBeenCalledOnce());
    expect(calls).toEqual(["share_link", "move"]);
    expect(setRecruitmentClientRate).not.toHaveBeenCalled();
    expect(showSuccess).toHaveBeenCalledWith(
      expect.stringContaining("Stawka do klienta bez zmian"),
    );
  });

  it("rola bez uprawnienia finansowego nie widzi pola stawki, a wysyłka i tak idzie", async () => {
    authState.user = { role: "recruiter", roles: ["recruiter"] };
    renderWorkbench();
    await readySendButton();

    expect(screen.queryByLabelText("Kwota")).toBeNull();
    expect(screen.getByText(/Stawkę do klienta zapisuje admin/)).toBeTruthy();

    await userEvent.click(await sendButton());
    await waitFor(() => expect(move).toHaveBeenCalledOnce());
    expect(setRecruitmentClientRate).not.toHaveBeenCalled();
    expect(calls).toEqual(["share_link", "move"]);
  });

  it("bez sfinalizowanego CV brandowanego link nie powstaje, a powód jest widoczny", async () => {
    brandedGet.mockResolvedValue({ data: { status: "draft" } });
    renderWorkbench();
    expect(
      await screen.findByText(/wymaga sfinalizowanego CV brandowanego/),
    ).toBeTruthy();
    await readySendButton();

    await userEvent.click(await sendButton());

    await waitFor(() => expect(move).toHaveBeenCalledOnce());
    expect(shareCreate).not.toHaveBeenCalled();
    expect(calls).toEqual(["move"]);
  });

  it("w oknie ładowania stanu CV brandowanego wysyłka jest zablokowana (nie „bez linku” po cichu)", async () => {
    let resolveBranded: (v: unknown) => void = () => {};
    brandedGet.mockImplementation(
      () => new Promise((resolve) => { resolveBranded = resolve; }),
    );
    renderWorkbench();
    const button = await sendButton();
    expect(button).toBeDisabled();
    expect(button.getAttribute("title")).toContain("Sprawdzam stan CV brandowanego");
    resolveBranded({ data: { status: "finalized" } });
    await waitFor(() => expect(button).not.toBeDisabled());
  });

  it("porażka linku ZATRZYMUJE ruch i mówi, że nic nie zostało zmienione", async () => {
    shareCreate.mockRejectedValueOnce(new Error("409 brak finalizacji"));
    renderWorkbench();
    await readySendButton();

    await userEvent.type(screen.getByLabelText("Kwota"), "25000");
    await userEvent.click(await sendButton());

    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(move).not.toHaveBeenCalled();
    expect(setRecruitmentClientRate).not.toHaveBeenCalled();
    const msg = showError.mock.calls[0][0] as string;
    expect(msg).toContain("utworzenie linku dla klienta");
    expect(msg).toContain("409 brak finalizacji");
    expect(msg).toContain("Nic nie zostało zmienione");
  });

  it("porażka ruchu pokazuje utworzony link w doku i odznacza „Utwórz link”, żeby ponowienie nie zrobiło drugiego", async () => {
    move.mockRejectedValueOnce(new Error("409 weto hiring managera"));
    renderWorkbench();
    await readySendButton();

    await userEvent.click(await sendButton());

    await waitFor(() => expect(showError).toHaveBeenCalled());
    const msg = showError.mock.calls[0][0] as string;
    expect(msg).toContain("przeniesienie na „CV Wysłane”");
    expect(msg).toContain("JUŻ ISTNIEJE");
    expect(setRecruitmentClientRate).not.toHaveBeenCalled();
    // Sekret tokenu jest zwracany RAZ — musi zostać na ekranie.
    expect(await screen.findByText("abc123")).toBeTruthy();
    expect(
      screen.getByRole("checkbox", { name: /Utwórz link do brandowanego CV/ }),
    ).not.toBeChecked();
  });

  it("porażka stawki PO ruchu nie cofa ruchu — ostrzeżenie z następnym krokiem, jak na tablicy", async () => {
    setRecruitmentClientRate.mockRejectedValueOnce(
      new Error("Requires candidate role: ['admin']"),
    );
    const { onMoved } = renderWorkbench();
    await readySendButton();

    await userEvent.type(screen.getByLabelText("Kwota"), "25000");
    await userEvent.click(await sendButton());

    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(calls).toEqual(["share_link", "move"]);
    expect(onMoved).toHaveBeenCalled();
    const msg = showError.mock.calls[0][0] as string;
    expect(msg).toContain("Kandydat przeniesiony");
    expect(msg).toContain("NIE udało się zapisać");
    expect(msg).toContain("uzupełnij ją z profilu kandydata");
  });

  it("karta czekająca na akceptację stawki NIE jest blokowana (pending nie jest bramką ruchu), tylko oznaczona", async () => {
    renderWorkbench({
      columns: columns([item({ verification_status: "pending" })]),
    });
    const button = await readySendButton();
    expect(button).not.toBeDisabled();
    expect(screen.getByText(/Stawka czeka na/)).toBeTruthy();
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

  it("link do reguł CV klienta tylko dla ról z `cv_rule.manage` (inne dostałyby 403 z middleware)", () => {
    const { unmount } = renderWorkbench();
    expect(screen.getByRole("link", { name: /Reguły CV klienta/ })).toBeTruthy();
    unmount();

    canManageCvRules = false;
    renderWorkbench();
    expect(screen.queryByRole("link", { name: /Reguły CV klienta/ })).toBeNull();
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
