/**
 * Strona rekrutacji (wersja 3): adres → widok / segment / sekcja panelu / okno.
 *
 * Dzieci są atrapami — test pilnuje OKABLOWANIA strony: że stare linki
 * z powiadomień lądują tam, gdzie trzeba, są przepisywane `router.replace`
 * (bez wpisu w historii), a `?candidate=` otwiera osobę raz i znika.
 */
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
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
  header: null as Record<string, unknown> | null,
  champion: null as Record<string, unknown> | null,
  workspace: null as Record<string, unknown> | null,
  close: null as Record<string, unknown> | null,
  add: null as Record<string, unknown> | null,
  strip: null as Record<string, unknown> | null,
  chip: null as Record<string, unknown> | null,
}));
// Zalogowane konto. Domyślnie administrator; testy uprawnień podstawiają inne.
const auth = vi.hoisted(() => ({
  user: { id: 9, role: "admin" } as Record<string, unknown>,
  realUser: null as Record<string, unknown> | null,
}));
const apiMock = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn(), post: vi.fn() }));
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
// `canMutateSection` (prawa zespołu w nagłówku) zostaje prawdziwy: „podgląd
// jako” nadal odbiera zapis.
vi.mock("@/lib/section-access", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/section-access")>()),
  hasSectionAccess: () => true,
}));
vi.mock("@/store/tabs", () => ({
  useTabsStore: (sel: (s: unknown) => unknown) => sel({ openTab: vi.fn() }),
}));

// Tablica: od 14.10.2026 nic nie stoi nad kolumnami — „Kandydaci do dodania”
// są trzecią linią nagłówka.
vi.mock("@/components/v2/pages/KanbanBoardV2", () => ({
  KanbanBoardV2: (props: Record<string, unknown>) => {
    seen.kanban = props;
    return <div data-testid="kanban" />;
  },
}));
vi.mock("@/components/v2/jobs/CandidateSourcesStrip", () => ({
  CandidateSourcesStrip: stub("strip", "sources-strip"),
}));
vi.mock("@/components/v2/recruitment/AddCandidatesPanel", () => ({
  AddCandidatesPanel: stub("add", "add-window"),
}));
vi.mock("@/components/v2/recruitment/slideovers/OrderSlideOver", () => ({
  OrderSlideOver: stub("order", "order-window"),
}));
vi.mock("@/components/v2/recruitment/slideovers/HistoryChatSlideOver", () => ({
  HistoryChatSlideOver: stub("history", "history-window"),
}));
vi.mock("@/components/v2/recruitment/slideovers/QuestionBankSlideOver", () => ({
  QuestionBankSlideOver: stub("questions", "questions-window"),
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
vi.mock("@/components/champion/ChampionWorkspace", () => ({
  ChampionWorkspace: stub("workspace", "champion-workspace"),
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
vi.mock("@/components/v2/job-ad/JobAdWindow", () => ({ JobAdWindow: () => null }));
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

function renderPage(search = "", { refetchOnWindowFocus = true } = {}) {
  nav.search = search;
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus } },
  });
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
  // „Zwiń” nagłówka jest pamiętane w przeglądarce — każdy test zaczyna od rozwiniętego.
  window.localStorage.clear();
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
    // Tryb „Tabela" usunięty — widoki to zakładki „Tablica” i „Profil Championa”.
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
    // Braki zlecenia niesie odznaka przy zakładce „Profil Championa”.
    await waitFor(() =>
      expect(screen.getByTestId("open-champion-profile")).toHaveTextContent("brakuje 2"),
    );
    // Ścieżki „Zlecenie → … → Umowa” i liczników już nie ma (02.10.2026).
    expect(screen.queryByTestId("job-recruitment-path")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-nearest-step")).not.toBeInTheDocument();
    expect(screen.queryByTestId("job-header-kpis")).not.toBeInTheDocument();
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

  it("?tab=portals → okno „Zlecenie” z sekcją portali (R5-8); ?tab=questions → baza pytań; ?tab=manual-search → zakładka „Szukaj ręcznie”", async () => {
    // 04.10.2026: portale żyją w zakładce „Zespół i ogłoszenie” Profilu
    // Championa — stary adres prowadzi tam wprost, z rozwiniętymi portalami.
    const first = renderPage("tab=portals");
    await screen.findByTestId("champion-workspace");
    await waitFor(() =>
      expect(seen.workspace).toMatchObject({ tab: "team", portalsFocus: true }),
    );
    expect(window.location.search).toContain("ptab=team");
    expect(window.location.search).not.toContain("win=order");
    first.unmount();
    const second = renderPage("tab=questions");
    expect(await screen.findByTestId("questions-window")).toBeInTheDocument();
    second.unmount();
    // 14.10.2026: „Szukaj ręcznie” to zakładka okna „Kandydaci do dodania”.
    renderPage("tab=manual-search");
    expect(await screen.findByTestId("add-window")).toBeInTheDocument();
    expect(seen.add).toMatchObject({ open: true, tab: "manual" });
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
    await userEvent.click(screen.getByRole("button", { name: "Więcej akcji rekrutacji" }));
    await userEvent.click(await screen.findByTestId("open-order"));
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
    // Domyślnie zakładka „Brief”; pełny formularz z menu „⋯”.
    expect(await screen.findByTestId("champion-workspace")).toBeInTheDocument();
    expect(seen.workspace).toMatchObject({ tab: "brief" });
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

  it("na widoku „Profil Championa” są zakładki zamiast panelu bocznego", async () => {
    renderPage("tab=champion");
    await screen.findByTestId("champion-workspace");
    expect(screen.queryByTestId("open-order")).not.toBeInTheDocument();
    expect(screen.queryByTestId("readiness-dock")).not.toBeInTheDocument();
    expect(screen.getByTestId("open-champion-profile")).toHaveAttribute("aria-current", "page");
    expect(screen.getByTestId("open-champion-profile")).toHaveTextContent("Profil Championa");
    expect(seen.workspace).toMatchObject({
      tab: "brief",
      canEditChampion: true,
      canWritePipeline: true,
    });
  });

  it("stare zakładki panelu z adresu: ?ptab=readiness → Brief, ?ptab=announce → Zespół z portalami", async () => {
    const first = renderPage("tab=champion&ptab=readiness");
    await screen.findByTestId("champion-workspace");
    expect(seen.workspace).toMatchObject({ tab: "brief" });
    first.unmount();
    renderPage("tab=champion&ptab=announce");
    await screen.findByTestId("champion-workspace");
    expect(seen.workspace).toMatchObject({ tab: "team", portalsFocus: true });
  });

  it("zakładka z `onTabChange` trafia do adresu (`ptab`), Brief go zdejmuje", async () => {
    renderPage("tab=champion");
    await screen.findByTestId("champion-workspace");
    act(() => (seen.workspace?.onTabChange as (t: string) => void)("client"));
    await waitFor(() => expect(seen.workspace).toMatchObject({ tab: "client" }));
    expect(window.location.search).toContain("ptab=client");
    act(() => (seen.workspace?.onTabChange as (t: string) => void)("brief"));
    await waitFor(() => expect(window.location.search).not.toContain("ptab="));
  });

  it("?mode=edit otwiera pełny formularz; „Wróć do Profilu Championa” wraca do zakładek", async () => {
    renderPage("tab=champion&mode=edit");
    await screen.findByTestId("champion-editor");
    expect(seen.champion).toMatchObject({ layout: "workspace", canEdit: true });
    expect(screen.queryByTestId("champion-workspace")).not.toBeInTheDocument();
    await userEvent.click(screen.getByTestId("champion-back-to-tabs"));
    expect(await screen.findByTestId("champion-workspace")).toBeInTheDocument();
    expect(window.location.search).not.toContain("mode=edit");
  });

  it("menu „⋯ → Edytuj Profil Championa” otwiera pełny formularz", async () => {
    renderPage("tab=champion");
    await screen.findByTestId("champion-workspace");
    await userEvent.click(screen.getByRole("button", { name: "Więcej akcji rekrutacji" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /Edytuj Profil Championa/ }));
    expect(await screen.findByTestId("champion-editor")).toBeInTheDocument();
    expect(window.location.search).toContain("mode=edit");
  });
});

describe("strona rekrutacji — nagłówek i „Kandydaci do dodania” (02.10.2026)", () => {
  it("nagłówek pokazuje trzy fakty: klient, budżet i tryb pracy", async () => {
    apiMock.get.mockImplementation((url: string) => {
      if (url === "/api/jobs/42") {
        return Promise.resolve({
          data: { ...JOB, working_title: "Java · Spring", client_reference: "ZOB-1", remote_policy: "remote" },
        });
      }
      if (url === "/api/pipeline/kanban/42") return Promise.resolve({ data: KANBAN });
      return Promise.resolve({ data: [] });
    });
    renderPage();
    const facts = await screen.findByTestId("job-header-facts");
    expect(facts).toHaveTextContent("Bank Alfa");
    expect(facts).toHaveTextContent("190");
    expect(facts).toHaveTextContent("Zdalnie");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Java · Spring");
    expect(screen.getByTestId("header-client-title")).toHaveTextContent("Senior Java Developer");
    expect(screen.getByTestId("header-client-reference")).toHaveTextContent("ZOB-1");
  });

  it("źródło w nagłówku otwiera okno źródeł na swojej zakładce i zapisuje to w adresie", async () => {
    renderPage();
    const strip = await screen.findByTestId("sources-strip");
    expect(screen.getByTestId("job-header-sources-row")).toContainElement(strip);
    expect(seen.strip).toMatchObject({ jobId: 42, canSeeSimilar: true });
    expect(seen.add).toMatchObject({ open: false });

    act(() => (seen.strip?.onOpen as (tab: string) => void)("postings"));
    expect(await screen.findByTestId("add-window")).toBeInTheDocument();
    expect(seen.add).toMatchObject({ open: true, tab: "postings", jobId: 42 });
    expect(window.location.search).toBe("?win=add&wintab=postings");

    // Zmiana zakładki w oknie zostaje w adresie; zamknięcie go czyści.
    act(() => (seen.add?.onTabChange as (tab: string) => void)("search"));
    await waitFor(() => expect(window.location.search).toBe("?win=add&wintab=search"));
    act(() => (seen.add?.onOpenChange as (open: boolean) => void)(false));
    await waitFor(() => expect(window.location.search).toBe(""));
  });

  it("stary adres ?win=similar otwiera to samo okno na „Podobnych rekrutacjach”", async () => {
    renderPage("win=similar");
    expect(await screen.findByTestId("add-window")).toBeInTheDocument();
    expect(seen.add).toMatchObject({ open: true, tab: "similar" });
  });

  it("stary adres ?win=manual-search otwiera okno źródeł na „Szukaj ręcznie” i przepisuje adres", async () => {
    renderPage("win=manual-search");
    expect(await screen.findByTestId("add-window")).toBeInTheDocument();
    expect(seen.add).toMatchObject({ open: true, tab: "manual" });
    await waitFor(() =>
      expect(nav.replace).toHaveBeenCalledWith("/jobs/42?win=add&wintab=manual", { scroll: false }),
    );
  });

  it("„Szukaj ręcznie” z ekranu propozycji otwiera zakładkę okna, nie osobne okno", async () => {
    renderPage("tab=people&seg=proposals");
    await screen.findByTestId("proposals-screen");
    act(() => (seen.proposals?.onOpenManualSearch as () => void)());
    expect(await screen.findByTestId("add-window")).toBeInTheDocument();
    expect(seen.add).toMatchObject({ open: true, tab: "manual" });
    expect(window.location.search).toContain("win=add&wintab=manual");
  });

  it("„Przeszukaj całą bazę (AI)” z menu „⋯” otwiera „Propozycje z bazy” i zleca przegląd", async () => {
    renderPage();
    await screen.findByTestId("kanban");
    const before = (seen.add?.fullReviewRequest as number | undefined) ?? 0;
    await userEvent.click(screen.getByRole("button", { name: "Więcej akcji rekrutacji" }));
    // Od 25.10.2026 w podmenu „Dodaj kandydatów”.
    await userEvent.click(await screen.findByTestId("menu-add-candidates"));
    await userEvent.click(await screen.findByTestId("menu-full-review"));
    await waitFor(() => expect(seen.add).toMatchObject({ open: true, tab: "base" }));
    expect(seen.add?.fullReviewRequest).toBe(before + 1);
    // Okno oddaje żądanie — po zamknięciu i ponownym otwarciu skan nie rusza drugi raz.
    act(() => (seen.add?.onFullReviewHandled as () => void)());
    await waitFor(() => expect(seen.add?.fullReviewRequest).toBeNull());
  });

  it("plakietka statusu otwiera okienko championów i pyta o listę (D2); menu „⋯” już nie (25.10.2026)", async () => {
    apiMock.get.mockImplementation((url: string) => {
      if (url === "/api/jobs/42") {
        return Promise.resolve({ data: { ...JOB, request_status: "searching", champions: [] } });
      }
      if (url === "/api/pipeline/kanban/42") return Promise.resolve({ data: KANBAN });
      if (url === "/api/jobs/42/champions") {
        return Promise.resolve({
          data: {
            job_id: 42,
            can_edit: true,
            seats: 1,
            hired_count: 0,
            search_stopped: false,
            legacy_flag: false,
            work_state: "searching",
            champions: [],
            eligible: [
              {
                candidate_id: 7,
                name: "Karol Wzorcowy",
                column: "client_interview",
                stage_label: "Rozmowa u klienta",
                is_champion: false,
              },
            ],
          },
        });
      }
      return Promise.resolve({ data: [] });
    });
    renderPage();
    await screen.findByTestId("kanban");
    // Plakietka statusu jest przyciskiem okienka; listy nie pobieramy przed otwarciem.
    expect(await screen.findByTestId("job-champions-status")).toHaveTextContent("Szukamy");
    expect(apiMock.get).not.toHaveBeenCalledWith("/api/jobs/42/champions");
    await userEvent.click(screen.getByRole("button", { name: "Więcej akcji rekrutacji" }));
    await screen.findByTestId("open-order");
    expect(screen.queryByTestId("toggle-champion")).toBeNull();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(screen.getByTestId("job-champions-status"));
    const popover = await screen.findByTestId("job-champions-popover");
    expect(await within(popover).findByText("Karol Wzorcowy")).toBeInTheDocument();
    expect(apiMock.get).toHaveBeenCalledWith("/api/jobs/42/champions");
    // Stary przełącznik „Mamy championa” nie jest już wysyłany.
    expect(apiMock.post).not.toHaveBeenCalledWith("/api/jobs/42/champion-found", expect.anything());
  });

  it("Tablica nie dostaje już skoku do kolumny ani panelu dodawania w „Nowych”", async () => {
    renderPage();
    await screen.findByTestId("kanban");
    await waitFor(() => expect(seen.kanban?.workbenchContext).toBeTruthy());
    expect(seen.kanban).not.toHaveProperty("focusColumnRequest");
    expect(seen.kanban).not.toHaveProperty("onOpenAddCandidates");
    // „Kandydaci do dodania” nie stoją już nad kolumnami (K-D1, 14.10.2026).
    expect(seen.kanban?.renderAbove).toBeUndefined();
  });
});

describe("strona rekrutacji — priorytet, rekruter i „Zwiń” w nagłówku (14.10.2026)", () => {
  beforeEach(() => {
    apiMock.get.mockImplementation((url: string) => {
      if (url === "/api/jobs/42") {
        return Promise.resolve({
          data: {
            ...JOB,
            priority_level: "p1",
            can_set_priority: true,
            can_staff: true,
            recruiters: [
              { user_id: 31, name: "Ewa Testowa", via: "owner", proposed: false, assigned_by_name: null },
            ],
            delivery_lead_user: { id: 5, name: "Olga Wzorcowa" },
          },
        });
      }
      if (url === "/api/pipeline/kanban/42") return Promise.resolve({ data: KANBAN });
      return Promise.resolve({ data: [] });
    });
  });

  it("plakietka priorytetu przed tytułem i fakt „Rekruter” w linii faktów", async () => {
    renderPage();
    const priority = await screen.findByTestId("job-header-priority");
    expect(priority).toHaveTextContent("P1");
    expect(screen.getByTestId("job-header-title").parentElement).toContainElement(priority);
    const recruiter = screen.getByTestId("job-header-recruiter");
    expect(recruiter).toHaveTextContent("Ewa T.");
    expect(screen.getByTestId("job-header-facts").parentElement).toContainElement(recruiter);
  });

  it("„Zwiń” zostawia linię tytułu i jest pamiętane dla osoby po ponownym wejściu", async () => {
    const first = renderPage();
    await screen.findByTestId("sources-strip");
    expect(seen.kanban?.headerCollapsed).toBe(false);
    await userEvent.click(screen.getByTestId("job-header-collapse"));
    // Tablica dostaje zmianę — to sygnał do ponownego pomiaru wysokości kolumn.
    await waitFor(() => expect(seen.kanban?.headerCollapsed).toBe(true));
    expect(screen.queryByTestId("job-header-facts")).not.toBeInTheDocument();
    expect(screen.queryByTestId("sources-strip")).not.toBeInTheDocument();
    expect(window.localStorage.getItem("nexus:job-header-collapsed:9")).toBe("1");
    first.unmount();

    renderPage();
    await screen.findByTestId("job-header-title");
    await waitFor(() =>
      expect(screen.getByTestId("job-header-collapse")).toHaveAttribute("aria-expanded", "false"),
    );
    expect(screen.queryByTestId("job-header-facts")).not.toBeInTheDocument();
  });
});

describe("strona rekrutacji — „Profil Championa”: szkic pełnego formularza przeżywa powrót do zakładek", () => {
  it("formularz → zakładki → formularz nie odmontowuje edytora (niezapisane zmiany zostają)", async () => {
    renderPage("tab=champion&mode=edit");
    await screen.findByTestId("champion-editor");
    const firstProps = seen.champion;
    act(() => (seen.champion?.onDirtyChange as (dirty: boolean) => void)(true));
    expect(screen.getByTestId("champion-back-to-tabs")).toHaveTextContent("niezapisane");
    await userEvent.click(screen.getByTestId("champion-back-to-tabs"));
    expect(await screen.findByTestId("champion-workspace")).toBeInTheDocument();
    // Edytor jest nadal w drzewie (ukryty), a nie odmontowany — i strona o tym mówi.
    expect(screen.getByTestId("champion-editor")).toBeInTheDocument();
    const notice = screen.getByTestId("champion-unsaved-full-form");
    await userEvent.click(within(notice).getByRole("button", { name: "Wróć do formularza" }));
    expect(window.location.search).toContain("mode=edit");
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

describe("strona rekrutacji — filtr „Kto dodał” (14.10.2026, D2–D3)", () => {
  const card = (id: number, by: number | null, name: string | null) => ({
    id: 500 + id,
    candidate_id: id,
    stage: "new",
    added_to_job_by_id: by,
    added_to_job_by_name: name,
  });
  const BOARD = {
    columns: [
      {
        stage: "new",
        name: "Nowi",
        category: "internal",
        stage_def_id: 1,
        count: 3,
        items: [card(1, 9, "Ada Admin"), card(2, 5, "Paulina Wrona"), card(3, 9, "Ada Admin")],
      },
    ],
    off_template: null,
  };

  beforeEach(() => {
    apiMock.get.mockImplementation((url: string) => {
      if (url === "/api/jobs/42") return Promise.resolve({ data: JOB });
      if (url === "/api/pipeline/kanban/42") return Promise.resolve({ data: BOARD });
      return Promise.resolve({ data: [] });
    });
  });

  it("?added_by= trafia do Tablicy i na przycisk w nagłówku; „✕” zdejmuje parametr z adresu", async () => {
    window.history.replaceState(null, "", "/jobs/42?added_by=9&tab=board");
    renderPage("added_by=9&tab=board");
    const trigger = await screen.findByTestId("added-by-trigger");
    expect(trigger).toHaveTextContent("Kto dodał:Ty· 2 z 3");
    expect(seen.kanban?.addedBy).toEqual({ kind: "user", userId: 9 });

    await userEvent.click(screen.getByTestId("added-by-clear"));
    expect(window.location.search).toBe("?tab=board");
    // Zapis bez routera Nexta — strona nie przewija się na górę.
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("bez parametru: „Kto dodał: wszyscy”, Tablica dostaje filtr „wszyscy”", async () => {
    renderPage();
    expect(await screen.findByTestId("added-by-trigger")).toHaveTextContent("Kto dodał:wszyscy");
    expect(seen.kanban?.addedBy).toEqual({ kind: "all" });
  });
});

// 27.10.2026: odświeżanie przy powrocie do karty jest globalnie wyłączone
// (`QueryProvider`), ale nie tu — własny ruch z drugiej karty nie przychodzi
// gniazdem (serwer pomija autora `pipeline_changed`).
describe("JobDetailPage — Tablica i rekrutacja wracają świeże po powrocie do karty", () => {
  it("powrót do karty pobiera Tablicę i rekrutację jeszcze raz", async () => {
    // Domyślne opcje jak w `QueryProvider`.
    renderPage("", { refetchOnWindowFocus: false });
    await waitFor(() => expect(apiMock.get).toHaveBeenCalledWith("/api/pipeline/kanban/42"));
    const count = (url: string) => apiMock.get.mock.calls.filter(([u]) => u === url).length;
    const before = { kanban: count("/api/pipeline/kanban/42"), job: count("/api/jobs/42") };
    act(() => {
      focusManager.setFocused(false);
      focusManager.setFocused(true);
    });
    await waitFor(() => expect(count("/api/pipeline/kanban/42")).toBe(before.kanban + 1));
    await waitFor(() => expect(count("/api/jobs/42")).toBe(before.job + 1));
    focusManager.setFocused(undefined);
  });
});

// 29.10.2026: okruszek w powłoce (`BreadcrumbV2`) czyta rekrutację pod tym
// samym kluczem `["job", id]` i hydratuje się wcześniej niż strona. Gdy jego
// odpowiedź przyszła, zanim React doszedł do strony, pierwszy render klienta
// miał już dane (widok rekrutacji), a serwer wysłał „Ładowanie...” — React
// zgłaszał „Hydration failed”.
describe("JobDetailPage — hydratacja z rekrutacją już w cache'u", () => {
  it("pierwszy render klienta jest taki sam jak HTML z serwera", async () => {
    nav.search = "tab=chat";
    const tree = (client: QueryClient) => (
      <QueryClientProvider client={client}>
        <JobDetailPage />
      </QueryClientProvider>
    );
    const serverClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const container = document.createElement("div");
    container.innerHTML = renderToString(tree(serverClient));
    document.body.appendChild(container);
    expect(container.textContent).toContain("Ładowanie...");

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["job", "42"], JOB);
    const recoverable: unknown[] = [];
    let root: Root | undefined;
    await act(async () => {
      root = hydrateRoot(container, tree(client), {
        onRecoverableError: (error) => recoverable.push(error),
      });
    });

    expect(recoverable).toEqual([]);
    // Po hydratacji widok rekrutacji pokazuje się od razu z danych w cache'u.
    expect(await within(container).findByTestId("kanban")).toBeInTheDocument();
    act(() => root?.unmount());
    container.remove();
  });
});
