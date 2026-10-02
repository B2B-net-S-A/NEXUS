/**
 * Strona rekrutacji (wersja 3): adres → widok / segment / sekcja panelu / okno.
 *
 * Dzieci są atrapami — test pilnuje OKABLOWANIA strony: że stare linki
 * z powiadomień lądują tam, gdzie trzeba, są przepisywane `router.replace`
 * (bez wpisu w historii), a `?candidate=` otwiera osobę raz i znika.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({
  search: "",
  replace: vi.fn(),
  listeners: new Set<() => void>(),
}));
const seen = vi.hoisted(() => ({
  proposals: null as Record<string, unknown> | null,
  kanban: null as Record<string, unknown> | null,
  order: null as Record<string, unknown> | null,
  history: null as Record<string, unknown> | null,
  questions: null as Record<string, unknown> | null,
  manual: null as Record<string, unknown> | null,
  header: null as Record<string, unknown> | null,
  champion: null as Record<string, unknown> | null,
  brief: null as Record<string, unknown> | null,
  dock: null as Record<string, unknown> | null,
  close: null as Record<string, unknown> | null,
  chip: null as Record<string, unknown> | null,
}));
// Zalogowane konto. Domyślnie administrator; testy uprawnień podstawiają inne.
const auth = vi.hoisted(() => ({
  user: { id: 9, role: "admin" } as Record<string, unknown>,
  realUser: null as Record<string, unknown> | null,
}));
const apiMock = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn() }));
// Atrapa dziecka: zapamiętuje propsy; zamknięte okno nie renderuje nic.
const stub = vi.hoisted(
  () =>
    (slot: string, testId: string) =>
      function Stub(props: Record<string, unknown>) {
        (seen as Record<string, unknown>)[slot] = props;
        return props.open === false ? null : <div data-testid={testId} />;
      },
);

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "42" }),
  usePathname: () => "/jobs/42",
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));
vi.mock("@/lib/api", () => ({
  default: apiMock,
  api: apiMock,
  jobChatApi: { getUnreadCount: vi.fn().mockResolvedValue({ data: { unread_count: 2 } }) },
  matchingApi: { pipelineScores: vi.fn().mockResolvedValue({ data: { scores: {} } }) },
}));
vi.mock("@/lib/job-proposals-api", () => ({
  jobProposalsApi: { inbox: vi.fn().mockResolvedValue({ total: 7, items: [] }) },
  jobProposalsKeys: {
    all: (id: number) => ["job-proposals", id],
    recommendations: (id: number) => ["proposal-latest", id],
    visibleCount: (id: number) => ["job-proposals", id, "visible-count"],
  },
}));
vi.mock("@/lib/candidate-search-api", () => ({
  shortlistApi: { list: vi.fn().mockResolvedValue([{ id: 1 }]) },
}));
vi.mock("@/lib/client-playbooks", () => ({
  useClientPlaybook: () => ({ data: { sla_business_days: 5 } }),
}));
vi.mock("@/hooks/useCapability", () => ({ useCapability: () => true }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }),
}));
vi.mock("@/hooks/useJobPipelineTemplate", () => ({
  useJobPipelineTemplate: () => ({
    rejectionReasons: [],
    stagesWithScorecard: new Set<number>(),
    templateName: null,
    budgetHourly: null,
    canWriteClientRate: false,
  }),
}));
// Pomocniki ról (`getUserRoles` i reszta) zostają prawdziwe — czyta je reguła
// pełnej edycji (`hasFullJobEditFallback`); podmieniamy tylko stan i `hasRole`.
vi.mock("@/store/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/store/auth")>()),
  useAuthStore: (sel: (s: unknown) => unknown) =>
    sel({ user: auth.user, realUser: auth.realUser }),
  hasRole: () => true,
}));
vi.mock("@/lib/section-access", () => ({ hasSectionAccess: () => true }));
vi.mock("@/store/tabs", () => ({
  useTabsStore: (sel: (s: unknown) => unknown) => sel({ openTab: vi.fn() }),
}));

vi.mock("@/components/v2/pages/KanbanBoardV2", () => ({ KanbanBoardV2: stub("kanban", "kanban") }));
vi.mock("@/components/v2/recruitment/slideovers/OrderSlideOver", () => ({
  OrderSlideOver: stub("order", "order-window"),
}));
vi.mock("@/components/v2/recruitment/slideovers/HistoryChatSlideOver", () => ({
  HistoryChatSlideOver: stub("history", "history-window"),
}));
vi.mock("@/components/v2/recruitment/slideovers/QuestionBankSlideOver", () => ({
  QuestionBankSlideOver: stub("questions", "questions-window"),
}));
vi.mock("@/components/v2/recruitment/slideovers/ManualSearchSlideOver", () => ({
  ManualSearchSlideOver: stub("manual", "manual-window"),
}));
vi.mock("@/components/v2/recruitment/ProposalsSegment", () => ({
  ProposalsSegment: stub("proposals", "proposals-screen"),
}));
vi.mock("@/components/v2/recruitment/ProposalMatchDetails", () => ({ ProposalMatchDetails: () => null }));
vi.mock("@/components/v2/recruitment/JobAIActions", () => ({
  JobAIActions: () => <div data-testid="job-ai-actions" />,
}));
vi.mock("@/components/v2/recruitment/EmailTemplateModal", () => ({ EmailTemplateModal: () => null }));
vi.mock("@/components/ChampionProfileEditor", () => ({
  ChampionProfileEditor: stub("champion", "champion-editor"),
}));
vi.mock("@/components/v2/jobs/ChampionSectionNav", () => ({ ChampionSectionNav: () => null }));
vi.mock("@/components/v2/jobs/JobSummaryCard", () => ({ JobSummaryCard: () => null }));
vi.mock("@/components/v2/jobs/JobReadinessDock", () => ({
  JobReadinessDock: stub("dock", "readiness-dock"),
}));
vi.mock("@/components/champion/ChampionBriefView", () => ({
  ChampionBriefView: stub("brief", "champion-brief"),
}));
vi.mock("@/components/v2/jobs/JobCloseWithReasonDialog", () => ({
  JobCloseWithReasonDialog: stub("close", "close-dialog"),
}));
vi.mock("@/components/v2/jobs/ManagedInNexusSwitch", () => ({
  ManagedInTraffitNotice: () => null,
  ManagedInNexusChip: (props: Record<string, unknown>) => {
    (seen as Record<string, unknown>).chip = props;
    return null;
  },
}));
vi.mock("@/components/v2/jobs/JobShortlist", () => ({
  JobShortlist: () => <div data-testid="shortlist-screen" />,
  jobShortlistQueryKey: (id: number) => ["job-shortlist", id],
}));
vi.mock("@/components/v2/jobs/PipelineBoardGate", () => ({
  PipelineBoardGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/AppShell", () => ({ EditJobModal: () => null }));
vi.mock("@/components/v2/jobs/AIJobWriterModal", () => ({ AIJobWriterModal: () => null }));
vi.mock("@/components/v2/modals/AddCandidatesQuickModal", () => ({ AddCandidatesQuickModal: () => null }));
vi.mock("@/components/v2/modals/GenerateInviteLinkV2", () => ({ GenerateInviteLinkV2: () => null }));
vi.mock("@/components/v2/presence/ActiveViewers", () => ({ ActiveViewers: () => null }));

import JobDetailPage from "@/app/jobs/[id]/page";
import { permissionSnapshot } from "@/__tests__/fixtures/permission-snapshot";

const JOB = {
  id: 42,
  title: "Senior Java Developer",
  client_id: 3,
  client_name: "Bank Alfa",
  status: "published",
  can_write_client_rate: true,
  effective_budget_hourly: 190,
};
const KANBAN = { columns: [], off_template: null };

function renderPage(search = "") {
  nav.search = search;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = () => (
    <QueryClientProvider client={client}>
      <JobDetailPage />
    </QueryClientProvider>
  );
  const view = render(tree());
  return {
    ...view,
    /** Miękka nawigacja: ten sam komponent, inny adres. */
    navigate: (next: string) => {
      nav.search = next;
      view.rerender(tree());
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  for (const key of Object.keys(seen) as Array<keyof typeof seen>) seen[key] = null;
  auth.user = { id: 9, role: "admin" };
  auth.realUser = null;
  window.history.replaceState(null, "", "/jobs/42");
  apiMock.get.mockImplementation((url: string) => {
    if (url === "/api/jobs/42") return Promise.resolve({ data: JOB });
    if (url === "/api/pipeline/kanban/42") return Promise.resolve({ data: KANBAN });
    if (url === "/api/jobs/42/readiness") {
      return Promise.resolve({ data: { ready: false, blockers: ["Brak HM", "Brak budżetu"] } });
    }
    return Promise.resolve({ data: [] });
  });
});

describe("strona rekrutacji — widoki", () => {
  it("domyślnie „Tablica” (decyzja 22.09.2026), bez przepisywania adresu", async () => {
    renderPage();
    expect(await screen.findByTestId("kanban")).toBeInTheDocument();
    expect(screen.queryByTestId("proposals-screen")).not.toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
    // Tryb „Tabela" usunięty — widoki to zakładki „Tablica” i „Zlecenie i Champion”.
    expect(screen.queryByTestId("view-people")).not.toBeInTheDocument();
    expect(screen.getByTestId("view-board")).toHaveAttribute("aria-current", "page");
  });

  it("dawny adres „Tabeli” (?tab=people) otwiera Tablicę z kontekstem warsztatów", async () => {
    renderPage("tab=people");
    expect(await screen.findByTestId("kanban")).toBeInTheDocument();
    await waitFor(() =>
      expect(seen.kanban).toMatchObject({
        jobId: 42,
        kanbanQueryState: expect.objectContaining({ isSuccess: true }),
        workbenchContext: expect.objectContaining({ clientId: 3, clientName: "Bank Alfa", canCloseJob: true }),
      }),
    );
    // Krok 1 „Ścieżki rekrutacji" niesie braki zlecenia (zamiast przycisku „Zlecenie").
    expect(await screen.findByText("brakuje 2 — uzupełnij")).toBeInTheDocument();
    expect(screen.queryByTestId("open-order")).not.toBeInTheDocument();
  });

  it("„Do przejrzenia” (propozycje z bazy i shortlista) to osobny ekran z powrotem na Tablicę", async () => {
    renderPage("tab=people&seg=proposals");
    expect(await screen.findByTestId("proposals-screen")).toBeInTheDocument();
    expect(screen.queryByTestId("kanban")).not.toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: /Propozycje z bazy/ })).toHaveAttribute("aria-selected", "true");
    await userEvent.click(screen.getByRole("tab", { name: /Shortlista/ }));
    expect(await screen.findByTestId("shortlist-screen")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("view-board"));
    expect(await screen.findByTestId("kanban")).toBeInTheDocument();
    expect(window.location.search).toBe("");
  });

  it("?tab=champion (+ stary champion-profile z ?intake=1) otwiera pełny widok Championa", async () => {
    const view = renderPage("tab=champion-profile&intake=1");
    expect(await screen.findByTestId("champion-editor")).toBeInTheDocument();
    expect(seen.champion).toMatchObject({ intakeDefaultOpen: true });
    expect(nav.replace).toHaveBeenCalledWith("/jobs/42?intake=1&tab=champion", { scroll: false });
    view.unmount();
  });
});

describe("strona rekrutacji — stare adresy", () => {
  it.each([
    ["tab=screening", "kanban", "/jobs/42?tab=people&seg=group%3Ascreening&panel=screening"],
    ["tab=cv", "kanban", "/jobs/42?tab=people&seg=group%3Averification&panel=cv"],
    ["tab=ai-matching", "proposals-screen", "/jobs/42?tab=people&seg=proposals"],
    ["tab=similar", "proposals-screen", "/jobs/42?tab=people&seg=proposals"],
    ["tab=pipeline", "kanban", "/jobs/42?tab=people"],
  ])("?%s → %s", async (search, testId, rewritten) => {
    renderPage(search);
    expect(await screen.findByTestId(testId)).toBeInTheDocument();
    expect(nav.replace).toHaveBeenCalledWith(rewritten, { scroll: false });
  });

  it("?tab=chat otwiera okno „Historia i czat” na czacie; ?tab=history na historii requestów", async () => {
    const view = renderPage("tab=chat");
    expect(await screen.findByTestId("history-window")).toBeInTheDocument();
    expect(seen.history).toMatchObject({ open: true, initialTab: "chat" });
    view.unmount();
    renderPage("tab=history");
    await screen.findByTestId("history-window");
    expect(seen.history).toMatchObject({ open: true, initialTab: "request" });
  });

  it("?tab=portals → okno „Zlecenie” z sekcją portali (R5-8); ?tab=questions → baza pytań; ?tab=manual-search → wyszukiwarka", async () => {
    // 29.09.2026: portale żyją w panelu obok Profilu Championa (zakładka
    // „Ogłoszenie”) — stary adres prowadzi tam wprost, z rozwiniętymi portalami.
    const first = renderPage("tab=portals");
    await screen.findByTestId("champion-brief");
    await waitFor(() =>
      expect(seen.dock).toMatchObject({ panelTab: "announce", portalsFocus: true }),
    );
    expect(window.location.search).toContain("ptab=announce");
    expect(window.location.search).not.toContain("win=order");
    first.unmount();
    const second = renderPage("tab=questions");
    expect(await screen.findByTestId("questions-window")).toBeInTheDocument();
    second.unmount();
    renderPage("tab=manual-search");
    expect(await screen.findByTestId("manual-window")).toBeInTheDocument();
  });

  it("miękka nawigacja na tej samej rekrutacji (klik w powiadomienie) też działa", async () => {
    const view = renderPage("tab=people");
    await screen.findByTestId("kanban");
    expect(seen.history).toMatchObject({ open: false });
    view.navigate("tab=chat");
    expect(await screen.findByTestId("history-window")).toBeInTheDocument();
    // Ręczne zamknięcie nie jest cofane przy kolejnym renderze z tym samym adresem.
    act(() => (seen.history?.onOpenChange as (open: boolean) => void)(false));
    await waitFor(() => expect(seen.history).toMatchObject({ open: false }));
    view.navigate("tab=chat");
    expect(seen.history).toMatchObject({ open: false });
  });
});

describe("strona rekrutacji — ?candidate=", () => {
  it("z sekcją panelu (?tab=notes) otwiera warsztat osoby na Tablicy, nie dok", async () => {
    renderPage("tab=notes&candidate=77");
    await screen.findByTestId("kanban");
    await waitFor(() =>
      expect(seen.kanban).toMatchObject({
        initialWorkbench: { candidateId: 77, section: "notes" },
        initialDockCandidateId: null,
      }),
    );
    act(() => (seen.kanban?.onInitialWorkbenchHandled as () => void)());
    const urls = nav.replace.mock.calls.map(([url]) => url as string);
    expect(urls.some((url) => !url.includes("candidate="))).toBe(true);
  });

  it("na „Tablicy” osoba idzie do doku kanbana, jak dotąd", async () => {
    renderPage("tab=board&candidate=77");
    await screen.findByTestId("kanban");
    await waitFor(() => expect(seen.kanban).toMatchObject({ initialDockCandidateId: 77 }));
  });
});

describe("strona rekrutacji — okna z nagłówka i z warsztatów", () => {
  it("przyciski nagłówka otwierają okna i zapisują je w adresie", async () => {
    renderPage();
    await screen.findByTestId("kanban");
    await userEvent.click(screen.getByTestId("path-step-order"));
    expect(await screen.findByTestId("order-window")).toBeInTheDocument();
    expect(window.location.search).toBe("?win=order");
    act(() => (seen.order?.onOpenChange as (open: boolean) => void)(false));
    await waitFor(() => expect(window.location.search).toBe(""));
    await userEvent.click(screen.getByTestId("open-history-chat"));
    expect(seen.history).toMatchObject({ open: true, initialTab: "all", chatUnreadCount: 2 });
  });

  it("warsztat proszący o dawną zakładkę „questions” dostaje okno, nie zmianę widoku", async () => {
    renderPage();
    await screen.findByTestId("kanban");
    await waitFor(() => expect(seen.kanban?.workbenchContext).toBeTruthy());
    const ctx = seen.kanban?.workbenchContext as { onTabChange: (tab: string) => void };
    act(() => ctx.onTabChange("questions"));
    expect(await screen.findByTestId("questions-window")).toBeInTheDocument();
    expect(screen.getByTestId("kanban")).toBeInTheDocument();
  });

  it("„Otwórz pełne” w oknie Zlecenie prowadzi do widoku Championa", async () => {
    renderPage("win=order");
    await screen.findByTestId("order-window");
    act(() => (seen.order?.onNavigate as (target: string) => void)("champion"));
    // Domyślnie „Podgląd” — brief do czytania; edytor po „Edytuj”.
    expect(await screen.findByTestId("champion-brief")).toBeInTheDocument();
    expect(window.location.search).toContain("tab=champion");
  });
});

describe("strona rekrutacji — poprawki po integracji v3", () => {
  it("narzędzia AI administratora otwierają się z menu „…”, bez zaznaczonej propozycji", async () => {
    renderPage();
    await screen.findByTestId("kanban");
    expect(screen.queryByTestId("job-ai-actions")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Więcej akcji rekrutacji" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /Narzędzia AI \(administrator\)/ }));
    const dialog = await screen.findByRole("dialog", { name: "Narzędzia AI (administrator)" });
    expect(dialog).toContainElement(screen.getByTestId("job-ai-actions"));
  });

  it("podpowiedź „Obsada kompletna” otwiera od razu dialog zamknięcia z powodem", async () => {
    renderPage();
    await screen.findByTestId("kanban");
    await waitFor(() => expect(seen.kanban?.workbenchContext).toBeTruthy());
    const ctx = seen.kanban?.workbenchContext as { onRequestCloseJob: () => void };
    act(() => ctx.onRequestCloseJob());
    await waitFor(() => expect(seen.close).toMatchObject({ open: true }));
    // Stary adres okna nie zostaje — zamknięcie żyje w menu „⋯”.
    expect(window.location.search).not.toContain("win=order");
  });

  it("na widoku „Zlecenie i Champion” nie ma okna „Zlecenie” — braki, zespół i ogłoszenie są w panelu obok", async () => {
    renderPage("tab=champion");
    await screen.findByTestId("champion-brief");
    expect(screen.queryByTestId("open-order")).not.toBeInTheDocument();
    expect(screen.getByTestId("readiness-dock")).toBeInTheDocument();
    expect(screen.getByTestId("open-champion-profile")).toHaveAttribute("aria-current", "page");
  });

  it("?mode=edit otwiera edytor w układzie „workspace” (pasek sekcji, „Wypełnij szybciej”)", async () => {
    renderPage("tab=champion&mode=edit");
    await screen.findByTestId("champion-editor");
    expect(seen.champion).toMatchObject({ layout: "workspace", canEdit: true });
    expect(screen.queryByTestId("champion-brief")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Podgląd" }));
    expect(await screen.findByTestId("champion-brief")).toBeInTheDocument();
    expect(window.location.search).not.toContain("mode=edit");
  });
});

describe("strona rekrutacji — ścieżka rekrutacji i najbliższy krok", () => {
  const COLUMNS = [
    { stage: "new", name: "Nowi", category: "internal", stage_def_id: 1, count: 1, items: [{ id: 11, candidate_id: 101, stage: "new" }] },
    { stage: "screening", name: "Screening", category: "internal", stage_def_id: 2, count: 0, items: [] },
    { stage: "verified", name: "Zweryfikowany", category: "internal", stage_def_id: 3, count: 0, items: [] },
    { stage: "new", name: "QC CV", category: "internal", stage_def_id: 4, count: 2, items: [{ id: 41, candidate_id: 401, stage: "new" }, { id: 42, candidate_id: 402, stage: "new" }] },
    { stage: "cv_sent", name: "CV Wysłane", category: "internal", stage_def_id: 5, count: 0, items: [] },
    { stage: "client_interview", name: "Interview Klient", category: "external", stage_def_id: 6, count: 0, items: [] },
  ];

  it("kolejność reguł: braki zlecenia wygrywają, a „Zlecenie” w ścieżce otwiera okno", async () => {
    apiMock.get.mockImplementation((url: string) => {
      if (url === "/api/jobs/42") return Promise.resolve({ data: { ...JOB, headcount: 1 } });
      if (url === "/api/pipeline/kanban/42") return Promise.resolve({ data: { columns: COLUMNS, off_template: null } });
      if (url === "/api/jobs/42/readiness") {
        return Promise.resolve({ data: { ready: false, blockers: ["Brak HM", "Brak budżetu"] } });
      }
      return Promise.resolve({ data: [] });
    });
    renderPage();
    const nearest = await screen.findByTestId("job-nearest-step");
    expect(nearest).toHaveAttribute("data-rule", "order");
    expect(nearest).toHaveTextContent("Uzupełnij zlecenie (brakuje 2)");
    expect(screen.getByTestId("path-step-cv")).toHaveTextContent("2 w QC · 0 wysłanych");
    expect(screen.getByTestId("path-step-contract")).toHaveTextContent("obsada 0 / 1");
    await userEvent.click(screen.getByRole("button", { name: /Otwórz zlecenie/ }));
    await waitFor(() => expect(seen.order).toMatchObject({ open: true }));
  });

  it("bez braków zlecenia najbliższy krok to QC CV, a klik przekazuje Tablicy skok do kolumny", async () => {
    apiMock.get.mockImplementation((url: string) => {
      if (url === "/api/jobs/42") return Promise.resolve({ data: JOB });
      if (url === "/api/pipeline/kanban/42") return Promise.resolve({ data: { columns: COLUMNS, off_template: null } });
      if (url === "/api/jobs/42/readiness") return Promise.resolve({ data: { ready: true, blockers: [] } });
      return Promise.resolve({ data: [] });
    });
    renderPage();
    const nearest = await screen.findByTestId("job-nearest-step");
    await waitFor(() => expect(nearest).toHaveAttribute("data-rule", "qc"));
    expect(nearest).toHaveTextContent("Sprawdź CV w QC (2)");
    await userEvent.click(screen.getByRole("button", { name: /Pokaż QC CV/ }));
    await waitFor(() =>
      expect(seen.kanban).toMatchObject({ focusColumnRequest: { column: "cv_qc", seq: 1 } }),
    );
    await userEvent.click(screen.getByTestId("path-step-interviews"));
    await waitFor(() =>
      expect(seen.kanban).toMatchObject({ focusColumnRequest: { column: "client_interview", seq: 2 } }),
    );
  });
});

describe("strona rekrutacji — „Zlecenie i Champion”: szkic przeżywa przełączanie trybu", () => {
  it("Edytuj → Podgląd → Edytuj nie odmontowuje edytora (niezapisane zmiany zostają)", async () => {
    renderPage("tab=champion&mode=edit");
    await screen.findByTestId("champion-editor");
    const firstProps = seen.champion;
    // Edytor zgłasza niezapisane zmiany — przełącznik trybu je pokazuje.
    act(() => (seen.champion?.onDirtyChange as (dirty: boolean) => void)(true));
    await userEvent.click(screen.getByRole("button", { name: "Podgląd" }));
    expect(await screen.findByTestId("champion-brief")).toBeInTheDocument();
    // Edytor jest nadal w drzewie (ukryty), a nie odmontowany.
    expect(screen.getByTestId("champion-editor")).toBeInTheDocument();
    expect(screen.getByTestId("champion-mode-edit")).toHaveTextContent("niezapisane");
    await userEvent.click(screen.getByTestId("champion-mode-edit"));
    expect(seen.champion?.jobId).toBe(firstProps?.jobId);
  });
});

// Zamknięcie rekrutacji, bramka gotowości i powrót do Traffita idą za
// uprawnieniem „Rekrutacje: zakładanie, zamykanie, wysyłka CV do klienta”.
// `useCapability` jest tu atrapą (pełna redakcja = tak), więc każde konto
// niżej REDAGUJE rekrutację — różni je tylko to uprawnienie.
describe("strona rekrutacji — prowadzenie rekrutacji za uprawnieniem", () => {
  const readinessAsked = () =>
    apiMock.get.mock.calls.some(([url]) => url === "/api/jobs/42/readiness");

  async function openPage() {
    renderPage();
    await screen.findByTestId("kanban");
    await waitFor(() => expect(seen.kanban?.workbenchContext).toBeTruthy());
    await waitFor(() => expect(seen.chip).toBeTruthy());
  }

  async function closeMenuItem() {
    await userEvent.click(screen.getByRole("button", { name: "Więcej akcji rekrutacji" }));
    await screen.findByRole("menuitem", { name: /Kopiuj link/ });
    return screen.queryByRole("menuitem", { name: /Zamknij rekrutację/ });
  }

  function expectManages(manages: boolean) {
    const ctx = seen.kanban?.workbenchContext as { canCloseJob: boolean };
    expect(ctx.canCloseJob).toBe(manages);
    expect(seen.chip).toMatchObject({ canRevert: manages });
    expect(readinessAsked()).toBe(manages);
    // Dialog zamknięcia w ogóle nie jest montowany bez uprawnienia.
    expect(seen.close !== null).toBe(manages);
  }

  it.each([
    ["Delivery Lead (uprawnienie domyślne)", { id: 10, role: "delivery_lead", roles: ["delivery_lead"] }],
    [
      "rekruter z nadanym uprawnieniem",
      {
        id: 11,
        role: "recruiter",
        roles: ["recruiter"],
        effective_action_access: permissionSnapshot("recruitment_manage"),
      },
    ],
  ])("%s zamyka rekrutację, widzi bramkę gotowości i może cofnąć rekrutację do Traffita", async (_label, user) => {
    auth.user = user;
    await openPage();

    await waitFor(() => expectManages(true));
    expect(await closeMenuItem()).toBeInTheDocument();
  });

  it.each([
    ["rekruter bez uprawnienia", { id: 12, role: "recruiter", roles: ["recruiter"] }],
    [
      "Delivery Lead z wyłączonym uprawnieniem",
      {
        id: 13,
        role: "delivery_lead",
        roles: ["delivery_lead"],
        effective_action_access: permissionSnapshot("delivery_view", "clients_edit"),
      },
    ],
  ])("%s nie zamyka rekrutacji i nie pyta o bramkę gotowości", async (_label, user) => {
    auth.user = user;
    await openPage();

    expectManages(false);
    expect(await closeMenuItem()).not.toBeInTheDocument();
  });

  it("w podglądzie jako inny użytkownik nie ma zamknięcia ani powrotu do Traffita", async () => {
    auth.user = { id: 10, role: "delivery_lead", roles: ["delivery_lead"] };
    auth.realUser = { id: 9, role: "admin", roles: ["admin"] };
    await openPage();

    const ctx = seen.kanban?.workbenchContext as { canCloseJob: boolean };
    expect(ctx.canCloseJob).toBe(false);
    expect(seen.chip).toMatchObject({ canRevert: false });
    expect(seen.close).toBeNull();
    expect(await closeMenuItem()).not.toBeInTheDocument();
  });
});
