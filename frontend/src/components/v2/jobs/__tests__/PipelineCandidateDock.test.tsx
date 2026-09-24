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

import type { ComponentProps } from "react";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getForStage = vi.fn();
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
    get: (...a: unknown[]) => apiGet(...a),
    post: (...a: unknown[]) => apiPost(...a),
  },
  candidatesApi: {
    get: (...a: unknown[]) => candidatesGet(...a),
  },
  candidateStageCvApi: {
    original: { get: (...a: unknown[]) => originalGet(...a) },
    branded: { get: (...a: unknown[]) => brandedGet(...a) },
  },
  screeningApi: {
    getForStage: (...a: unknown[]) => getForStage(...a),
  },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: vi.fn(),
    showError: vi.fn(),
  }),
}));

// Modale CV/email mają WŁASNE zapytania (inne endpointy) — dok tylko je
// otwiera/zamyka, więc dla testów doku wystarczy pusty stub.
vi.mock("@/components/v2/modals/CVOriginalPreviewModal", () => ({
  CVOriginalPreviewModal: () => null,
}));
vi.mock("@/components/v2/modals/CVShareLinkModal", () => ({
  CVShareLinkModal: () => null,
}));
vi.mock("@/components/v2/modals/SendEmailV2", () => ({
  SendEmailV2: () => null,
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

import { PipelineCandidateDock, nowSectionForStage } from "@/components/v2/jobs/PipelineCandidateDock";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { KanbanColumn, KanbanItem } from "@/components/v2/pages/kanban-shared";

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

function renderDock(overrides: Partial<DockProps> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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
      <TooltipProvider>
        <PipelineCandidateDock {...props} />
      </TooltipProvider>
    </QueryClientProvider>
  );
  return props;
}

describe("PipelineCandidateDock", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getForStage.mockResolvedValue({
      data: {
        stage_id: 501,
        candidate_id: 42,
        job_id: 10,
        champion_profile: {},
        screening_answers: null,
      },
    });
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
    expect(await screen.findByText("CV do klienta: brak")).toBeInTheDocument();
    expect(screen.queryByText(/Stwórz brandowane|CV firmowe/)).toBeNull();
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
    expect(await screen.findByText("CV do klienta: szkic")).toBeInTheDocument();
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

  it("zakładka Screening otwiera Screening Championa przez onOpenScreening", async () => {
    const user = userEvent.setup();
    const onOpenScreening = vi.fn();
    renderDock({ onOpenScreening });

    await user.click(screen.getByRole("button", { name: /^Screening/ }));
    await user.click(
      screen.getByRole("button", { name: /Otwórz Screening Championa/ })
    );

    expect(onOpenScreening).toHaveBeenCalledWith(501, "Anna Kowalska");
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

  it("bez kontekstu warsztatów dok nie pokazuje ich przycisków", async () => {
    renderDock({ item: { ...baseItem(), stage: "verified" } });
    await screen.findByRole("button", { name: /Pokaż CV oryginalne/ });
    expect(screen.queryByRole("button", { name: /Wysyłka CV do klienta/ })).toBeNull();
  });
});

// ── Fala 3 („parytet z makietami") ─────────────────────────────────────────

describe("PipelineCandidateDock — nawigator, oś czasu i główna akcja", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getForStage.mockResolvedValue({ data: { screening_answers: null } });
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
    expect(screen.getByText("Karta w procesie")).toBeTruthy();
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
    expect(screen.getByText("Pokrycie must")).toBeTruthy();
    expect(screen.getByText("brak stawki")).toBeTruthy();
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
