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
  workspace: null as Record<string, unknown> | null,
  kanban: null as Record<string, unknown> | null,
  order: null as Record<string, unknown> | null,
  history: null as Record<string, unknown> | null,
  questions: null as Record<string, unknown> | null,
  manual: null as Record<string, unknown> | null,
  header: null as Record<string, unknown> | null,
  champion: null as Record<string, unknown> | null,
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
vi.mock("@/hooks/useJobPipelineTemplate", () => ({
  useJobPipelineTemplate: () => ({
    rejectionReasons: [],
    stagesWithScorecard: new Set<number>(),
    templateName: null,
    budgetHourly: null,
    canWriteClientRate: false,
  }),
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (sel: (s: unknown) => unknown) => sel({ user: { id: 9, role: "admin" }, realUser: null }),
  hasRole: () => true,
}));
vi.mock("@/lib/section-access", () => ({ hasSectionAccess: () => true }));
vi.mock("@/store/tabs", () => ({
  useTabsStore: (sel: (s: unknown) => unknown) => sel({ openTab: vi.fn() }),
}));
vi.mock("@/lib/use-local-storage-flag", () => ({
  useLocalStorageFlag: (_key: string, initial: boolean) => [initial, vi.fn()],
}));

vi.mock("@/components/v2/recruitment/RecruitmentWorkspace", () => ({
  RecruitmentWorkspace: stub("workspace", "workspace"),
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
  ProposalsSegment: () => null,
  ProposalsCountProbe: () => null,
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
vi.mock("@/components/v2/jobs/JobReadinessDock", () => ({ JobReadinessDock: () => null }));
vi.mock("@/components/v2/jobs/ManagedInNexusSwitch", () => ({
  ManagedInNexusBanner: () => null,
  ManagedInNexusChip: () => null,
}));
vi.mock("@/components/v2/jobs/JobShortlist", () => ({
  JobShortlist: () => null,
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
  it("domyślnie „Tabela”: workspace dostaje tablicę, liczniki, prawa i SLA", async () => {
    renderPage();
    expect(await screen.findByTestId("workspace")).toBeInTheDocument();
    expect(screen.queryByTestId("kanban")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(seen.workspace).toMatchObject({
        jobId: 42,
        segment: "in-process",
        canWritePipeline: true,
        canWriteClientRate: true,
        openProposalsCount: 7,
        shortlistCount: 1,
        activeCandidateId: null,
      }),
    );
    expect((seen.workspace?.job as { budgetHourly: number; slaDays: number }).budgetHourly).toBe(190);
    expect((seen.workspace?.job as { slaDays: number }).slaDays).toBe(5);
    // Odznaka „brakuje N" z oficjalnej bramki gotowości.
    expect(await screen.findByText("brakuje 2")).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("przełącznik „Tablica” pokazuje kanban i zapisuje widok w adresie", async () => {
    renderPage();
    await screen.findByTestId("workspace");
    await userEvent.click(screen.getByTestId("view-board"));
    expect(await screen.findByTestId("kanban")).toBeInTheDocument();
    expect(screen.queryByTestId("workspace")).not.toBeInTheDocument();
    expect(window.location.search).toBe("?tab=board");
    await userEvent.click(screen.getByTestId("view-people"));
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
    ["tab=screening", { segment: "group:screening", panelSection: "screening" }, "/jobs/42?seg=group%3Ascreening&panel=screening"],
    ["tab=cv", { segment: "group:verification", panelSection: "cv" }, "/jobs/42?seg=group%3Averification&panel=cv"],
    ["tab=ai-matching", { segment: "proposals" }, "/jobs/42?seg=proposals"],
    ["tab=similar", { segment: "proposals" }, "/jobs/42?seg=proposals"],
    ["tab=pipeline", { segment: "in-process" }, "/jobs/42"],
  ])("?%s → tabela ze stanem %o", async (search, expected, rewritten) => {
    renderPage(search);
    await screen.findByTestId("workspace");
    expect(seen.workspace).toMatchObject(expected);
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

  it("?tab=portals → okno „Zlecenie” na portalach; ?tab=questions → baza pytań; ?tab=manual-search → wyszukiwarka", async () => {
    const first = renderPage("tab=portals");
    await screen.findByTestId("order-window");
    expect(seen.order).toMatchObject({ open: true, initialSection: "portals" });
    first.unmount();
    const second = renderPage("tab=questions");
    expect(await screen.findByTestId("questions-window")).toBeInTheDocument();
    second.unmount();
    renderPage("tab=manual-search");
    expect(await screen.findByTestId("manual-window")).toBeInTheDocument();
  });

  it("miękka nawigacja na tej samej rekrutacji (klik w powiadomienie) też działa", async () => {
    const view = renderPage();
    await screen.findByTestId("workspace");
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
  it("otwiera osobę w tabeli po świeżej tablicy i zdejmuje parametr (z sekcją z ?tab=notes)", async () => {
    renderPage("tab=notes&candidate=77");
    await screen.findByTestId("workspace");
    await waitFor(() => expect(seen.workspace).toMatchObject({ activeCandidateId: 77, panelSection: "notes" }));
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
    await screen.findByTestId("workspace");
    await userEvent.click(screen.getByTestId("open-order"));
    expect(await screen.findByTestId("order-window")).toBeInTheDocument();
    expect(window.location.search).toBe("?win=order");
    act(() => (seen.order?.onOpenChange as (open: boolean) => void)(false));
    await waitFor(() => expect(window.location.search).toBe(""));
    await userEvent.click(screen.getByTestId("open-history-chat"));
    expect(seen.history).toMatchObject({ open: true, initialTab: "all", chatUnreadCount: 2 });
  });

  it("warsztat proszący o dawną zakładkę „questions” dostaje okno, nie zmianę widoku", async () => {
    renderPage();
    await screen.findByTestId("workspace");
    const ctx = seen.workspace?.workbenchContext as { onTabChange: (tab: string) => void };
    act(() => ctx.onTabChange("questions"));
    expect(await screen.findByTestId("questions-window")).toBeInTheDocument();
    expect(screen.getByTestId("workspace")).toBeInTheDocument();
  });

  it("„Otwórz pełne” w oknie Zlecenie prowadzi do widoku Championa", async () => {
    renderPage("win=order");
    await screen.findByTestId("order-window");
    act(() => (seen.order?.onNavigate as (target: string) => void)("champion"));
    expect(await screen.findByTestId("champion-editor")).toBeInTheDocument();
    expect(window.location.search).toContain("tab=champion");
  });
});

describe("strona rekrutacji — poprawki po integracji v3", () => {
  it("narzędzia AI administratora otwierają się z menu „…”, bez zaznaczonej propozycji", async () => {
    renderPage();
    await screen.findByTestId("workspace");
    expect(screen.queryByTestId("job-ai-actions")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Więcej akcji rekrutacji" }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /Narzędzia AI \(administrator\)/ }));
    const dialog = await screen.findByRole("dialog", { name: "Narzędzia AI (administrator)" });
    expect(dialog).toContainElement(screen.getByTestId("job-ai-actions"));
  });

  it("„Tabela” → „Tablica” otwiera dok osoby z panelu; powrót otwiera w panelu osobę z doku", async () => {
    renderPage();
    await screen.findByTestId("workspace");
    act(() => (seen.workspace?.onActiveCandidateChange as (id: number | null) => void)(7));
    await userEvent.click(screen.getByTestId("view-board"));
    await waitFor(() => expect(seen.kanban?.initialDockCandidateId).toBe(7));
    // Prośba jest jednorazowa — po obsłużeniu znika, jak `?candidate=`.
    act(() => (seen.kanban?.onInitialDockHandled as () => void)());
    await waitFor(() => expect(seen.kanban?.initialDockCandidateId).toBeNull());
    // Na tablicy użytkownik otworzył kogoś innego.
    act(() => (seen.kanban?.onDockCandidateChange as (id: number | null) => void)(9));
    await userEvent.click(screen.getByTestId("view-people"));
    await waitFor(() => expect(seen.workspace?.activeCandidateId).toBe(9));
  });

  it("zamknięty dok na „Tablicy” nie zamyka panelu po powrocie do „Tabeli”", async () => {
    renderPage();
    await screen.findByTestId("workspace");
    act(() => (seen.workspace?.onActiveCandidateChange as (id: number | null) => void)(7));
    await userEvent.click(screen.getByTestId("view-board"));
    await waitFor(() => expect(seen.kanban).not.toBeNull());
    act(() => (seen.kanban?.onDockCandidateChange as (id: number | null) => void)(null));
    await userEvent.click(screen.getByTestId("view-people"));
    await waitFor(() => expect(seen.workspace?.activeCandidateId).toBe(7));
  });

  it("podpowiedź „Obsada kompletna” otwiera okno „Zlecenie” na akcji zamknięcia", async () => {
    renderPage();
    await screen.findByTestId("workspace");
    const ctx = seen.workspace?.workbenchContext as { onRequestCloseJob: () => void };
    act(() => ctx.onRequestCloseJob());
    await waitFor(() => expect(seen.order).toMatchObject({ open: true, initialSection: "close" }));
    expect(window.location.search).toContain("win=order");
    expect(window.location.search).toContain("wintab=close");
  });

  it("na widoku „Zlecenie i Champion” przycisk „Zlecenie” otwiera okno jak na pozostałych widokach", async () => {
    renderPage("tab=champion");
    await screen.findByTestId("champion-editor");
    const button = screen.getByTestId("open-order");
    expect(button).not.toHaveAttribute("aria-current");
    await userEvent.click(button);
    await waitFor(() => expect(seen.order).toMatchObject({ open: true }));
    expect(window.location.search).toContain("win=order");
    // Widok pod oknem zostaje — okno nie przełącza strony.
    expect(screen.getByTestId("champion-editor")).toBeInTheDocument();
  });
});
