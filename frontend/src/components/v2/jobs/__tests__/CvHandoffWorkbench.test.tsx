/**
 * CvHandoffWorkbench — stanowisko „CV do klienta" (krok 06, program „flow
 * w języku C2", PR 6/7).
 *
 * Zakres: kolejka zweryfikowanych, bramka wysyłki widoczna z powodem oraz
 * SEKWENCJA „Wyślij klientowi" — kolejność `move → share-token → client-rate`
 * (ruch pierwszy, bo link to żywy dostęp do CV i nie może powstać dla ruchu,
 * którego serwer odmówi; link celuje w etap SPRZED ruchu, gdzie leży CV
 * brandowane; stawka po ruchu, bo zapisuje się na najnowszym etapie), porażka
 * ruchu przerywa resztę, porażka linku lub stawki PO ruchu jest ostrzeżeniem.
 * Stawkę do klienta zapisuje wyłącznie admin (`CandidateFinanceAccess`) —
 * inne role nie widzą pola.
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
const selectGenerated = vi.fn();
const shareList = vi.fn();
const shareRevokeAll = vi.fn();
const createScreeningShareToken = vi.fn();
// Schowek sterowany wprost — `user-event` podmienia `navigator.clipboard`
// własną zaślepką, która zawsze się udaje, a tu testujemy także porażkę.
const copyText = vi.fn(async (..._a: unknown[]) => true);

vi.mock("@/lib/clipboard", () => ({
  copyTextToClipboard: (...a: unknown[]) => copyText(...a),
}));

vi.mock("next/dynamic", () => ({ default: () => () => null }));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: vi.fn(), post: vi.fn() },
  pipelineApi: { move: (...a: unknown[]) => move(...a) },
  candidatesApi: {
    setRecruitmentClientRate: (...a: unknown[]) =>
      setRecruitmentClientRate(...a),
  },
  cvGeneratedShareApi: { approvedVersions: async () => ({data: [{id: 81, version: 2, language: "pl", approved_at: "2026-09-09T12:00:00Z"}]}) },
  candidateStageCvApi: {
    original: { get: (...a: unknown[]) => originalGet(...a) },
    branded: { get: (...a: unknown[]) => brandedGet(...a), selectGenerated: (...a: unknown[]) => selectGenerated(...a) },
    share: {
      create: (...a: unknown[]) => shareCreate(...a),
      list: (...a: unknown[]) => shareList(...a),
      revokeAll: (...a: unknown[]) => shareRevokeAll(...a),
    },
  },
  // Link do karty Championa w doku — ten sam endpoint, którego używa krok 07.
  screeningApi: {
    createShareToken: (...a: unknown[]) => createScreeningShareToken(...a),
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
    onSelectForRecruitment?: (item: { id: number; filename: string }) => void;
  }) => (
    <div data-testid="cv-generator-stub">
      {`prefill:${p.prefillCandidateId}/${p.prefillJobId}`}
      {p.onSelectForRecruitment && <button onClick={() => p.onSelectForRecruitment!({ id: 42, filename: "Wybrane.docx" })}>Użyj w rekrutacji</button>}
    </div>
  ),
}));
// Reguła CV klienta — szyna makiety wypisuje ją klockami, więc test musi móc
// podać ZATWIERDZONĄ regułę (bez `is_active` obowiązuje baner „brak reguł").
let cvRule: Record<string, unknown> | undefined = undefined;
vi.mock("@/components/v2/cv-generator/ClientCvRuleBanner", () => ({
  ClientCvRuleBanner: () => <div data-testid="cv-rule-banner" />,
  useClientCvRule: () => ({ data: cvRule, isLoading: false, isError: false }),
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
    name: /(?:Utwórz link i oznacz|Oznacz) „CV Wysłane”/,
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
  cvRule = undefined;
  originalGet.mockResolvedValue({ data: { has_snapshot: true } });
  brandedGet.mockResolvedValue({ data: { status: "finalized" } });
  shareList.mockResolvedValue({ data: [] });
  copyText.mockResolvedValue(true);
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
    // Jedna karta na „CV Wysłane" przy limicie 3 z karty klienta — ta sama
    // liczba w pigułce nagłówka i w szynie reguł klienta (makieta kroku 06).
    expect(screen.getByText("Limit CV: 1 z 3")).toBeTruthy();
    expect(screen.getByText("Limit CV na proces: 3")).toBeTruthy();
    expect(screen.getByText("u klienta jest 1")).toBeTruthy();
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

  it("sekwencja idzie: ruch → link (na etapie SPRZED ruchu) → stawka (na NOWYM etapie)", async () => {
    const { onMoved } = renderWorkbench();
    await readySendButton();

    await userEvent.type(screen.getByLabelText("Kwota"), "25000");
    await userEvent.click(await sendButton());

    await waitFor(() => expect(setRecruitmentClientRate).toHaveBeenCalledOnce());
    expect(calls).toEqual(["move", "share_link", "client_rate"]);
    // Etap 21 = „Zweryfikowany", na którym leży sfinalizowane CV brandowane —
    // nie świeży „CV Wysłane" (id 99), który ruch właśnie utworzył.
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

    await waitFor(() => expect(shareCreate).toHaveBeenCalledOnce());
    expect(calls).toEqual(["move", "share_link"]);
    expect(setRecruitmentClientRate).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(showSuccess).toHaveBeenCalledWith(
        expect.stringContaining("Stawka do klienta bez zmian"),
      ),
    );
  });

  it("rola bez uprawnienia finansowego nie widzi pola stawki, a wysyłka i tak idzie", async () => {
    authState.user = { role: "recruiter", roles: ["recruiter"] };
    renderWorkbench();
    await readySendButton();

    expect(screen.queryByLabelText("Kwota")).toBeNull();
    expect(screen.getByText(/Stawkę do klienta zapisuje admin/)).toBeTruthy();

    await userEvent.click(await sendButton());
    await waitFor(() => expect(shareCreate).toHaveBeenCalledOnce());
    expect(setRecruitmentClientRate).not.toHaveBeenCalled();
    expect(calls).toEqual(["move", "share_link"]);
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

  it("porażka linku PO ruchu: ruch został, a panel wyników daje ponowienie na etapie sprzed ruchu", async () => {
    shareCreate.mockRejectedValueOnce(new Error("502 bramka"));
    const { onMoved } = renderWorkbench();
    await readySendButton();

    await userEvent.type(screen.getByLabelText("Kwota"), "25000");
    await userEvent.click(await sendButton());

    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(move).toHaveBeenCalledOnce();
    // Stawka i tak się zapisuje — porażka linku nie jest fatalna.
    expect(setRecruitmentClientRate).toHaveBeenCalledOnce();
    expect(onMoved).toHaveBeenCalled();
    const msg = showError.mock.calls[0][0] as string;
    expect(msg).toContain("Kandydat przeniesiony");
    expect(msg).toContain("Linku dla klienta NIE udało się utworzyć");
    expect(msg).toContain("502 bramka");

    // Profil i dok celują w najnowszy etap (bez CV brandowanego), więc jedyna
    // droga do linku to ponowienie z ZAPAMIĘTANEGO etapu 21.
    shareCreate.mockResolvedValueOnce({ data: { share_url_suffix: "/cv/retried" } });
    await userEvent.click(
      await screen.findByRole("button", {
        name: /Utwórz link ponownie: Grzegorz Żebrowski/,
      }),
    );
    await waitFor(() => expect(shareCreate).toHaveBeenCalledTimes(2));
    expect(shareCreate).toHaveBeenLastCalledWith(21, 14);
    expect(await screen.findByText(/\/cv\/retried/)).toBeTruthy();
  });

  it("porażka ruchu (odmowa serwera) NIE tworzy linku ani stawki — i mówi o tym wprost", async () => {
    move.mockRejectedValueOnce(
      Object.assign(new Error("409 weto hiring managera"), {
        response: { status: 409 },
      }),
    );
    renderWorkbench();
    await readySendButton();

    await userEvent.type(screen.getByLabelText("Kwota"), "25000");
    await userEvent.click(await sendButton());

    await waitFor(() => expect(showError).toHaveBeenCalled());
    const msg = showError.mock.calls[0][0] as string;
    expect(msg).toContain("przeniesienie na „CV Wysłane”");
    expect(msg).toContain("Nic nie zostało zmienione");
    expect(msg).toContain("link dla klienta nie powstał");
    // Do 09.2026 link powstawał PRZED ruchem — odmowa zostawiała żywy,
    // wielodniowy dostęp do CV, którego nikt nie wysłał.
    expect(shareCreate).not.toHaveBeenCalled();
    expect(setRecruitmentClientRate).not.toHaveBeenCalled();
    expect(screen.queryByRole("region", { name: "Utworzone linki do CV" })).toBeNull();
  });

  it("limit czasu ruchu NIE mówi „nic się nie zmieniło” — każe odświeżyć kartę przed ponowieniem", async () => {
    // Bez odpowiedzi serwera ruch mógł się zatwierdzić; „nic się nie stało"
    // zachęcało do ponowienia, które dopisuje drugi etap „CV Wysłane".
    move.mockRejectedValueOnce(
      Object.assign(new Error("timeout of 60000ms exceeded"), {
        code: "ECONNABORTED",
      }),
    );
    renderWorkbench();
    await readySendButton();

    await userEvent.type(screen.getByLabelText("Kwota"), "25000");
    await userEvent.click(await sendButton());

    await waitFor(() => expect(showError).toHaveBeenCalled());
    const msg = showError.mock.calls[0][0] as string;
    expect(msg).not.toContain("Nic nie zostało zmienione");
    expect(msg).toContain("Nie wiadomo, czy się udało");
    expect(msg).toContain("Odśwież kartę kandydata");
    // Link i stawka i tak nie powstały — sekwencja stanęła na ruchu.
    expect(shareCreate).not.toHaveBeenCalled();
    expect(setRecruitmentClientRate).not.toHaveBeenCalled();
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
    expect(calls).toEqual(["move", "share_link"]);
    expect(onMoved).toHaveBeenCalled();
    const msg = showError.mock.calls[0][0] as string;
    expect(msg).toContain("Kandydat przeniesiony");
    expect(msg).toContain("NIE udało się zapisać");
    expect(msg).toContain("uzupełnij ją z profilu kandydata");
  });

  it("karta czekająca na akceptację stawki JEST zablokowana z powodem — serwer odmawia każdego ruchu (409)", async () => {
    renderWorkbench({
      columns: columns([item({ verification_status: "pending" })]),
    });
    const button = await sendButton();
    await waitFor(() =>
      expect(button.getAttribute("title")).toContain("czeka na akceptację"),
    );
    expect(button).toBeDisabled();
    expect(screen.getByText(/Stawka czeka na/)).toBeTruthy();
    expect(shareCreate).not.toHaveBeenCalled();
    expect(move).not.toHaveBeenCalled();
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

  // ── Link do karty Championa: sekret zwracany RAZ ────────────────────────
  it("link do karty Championa: nieudane kopiowanie NIE udaje sukcesu, a adres zostaje na ekranie", async () => {
    createScreeningShareToken.mockResolvedValueOnce({
      data: { share_url_suffix: "/share/champion-card/sekret-1" },
    });
    copyText.mockResolvedValueOnce(false);
    renderWorkbench();

    await userEvent.click(
      await screen.findByRole("button", { name: "Utwórz link (30 dni)" }),
    );

    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(showError.mock.calls[0][0]).toContain("nie udało się go skopiować");
    expect(showSuccess).not.toHaveBeenCalledWith(
      expect.stringContaining("skopiowany"),
    );
    const field = await screen.findByLabelText("Link do karty Championa");
    expect((field as HTMLInputElement).value).toBe(
      `${window.location.origin}/share/champion-card/sekret-1`,
    );
    expect(createScreeningShareToken).toHaveBeenCalledWith(21, 30);
  });

  it("link do karty Championa: udane kopiowanie potwierdza toastem i też zostawia adres", async () => {
    createScreeningShareToken.mockResolvedValueOnce({
      data: { share_url_suffix: "/share/champion-card/sekret-2" },
    });
    renderWorkbench();

    await userEvent.click(
      await screen.findByRole("button", { name: "Utwórz link (30 dni)" }),
    );

    await waitFor(() =>
      expect(showSuccess).toHaveBeenCalledWith(
        "Link do karty Championa skopiowany (ważny 30 dni).",
      ),
    );
    expect(copyText).toHaveBeenCalledWith(
      `${window.location.origin}/share/champion-card/sekret-2`,
    );
    expect(
      ((await screen.findByLabelText("Link do karty Championa")) as HTMLInputElement)
        .value,
    ).toContain("sekret-2");
  });

  it("link do reguł CV klienta tylko dla ról z `cv_rule.manage` (inne dostałyby 403 z middleware)", () => {
    const { unmount } = renderWorkbench();
    expect(screen.getByRole("link", { name: /Reguły CV \(DL\)/ })).toBeTruthy();
    unmount();

    canManageCvRules = false;
    renderWorkbench();
    expect(screen.queryByRole("link", { name: /Reguły CV \(DL\)/ })).toBeNull();
  });

  it("tryb tylko do odczytu nie pokazuje wysyłki", () => {
    renderWorkbench({ readOnly: true });
    expect(
      screen.queryByRole("button", {
        name: /Utwórz link i oznacz/,
      }),
    ).toBeNull();
  });

  // ── Parytet z makietą (fala 3) ─────────────────────────────────────────
  it("zatwierdzona reguła klienta jest wypisana klockami PRZED generacją", async () => {
    cvRule = {
      is_active: true,
      client_name: "PKO BP",
      cv_language: "pl",
      content_mode: "redact",
      content_mode_locked: true,
      requires_rodo_consent_block: true,
      filename_preview: "B2B_Python_G.Zebrowski.docx",
    };
    renderWorkbench();
    expect(await screen.findByText("Język CV: PL")).toBeTruthy();
    expect(screen.getByText("Tryb: Redakcja")).toBeTruthy();
    expect(
      screen.getByText(/zablokowany regułą — serwer nadpisze inny wybór/),
    ).toBeTruthy();
    expect(screen.getByText("Zrzut zgody RODO")).toBeTruthy();
    expect(screen.getByText("B2B_Python_G.Zebrowski.docx")).toBeTruthy();
    // Stopka doku powtarza konsekwencję braku zrzutu — 422 przed naliczeniem.
    expect(screen.getByText(/odmawia \(422\)/)).toBeTruthy();
  });

  it("bez zatwierdzonej reguły zostaje baner o jej braku, ale limit CV nadal widać", () => {
    renderWorkbench();
    expect(screen.getByTestId("cv-rule-banner")).toBeTruthy();
    // Limit idzie z KARTY KLIENTA, nie z reguły CV — brak reguły go nie kasuje.
    expect(screen.getByText("Limit CV na proces: 3")).toBeTruthy();
  });

  it("marża liczy się dopiero przy zgodnych jednostkach — inaczej myślnik z powodem", async () => {
    renderWorkbench();
    await userEvent.type(screen.getByLabelText("Kwota"), "165");
    // Kandydat ma 118 PLN/h, jednostka doku startuje na „miesięcznie" —
    // dopóki się nie zgadzają, marża NIE może pokazać liczby.
    const margin = await screen.findByText("—");
    expect(margin.getAttribute("title")).toContain("Różne jednostki");
  });

  it("dok ma zakładki makiety, a lista linków startuje dopiero po wejściu na nią", async () => {
    renderWorkbench();
    expect(screen.getByRole("tab", { name: "Przekazanie" })).toBeTruthy();
    expect(shareList).not.toHaveBeenCalled();

    await userEvent.click(
      screen.getByRole("tab", { name: "Linki i historia" }),
    );
    await waitFor(() => expect(shareList).toHaveBeenCalledWith(21));
    expect(
      await screen.findByText(/nie ma jeszcze żadnego linku/),
    ).toBeTruthy();
  });

  it("odwołanie linków dotyczy tylko AKTYWNYCH i mówi ile ich jest", async () => {
    shareList.mockResolvedValue({
      data: [
        { revoke_key: "a", token_preview: "abc…", view_count: 2, revoked: false },
        { revoke_key: "b", token_preview: "def…", view_count: 0, revoked: true },
      ],
    });
    shareRevokeAll.mockResolvedValue({ data: { status: "ok", count: 1 } });
    renderWorkbench();
    await userEvent.click(
      screen.getByRole("tab", { name: "Linki i historia" }),
    );
    const button = await screen.findByRole("button", {
      name: /Odwołaj wcześniejsze linki \(1\)/,
    });
    await userEvent.click(button);
    await waitFor(() => expect(shareRevokeAll).toHaveBeenCalled());
    expect(shareRevokeAll.mock.calls[0][0]).toBe(21);
  });
});


import {useState as useAuditState} from "react";

it("successful move must preserve the one-time share link after queue refresh", async () => {
  const qc = new QueryClient({defaultOptions:{queries:{retry:false}}});
  function AuditHost() {
    const [remaining,setRemaining] = useAuditState(true);
    return <CvHandoffWorkbench jobId={7} jobTitle="Synthetic job" clientId={4}
      columns={columns(remaining ? [item()] : [])}
      isLoading={false} isError={false} error={null} isSuccess
      onRetry={()=>{}} onMoved={()=>setRemaining(false)} readOnly={false}/>;
  }
  render(<QueryClientProvider client={qc}><AuditHost/></QueryClientProvider>);
  await userEvent.click(await readySendButton());
  await screen.findByText(/Nikt nie czeka na wysyłkę CV/);
  expect(shareCreate).toHaveBeenCalledOnce();
  expect(move).toHaveBeenCalledOnce();
  expect(screen.queryByText(/abc123/)).not.toBeNull();
});

it("retains each result with its original candidate when moving to the next one", async () => {
  shareCreate.mockResolvedValueOnce({ data: { share_url_suffix: "/cv/first" } });
  shareCreate.mockResolvedValueOnce({ data: { share_url_suffix: "/cv/second" } });
  const qc = new QueryClient({defaultOptions:{queries:{retry:false}}});
  function Host() {
    const [step, setStep] = useAuditState(0);
    return <CvHandoffWorkbench jobId={7} jobTitle="Synthetic job" clientId={4}
      columns={columns(step === 0 ? [item()] : step === 1 ? [item({id:22,candidate_id:122,name:"Anna",lastname:"Testowa"})] : [])}
      isLoading={false} isError={false} error={null} isSuccess
      onRetry={()=>{}} onMoved={()=>setStep((n)=>n+1)} readOnly={false}/>;
  }
  render(<QueryClientProvider client={qc}><Host/></QueryClientProvider>);
  await userEvent.click(await readySendButton());
  await screen.findByText(/\/cv\/first/);
  await userEvent.click(await readySendButton());
  await screen.findByText(/Nikt nie czeka na wysyłkę CV/);
  const results = screen.getByRole("region", {name: "Utworzone linki do CV"});
  expect(within(results).getByText(/\/cv\/first/)).toBeTruthy();
  expect(within(results).getByText(/\/cv\/second/)).toBeTruthy();
  expect(within(results).getByRole("button", {name:"Kopiuj link: Grzegorz Żebrowski"})).toBeTruthy();
  expect(within(results).getByRole("button", {name:"Kopiuj link: Anna Testowa"})).toBeTruthy();
  const drafts = within(results).getAllByRole("link", {name:"Przygotuj wiadomość"});
  expect(decodeURIComponent(drafts[0].getAttribute("href")!)).toContain("Grzegorz Żebrowski");
  expect(decodeURIComponent(drafts[1].getAttribute("href")!)).toContain("Anna Testowa");
});


describe("wybór konkretnego wyniku generatora", () => {
  it("wymaga jawnego zastąpienia i wysyła wersję szkicu z chwili wyboru", async () => {
    brandedGet.mockResolvedValue({ data: { status: "draft", edit_revision: 7, version: 1 } });
    selectGenerated.mockResolvedValue({ data: { status: "draft", edit_revision: 8, version: 1,
      generated_document_id: 42, from_generator: true } });
    renderWorkbench();
    await userEvent.click(await screen.findByRole("button", { name: "Użyj w rekrutacji" }));
    expect(selectGenerated).not.toHaveBeenCalled();
    expect(screen.getByText(/Wczytać „Wybrane.docx”/)).toBeTruthy();
    await screen.findByRole("option", {name: /Zatwierdzona wersja 2/});
    await userEvent.selectOptions(screen.getByLabelText("Wersja CV do rekrutacji"), "81");
    await userEvent.click(screen.getByRole("button", { name: "Zastąp szkic i otwórz edytor" }));
    await waitFor(() => expect(selectGenerated).toHaveBeenCalledWith(21, 42, 7, 81));
    expect(await screen.findByText(/Wybrany wynik generatora #42/)).toBeTruthy();
    expect(shareCreate).not.toHaveBeenCalled();
    expect(move).not.toHaveBeenCalled();
  });

  it("po konflikcie zachowuje wybór i nie udaje powodzenia", async () => {
    brandedGet.mockResolvedValue({ data: { status: "draft", edit_revision: 7, version: 1 } });
    selectGenerated.mockRejectedValueOnce(new Error("409"));
    renderWorkbench();
    await userEvent.click(await screen.findByRole("button", { name: "Użyj w rekrutacji" }));
    await userEvent.click(screen.getByRole("button", { name: "Zastąp szkic i otwórz edytor" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wybrać CV");
    expect(screen.getByText(/Wczytać „Wybrane.docx”/)).toBeTruthy();
    expect(screen.queryByText(/Wybrany wynik generatora #42/)).toBeNull();
  });
});

it("przy braku zasobów wraca do generatora bez ponownego zastępowania szkicu", async () => {
  brandedGet.mockResolvedValue({data: {status: "draft", edit_revision: 7, version: 1}});
  selectGenerated.mockRejectedValueOnce({response: {data: {detail: {code: "cv_editor_assets_unavailable"}}}});
  Element.prototype.scrollIntoView = vi.fn();
  renderWorkbench();
  await userEvent.click(await screen.findByRole("button", {name: "Użyj w rekrutacji"}));
  await userEvent.click(screen.getByRole("button", {name: "Zastąp szkic i otwórz edytor"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Obecny szkic pozostaje bez zmian");
  await userEvent.click(screen.getByRole("button", {name: "Przejdź do generatora"}));
  expect(selectGenerated).toHaveBeenCalledTimes(1);
  expect(screen.queryByText(/Wczytać „Wybrane.docx”/)).toBeNull();
  expect(screen.queryByText(/Wybrany wynik generatora #42/)).toBeNull();
  expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
});
