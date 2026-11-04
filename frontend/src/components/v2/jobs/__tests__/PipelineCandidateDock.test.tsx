/**
 * PipelineCandidateDock — testy doku „Karta w procesie" (krok 04 Pipeline,
 * program „flow w języku C2", PR 3/7).
 *
 * Zakres celowo wąski: render + bramka „Przenieś na etap" (wyszarzony
 * przycisk z powodem w `title`, klik na odblokowaną pigułkę woła `onMoveTo`
 * z DOKŁADNIE tą kolumną, którą dostał komponent — bramka sama w sobie
 * liczy się w `KanbanBoardV2`, ten test sprawdza tylko, że dok ją poprawnie
 * RENDERUJE i PRZEKAZUJE dalej) + `readOnly`/`canReject` chowają akcje
 * zapisu. Modale CV/email i `DopasowanieTab` są zamockowane — mają WŁASNE
 * zapytania do innych endpointów, niepowiązane z tym, co testujemy tutaj.
 */

import { useContext, type ComponentProps, type ReactNode } from "react";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// 09.10.2026: sekcja „Screening” czyta stan formularza pary
// (`GET /api/screening-form`), nie arkusz etapu.
const formGet = vi.fn();
const originalGet = vi.fn();
const brandedGet = vi.fn();
const candidatesGet = vi.fn();
const apiGet = vi.fn();
const apiPost = vi.fn();

// `next/dynamic` (`CVBrandedEditModal`) — precedens z `app/settings/page.test.tsx`:
// mockujemy sam `next/dynamic`, żeby dynamicznie importowany moduł nigdy nie
// próbował się realnie rozwiązać w jsdom.
vi.mock("next/dynamic", () => ({ default: () => () => null }));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (url: string, ...rest: unknown[]) =>
      url === "/api/screening-form" ? formGet(url, ...rest) : apiGet(url, ...rest),
    post: (...a: unknown[]) => apiPost(...a),
  },
  candidatesApi: {
    get: (...a: unknown[]) => candidatesGet(...a),
  },
  candidateStageCvApi: {
    original: { get: (...a: unknown[]) => originalGet(...a) },
    branded: { get: (...a: unknown[]) => brandedGet(...a) },
  },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
}));

const toastSuccess = vi.fn();
const toastError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: (...a: unknown[]) => toastSuccess(...a),
    showError: (...a: unknown[]) => toastError(...a),
  }),
}));

// Modale CV/email mają WŁASNE zapytania (inne endpointy) — dok tylko je
// otwiera/zamyka, więc dla testów doku wystarczy pusty stub.
// „Ściąga do rozmowy” ma własne zapytanie (wyjaśnienie „po ludzku”) i testy.
vi.mock("@/components/v2/jobs/DockCallCheatsheet", () => ({
  DockCallCheatsheet: () => null,
}));
vi.mock("@/components/v2/modals/QuickAssignV2", () => ({
  QuickAssignV2: ({ candidateName }: { candidateName: string }) => (
    <h2>Przypisz do rekrutacji — {candidateName}</h2>
  ),
}));
vi.mock("@/components/v2/modals/CVOriginalPreviewModal", () => ({
  CVOriginalPreviewModal: () => null,
}));
vi.mock("@/components/v2/modals/CVShareLinkModal", () => ({
  CVShareLinkModal: () => null,
}));
const composeDialog = vi.fn();
vi.mock("@/components/emails/EmailCompose", () => ({
  default: (props: Record<string, unknown>) => {
    composeDialog(props);
    return <div data-testid="m365-compose-dialog" />;
  },
}));
// Okno generatora CV (v3) — dok tylko je otwiera z osobą i rekrutacją.
const generatorDialog = vi.fn();
vi.mock("@/components/v2/cv-generator/CvGeneratorDialog", () => ({
  CvGeneratorDialog: (props: Record<string, unknown>) => {
    generatorDialog(props);
    return <div data-testid="cv-generator-dialog" />;
  },
}));
// `DopasowanieTab` woła `matchScoringApi` — niepowiązane z tym, co testujemy;
// stub żeby nie trzeba było mockować jeszcze jednego modułu API.
vi.mock("@/components/v2/pages/DopasowanieTab", () => ({
  DopasowanieTab: () => <div data-testid="dopasowanie-tab-stub" />,
}));

// Okna akcji z ramki „Następny etap” — dok tylko je otwiera ze stageId.
const qcDialog = vi.fn();
vi.mock("@/components/v2/recruitment/CvQcDialog", () => ({
  CvQcDialog: (props: Record<string, unknown>) => {
    qcDialog(props);
    return <div data-testid="cv-qc-dialog" />;
  },
}));
vi.mock("@/components/v2/recruitment/DebriefRequiredDialog", () => ({
  DebriefRequiredDialog: () => <div data-testid="debrief-dialog" />,
}));

// „Pobierz Word / PDF” w sekcji CV (D1, 14.10.2026) — plik CV etapu i zapis na dysk.
const stageCvFile = vi.fn();
const stageCvPdf = vi.fn();
vi.mock("@/lib/stage-cv-file", () => ({
  fetchStageCvFile: (...a: unknown[]) => stageCvFile(...a),
  fetchStageCvPdf: (...a: unknown[]) => stageCvPdf(...a),
}));
const savedFiles = vi.fn();
vi.mock("@/lib/authenticated-files", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/authenticated-files")>()),
  downloadBlob: (...a: unknown[]) => savedFiles(...a),
}));

import { PipelineCandidateDock, nowSectionForStage, earlyQcSentence } from "@/components/v2/jobs/PipelineCandidateDock";
import { PersonPanelColumn, PersonPanelSideProvider } from "@/components/v2/person/PersonPanelSide";
import { TooltipProvider } from "@/components/ui/tooltip";
import { WorkbenchBelowTabsContext } from "@/components/v2/person/WorkbenchBelowTabs";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";
import { formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";
import type { ScreeningFormState } from "@/lib/api/screeningForm";
import { createNoteFillChannel, type NoteFillReceiver } from "@/lib/note-fill-channel";
import { useAuthStore } from "@/store/auth";

/** Stan formularza screeningu pary z doku (kandydat 42, rekrutacja 10, wiersz etapu 501). */
function dockForm(overrides: Partial<ScreeningFormState> = {}): ScreeningFormState {
  return formState({ candidate_id: 42, job_id: 10, stage_id: 501, ...overrides });
}

function baseItem(overrides: Partial<KanbanItem> = {}): KanbanItem {
  return {
    id: 501,
    candidate_id: 42,
    // Etap u klienta → sekcja „Teraz" to „W procesie" (oś czasu i warunki).
    stage: "cv_sent",
    name: "Anna",
    lastname: "Kowalska",
    days_in_stage: 3,
    verification_status: "active",
    ...overrides,
  };
}

function stageCol(
  stage: string,
  name: string,
  overrides: Partial<KanbanColumn> = {}
): KanbanColumn {
  return {
    stage,
    name,
    category: "internal",
    count: 0,
    items: [],
    stage_def_id: null,
    ...overrides,
  };
}

type DockProps = ComponentProps<typeof PipelineCandidateDock>;

let lastQueryClient: QueryClient | null = null;

function renderDock(overrides: Partial<DockProps> = {}, wrap: (dock: ReactNode) => ReactNode = (dock) => dock) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  lastQueryClient = qc;
  const props: DockProps = {
    item: baseItem(),
    jobId: 10,
    currentStageLabel: "Nowi / Analiza CV",
    moveTargets: [],
    readOnly: false,
    contactFeatureEnabled: false,
    canReject: true,
    onClose: vi.fn(),
    onMoveTo: vi.fn(),
    onOpenScreening: vi.fn(),
    onReject: vi.fn(),
    ...overrides,
  };
  render(
    <QueryClientProvider client={qc}>
      <TooltipProvider>{wrap(<PipelineCandidateDock {...props} />)}</TooltipProvider>
    </QueryClientProvider>
  );
  return props;
}

describe("PipelineCandidateDock", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    formGet.mockResolvedValue({ data: dockForm() });
    originalGet.mockResolvedValue({
      data: {
        candidate_stage_id: 501,
        candidate_id: 42,
        job_id: 10,
        has_snapshot: false,
        original_cv_filename: null,
        original_cv_language: null,
        original_snapshot_at: null,
        original_snapshot_source: null,
        download_url: null,
      },
    });
    brandedGet.mockResolvedValue({
      data: {
        candidate_stage_id: 501,
        status: "none",
        content_html: null,
        template: null,
        language: null,
        updated_at: null,
        updated_by: null,
        updated_by_name: null,
        finalized_at: null,
        finalized_by: null,
        finalized_by_name: null,
        snapshot_filename: null,
        rendered_from_default: false,
      },
    });
    candidatesGet.mockResolvedValue({ data: { email: "anna@example.com" } });
    apiGet.mockResolvedValue({ data: { items: [] } });
    apiPost.mockResolvedValue({ data: {} });
  });

  it("renderuje nagłówek i otwiera sekcję „Teraz” właściwą dla etapu", () => {
    renderDock();
    expect(screen.getByText("Anna Kowalska")).toBeTruthy();
    expect(screen.getByText(/Etap · Nowi \/ Analiza CV/)).toBeTruthy();
    expect(screen.getByRole("button", { name: /W procesie.*Teraz/ })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("pozostałe sekcje są zwinięte, ale wszystkie osiągalne (bez chowania za krawędzią)", () => {
    renderDock();
    for (const name of [/^Screening/, /^CV/, /^Dopasowanie/, /^Notatki/]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute("aria-expanded", "false");
    }
  });

  it("sekcja „Teraz” zależy od etapu: Nowi (także Screening) → Screening, Zweryfikowany → CV", () => {
    expect(nowSectionForStage("new")).toBe("screening");
    expect(nowSectionForStage("posting")).toBe("screening");
    expect(nowSectionForStage("prep_call")).toBe("screening");
    expect(nowSectionForStage("screening")).toBe("screening");
    expect(nowSectionForStage("verified")).toBe("cv");
    expect(nowSectionForStage("client_interview")).toBe("process");
    expect(nowSectionForStage(null)).toBe("process");
  });

  it("wyszarza zablokowany etap w menu „Inny etap…” z powodem pod nazwą", async () => {
    const user = userEvent.setup();
    const target = stageCol("cv_sent", "CV Wysłane", { stage_def_id: 5 });
    renderDock({
      moveTargets: [
        { col: target, blockedReason: "Weto hiring managera — nie proponuj ponownie." },
      ],
    });

    // Ściana pigułek zniknęła — etapy są dopiero w menu.
    expect(screen.queryByRole("button", { name: "CV Wysłane" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Inny etap…" }));
    const item = await screen.findByRole("menuitem", { name: "CV Wysłane" });
    expect(item).toHaveAttribute("aria-disabled", "true");
    expect(item).toHaveTextContent("Weto hiring managera — nie proponuj ponownie.");
  });

  it("wybór odblokowanego etapu z menu woła onMoveTo z tą samą kolumną", async () => {
    const user = userEvent.setup();
    const target = stageCol("screening", "Screening", { stage_def_id: 2 });
    const onMoveTo = vi.fn();
    renderDock({ moveTargets: [{ col: target, blockedReason: null }], onMoveTo });

    await user.click(screen.getByRole("button", { name: "Inny etap…" }));
    const item = await screen.findByRole("menuitem", { name: "Screening" });
    expect(item).not.toHaveAttribute("aria-disabled", "true");
    await user.click(item);

    await waitFor(() => expect(onMoveTo).toHaveBeenCalledTimes(1));
    expect(onMoveTo).toHaveBeenCalledWith(target);
  });

  it("nie pokazuje menu etapów, gdy moveTargets jest puste (nie wymyśla etapów)", () => {
    renderDock({ moveTargets: [] });
    expect(screen.queryByRole("button", { name: "Inny etap…" })).toBeNull();
  });

  it("w trybie readOnly nie pokazuje menu etapów ani noty o kodzie 409", () => {
    const target = stageCol("screening", "Screening", { stage_def_id: 2 });
    renderDock({ moveTargets: [{ col: target, blockedReason: "Tylko odczyt" }], readOnly: true });
    expect(screen.queryByRole("button", { name: "Inny etap…" })).toBeNull();
    expect(screen.queryByText(/409/)).toBeNull();
  });

  it("„Zrezygnował” obok odrzucenia woła rezygnację (Pipeline v4); readOnly je chowa", async () => {
    const user = userEvent.setup();
    const props = renderDock({ onWithdraw: vi.fn() });
    await user.click(screen.getByRole("button", { name: "Zrezygnował" }));
    expect(props.onWithdraw).toHaveBeenCalledTimes(1);
    cleanup();
    renderDock({ onWithdraw: vi.fn(), readOnly: true });
    expect(screen.queryByRole("button", { name: "Zrezygnował" })).toBeNull();
  });

  it("pasek po zamknięciu poprzedniej osoby: kto i dlaczego, „Pokaż” wraca do niej (13.10.2026)", async () => {
    const user = userEvent.setup();
    const onShow = vi.fn();
    renderDock({
      position: 1,
      total: 2,
      closedNotice: { verb: "Odrzucono", name: "Michał Zieliński", reason: "Brak Azure", onShow },
    });
    const notice = screen.getByRole("status", { name: "Poprzednia osoba" });
    expect(notice).toHaveTextContent("Odrzucono: Michał Zieliński · Brak Azure");
    await user.click(within(notice).getByRole("button", { name: "Pokaż" }));
    expect(onShow).toHaveBeenCalledTimes(1);
  });

  it("bez paska nie ma statusu poprzedniej osoby", () => {
    renderDock({ position: 1, total: 2 });
    expect(screen.queryByRole("status", { name: "Poprzednia osoba" })).toBeNull();
  });

  it("osoba spoza kolejności z „Wróć do kolejki” zamiast napisu „Panel osoby”", async () => {
    const user = userEvent.setup();
    const onReturnToQueue = vi.fn();
    renderDock({ position: null, total: 2, onReturnToQueue });
    await user.click(screen.getByRole("button", { name: "Wróć do kolejki" }));
    expect(onReturnToQueue).toHaveBeenCalledTimes(1);
    expect(within(screen.getByTestId("dock-person-bar")).queryByText("Panel osoby")).toBeNull();
  });

  it("chowa „Odrzuć z powodem”, gdy canReject=false (np. kandydat już terminalny)", () => {
    renderDock({ canReject: false });
    expect(screen.queryByRole("button", { name: /Odrzuć z powodem/ })).toBeNull();
  });

  it("w trybie readOnly chowa dodawanie notatki i odrzucenie, ale zostawia odczyt", async () => {
    const user = userEvent.setup();
    renderDock({ readOnly: true, canReject: true });

    expect(screen.queryByRole("button", { name: /Odrzuć z powodem/ })).toBeNull();
    // Otwórz CV pozostaje — to podgląd, nie zapis (menu „⋯").
    await user.click(screen.getByRole("button", { name: "Więcej akcji osoby" }));
    expect(await screen.findByRole("menuitem", { name: /Otwórz CV/ })).toBeInTheDocument();
    await user.keyboard("{Escape}");

    expect(screen.queryByPlaceholderText(/Dodaj notatkę/)).toBeNull();

    await user.click(screen.getByRole("button", { name: /^CV/ }));
    expect(screen.queryByText(/Stwórz brandowane/)).toBeNull();
    expect(screen.queryByText(/Wyślij klientowi/)).toBeNull();
  });

  it("sekcja CV: bez CV do klienta „Generuj CV” otwiera okno generatora z osobą i rekrutacją", async () => {
    const user = userEvent.setup();
    renderDock();
    await user.click(screen.getByRole("button", { name: /^CV/ }));
    expect(await screen.findByText("CV firmowe: brak")).toBeInTheDocument();
    expect(screen.queryByText(/Stwórz brandowane/)).toBeNull();
    await user.click(await screen.findByRole("button", { name: /Generuj CV/ }));
    expect(screen.getByTestId("cv-generator-dialog")).toBeInTheDocument();
    expect(generatorDialog).toHaveBeenLastCalledWith(
      expect.objectContaining({ candidateId: 42, jobId: 10 }),
    );
  });

  it("sekcja CV: szkic z generatora to plakietka „CV do klienta: szkic” i „Edytuj CV”", async () => {
    const user = userEvent.setup();
    brandedGet.mockResolvedValue({ data: { status: "draft", from_generator: true, edit_revision: 1, version: 1 } });
    renderDock();
    await user.click(screen.getByRole("button", { name: /^CV/ }));
    expect(await screen.findByText("CV firmowe: szkic")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Edytuj CV/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Generuj CV/ })).toBeNull();
  });

  it("zamknięcie doku woła onClose", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    renderDock({ onClose });

    await user.click(screen.getByRole("button", { name: "Zamknij dok" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("pokazuje flagę weta HM w nagłówku, gdy karta ją niesie", () => {
    renderDock({
      item: baseItem({
        hm_veto: {
          hiring_manager_contact_id: 7,
          hiring_manager_name: "Jan Nowak",
          source_job_id: 99,
          source_job_title: "Inna rekrutacja",
          rejected_at: "2026-08-01T00:00:00Z",
          rejection_reason_name: "Nie pasuje kulturowo",
        },
      }),
    });
    expect(screen.getByText("Weto HM")).toBeTruthy();
  });

  it("głowa panelu: krótka pigułka „Pracuje u nas”, szczegóły w dymku po kliknięciu", async () => {
    const user = userEvent.setup();
    renderDock({
      item: baseItem({
        employment_marker: {
          phase: "working",
          source: "contract",
          elsewhere: true,
          clients: [
            {
              client_id: 4,
              client_name: "Bank Przykładowy",
              contract_id: 40,
              phase: "working",
              order_end_date: "2026-12-31",
              delivery_lead_name: "Karol Wzorcowy",
            },
          ],
        },
      }),
    });

    // Bez nazwy klienta — głowa panelu nie może rosnąć (zapas na treść pod nią).
    const pill = screen.getByRole("button", { name: "Pracuje u nas · do 31.12" });
    expect(screen.queryByRole("note")).toBeNull();

    await user.click(pill);
    const notice = screen.getByRole("note");
    expect(notice).toHaveTextContent("Pracuje u nas · Bank Przykładowy");
    expect(notice).toHaveTextContent("Zamówienie do 31.12.2026 · Delivery Lead: Karol Wzorcowy");
  });

  it("bez znacznika głowa panelu nie ma pigułki zatrudnienia", () => {
    renderDock();
    expect(screen.queryByRole("button", { name: /Pracuje u nas/ })).toBeNull();
  });

  it("zakładka Screening otwiera Screening Championa przez onOpenScreening", async () => {
    const user = userEvent.setup();
    const onOpenScreening = vi.fn();
    renderDock({ onOpenScreening });

    await user.click(screen.getByRole("button", { name: /^Screening/ }));
    await user.click(
      screen.getByRole("button", { name: /Otwórz rozmowę z kandydatem/ })
    );

    expect(onOpenScreening).toHaveBeenCalledWith(501, "Anna Kowalska");
  });

  it("akcja maila otwiera kompozytor M365 z pobranym adresem i kontekstem rekrutacji", async () => {
    const user = userEvent.setup();
    renderDock();
    await user.click(screen.getByRole("button", { name: "Więcej akcji osoby" }));
    await user.click(screen.getByRole("menuitem", { name: "Wyślij wiadomość" }));
    await screen.findByTestId("m365-compose-dialog");
    expect(composeDialog).toHaveBeenLastCalledWith(
      expect.objectContaining({
        mode: "new",
        candidateId: 42,
        candidateName: "Anna Kowalska",
        defaultTo: "anna@example.com",
        requestId: 10,
      }),
    );
  });
  it("warsztaty z dawnej Tabeli (CV do klienta, rozmowy, umowa) otwierają się z doku", async () => {
    const user = userEvent.setup();
    const onOpenWorkbench = vi.fn();
    renderDock({ onOpenWorkbench, item: { ...baseItem(), stage: "verified" } });
    // Etap „Zweryfikowany" → sekcja „Teraz" to CV.
    await user.click(
      await screen.findByRole("button", { name: /Wysyłka CV do klienta/ }),
    );
    expect(onOpenWorkbench).toHaveBeenLastCalledWith("cv");
    await user.click(screen.getByRole("button", { name: /^W procesie/ }));
    await user.click(await screen.findByRole("button", { name: /Rozmowy i werdykt klienta/ }));
    expect(onOpenWorkbench).toHaveBeenLastCalledWith("interviews");
    await user.click(screen.getByRole("button", { name: /^Umowa/ }));
    expect(onOpenWorkbench).toHaveBeenLastCalledWith("contract");
  });

  it("poza „Zweryfikowanym” link do karty CV nie obiecuje stawki i wysyłki (D3)", async () => {
    const user = userEvent.setup();
    const onOpenWorkbench = vi.fn();
    renderDock({ onOpenWorkbench, item: baseItem({ stage: "cv_sent" }) });
    await user.click(screen.getByRole("button", { name: /^CV/ }));
    await user.click(await screen.findByRole("button", { name: /CV do klienta: strony i wersje/ }));
    expect(onOpenWorkbench).toHaveBeenLastCalledWith("cv");
    expect(screen.queryByRole("button", { name: /Wysyłka CV do klienta/ })).toBeNull();
  });

  it("bez kontekstu warsztatów dok nie pokazuje ich przycisków", async () => {
    renderDock({ item: { ...baseItem(), stage: "verified" } });
    await screen.findByText(/Oryginał CV:/);
    expect(screen.queryByRole("button", { name: /Wysyłka CV do klienta/ })).toBeNull();
  });

  // 17.10.2026: „Pracuje u nas” liczy się wyłącznie z umowy w Kontraktach.
  it("karta na „Zatrudniony” bez umowy: pigułka „Brak umowy w Kontraktach” z wyjaśnieniem", () => {
    renderDock({ item: baseItem({ stage: "hired", missing_contract: true }) });
    const pill = screen.getByTestId("dock-missing-contract");
    expect(pill).toHaveTextContent("Brak umowy w Kontraktach");
    expect(pill.getAttribute("title")).toContain("„Pracuje u nas” pojawi się po wpisaniu umowy.");
    cleanup();
    renderDock({ item: baseItem({ stage: "hired" }) });
    expect(screen.queryByTestId("dock-missing-contract")).toBeNull();
  });

  it("czarna lista u nas: pigułka, a w dymku kto, kiedy i dlaczego (17.10.2026)", async () => {
    const user = userEvent.setup();
    candidatesGet.mockResolvedValue({
      data: {
        email: "anna@example.com",
        status: "blacklisted",
        blacklist: {
          since: "2026-10-17T08:30:00Z",
          by_user_id: 5,
          by_name: "Ola Rekruterka",
          reason: "zrezygnowała dzień przed startem",
        },
      },
    });
    renderDock();
    await user.click(await screen.findByRole("button", { name: "Czarna lista — szczegóły" }));
    expect(await screen.findByText("Nie współpracujemy z tą osobą")).toBeInTheDocument();
    expect(screen.getByText("Od 17.10.2026 · dodał(a) Ola Rekruterka")).toBeInTheDocument();
    expect(screen.getByText("Powód: zrezygnowała dzień przed startem")).toBeInTheDocument();
  });

  it("„⋯ → Czarna lista…” z prawem zapisu otwiera okno czarnej listy", async () => {
    const user = userEvent.setup();
    useAuthStore.setState({ user: { id: 7, role: "recruiter", roles: ["recruiter"] } } as never);
    try {
      renderDock();
      await user.click(screen.getByRole("button", { name: "Więcej akcji osoby" }));
      await user.click(await screen.findByRole("menuitem", { name: /Czarna lista…/ }));
      expect(
        await screen.findByRole("heading", { name: "Czarna lista — Anna Kowalska" }),
      ).toBeInTheDocument();
    } finally {
      useAuthStore.setState({ user: null } as never);
    }
  });

  it("bez prawa zapisu profilu menu „⋯” nie ma „Czarnej listy…”", async () => {
    const user = userEvent.setup();
    renderDock();
    await user.click(screen.getByRole("button", { name: "Więcej akcji osoby" }));
    await screen.findByRole("menuitem", { name: /Otwórz CV/ });
    expect(screen.queryByRole("menuitem", { name: /Czarna lista/ })).toBeNull();
    expect(screen.queryByRole("menuitem", { name: /Dodaj też do rekrutacji/ })).toBeNull();
  });

  it("„⋯ → Dodaj też do rekrutacji…” otwiera okno „Przypisz do rekrutacji” (29.10.2026)", async () => {
    const user = userEvent.setup();
    useAuthStore.setState({ user: { id: 7, role: "recruiter", roles: ["recruiter"] } } as never);
    try {
      renderDock();
      await user.click(screen.getByRole("button", { name: "Więcej akcji osoby" }));
      await user.click(await screen.findByRole("menuitem", { name: /Dodaj też do rekrutacji…/ }));
      expect(
        await screen.findByRole("heading", { name: "Przypisz do rekrutacji — Anna Kowalska" }),
      ).toBeInTheDocument();
    } finally {
      useAuthStore.setState({ user: null } as never);
    }
  });
});

// ── Fala 3 („parytet z makietami") ─────────────────────────────────────────

describe("PipelineCandidateDock — nawigator, oś czasu i główna akcja", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    formGet.mockResolvedValue({ data: dockForm() });
    originalGet.mockResolvedValue({ data: { has_snapshot: false } });
    brandedGet.mockResolvedValue({ data: { status: "none" } });
    candidatesGet.mockResolvedValue({
      data: {
        email: "anna@example.com",
        city: "Warszawa",
        status: "active",
        max_onsite_days_per_week: 2,
        availability_date: "2026-10-01",
        linkedin_current_title: "Python Developer",
        linkedin_current_company: "Asseco",
      },
    });
    apiGet.mockResolvedValue({ data: { items: [] } });
    apiPost.mockResolvedValue({ data: {} });
  });

  it("bez podanej pozycji nie zgaduje nawigatora „N z M”", () => {
    renderDock();
    expect(screen.queryByRole("button", { name: "Następna karta" })).toBeNull();
    expect(screen.getByText("Panel osoby")).toBeTruthy();
  });

  it("nawigator pokazuje pozycję w kolejności tablicy i woła sąsiadów", async () => {
    const user = userEvent.setup();
    const onSelectNext = vi.fn();
    const onSelectPrevious = vi.fn();
    renderDock({ position: 1, total: 15, onSelectNext, onSelectPrevious });

    expect(screen.getByText("1 z 15")).toBeTruthy();
    // Na pierwszej karcie „poprzedni" jest wyłączony — w obu miejscach.
    for (const btn of screen.getAllByRole("button", { name: /Poprzedni/ })) {
      expect(btn).toBeDisabled();
    }
    await user.click(screen.getAllByRole("button", { name: /Następn/ })[0]);
    expect(onSelectNext).toHaveBeenCalled();
    expect(onSelectPrevious).not.toHaveBeenCalled();
  });

  it("za licznikiem stoi nazwa kolejki; z menu „Kto dodał” zmienia filtr (14.10.2026)", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderDock({
      position: 1,
      total: 2,
      queueLabel: "Nowi · dodani przez Ciebie",
      addedByMenu: {
        options: [
          { filter: { kind: "all" }, key: "all", label: "Wszyscy", count: 5, isViewer: false },
          { filter: { kind: "user", userId: 7 }, key: "user:7", label: "Ty", count: 2, isViewer: true },
        ],
        value: { kind: "user", userId: 7 },
        onChange,
      },
    });
    const label = screen.getByTestId("dock-queue-label");
    expect(label).toHaveTextContent("Nowi · dodani przez Ciebie");
    await user.click(label);
    const menu = await screen.findByRole("menu");
    await user.click(within(menu).getByTestId("added-by-option-all"));
    expect(onChange).toHaveBeenCalledWith({ kind: "all" });
  });

  it("bez menu nazwa kolejki jest zwykłym tekstem; przy „Wróć do kolejki” też jest", () => {
    renderDock({ position: null, total: 2, onReturnToQueue: vi.fn(), queueLabel: "Screening" });
    expect(screen.getByRole("button", { name: "Wróć do kolejki" })).toBeTruthy();
    expect(screen.getByTestId("dock-queue-label").tagName).toBe("SPAN");
    expect(screen.getByTestId("dock-queue-label")).toHaveTextContent("Screening");
  });

  it("koniec kolejki: pasek z „Od pierwszej”, „Wszyscy (N)” i „Dalej” (D4)", async () => {
    const user = userEvent.setup();
    const onFirst = vi.fn();
    const showAll = vi.fn();
    const next = vi.fn();
    renderDock({
      position: 3,
      total: 3,
      queueEnd: {
        count: 3,
        onFirst,
        showAll: { label: "Wszyscy (8)", onClick: showAll },
        next: { label: "Dalej: Screening (4)", onClick: next },
      },
    });
    const end = screen.getByRole("status", { name: "Koniec kolejki" });
    expect(end).toHaveTextContent("To ostatnia z 3 osób w kolejce.");
    await user.click(within(end).getByRole("button", { name: "Od pierwszej" }));
    await user.click(within(end).getByRole("button", { name: "Wszyscy (8)" }));
    await user.click(within(end).getByRole("button", { name: "Dalej: Screening (4)" }));
    expect([onFirst, showAll, next].map((fn) => fn.mock.calls.length)).toEqual([1, 1, 1]);
  });

  it("jedyna osoba w kolejce i nic dalej — bez paska końca", () => {
    renderDock({ position: 1, total: 1, queueEnd: { count: 1 } });
    expect(screen.queryByRole("status", { name: "Koniec kolejki" })).toBeNull();
  });

  it("podtytuł składa się wyłącznie ze znanych członów", async () => {
    renderDock({ matchScore: 56 });
    expect(
      await screen.findByText("Python Developer · Asseco · Warszawa · 56 / 100"),
    ).toBeTruthy();
    // Status kandydata w nagłówku tylko wtedy, gdy wymaga uwagi (czarna lista).
    expect(screen.queryByText("Aktywny")).toBeNull();
  });

  it("oś czasu niesie następną akcję jako bieżący punkt", () => {
    renderDock({
      item: baseItem({
        added_to_job_by_name: "Katarzyna Nowak",
        added_to_job_at: "2026-09-03T14:20:00Z",
      }),
      nextAction: {
        label: "Umów screening",
        tone: "normal",
        kind: "screening",
        owner: "recruiter",
      },
    });

    expect(screen.getByText("Dodany do rekrutacji")).toBeTruthy();
    expect(screen.getByText("W etapie od 3 dni")).toBeTruthy();
    expect(screen.getByText("Następna akcja: Umów screening")).toBeTruthy();
  });

  it("zaległa akcja mówi o terminie, a bramka odsyła do pigułek ruchu", () => {
    renderDock({
      nextAction: {
        label: "Brak następnej akcji",
        tone: "due",
        kind: "analysis",
        owner: "recruiter",
      },
    });
    expect(
      screen.getByText(/Po terminie — ta karta czeka dłużej/),
    ).toBeTruthy();
  });

  it("główna akcja przenosi na wskazany etap tą samą ścieżką co pigułki", async () => {
    const user = userEvent.setup();
    const target = stageCol("screening", "Screening", { stage_def_id: 2 });
    const onMoveTo = vi.fn();
    renderDock({ primaryTarget: target, onMoveTo });

    await user.click(
      screen.getByRole("button", { name: "Przenieś na etap: Screening" }),
    );
    expect(onMoveTo).toHaveBeenCalledWith(target);
  });

  it("w trybie readOnly głównej akcji nie ma wcale", () => {
    const target = stageCol("screening", "Screening", { stage_def_id: 2 });
    renderDock({ primaryTarget: target, readOnly: true });
    expect(
      screen.queryByRole("button", { name: /Przenieś na etap:/ }),
    ).toBeNull();
  });

  it("warunki wobec rekrutacji pokazują „—”, a nie znikają, gdy danych brak", async () => {
    candidatesGet.mockResolvedValue({ data: { email: "a@b.pl" } });
    renderDock({ item: baseItem({ expected_rate_value: null }) });

    expect(await screen.findByText("Dostępność")).toBeTruthy();
    expect(screen.getByText("Tryb")).toBeTruthy();
    expect(screen.getByText("brak stawki")).toBeTruthy();
  });

  // PR 5 (04.10.2026): fakty o osobie stoją raz, pod nazwiskiem — także gdy
  // sekcja „W procesie” jest zwinięta.
  it("fakty o osobie stoją pod nazwiskiem, nie w zwiniętej sekcji", async () => {
    renderDock({ item: baseItem({ stage: "new", expected_rate_value: 140, expected_rate_unit: "hourly" }) });
    const facts = await screen.findByTestId("dock-facts");
    expect(within(facts).getByText("Dostępność")).toBeTruthy();
    expect(within(facts).getByText(/140/)).toBeTruthy();
  });

  it("okres wypowiedzenia bez jednostki liczy się w dniach (jak przed wspólnymi faktami)", async () => {
    candidatesGet.mockResolvedValue({
      data: { email: "a@b.pl", notice_period: 30, notice_period_unit: null },
    });
    renderDock();
    const facts = await screen.findByTestId("dock-facts");
    expect(await within(facts).findByText("wypowiedzenie 30 dni")).toBeTruthy();
  });

  it("w „Nowych” panel daje „Biorę” i „Nie odebrał” (notatka-próba kontaktu)", async () => {
    apiPost.mockResolvedValue({ data: {} });
    const onTake = vi.fn();
    const user = userEvent.setup();
    renderDock({
      item: baseItem({ stage: "new", can_take: true, claim_user_id: null }),
      onTake,
    });
    const row = await screen.findByTestId("dock-contact-row");
    await user.click(within(row).getByRole("button", { name: /Biorę/ }));
    expect(onTake).toHaveBeenCalledTimes(1);
    await user.click(within(row).getByRole("button", { name: "Nie odebrał" }));
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith(
        "/api/notes",
        expect.objectContaining({ kind: "contact_attempt", job_id: 10, candidate_id: 42 }),
      ),
    );
  });

  it("po „Screeningu” panel nie pokazuje wiersza telefonu", async () => {
    renderDock({ item: baseItem({ stage: "cv_sent" }) });
    await screen.findByTestId("dock-facts");
    expect(screen.queryByTestId("dock-contact-row")).toBeNull();
  });

  it("stawka do klienta pojawia się tylko, gdy serwer ją przysłał", async () => {
    renderDock({
      item: baseItem({ client_rate_value: "180", client_rate_unit: "hourly", client_rate_currency: "PLN" }),
    });
    const facts = await screen.findByTestId("dock-facts");
    expect(within(facts).getByText("Do klienta")).toBeTruthy();
  });

  // 12.10.2026: para z czasów Traffita ma etapy bez kwot — stawki leżą
  // w karcie rekomendacji i w notatce Delivery Leada z dnia wysyłki.
  const rateHints = {
    candidate_id: 42,
    job_id: 10,
    expected_rate_hint: {
      amount_hourly: 90,
      raw: "90 zł/h",
      at: "2026-09-21T10:00:00+00:00",
      source: "card",
      author_name: "Anna Nowak",
    },
    client_rate_note: {
      note_id: 7,
      text: "Wysłany 150/100-110",
      at: "2026-09-22T09:53:00+00:00",
      author_name: "Ewa Lis",
    },
  };
  const withRateHints = () =>
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({
        data: url.endsWith("/recruitment-rate-hints") ? rateHints : { items: [] },
      }),
    );

  it("bez stawki na etapie pokazuje stawkę z karty i notatkę z wysyłki, z informacją skąd są", async () => {
    withRateHints();
    renderDock();
    const facts = await screen.findByTestId("dock-facts");
    expect(await within(facts).findByTestId("dock-rate-hint")).toHaveTextContent("90 zł/h");
    expect(within(facts).getByText("Screening (z notatki) · Anna Nowak · 21.09.2026")).toBeTruthy();
    expect(within(facts).queryByText("brak stawki", { selector: "span.text-muted-foreground" })).toBeTruthy();
    expect(
      within(facts).getByText("Notatka z wysyłki · Ewa Lis · 22.09.2026: „Wysłany 150/100-110”"),
    ).toBeTruthy();
    expect(apiGet).toHaveBeenCalledWith("/api/candidates/42/recruitment-rate-hints", {
      params: { job_id: 10 },
    });
  });

  it("stawki zapisane na etapie wygrywają i dok o podpowiedzi nie pyta", async () => {
    withRateHints();
    renderDock({
      item: baseItem({
        expected_rate_value: "120",
        expected_rate_unit: "hourly",
        expected_rate_currency: "PLN",
        client_rate_value: "180",
        client_rate_unit: "hourly",
        client_rate_currency: "PLN",
      }),
    });
    const facts = await screen.findByTestId("dock-facts");
    expect(within(facts).queryByTestId("dock-rate-hint")).toBeNull();
    expect(within(facts).queryByText(/Notatka z wysyłki/)).toBeNull();
    expect(
      apiGet.mock.calls.some(([url]) => String(url).endsWith("/recruitment-rate-hints")),
    ).toBe(false);
  });

  it("stawka ponad budżet jest nazwana wprost", async () => {
    renderDock({
      item: baseItem({
        expected_rate_value: 150,
        expected_rate_currency: "PLN",
        expected_rate_unit: "hourly",
        budget_max_at_move: 122,
      }),
    });
    expect(await screen.findByText("ponad budżet")).toBeTruthy();
  });

  it("stawka godzinowa jest normalizowana do miesiąca przed porównaniem z budżetem", async () => {
    // 150 zł/h × 168 h = 25 200 zł/mc > 20 000 zł/mc. Surowe porównanie
    // (150 < 20 000) mówiło „w budżecie" — dokładnie zgłoszony defekt.
    renderDock({
      item: baseItem({
        expected_rate_value: 150,
        expected_rate_currency: "PLN",
        expected_rate_unit: "hourly",
        budget_max_at_move: 20000,
      }),
    });
    expect(await screen.findByText("ponad budżet")).toBeTruthy();
    expect(screen.queryByText(/w budżecie do/)).toBeNull();
  });

  it("stawka godzinowa mieszcząca się po normalizacji jest „w budżecie”", async () => {
    // 100 zł/h × 168 h = 16 800 zł/mc ≤ 20 000 zł/mc.
    renderDock({
      item: baseItem({
        expected_rate_value: "100",
        expected_rate_currency: "PLN",
        expected_rate_unit: "hourly",
        budget_max_at_move: 20000,
      }),
    });
    expect(await screen.findByText(/w budżecie do 20\s000 PLN\/mc/)).toBeTruthy();
  });

  it("stawka w obcej walucie nie udaje porównania z budżetem w PLN", async () => {
    renderDock({
      item: baseItem({
        expected_rate_value: 40,
        expected_rate_currency: "EUR",
        expected_rate_unit: "hourly",
        budget_max_at_move: 20000,
      }),
    });
    expect(await screen.findByText(/nie do porównania z budżetem/)).toBeTruthy();
    expect(screen.queryByText(/w budżecie do/)).toBeNull();
    expect(screen.queryByText("ponad budżet")).toBeNull();
  });

  it("„Odrzuć z powodem” zostaje widoczne, ale zablokowane z powodem, gdy tablica tak mówi", () => {
    renderDock({ rejectBlockedReason: "Stawka czeka na akceptację" });
    const button = screen.getByRole("button", { name: /Odrzuć z powodem/ });
    expect(button).toBeDisabled();
    expect(button.getAttribute("title")).toBe("Stawka czeka na akceptację");
  });

  it("pole notatki stoi zawsze na dole i wysyła Enterem", async () => {
    const user = userEvent.setup();
    renderDock();
    const box = screen.getByRole("textbox", { name: "Dodaj notatkę" });
    await user.type(box, "Chce hybrydę{Enter}");
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("/api/notes", {
        candidate_id: 42,
        job_id: 10,
        content: "Chce hybrydę",
        note_type: "general",
      }),
    );
  });
});

// ── Ramka „Następny etap”, link do profilu i jasna sekcja CV (24.09.2026) ──

describe("PipelineCandidateDock — następny etap, profil i CV", () => {
  const requirements = (overrides: Record<string, unknown> = {}) => ({
    from_column: "new",
    to_column: "verified",
    skipped_columns: ["screening"],
    items: [
      {
        key: "screening_sheet",
        label: "Arkusz screeningu",
        status: "missing",
        blocking: true,
        detail: "odpowiedzi jeszcze nie zapisane",
        action: { kind: "open_screening", label: "Otwórz screening", stage_id: 777 },
      },
      { key: "availability", label: "Dostępność", status: "ok", blocking: false },
    ],
    primary: { kind: "blocked", label: "Najpierw uzupełnij: Arkusz screeningu" },
    owner_note: null,
    ...overrides,
  });

  function routeApiGet(opts: {
    requirements?: unknown;
    requirementsError?: boolean;
    profileDocs?: unknown[];
  }) {
    apiGet.mockImplementation((url: string) => {
      if (url.startsWith("/api/pipeline/move-requirements")) {
        if (opts.requirementsError) return Promise.reject(new Error("boom"));
        return Promise.resolve({ data: opts.requirements ?? requirements() });
      }
      if (url.includes("/documents?kind=cv")) {
        return Promise.resolve({ data: opts.profileDocs ?? [] });
      }
      return Promise.resolve({ data: { items: [] } });
    });
  }

  beforeEach(() => {
    vi.clearAllMocks();
    formGet.mockResolvedValue({ data: dockForm() });
    originalGet.mockResolvedValue({ data: { has_snapshot: false } });
    brandedGet.mockResolvedValue({ data: { status: "none" } });
    candidatesGet.mockResolvedValue({ data: { email: "anna@example.com" } });
    apiPost.mockResolvedValue({ data: {} });
  });

  it("ramka pokazuje numer i nazwę kolumny, licznik braków i przycisk, który usuwa brak", async () => {
    routeApiGet({
      requirements: requirements({
        items: [
          {
            key: "screening_sheet",
            label: "Arkusz screeningu",
            status: "missing",
            blocking: false,
            detail: "odpowiedzi jeszcze nie zapisane",
            action: { kind: "open_screening", label: "Otwórz screening", stage_id: 777 },
          },
          { key: "availability", label: "Dostępność", status: "ok", blocking: false },
        ],
        primary: { kind: "move", label: "Przesuń na „Zweryfikowany”" },
      }),
    });
    const user = userEvent.setup();
    const onOpenScreening = vi.fn();
    const onMoveTo = vi.fn();
    const target = stageCol("verified", "Zweryfikowany", { stage_def_id: 5 });
    renderDock({ primaryTarget: target, onOpenScreening, onMoveTo, item: baseItem({ stage: "new" }) });

    expect(await screen.findByText(/Następny etap: 3 · Zweryfikowany/)).toBeInTheDocument();
    expect(screen.getByTestId("dock-next-stage-counter")).toHaveTextContent("brakuje 1 z 2");
    expect(screen.getByTestId("dock-next-stage-reminder")).toHaveTextContent(/przypomnienie, nie blokada/);

    await user.click(screen.getByRole("button", { name: "Otwórz screening" }));
    expect(onOpenScreening).toHaveBeenCalledWith(777, "Anna Kowalska");

    // Główny przycisk działa mimo braków (serwer tego nie blokuje).
    await user.click(screen.getByRole("button", { name: "Przenieś na etap: Zweryfikowany" }));
    expect(onMoveTo).toHaveBeenCalledWith(target);
  });

  it("primary „blocked”: przycisk wyłączony z powodem, bez obietnicy „możesz przenieść”", async () => {
    routeApiGet({});
    const onMoveTo = vi.fn();
    renderDock({
      primaryTarget: stageCol("verified", "Zweryfikowany", { stage_def_id: 5 }),
      onMoveTo,
      item: baseItem({ stage: "new" }),
    });
    expect(await screen.findByTestId("dock-next-stage-counter")).toHaveTextContent("brakuje 1 z 2");
    const button = screen.getByRole("button", { name: "Przenieś na etap: Zweryfikowany" });
    expect(button).toBeDisabled();
    expect(screen.getByText("Najpierw uzupełnij: Arkusz screeningu.")).toBeInTheDocument();
    expect(screen.queryByTestId("dock-next-stage-reminder")).toBeNull();
  });

  it("hand_to_dl (rekruter): przycisk przekazuje na „QC CV” jak okno „Przesuń dalej”, bez ruchu na „CV wysłane”", async () => {
    routeApiGet({
      requirements: requirements({
        from_column: "verified",
        to_column: "cv_sent",
        items: [
          { key: "client_rate", label: "Stawka do klienta", status: "waiting", blocking: false },
        ],
        primary: { kind: "hand_to_dl", label: "Przekaż Delivery Leadowi", target_stage_def_id: 41 },
        owner_note: "CV wysyła Delivery Lead — trafi do jego „Czeka na Ciebie”.",
      }),
    });
    const user = userEvent.setup();
    const onMoveTo = vi.fn();
    const onMoveToStageDef = vi.fn();
    renderDock({
      primaryTarget: stageCol("cv_sent", "CV wysłane", { stage_def_id: 9 }),
      onMoveTo,
      onMoveToStageDef,
      item: baseItem({ stage: "verified" }),
    });
    const button = await screen.findByRole("button", { name: "Przekaż Delivery Leadowi" });
    expect(screen.queryByTestId("dock-next-stage-reminder")).toBeNull();
    await user.click(button);
    expect(onMoveToStageDef).toHaveBeenCalledWith(41);
    expect(onMoveTo).not.toHaveBeenCalled();
    expect(toastSuccess).toHaveBeenCalledWith(expect.stringContaining("Delivery Leada"));
  });

  it("hand_to_cpro (Delivery Lead Nordei): przycisk prowadzi na etap Cpro, nie na „Wysłane do Cpro”", async () => {
    routeApiGet({
      requirements: requirements({
        from_column: "cv_qc",
        to_column: "cv_sent",
        items: [{ key: "cpro_upload", label: "Wrzucenie do Cpro", status: "waiting", blocking: false }],
        primary: { kind: "hand_to_cpro", label: "Przejrzyj i zaakceptuj do Cpro", target_stage_def_id: 45 },
      }),
    });
    const user = userEvent.setup();
    const onMoveTo = vi.fn();
    const onMoveToStageDef = vi.fn();
    renderDock({
      primaryTarget: stageCol("cv_sent", "Wysłane do Cpro", { stage_def_id: 9 }),
      onMoveTo,
      onMoveToStageDef,
      item: baseItem({ stage: "interview" }),
    });
    await user.click(await screen.findByRole("button", { name: "Przejrzyj i zaakceptuj do Cpro" }));
    expect(onMoveToStageDef).toHaveBeenCalledWith(45);
    expect(onMoveTo).not.toHaveBeenCalled();
  });

  it("po unieważnieniu wymagań (akcja z ramki) lista i licznik zostają — dok nie zeruje zapytania", async () => {
    // #1789 dołożył drugi obserwator z `queryFn: () => null`: react-query brał
    // go jako funkcję zapytania i refetch po `invalidateQueries` dawał `null`.
    routeApiGet({});
    renderDock({
      primaryTarget: stageCol("verified", "Zweryfikowany", { stage_def_id: 5 }),
      item: baseItem({ stage: "new" }),
    });
    expect(await screen.findByTestId("dock-next-stage-counter")).toHaveTextContent("brakuje 1 z 2");
    await lastQueryClient!.invalidateQueries({ queryKey: ["move-requirements"] });
    await waitFor(() =>
      expect(
        apiGet.mock.calls.filter(([url]) => String(url).startsWith("/api/pipeline/move-requirements")).length,
      ).toBeGreaterThanOrEqual(2),
    );
    expect(screen.getByTestId("dock-next-stage-counter")).toHaveTextContent("brakuje 1 z 2");
    expect(screen.getByText("Arkusz screeningu")).toBeInTheDocument();
  });

  it("etap bez CV etapu, a lista wymagań liczy CV firmowe z plików: „gotowe”, nie „brak”", async () => {
    // Produkcja 24.09.2026: ramka „Następny etap” mówiła ✓ „CV firmowe”, a dok
    // „brak” — dok przeczył sam sobie. CV z generatora albo plik „…B2B…” leży
    // w plikach kandydata, więc zdanie to mówi (D2, 14.10.2026).
    brandedGet.mockResolvedValue({ data: { status: "none" } });
    routeApiGet({
      requirements: requirements({
        to_column: "cv_qc",
        items: [{ key: "company_cv", label: "CV firmowe „Pod rekrutację”", status: "ok", blocking: true }],
        primary: { kind: "move", label: "Przenieś" },
      }),
    });
    const user = userEvent.setup();
    const target = stageCol("interview", "QC CV", { stage_def_id: 9 });
    renderDock({ primaryTarget: target, item: baseItem({ stage: "verified" }) });

    expect(await screen.findByText(/Następny etap: 4 · QC CV/)).toBeInTheDocument();
    const cvToggle = screen.getByRole("button", { name: /^CV/ });
    if (cvToggle.getAttribute("aria-expanded") !== "true") await user.click(cvToggle);
    await waitFor(() =>
      expect(screen.getAllByText("CV firmowe: gotowe (w plikach kandydata)").length).toBeGreaterThanOrEqual(1),
    );
    expect(screen.queryByText("CV firmowe: brak")).toBeNull();
    // Nie ma CV etapu, więc nie ma czego pobrać z rekrutacji.
    expect(screen.queryByRole("button", { name: /Pobierz Word/ })).toBeNull();
  });

  it("po ruchu dalej: CV firmowe pary z poprzedniego etapu — zdanie bez „nie podpięte”, pobranie i edycja tamtego wiersza", async () => {
    // Produkcja 26.09.2026: po przejściu na „CV wysłane” dok mówił „CV firmowe:
    // brak”, choć zatwierdzone CV leżało na „QC CV” (ruch zakłada nowy wiersz
    // etapu bez CV). Serwer wskazuje tamten wiersz (`pair_source_stage_id`).
    brandedGet.mockImplementation((stageId: number) =>
      Promise.resolve({
        data:
          stageId === 777
            ? { status: "finalized", from_generator: true, finalized_at: "2026-09-26T10:00:00Z", version: 2 }
            : { status: "none", pair_source_stage_id: 777, pair_source_status: "finalized" },
      }),
    );
    const blob = new Blob(["docx"]);
    stageCvFile.mockResolvedValue({ blob, filename: "CV_Anna_Kowalska.docx" });
    stageCvPdf.mockResolvedValue({ blob, filename: "CV_Anna_Kowalska.pdf" });
    routeApiGet({ requirements: requirements({ to_column: "client_interview", items: [] }) });
    const user = userEvent.setup();
    renderDock({
      primaryTarget: stageCol("client_interview", "Rozmowa u klienta", { stage_def_id: 9 }),
      item: baseItem({ stage: "cv_sent" }),
    });
    const cvToggle = await screen.findByRole("button", { name: /^CV/ });
    if (cvToggle.getAttribute("aria-expanded") !== "true") await user.click(cvToggle);
    const section = await screen.findByTestId("dock-company-cv");
    await waitFor(() => expect(section).toHaveTextContent("CV firmowe: zatwierdzone 26.09.2026"));
    expect(section).not.toHaveTextContent(/podpięte|z etapu/);
    expect(within(section).getByRole("button", { name: "Edytuj CV" })).toBeInTheDocument();
    expect(within(section).queryByRole("button", { name: /Generuj CV/ })).toBeNull();

    await user.click(within(section).getByRole("button", { name: /Pobierz Word/ }));
    await waitFor(() => expect(savedFiles).toHaveBeenCalledWith(blob, "CV_Anna_Kowalska.docx"));
    expect(stageCvFile).toHaveBeenCalledWith(777, { download: "dock" });

    await user.click(within(section).getByRole("button", { name: "Pobierz PDF" }));
    await waitFor(() => expect(savedFiles).toHaveBeenLastCalledWith(blob, "CV_Anna_Kowalska.pdf"));
    expect(stageCvPdf).toHaveBeenCalledWith(777, { download: "dock" });
  });

  it("bez zrzutu zgody RODO pobieranie jest wyłączone i dok mówi dlaczego", async () => {
    brandedGet.mockResolvedValue({
      data: { status: "draft", from_generator: true, edit_revision: 1, version: 1, consent_missing: true },
    });
    const onOpenWorkbench = vi.fn();
    const user = userEvent.setup();
    renderDock({ onOpenWorkbench });
    await user.click(screen.getByRole("button", { name: /^CV/ }));
    const section = await screen.findByTestId("dock-company-cv");
    await waitFor(() => expect(within(section).getByRole("button", { name: /Pobierz Word/ })).toBeDisabled());
    expect(within(section).getByRole("button", { name: "Pobierz PDF" })).toBeDisabled();
    expect(screen.getByTestId("dock-company-cv-consent")).toHaveTextContent(
      "Bez zrzutu zgody RODO nie pobierzesz CV.",
    );
    await user.click(screen.getByRole("button", { name: /Dołącz go w karcie „CV do klienta”/ }));
    expect(onOpenWorkbench).toHaveBeenLastCalledWith("cv");
    expect(stageCvFile).not.toHaveBeenCalled();
  });

  it("nieudane pobranie: komunikat serwera w toaście", async () => {
    brandedGet.mockResolvedValue({ data: { status: "draft", from_generator: true, edit_revision: 1, version: 1 } });
    stageCvFile.mockRejectedValue(
      Object.assign(new Error("x"), {
        response: { status: 503, data: { detail: "Plik CV jest chwilowo niedostępny." } },
      }),
    );
    const user = userEvent.setup();
    renderDock();
    await user.click(screen.getByRole("button", { name: /^CV/ }));
    await user.click(await screen.findByRole("button", { name: /Pobierz Word/ }));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(String(toastError.mock.calls.at(-1)?.[0])).toMatch(/chwilowo niedostępny/);
    expect(savedFiles).not.toHaveBeenCalled();
  });

  it("awaria odczytu CV firmowego nie udaje braku: bez pobierania i bez „Generuj CV”, z „Ponów”", async () => {
    brandedGet.mockRejectedValue({ response: { status: 500 } });
    const user = userEvent.setup();
    renderDock();
    await user.click(screen.getByRole("button", { name: /^CV/ }));
    const section = await screen.findByTestId("dock-company-cv");
    await waitFor(() => expect(section).toHaveTextContent("CV firmowe: nie udało się sprawdzić"));
    expect(within(section).queryByRole("button", { name: /Pobierz Word/ })).toBeNull();
    expect(within(section).queryByRole("button", { name: /Generuj CV/ })).toBeNull();
    brandedGet.mockResolvedValue({ data: { status: "none" } });
    await user.click(within(section).getByRole("button", { name: "Ponów" }));
    await waitFor(() => expect(section).toHaveTextContent("CV firmowe: brak"));
  });

  it("brak pilnowany przez serwer (QC CV) jest nazwany wprost", async () => {
    routeApiGet({
      requirements: requirements({
        to_column: "cv_sent",
        items: [
          {
            key: "cv_qc",
            label: "QC CV",
            status: "missing",
            blocking: true,
            action: { kind: "open_qc", label: "Otwórz QC CV", stage_id: 501 },
          },
        ],
      }),
    });
    const user = userEvent.setup();
    renderDock({ primaryTarget: stageCol("cv_sent", "CV wysłane", { stage_def_id: 9 }) });

    expect(await screen.findByTestId("dock-next-stage-enforced")).toHaveTextContent(
      "Bez: QC CV system nie przepuści ruchu.",
    );
    await user.click(screen.getByRole("button", { name: "Otwórz QC CV" }));
    expect(screen.getByTestId("cv-qc-dialog")).toBeInTheDocument();
    expect(qcDialog).toHaveBeenLastCalledWith(expect.objectContaining({ stageId: 501 }));
    // Dok bez `onAdvance` nie umie przesunąć — okno QC nie dostaje przycisku ruchu.
    expect(qcDialog.mock.lastCall![0].onMoveNext).toBeUndefined();
  });

  it("„Przesuń dalej” z okna QC zamyka je i woła ruch Tablicy", async () => {
    routeApiGet({
      requirements: requirements({
        to_column: "cv_sent",
        items: [
          {
            key: "cv_qc",
            label: "QC CV",
            status: "missing",
            blocking: true,
            action: { kind: "open_qc", label: "Otwórz QC CV", stage_id: 501 },
          },
        ],
      }),
    });
    const user = userEvent.setup();
    const onAdvance = vi.fn();
    renderDock({ primaryTarget: stageCol("cv_sent", "CV wysłane", { stage_def_id: 9 }), onAdvance });
    await user.click(await screen.findByRole("button", { name: "Otwórz QC CV" }));
    const onMoveNext = qcDialog.mock.lastCall![0].onMoveNext as () => void;
    act(() => onMoveNext());
    expect(onAdvance).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByTestId("cv-qc-dialog")).toBeNull());
  });

  it("przycisk, którego dok nie umie obsłużyć, się nie renderuje", async () => {
    routeApiGet({
      requirements: requirements({
        to_column: "client_interview",
        items: [
          {
            key: "client_slot",
            label: "Termin od klienta",
            status: "waiting",
            blocking: false,
            action: { kind: "request_slots", label: "Dodaj terminy od klienta", stage_id: 501 },
          },
        ],
      }),
    });
    renderDock({ primaryTarget: stageCol("client_interview", "Rozmowa u klienta", { stage_def_id: 11 }) });
    expect(await screen.findByText("Termin od klienta")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dodaj terminy od klienta" })).toBeNull();
  });

  it("awaria wymagań to krótki komunikat, a przycisk ruchu działa dalej", async () => {
    routeApiGet({ requirementsError: true });
    const user = userEvent.setup();
    const onMoveTo = vi.fn();
    const target = stageCol("verified", "Zweryfikowany", { stage_def_id: 5 });
    renderDock({ primaryTarget: target, onMoveTo });

    expect(await screen.findByText(/Nie udało się sprawdzić wymagań/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Przenieś na etap: Zweryfikowany" }));
    expect(onMoveTo).toHaveBeenCalledWith(target);
  });

  it("link „Profil ↗” prowadzi do profilu kandydata z powrotem do rekrutacji, w nowej karcie", () => {
    routeApiGet({});
    renderDock();
    const link = screen.getByRole("link", { name: /Profil kandydata Anna Kowalska/ });
    expect(link.getAttribute("href")).toMatch(/^\/candidates\/42\?/);
    expect(link.getAttribute("href")).toContain("jobId=10");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("CV: bez kopii w zgłoszeniu, ale z plikiem w profilu — „z profilu”, nie „brak CV”", async () => {
    routeApiGet({
      profileDocs: [
        {
          id: 3,
          filename: "cv.pdf",
          is_primary: true,
          uploaded_at: "2026-09-01T10:00:00Z",
          created_at: "2026-09-01T10:00:00Z",
          content_type: "application/pdf",
          size_bytes: 10,
          document_kind: "cv",
          external_source: null,
        },
      ],
    });
    const user = userEvent.setup();
    renderDock();
    await user.click(screen.getByRole("button", { name: /^CV/ }));

    expect(await screen.findByText(/Oryginał CV: z profilu \(1\.09\.2026\) — do zgłoszenia nie dołączono pliku/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pokaż CV z profilu/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pokaż CV oryginalne/ })).toBeNull();
    expect(screen.queryByText(/Brak CV w momencie zgłoszenia/)).toBeNull();
  });

  it("CV: „brak pliku” tylko, gdy ani zgłoszenie, ani profil nie ma CV", async () => {
    routeApiGet({ profileDocs: [] });
    const user = userEvent.setup();
    renderDock();
    await user.click(screen.getByRole("button", { name: /^CV/ }));
    expect(
      await screen.findByText("Oryginał CV: brak pliku — ani w zgłoszeniu, ani w profilu kandydata"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pokaż CV/ })).toBeNull();
  });

  it("CV: kopia ze zgłoszenia i zatwierdzone CV firmowe — oba z datą", async () => {
    routeApiGet({});
    originalGet.mockResolvedValue({
      data: { has_snapshot: true, original_snapshot_at: "2026-08-20T08:00:00Z", original_cv_filename: "a.pdf" },
    });
    brandedGet.mockResolvedValue({
      data: { status: "finalized", from_generator: true, finalized_at: "2026-09-02T08:00:00Z" },
    });
    const user = userEvent.setup();
    renderDock();
    await user.click(screen.getByRole("button", { name: /^CV/ }));
    expect(await screen.findByText(/Oryginał CV: dołączony do zgłoszenia · 20\.08\.2026/)).toBeInTheDocument();
    expect(await screen.findByText("CV firmowe: zatwierdzone 2.09.2026")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pokaż CV oryginalne/ })).toBeInTheDocument();
  });

  // PR 4 (04.10.2026): QC CV widać już na „Zweryfikowanym” — rekruter poprawia
  // CV, zanim przekaże kartę do „QC CV”.
  it("Zweryfikowany z CV firmowym: dok pokazuje wynik QC i otwiera okno QC", async () => {
    routeApiGet({});
    const fallback = apiGet.getMockImplementation()!;
    apiGet.mockImplementation((url: string) =>
      url === "/api/pipeline/stages/501/qc"
        ? Promise.resolve({ data: { passed: false, blocking_failed: 2, override: null, checks: [] } })
        : fallback(url),
    );
    brandedGet.mockResolvedValue({
      data: { status: "finalized", from_generator: true, finalized_at: "2026-09-02T08:00:00Z" },
    });
    const onOpenQc = vi.fn();
    const user = userEvent.setup();
    // Na „Zweryfikowanym” sekcja CV jest „Teraz” — otwarta od startu.
    renderDock({ item: baseItem({ stage: "verified" }), onOpenQc });
    expect(
      await screen.findByText("QC CV: 2 rzeczy do poprawy przed wysłaniem"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Otwórz QC" }));
    expect(onOpenQc).toHaveBeenCalledTimes(1);
  });

  // 18.10.2026 (Kalwala, 789131): karta „QC: 2 do poprawy”, panel „1 rzecz” — panel
  // dopisuje nieblokujące uwagi tą samą regułą co plakietka karty.
  it("zdanie QC dopisuje uwagi nieblokujące — te same liczby co karta", () => {
    expect(earlyQcSentence(false, { passed: false, blocking_failed: 1, warnings_count: 1, override: null })).toBe(
      "QC CV: 1 rzecz do poprawy przed wysłaniem · 1 uwaga (nie blokuje)",
    );
    expect(earlyQcSentence(false, { passed: true, blocking_failed: 0, warnings_count: 3, override: null })).toBe(
      "QC CV: bez blokad — można przekazać dalej · 3 uwagi (nie blokuje)",
    );
    expect(earlyQcSentence(false, { passed: false, blocking_failed: 2, override: null })).toBe(
      "QC CV: 2 rzeczy do poprawy przed wysłaniem",
    );
  });

  it("bez CV firmowego dok nie liczy QC", async () => {
    routeApiGet({});
    renderDock({ item: baseItem({ stage: "verified" }), onOpenQc: vi.fn() });
    await screen.findByText("CV firmowe: brak");
    expect(screen.queryByTestId("dock-early-qc")).toBeNull();
    expect(apiGet).not.toHaveBeenCalledWith("/api/pipeline/stages/501/qc");
  });

  // 13.10.2026 (zgłoszenie rekruterki): wgrywanie CV „na wierzchu” — w sekcji
  // CV panelu osoby, bez przechodzenia do profilu.
  describe("Wgraj nowe CV", () => {
    afterEach(() => {
      useAuthStore.setState({ user: null } as never);
    });

    it("osoba bez CV: kafelek „Wgraj CV” zamiast linku do profilu", async () => {
      useAuthStore.setState({ user: { id: 7, role: "recruiter", roles: ["recruiter"] } } as never);
      routeApiGet({ profileDocs: [] });
      const user = userEvent.setup();
      renderDock();
      await user.click(screen.getByRole("button", { name: /^CV/ }));

      await screen.findByText("Oryginał CV: brak pliku — ani w zgłoszeniu, ani w profilu kandydata");
      expect(screen.getByLabelText(/^Wgraj CV/)).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: /Dodaj CV w profilu kandydata/ })).toBeNull();
    });

    it("osoba z CV: kafelek „Wgraj nowe CV” obok kopii ze zgłoszenia", async () => {
      useAuthStore.setState({ user: { id: 7, role: "recruiter", roles: ["recruiter"] } } as never);
      routeApiGet({});
      originalGet.mockResolvedValue({
        data: { has_snapshot: true, original_snapshot_at: "2026-08-20T08:00:00Z", original_cv_filename: "a.pdf" },
      });
      const user = userEvent.setup();
      renderDock();
      await user.click(screen.getByRole("button", { name: /^CV/ }));

      await screen.findByText(/Oryginał CV: dołączony do zgłoszenia · 20\.08\.2026/);
      expect(screen.getByLabelText(/^Wgraj nowe CV/)).toBeInTheDocument();
    });

    it("tylko do odczytu: bez kafelka, zostaje link do profilu", async () => {
      useAuthStore.setState({ user: { id: 7, role: "recruiter", roles: ["recruiter"] } } as never);
      routeApiGet({ profileDocs: [] });
      const user = userEvent.setup();
      renderDock({ readOnly: true });
      await user.click(screen.getByRole("button", { name: /^CV/ }));

      expect(await screen.findByRole("link", { name: /Dodaj CV w profilu kandydata/ })).toBeInTheDocument();
      expect(screen.queryByLabelText(/Wgraj/)).toBeNull();
    });

    it("nowsze CV w profilu niż kopia ze zgłoszenia: ramka „Użyj w tej rekrutacji”", async () => {
      useAuthStore.setState({ user: { id: 7, role: "recruiter", roles: ["recruiter"] } } as never);
      routeApiGet({
        profileDocs: [
          {
            id: 9,
            filename: "Anna_CV_2026.pdf",
            is_primary: true,
            uploaded_at: "2026-10-13T09:00:00Z",
            created_at: "2026-10-13T09:00:00Z",
            content_type: "application/pdf",
            size_bytes: 10,
            document_kind: "cv",
            external_source: "m365",
          },
        ],
      });
      originalGet.mockResolvedValue({
        data: { has_snapshot: true, original_snapshot_at: "2026-08-20T08:00:00Z", original_cv_filename: "a.pdf" },
      });
      const user = userEvent.setup();
      renderDock();
      await user.click(screen.getByRole("button", { name: /^CV/ }));

      expect(await screen.findByText("W profilu jest nowsze CV")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Użyj w tej rekrutacji/ })).toBeInTheDocument();
    });
  });
});

// Runda 10 (R10-N15-3): awaria odczytu w doku to komunikat z „Ponów”, nie
// „Brak …” — rekruter dopisywał notatkę albo robił screening drugi raz.
describe("PipelineCandidateDock — awaria odczytu to nie pustka", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    originalGet.mockResolvedValue({ data: { has_snapshot: false } });
    brandedGet.mockResolvedValue({ data: { status: "none" } });
    candidatesGet.mockResolvedValue({ data: { email: "anna@example.com" } });
    apiPost.mockResolvedValue({ data: {} });
  });

  it("screening: 500 daje „Nie udało się wczytać” z Ponów", async () => {
    const user = userEvent.setup();
    formGet.mockRejectedValue(new Error("500"));
    apiGet.mockResolvedValue({ data: { items: [] } });
    renderDock({ item: baseItem({ stage: "new" }) });

    expect(await screen.findByText(/Nie udało się wczytać: screening/)).toBeTruthy();
    // Awaria nie wygląda jak pusty screening.
    expect(screen.queryByTestId("screening-form-readonly")).toBeNull();

    formGet.mockResolvedValue({ data: dockForm() });
    await user.click(screen.getByRole("button", { name: "Ponów" }));
    expect(await screen.findByTestId("screening-form-readonly")).toBeTruthy();
  });

  // 02.10.2026: dok mówił tylko „Odpowiedziano na N pytań” — rekruter nie
  // widział, co kandydat odpowiedział, bez otwierania arkusza.
  // 09.10.2026: jedna sekcja „Screening” — warunki, odpowiedzi i ocena razem,
  // bez osobnej „Karty rekomendacji”.
  it("screening: jedna sekcja z warunkami, odpowiedziami i oceną — bez „Karty rekomendacji”", async () => {
    apiGet.mockResolvedValue({ data: { items: [] } });
    formGet.mockResolvedValue({
      data: dockForm({
        sheet: {
          answers: [
            {
              question_id: "q1",
              question_text: "Ile lat pracujesz z Javą?",
              response: "Tak, 3 lata. Kafka i Spring Boot.",
              deal_breaker_hit: false,
            },
            { question_id: "q2", question_text: "Czy pracowałeś z Kafką?", response: "", deal_breaker_hit: false, skipped: true },
          ],
          experience_checks: [{ kind: "domains", name: "Bankowość", status: "confirmed", note: "" }],
          overall_fit: "fit",
          notes: "Dobra komunikacja.",
          internal_note: null,
          answered_at: "2026-09-30T10:00:00Z",
        },
        legacy_notes: "Dobra komunikacja.",
        questions: [
          {
            number: 1,
            question: "Ile lat pracujesz z Javą?",
            answer: "Tak, 3 lata. Kafka i Spring Boot.",
            source: "sheet",
            question_id: "q1",
            deal_breaker: "Poniżej 2 lat",
            deal_breaker_hit: false,
          },
          {
            number: 2,
            question: "Czy pracowałeś z Kafką?",
            answer: "",
            source: null,
            question_id: "q2",
            deal_breaker: null,
            deal_breaker_hit: false,
          },
        ],
        card: {
          fields: { availability: { raw: "od 1 listopada", source: "manual", by_name: "Marta Testowa" } },
          previous: { work_mode: { raw: "zdalnie" } },
          suggestions: {},
          completeness: { status: "partial", filled: 2, total: 10, missing: ["work_mode", "recommendation"] },
          labels: {
            availability: "Dostępność",
            work_mode: "Tryb pracy",
            recommendation: "Notatka",
            red_flags: "Red flags",
          },
          editable_fields: ["availability", "work_mode", "rate", "recommendation", "red_flags"],
        },
        rate: { amount: 140, unit: "hourly", currency: "PLN", source: "stage", at: null },
      }),
    });
    renderDock({ item: baseItem({ stage: "new" }) });

    const view = await screen.findByTestId("screening-form-readonly");
    expect(within(view).getByTestId("screening-summary-status")).toHaveTextContent("Pasuje");
    expect(within(view).getByTestId("screening-summary-status")).toHaveTextContent("Odpowiedzi: 1 z 2");
    expect(within(view).getByTestId("screening-summary-status")).toHaveTextContent("Brakuje pól: 2");
    // Warunki: stawka z etapu, pole z formularza i podpowiedź z poprzedniej próby.
    const terms = within(view).getByTestId("screening-form-readonly-terms");
    expect(terms).toHaveTextContent("140 zł/h");
    expect(terms).toHaveTextContent("od 1 listopada");
    expect(terms).toHaveTextContent("brak — ostatnio: zdalnie");
    // Odpowiedzi z „Odpada, gdy…” pod pytaniem.
    const answers = within(view).getByRole("list", { name: "Pytania i odpowiedzi" });
    expect(within(answers).getByText(/Ile lat pracujesz z Javą\?/)).toBeTruthy();
    expect(within(answers).getByText("Tak, 3 lata. Kafka i Spring Boot.")).toBeTruthy();
    expect(within(answers).getByText("Odpada, gdy: Poniżej 2 lat")).toBeTruthy();
    expect(within(answers).getByText("— pominięte —")).toBeTruthy();
    expect(screen.getByText("Sprawdzone w rozmowie")).toBeTruthy();
    expect(screen.getByText("Dobra komunikacja.")).toBeTruthy();
    // Ocena w tym samym widoku; osobnej sekcji i nazwy „Karta rekomendacji” nie ma.
    expect(within(view).getByTestId("screening-form-readonly-assessment")).toHaveTextContent("Dlaczego ten kandydat");
    expect(screen.queryByText("Karta rekomendacji")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Karta/ })).toBeNull();
    // Tekst w starym formacie jest pod ręką, ale zapytanie idzie dopiero po rozwinięciu.
    expect(within(view).getByRole("button", { name: "W starym formacie" })).toHaveAttribute("aria-expanded", "false");
    expect(apiGet.mock.calls.some(([url]) => String(url).startsWith("/api/recommendation-cards"))).toBe(false);
  });

  // Dok zostaje zamontowany po ruchu karty, a stan screeningu jest per para —
  // bez odświeżenia pokazywałby stawkę i kolumnę sprzed ruchu.
  it("screening: po ruchu karty (inny wiersz etapu) stan odświeża się raz, nie w pętli", async () => {
    apiGet.mockResolvedValue({ data: { items: [] } });
    formGet.mockResolvedValue({ data: dockForm({ stage_id: 400 }) });
    renderDock({ item: baseItem({ stage: "new" }) });

    await screen.findByTestId("screening-form-readonly");
    await waitFor(() => expect(formGet).toHaveBeenCalledTimes(2));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(formGet).toHaveBeenCalledTimes(2);
  });

  it("notatki: 500 daje „Nie udało się wczytać”, nie „Brak notatek”", async () => {
    const user = userEvent.setup();
    formGet.mockResolvedValue({ data: dockForm() });
    apiGet.mockImplementation((url: string) =>
      url.startsWith("/api/notes")
        ? Promise.reject(new Error("500"))
        : Promise.resolve({ data: { items: [] } }),
    );
    renderDock();

    await user.click(screen.getByRole("button", { name: /^Notatki/ }));
    expect(await screen.findByText(/Nie udało się wczytać: notatki/)).toBeTruthy();
    expect(screen.queryByText(/Brak notatek dla tej rekrutacji/)).toBeNull();
    expect(screen.queryByText(/jeszcze nic nie zapisano/)).toBeNull();
  });

  it("notatki: podpis sekcji mówi o historii poza rekrutacją, a „Cała historia” otwiera zakładkę", async () => {
    const user = userEvent.setup();
    const onOpenWorkbench = vi.fn();
    apiGet.mockImplementation((url: string) =>
      url === "/api/notes?candidate_id=42"
        ? Promise.resolve({
            data: {
              items: [
                { id: 1, job_id: 77, job_title: "Analityk systemowy", content: "Feedback klienta.", author_name: "Piotr Wrona", created_at: "2025-04-02T09:40:00Z", group: "talks", replies: [] },
                { id: 2, job_id: null, content: "Nie dzwonić przed 10:00.", author_name: null, created_at: "2023-05-11T07:12:00Z", group: "talks", replies: [] },
                { id: 3, job_id: 77, content: "Auto-match 70/100.", is_system: true, group: "automat", created_at: "2025-03-01T00:00:00Z", replies: [] },
              ],
            },
          })
        : Promise.resolve({ data: { items: [] } }),
    );
    renderDock({ onOpenWorkbench });

    // Zwinięta sekcja od razu mówi, że osoba ma u nas historię (12.10.2026:
    // 1 417 otwartych kart pokazywało „0 w tej rekrutacji” mimo notatek gdzie indziej).
    expect(await screen.findByRole("button", { name: /^Notatki.*0 tu · 2 wcześniej/ })).toBeTruthy();
    // Jedno zapytanie o wszystkie notatki osoby, bez `job_id`.
    expect(apiGet.mock.calls.some(([url]) => String(url).includes("job_id="))).toBe(false);

    await user.click(screen.getByRole("button", { name: /^Notatki/ }));
    expect(await screen.findByText("W tej rekrutacji jeszcze nic nie zapisano.")).toBeTruthy();
    expect(screen.getByText("Feedback klienta.")).toBeTruthy();
    expect(screen.queryByText(/Auto-match 70/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "Cała historia (2)" }));
    expect(onOpenWorkbench).toHaveBeenLastCalledWith("notes");
  });

  it("notatki: bez historii poza rekrutacją podpis zostaje „N w tej rekrutacji”", async () => {
    apiGet.mockImplementation((url: string) =>
      url === "/api/notes?candidate_id=42"
        ? Promise.resolve({
            data: {
              items: [
                { id: 1, job_id: 10, content: "Umówiony telefon.", author_name: "Anna Kowalczyk", created_at: "2026-10-12T08:00:00Z", group: "talks", replies: [] },
              ],
            },
          })
        : Promise.resolve({ data: { items: [] } }),
    );
    renderDock();
    expect(await screen.findByRole("button", { name: /^Notatki.*1 w tej rekrutacji/ })).toBeTruthy();
  });
});

// ── Rozwinięty panel: pasek zakładek stoi w miejscu, kontakt pod nazwiskiem
//    (09.10.2026, zgłoszenie rekruterów) ─────────────────────────────────

/** Zastępuje `PersonWorkbenchTabs`: pokazuje to, co dok podaje pod pasek zakładek. */
function WorkbenchSlot() {
  return <div data-testid="workbench-slot">{useContext(WorkbenchBelowTabsContext)}</div>;
}

describe("PipelineCandidateDock — rozwinięty panel i dane kontaktowe (09.10.2026)", () => {
  const target = stageCol("verified", "Zweryfikowany", { stage_def_id: 5 });

  beforeEach(() => {
    vi.clearAllMocks();
    formGet.mockResolvedValue({ data: dockForm() });
    originalGet.mockResolvedValue({ data: { has_snapshot: false } });
    brandedGet.mockResolvedValue({ data: { status: "none" } });
    candidatesGet.mockResolvedValue({
      data: { city: "Lublin", email: "anna@example.com", phone: "+48 600 100 200" },
    });
    apiPost.mockResolvedValue({ data: {} });
    apiGet.mockImplementation((url: string) => {
      if (url.startsWith("/api/pipeline/move-requirements")) {
        return Promise.resolve({
          data: {
            from_column: "new",
            to_column: "verified",
            skipped_columns: ["screening"],
            items: [
              { key: "screening_sheet", label: "Arkusz screeningu", status: "missing", blocking: false },
              { key: "availability", label: "Dostępność", status: "ok", blocking: false },
            ],
            primary: { kind: "move", label: "Przesuń na „Zweryfikowany”" },
            owner_note: null,
          },
        });
      }
      return Promise.resolve({ data: { items: [] } });
    });
  });

  it("telefon i e-mail stoją pod nazwiskiem; numer dzwoni, ikony kopiują", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    // Po `userEvent.setup()` — ten podmienia schowek własną atrapą.
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderDock({ item: baseItem({ stage: "new" }) });

    const line = await screen.findByTestId("person-contact-line");
    expect(within(line).getByRole("link", { name: "+48 600 100 200" })).toHaveAttribute(
      "href",
      "tel:+48600100200",
    );
    expect(within(line).getByText("anna@example.com")).toBeTruthy();
    await user.click(within(line).getByRole("button", { name: "Kopiuj numer: Anna Kowalska" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("+48 600 100 200"));
    await user.click(within(line).getByRole("button", { name: "Kopiuj adres e-mail: Anna Kowalska" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("anna@example.com"));
    expect(toastSuccess).toHaveBeenCalledWith("Skopiowano adres e-mail");
  });

  it("„Nowy w bazie · N dni” w głowie panelu — tylko osoba dodana w ostatnich 14 dniach", async () => {
    candidatesGet.mockResolvedValue({
      data: {
        city: "Lublin",
        added_to_base_at: new Date(Date.now() - 3 * 24 * 3_600_000).toISOString(),
        added_to_base_exact: true,
        added_via: "CV upload",
        created_by_user: { id: 7, name: "Marta Nowak" },
      },
    });
    renderDock({ item: baseItem({ stage: "new" }) });

    const pill = await within(screen.getByTestId("dock-person-bar")).findByTestId("new-in-base-pill");
    expect(pill).toHaveTextContent(/^Nowy w bazie · \d+ dni$/);
    expect(pill.getAttribute("title")).toMatch(/^W bazie od \d{2}\.\d{2}\.\d{4} · dodał\(a\) Marta Nowak · CV upload$/);
  });

  it("bez pigułki dla osoby dawno w bazie i dla daty niedokładnej z importu", async () => {
    candidatesGet.mockResolvedValue({
      data: { city: "Lublin", added_to_base_at: "2019-05-11T22:00:00Z", added_to_base_exact: true },
    });
    renderDock({ item: baseItem({ stage: "new" }) });
    expect(await screen.findByText(/Lublin/)).toBeTruthy();
    expect(screen.queryByTestId("new-in-base-pill")).toBeNull();

    cleanup();
    candidatesGet.mockResolvedValue({
      data: {
        city: "Lublin",
        added_to_base_at: new Date(Date.now() - 24 * 3_600_000).toISOString(),
        added_to_base_exact: false,
      },
    });
    renderDock({ item: baseItem({ stage: "new" }) });
    expect(await screen.findByText(/Lublin/)).toBeTruthy();
    expect(screen.queryByTestId("new-in-base-pill")).toBeNull();
  });

  it("profil bez telefonu i adresu nie pokazuje pustej linii kontaktu", async () => {
    candidatesGet.mockResolvedValue({ data: { city: "Lublin" } });
    renderDock({ item: baseItem({ stage: "new" }) });
    expect(await screen.findByText(/Lublin/)).toBeTruthy();
    expect(screen.queryByTestId("person-contact-line")).toBeNull();
  });

  it("po „Rozwiń” głowa nie ma faktów ani „Następnego etapu” — stoją w zwiniętej linii pod zakładkami", async () => {
    const user = userEvent.setup();
    renderDock({
      item: baseItem({ stage: "new" }),
      primaryTarget: target,
      expanded: true,
      workbench: <WorkbenchSlot />,
    });

    const slot = await screen.findByTestId("workbench-slot");
    const fold = within(slot).getByTestId("dock-stage-fold");
    const toggle = within(fold).getByRole("button", { name: /Warunki i następny etap/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(await within(fold).findByText("Zweryfikowany · brakuje 1 z 2")).toBeTruthy();
    // Zwinięta: żadnego z trzech bloków nie ma ani w głowie, ani pod zakładkami.
    expect(screen.queryByTestId("dock-facts")).toBeNull();
    expect(screen.queryByTestId("dock-contact-row")).toBeNull();
    expect(screen.queryByTestId("dock-next-stage")).toBeNull();
    // Rząd akcji zostaje w głowie: stoi nad paskiem zakładek i nie przewija
    // się z treścią zakładki.
    const reject = screen.getByRole("button", { name: /Odrzuć z powodem/ });
    expect(reject.closest("[data-person-scroll]")).toBeNull();
    expect(slot.closest("[data-person-scroll]")).not.toBeNull();
    expect(document.querySelectorAll("[data-person-scroll]")).toHaveLength(1);

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(within(fold).getByTestId("dock-facts")).toBeTruthy();
    expect(within(fold).getByTestId("dock-contact-row")).toBeTruthy();
    expect(await within(fold).findByTestId("dock-next-stage")).toBeTruthy();
  });

  describe("Tryb rozmowy (29.10.2026)", () => {
    const originalMatchMedia = window.matchMedia;
    function inPanel(split: boolean) {
      return function InPanel(dock: ReactNode) {
        return (
          <PersonPanelSideProvider>
            <PersonPanelColumn split={split}>{dock}</PersonPanelColumn>
          </PersonPanelSideProvider>
        );
      };
    }

    beforeEach(() => {
      window.matchMedia = ((query: string) => ({
        matches: true,
        media: query,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
      })) as unknown as typeof window.matchMedia;
      window.localStorage.clear();
    });

    afterEach(() => {
      window.matchMedia = originalMatchMedia;
      window.localStorage.clear();
    });

    it("rozwinięty panel ma przełącznik obok „Zwiń”; klik ustawia tryb na kolumnie", async () => {
      const user = userEvent.setup();
      renderDock(
        { item: baseItem({ stage: "screening" }), expanded: true, split: true, onToggleExpanded: vi.fn() },
        inPanel(true),
      );
      const toggle = screen.getByRole("button", { name: "Tryb rozmowy" });
      expect(toggle).toHaveAttribute("aria-pressed", "false");
      expect(screen.getByRole("button", { name: "Zwiń" })).toBeTruthy();

      await user.click(toggle);
      expect(screen.getByRole("button", { name: "Tryb rozmowy" })).toHaveAttribute("aria-pressed", "true");
      expect(screen.getByTestId("person-panel-column")).toHaveAttribute("data-compact", "");
      // Rząd akcji etapu zostaje w trybie rozmowy.
      expect(screen.getByRole("button", { name: /Odrzuć z powodem/ })).toBeTruthy();
    });

    it("wąski dok i dok poza panelem nie mają przełącznika", () => {
      renderDock({ item: baseItem({ stage: "screening" }), expanded: false, onToggleExpanded: vi.fn() }, inPanel(false));
      expect(screen.queryByRole("button", { name: "Tryb rozmowy" })).toBeNull();
      cleanup();
      renderDock({ item: baseItem({ stage: "screening" }), expanded: true, onToggleExpanded: vi.fn() });
      expect(screen.queryByRole("button", { name: "Tryb rozmowy" })).toBeNull();
    });
  });

  it("zakładka z własnym ruchem i własnymi warunkami (Screening w „Nowych”) nie ma linii", async () => {
    renderDock({
      item: baseItem({ stage: "new" }),
      primaryTarget: target,
      expanded: true,
      split: true,
      hidePrimaryMove: true,
      workbench: <WorkbenchSlot />,
    });
    const slot = await screen.findByTestId("workbench-slot");
    expect(await screen.findByText(/Lublin/)).toBeTruthy();
    expect(within(slot).queryByTestId("dock-stage-fold")).toBeNull();
    expect(screen.queryByTestId("dock-next-stage")).toBeNull();
  });

  it("zakładka z własnym ruchem, ale bez własnych warunków, ma linię samych „Warunków”", async () => {
    renderDock({
      item: baseItem({ stage: "verified" }),
      primaryTarget: target,
      expanded: true,
      hidePrimaryMove: true,
      workbench: <WorkbenchSlot />,
    });
    const slot = await screen.findByTestId("workbench-slot");
    expect(within(slot).getByRole("button", { name: "Warunki wobec rekrutacji" })).toBeTruthy();
  });

  it("wąski dok (bez „Rozwiń”) pokazuje fakty i „Następny etap” wprost, bez zwiniętej linii", async () => {
    renderDock({
      item: baseItem({ stage: "new" }),
      primaryTarget: target,
      expanded: false,
      workbench: <WorkbenchSlot />,
    });
    expect(await screen.findByTestId("dock-facts")).toBeTruthy();
    expect(await screen.findByTestId("dock-next-stage")).toBeTruthy();
    expect(screen.queryByTestId("dock-stage-fold")).toBeNull();
  });

  // 09.10.2026 (zgłoszenie z laptopa 1280 × 650): cała głowa wąskiego doku
  // stała w miejscu i na sekcje zostawało 92 px. W miejscu stoi już tylko
  // pasek osoby i pole notatki — reszta przewija się razem.
  it("wąski dok przewija się w całości: fakty, „Następny etap”, przyciski i sekcje w jednym obszarze", async () => {
    renderDock({
      item: baseItem({ stage: "new" }),
      primaryTarget: target,
      expanded: false,
      workbench: <WorkbenchSlot />,
    });
    const facts = await screen.findByTestId("dock-facts");
    const scrollAreas = document.querySelectorAll("[data-person-scroll]");
    expect(scrollAreas).toHaveLength(1);
    const scroll = scrollAreas[0];
    expect(scroll.contains(facts)).toBe(true);
    expect(scroll.contains(await screen.findByTestId("dock-next-stage"))).toBe(true);
    expect(scroll.contains(screen.getByRole("button", { name: /Odrzuć z powodem/ }))).toBe(true);
    expect(scroll.contains(screen.getByTestId("dock-sections"))).toBe(true);
    // W miejscu zostaje pasek osoby (nazwisko, „Rozwiń”, zamknij) i notatka.
    const bar = screen.getByTestId("dock-person-bar");
    expect(scroll.contains(bar)).toBe(false);
    expect(within(bar).getByRole("button", { name: "Zamknij dok" })).toBeTruthy();
    expect(scroll.contains(screen.getByLabelText("Dodaj notatkę"))).toBe(false);
  });
});

// ── Pole notatki: rośnie, duże okno pisania, szkic (12.10.2026, zgłoszenie
//    rekruterów: jedna linia 230 px, tekst znikał po przejściu do innej osoby)

describe("PipelineCandidateDock — pole notatki: duże okno i szkic (12.10.2026)", () => {
  const DRAFT_KEY = "nexus:note-draft:v1:7:10:42";
  const HINT = "Enter dodaje notatkę · Shift+Enter nowa linia";
  const HINT_BIG = "Enter nowa linia · Ctrl+Enter dodaje";

  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
    useAuthStore.setState({ user: { id: 7, role: "recruiter", roles: ["recruiter"] } } as never);
    formGet.mockResolvedValue({ data: dockForm() });
    originalGet.mockResolvedValue({ data: { has_snapshot: false } });
    brandedGet.mockResolvedValue({ data: { status: "none" } });
    candidatesGet.mockResolvedValue({ data: { email: "anna@example.com" } });
    apiGet.mockResolvedValue({ data: { items: [] } });
    apiPost.mockResolvedValue({ data: {} });
  });

  afterEach(() => {
    useAuthStore.setState({ user: null } as never);
    sessionStorage.clear();
  });

  const noteBox = () => screen.getByRole("textbox", { name: "Dodaj notatkę" });
  const enlargeButton = () => screen.queryByRole("button", { name: "Powiększ pole notatki" });
  const notePosts = () => apiPost.mock.calls.filter(([url]) => url === "/api/notes");

  /** Dok z własnym klientem zapytań — do ponownego montażu i zmiany propsów. */
  function dockTree(
    overrides: Partial<DockProps> = {},
    qc = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  ) {
    const props: DockProps = {
      item: baseItem(),
      jobId: 10,
      currentStageLabel: "Nowi / Analiza CV",
      moveTargets: [],
      readOnly: false,
      contactFeatureEnabled: false,
      canReject: true,
      onClose: vi.fn(),
      onMoveTo: vi.fn(),
      onOpenScreening: vi.fn(),
      onReject: vi.fn(),
      ...overrides,
    };
    return (
      <QueryClientProvider client={qc}>
        <TooltipProvider>
          <PipelineCandidateDock {...props} />
        </TooltipProvider>
      </QueryClientProvider>
    );
  }

  async function enlarge(user: ReturnType<typeof userEvent.setup>) {
    await user.click(noteBox());
    await user.click(screen.getByRole("button", { name: "Powiększ pole notatki" }));
  }

  it("w spoczynku jest zwarte; po wejściu pokazuje klawisze i „Powiększ”, a Tab nie zwija rzędu", async () => {
    const user = userEvent.setup();
    renderDock();
    expect(enlargeButton()).toBeNull();
    expect(screen.queryByText(HINT)).toBeNull();
    expect(screen.getByRole("button", { name: "Dodaj notatkę — wyślij" })).toBeDisabled();

    await user.click(noteBox());
    expect(screen.getByText(HINT)).toBeTruthy();
    expect(enlargeButton()).toBeTruthy();

    await user.tab();
    expect(enlargeButton()).toHaveFocus();
  });

  it("puste pole po wyjściu wraca do zwartego, pole z tekstem zostaje otwarte", async () => {
    const user = userEvent.setup();
    renderDock();
    await user.type(noteBox(), "Chce hybrydę");
    await user.click(screen.getByText("Anna Kowalska"));
    expect(enlargeButton()).toBeTruthy();

    await user.clear(noteBox());
    await user.click(screen.getByText("Anna Kowalska"));
    expect(enlargeButton()).toBeNull();
  });

  it("„Powiększ”: pole dostaje fokus, reszta doku jest ukryta (nie odmontowana), Enter robi nową linię", async () => {
    const user = userEvent.setup();
    renderDock();
    const body = screen.getByTestId("dock-body");
    await user.type(noteBox(), "Rozmowa 12.10");
    await user.click(screen.getByRole("button", { name: "Powiększ pole notatki" }));

    expect(screen.getByTestId("dock-body")).toBe(body);
    expect(body).not.toBeVisible();
    expect(body).toHaveAttribute("inert");
    expect(screen.getByTestId("dock-person-bar")).toBeVisible();
    expect(noteBox()).toHaveFocus();
    expect(noteBox()).toHaveValue("Rozmowa 12.10");
    expect(screen.getByText(HINT_BIG)).toBeTruthy();

    await user.type(noteBox(), "{Enter}Selenium: 4 lata");
    expect(noteBox()).toHaveValue("Rozmowa 12.10\nSelenium: 4 lata");
    expect(notePosts()).toHaveLength(0);
  });

  it("w dużym oknie Ctrl+Enter dodaje notatkę i wraca zwykłe pole", async () => {
    const user = userEvent.setup();
    renderDock();
    await enlarge(user);
    await user.type(noteBox(), "Rozmowa 12.10{Enter}Dostępny od listopada");
    await user.keyboard("{Control>}{Enter}{/Control}");

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith("/api/notes", {
        candidate_id: 42,
        job_id: 10,
        content: "Rozmowa 12.10\nDostępny od listopada",
        note_type: "general",
      }),
    );
    await waitFor(() => expect(screen.getByTestId("dock-body")).toBeVisible());
    expect(noteBox()).toHaveValue("");
  });

  it("w dużym oknie notatkę dodaje też przycisk; „Zmniejsz” zostawia tekst", async () => {
    const user = userEvent.setup();
    renderDock();
    await enlarge(user);
    await user.type(noteBox(), "Oddzwonić po 15");
    await user.click(screen.getByRole("button", { name: "Zmniejsz" }));
    expect(screen.getByTestId("dock-body")).toBeVisible();
    expect(noteBox()).toHaveValue("Oddzwonić po 15");

    await user.click(screen.getByRole("button", { name: "Powiększ pole notatki" }));
    await user.click(screen.getByRole("button", { name: "Dodaj notatkę" }));
    await waitFor(() => expect(notePosts()).toHaveLength(1));
  });

  it("Esc zmniejsza duże okno także wtedy, gdy fokus jest poza polem", async () => {
    const user = userEvent.setup();
    renderDock();
    await enlarge(user);
    await user.type(noteBox(), "Oddzwonić");
    act(() => (document.activeElement as HTMLElement).blur());

    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.getByTestId("dock-body")).toBeVisible());
    expect(noteBox()).toHaveValue("Oddzwonić");
  });

  it("Esc w dużym oknie jest oznaczony jako obsłużony — nasłuch Tablicy go pominie w każdej kolejności", async () => {
    // W przeglądarce React przerysowuje między dwoma nasłuchami `window`: gdy
    // ten z doku działa pierwszy, znacznik dużego okna znika, zanim Tablica go
    // sprawdzi. Zostaje jej tylko `defaultPrevented` (przegląd kodu 12.10.2026).
    const user = userEvent.setup();
    renderDock();
    await enlarge(user);
    const escape = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    act(() => {
      window.dispatchEvent(escape);
    });
    expect(escape.defaultPrevented).toBe(true);
    expect(screen.getByTestId("dock-body")).toBeVisible();
  });

  it("duże okno w ukrytym doku (przegląd DL nad panelem) nie przechwytuje Esc", async () => {
    const user = userEvent.setup();
    const view = render(dockTree());
    await enlarge(user);
    view.container.hidden = true;
    const escape = new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    act(() => {
      window.dispatchEvent(escape);
    });
    expect(escape.defaultPrevented).toBe(false);
    expect(screen.getByTestId("dock-body")).toHaveAttribute("hidden");
  });

  it("dok tylko do odczytu nie zostaje pustym panelem po dużym oknie", async () => {
    const user = userEvent.setup();
    // Ten sam klient zapytań i to samo miejsce w drzewie — zmienia się tylko `readOnly`.
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = render(dockTree({}, qc));
    await enlarge(user);
    expect(screen.getByTestId("dock-body")).not.toBeVisible();

    view.rerender(dockTree({ readOnly: true }, qc));
    expect(screen.queryByRole("textbox", { name: "Dodaj notatkę" })).toBeNull();
    expect(screen.getByTestId("dock-body")).toBeVisible();
  });

  it("szkic wraca po ponownym otwarciu tej samej osoby i nie pojawia się u innej", async () => {
    const user = userEvent.setup();
    const first = render(dockTree());
    await user.type(noteBox(), "Oddzwonić po 15");
    expect(sessionStorage.getItem(DRAFT_KEY)).toBe("Oddzwonić po 15");
    first.unmount();

    const other = render(dockTree({ item: baseItem({ id: 502, candidate_id: 43, name: "Jan", lastname: "Nowak" }) }));
    expect(noteBox()).toHaveValue("");
    other.unmount();

    render(dockTree());
    expect(noteBox()).toHaveValue("Oddzwonić po 15");
    // Szkic otwiera pole — widać, że coś czeka na wysłanie.
    expect(enlargeButton()).toBeTruthy();
  });

  it("po udanym dodaniu szkicu nie ma", async () => {
    const user = userEvent.setup();
    renderDock();
    await user.type(noteBox(), "Chce hybrydę{Enter}");
    await waitFor(() => expect(noteBox()).toHaveValue(""));
    expect(sessionStorage.getItem(DRAFT_KEY)).toBeNull();
  });

  describe("„Zapisz notatkę i wypełnij formularz” (D3, 14.10.2026)", () => {
    const FILL = "Zapisz notatkę i wypełnij formularz";

    function withReceiver(receiver: NoteFillReceiver) {
      const channel = createNoteFillChannel();
      channel.register(42, receiver);
      return channel;
    }

    it("przycisk jest tylko wtedy, gdy formularz tej osoby czeka na notatkę", async () => {
      const user = userEvent.setup();
      const view = render(dockTree());
      await user.type(noteBox(), "Rozmowa: Java 6 lat");
      expect(screen.queryByRole("button", { name: FILL })).toBeNull();
      view.unmount();

      const other = createNoteFillChannel();
      other.register(43, vi.fn());
      render(dockTree({ noteFill: other }));
      await user.click(noteBox());
      expect(screen.queryByRole("button", { name: FILL })).toBeNull();
    });

    it("zapisuje notatkę zwykłą drogą i przekazuje jej numer i treść formularzowi", async () => {
      apiPost.mockImplementation((url: string) =>
        url === "/api/notes" ? Promise.resolve({ data: { id: 77 } }) : Promise.resolve({ data: {} }),
      );
      const receiver = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(dockTree({ noteFill: withReceiver(receiver) }));
      await user.type(noteBox(), "Rozmowa: Java 6 lat, od zaraz");
      await user.click(screen.getByRole("button", { name: FILL }));

      await waitFor(() => expect(receiver).toHaveBeenCalledWith({ noteId: 77, text: "Rozmowa: Java 6 lat, od zaraz" }));
      expect(notePosts()).toEqual([
        [
          "/api/notes",
          { candidate_id: 42, job_id: 10, content: "Rozmowa: Java 6 lat, od zaraz", note_type: "general" },
        ],
      ]);
      await waitFor(() =>
        expect(toastSuccess).toHaveBeenCalledWith(
          "Notatka dodana i przekazana do formularza screeningu — sprawdź pola i zapisz formularz.",
        ),
      );
      expect(toastSuccess).not.toHaveBeenCalledWith("Notatka dodana.");
      expect(noteBox()).toHaveValue("");
    });

    it("gdy formularz notatki nie przyjął, notatka i tak jest zapisana — komunikat to mówi", async () => {
      apiPost.mockImplementation((url: string) =>
        url === "/api/notes" ? Promise.resolve({ data: { id: 78 } }) : Promise.resolve({ data: {} }),
      );
      const receiver = vi.fn().mockRejectedValue(new Error("Luna nie odpowiada"));
      const user = userEvent.setup();
      render(dockTree({ noteFill: withReceiver(receiver) }));
      await user.type(noteBox(), "Rozmowa: Java 6 lat");
      await user.click(screen.getByRole("button", { name: FILL }));

      await waitFor(() =>
        expect(toastError).toHaveBeenCalledWith(
          "Notatka dodana i zostaje w historii, ale formularza z niej nie wypełniłem.",
        ),
      );
      expect(notePosts()).toHaveLength(1);
      expect(sessionStorage.getItem(DRAFT_KEY)).toBeNull();
    });

    it("Enter dalej tylko dodaje notatkę", async () => {
      apiPost.mockImplementation(() => Promise.resolve({ data: { id: 79 } }));
      const receiver = vi.fn().mockResolvedValue(undefined);
      const user = userEvent.setup();
      render(dockTree({ noteFill: withReceiver(receiver) }));
      await user.type(noteBox(), "Oddzwonić po 15{Enter}");
      await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Notatka dodana."));
      expect(receiver).not.toHaveBeenCalled();
    });
  });

  it("szkic znika z pamięci w chwili wysłania, a po błędzie zapisu wraca", async () => {
    // `onSuccess` działa też po odmontowaniu doku: gdyby szkic czekał w pamięci
    // do odpowiedzi serwera, „wyślij, wyjdź, wróć” oddawałoby wysłany tekst.
    let fail!: (error: Error) => void;
    apiPost.mockImplementation((url: string) =>
      url === "/api/notes"
        ? new Promise((_resolve, reject) => {
            fail = reject;
          })
        : Promise.resolve({ data: {} }),
    );
    const user = userEvent.setup();
    renderDock();
    await user.type(noteBox(), "Chce hybrydę{Enter}");
    await waitFor(() => expect(notePosts()).toHaveLength(1));
    expect(sessionStorage.getItem(DRAFT_KEY)).toBeNull();

    await act(async () => fail(new Error("Błąd sieci")));
    await waitFor(() => expect(sessionStorage.getItem(DRAFT_KEY)).toBe("Chce hybrydę"));
    expect(noteBox()).toHaveValue("Chce hybrydę");
    expect(toastError).toHaveBeenCalled();
  });

  describe("powód odrzucenia w panelu osoby (19.10.2026)", () => {
    it("odrzucona osoba: ramka z powodem, komentarzem, kto i kiedy — nad warunkami", () => {
      renderDock({
        currentStageLabel: "Odrzucony",
        item: baseItem({
          stage: "rejected",
          moved_at: "2026-10-16T10:00:00Z",
          rejection_reason_name: "Za wysokie oczekiwania finansowe",
          closed_by_name: "Julia Swidkiewicz",
          notes: "Oczekuje 190 zł/h, budżet do 150.",
        }),
      });
      const box = screen.getByTestId("dock-closed-reason");
      expect(box).toHaveAttribute("data-tone", "danger");
      expect(box).toHaveTextContent("Odrzucony: Za wysokie oczekiwania finansowe");
      expect(box).toHaveTextContent("Oczekuje 190 zł/h, budżet do 150.");
      expect(box).toHaveTextContent("Julia Swidkiewicz · 16.10.2026");
      // Pierwsza rzecz w sekcji akcji — widać ją bez przewijania.
      expect(screen.getByTestId("dock-actions").firstElementChild).toBe(box);
      // Oś czasu mówi, kiedy i dlaczego, zamiast „W etapie od 3 dni”.
      expect(screen.getByText("Odrzucony · Za wysokie oczekiwania finansowe")).toBeInTheDocument();
      expect(screen.queryByText(/W etapie od/)).not.toBeInTheDocument();
    });

    it("rezygnacja i brak powodu: szara ramka, bez zgadywania", () => {
      renderDock({
        currentStageLabel: "Rezygnacja",
        item: baseItem({ stage: "withdrawn", rejection_reason_name: null, notes: null }),
      });
      const box = screen.getByTestId("dock-closed-reason");
      expect(box).toHaveAttribute("data-tone", "neutral");
      expect(box).toHaveTextContent("Rezygnacja: powód nie został zapisany");
    });

    it("osoba w toku: bez ramki", () => {
      renderDock({ item: baseItem({ notes: "Notatka z ruchu" }) });
      expect(screen.queryByTestId("dock-closed-reason")).not.toBeInTheDocument();
    });
  });
});
