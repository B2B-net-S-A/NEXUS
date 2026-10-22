import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CaseCard, CaseDetail, CaseList } from "@/lib/api/admin-cases";
import type { CareContractCardSummary } from "@/lib/api/care";
import type { CareBoard, CareBoardCard } from "@/lib/api/care-board";
import type { HrConfig } from "@/lib/api/hr";

const mocks = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPatch: vi.fn(),
  apiPut: vi.fn(),
  push: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...args: unknown[]) => mocks.apiGet(...args),
    patch: (...args: unknown[]) => mocks.apiPatch(...args),
    put: (...args: unknown[]) => mocks.apiPut(...args),
  },
  default: { get: (...args: unknown[]) => mocks.apiGet(...args) },
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: mocks.toast }) }));

import { useAuthStore, type User } from "@/store/auth";

import { WorkBoard, type WorkBoardProps } from "../WorkBoard";

const TODAY = "2026-10-22";
const FRIDAY = "2026-10-23";

function caseCard(overrides: Partial<CaseCard>): CaseCard {
  return {
    id: 1,
    title: "Sprawa",
    area: "administration",
    priority: "P2",
    status: "new",
    due_on: null,
    follow_up_on: null,
    overdue: false,
    assignee: null,
    subject_user: null,
    contract: null,
    source: "manual",
    checklist_done: 0,
    checklist_total: 0,
    created_at: "2026-10-16T08:00:00Z",
    updated_at: "2026-10-16T08:00:00Z",
    closed_at: null,
    ...overrides,
  };
}

function careCard(overrides: Partial<CareBoardCard>): CareBoardCard {
  return {
    key: "contact:plan:1",
    kind: "contact",
    column: "new",
    title: "Rozmowa: Anna Przykładowa",
    subtitle: "Bank Przykładowy · menedżer: Jan Wzorcowy",
    reason_label: "Dzień 30",
    reason_kind: "day_30",
    due_on: "2026-10-20",
    overdue_days: 2,
    scheduled_at: null,
    retry_on: null,
    note_excerpt: "Chce więcej backendu.",
    note_on: "2026-09-26",
    contract_id: 10,
    candidate_id: 20,
    client_id: 30,
    client_name: "Bank Przykładowy",
    owner_user_id: 5,
    owner_name: "Natalia Opiekuńcza",
    health: { level: "risk", label: "Ryzyko", reasons: ["chce zmiany projektu (01.10)"] },
    ...overrides,
  };
}

function config(cases: boolean): HrConfig {
  const on = {
    people: true,
    leave: true,
    time: true,
    payroll: true,
    lifecycle: true,
    care: true,
    cases: true,
    equipment: true,
    settlements: false,
    approvals: false,
  };
  return {
    program: true,
    modules: on,
    open_modules: on,
    me: {
      has_profile: true,
      employment_status: "active",
      is_manager: false,
      direct_reports: 0,
      is_admin: false,
      people_admin: false,
      payroll: false,
      equipment: false,
      cases,
    },
  } as HrConfig;
}

function list(items: CaseCard[], extra: Partial<CaseList> = {}): CaseList {
  return {
    items,
    total: items.length,
    truncated: false,
    done_this_month: 4,
    counts: { areas: { administration: items.length }, week: 1, unassigned: 0, mine_care: 3 },
    today: TODAY,
    week_end: FRIDAY,
    can_manage: true,
    ...extra,
  };
}

function board(cards: CareBoardCard[]): CareBoard {
  return {
    today: TODAY,
    week_end: FRIDAY,
    cards,
    done: { this_week: 2, recent: [{ key: "contact:plan:99", kind: "contact", title: "Rozmowa: Paweł Makietowy", done_on: TODAY }] },
  };
}

interface Routes {
  cases?: CaseList | { error: number };
  board?: CareBoard;
  detail?: CaseDetail;
  summary?: CareContractCardSummary;
}

function route(routes: Routes) {
  mocks.apiGet.mockImplementation((url: string) => {
    if (url === "/api/cases") {
      const value = routes.cases ?? list([]);
      return "error" in value
        ? Promise.reject({ response: { status: value.error } })
        : Promise.resolve({ data: value });
    }
    if (url === "/api/care/board") return Promise.resolve({ data: routes.board ?? board([]) });
    if (/^\/api\/care\/contracts\/\d+\/card$/.test(url) && routes.summary) {
      return Promise.resolve({ data: routes.summary });
    }
    if (url.startsWith("/api/cases/") && routes.detail) return Promise.resolve({ data: routes.detail });
    return Promise.reject({ response: { status: 404 } });
  });
}

function renderBoard(props: Partial<WorkBoardProps> = {}, cfg: HrConfig = config(true)) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <WorkBoard scope="cases" config={cfg} {...props} />
    </QueryClientProvider>,
  );
}

function asUser(role: string, id = 5) {
  useAuthStore.setState({
    user: { id, name: "Natalia Opiekuńcza", role, roles: [role] } as unknown as User,
  });
}

beforeEach(() => {
  mocks.apiGet.mockReset();
  mocks.apiPatch.mockReset();
  mocks.apiPut.mockReset();
  mocks.push.mockReset();
  mocks.toast.mockReset();
  window.localStorage.clear();
  useAuthStore.setState({ user: null });
});

describe("tablica pracy — Ludzie → Sprawy z opieką", () => {
  it("opiekun widzi karty opieki obok spraw, zdrowie i „Moi podopieczni”", async () => {
    asUser("talent_community_manager");
    route({
      cases: list([
        caseCard({
          id: 1,
          title: "Negocjacje stawki: Karolina Przykładowa",
          contract: {
            id: 11,
            candidate_name: "Karolina Przykładowa",
            client_name: "Telekom Wzorcowy",
            start_date: null,
            end_date: null,
            care_owner_user_id: 5,
            care_owner_name: "Natalia Opiekuńcza",
            health: { level: "watch", label: "Uwaga", reasons: ["zaległa rozmowa"] },
          },
        }),
      ]),
      board: board([careCard({})]),
    });
    const user = userEvent.setup();
    renderBoard();

    const tile = await screen.findByRole("listitem", { name: "Rozmowa: Anna Przykładowa" });
    expect(within(tile).getByText("Opieka")).toBeInTheDocument();
    expect(within(tile).getByText("rozmowa · dzień 30")).toBeInTheDocument();
    expect(within(tile).getByText("2 dni po")).toBeInTheDocument();
    expect(within(tile).getByText("Ryzyko")).toBeInTheDocument();
    expect(within(tile).getByText("„Chce więcej backendu.” · 26.09")).toBeInTheDocument();
    // Bez okien opieki (Ludzie → Sprawy) akcja prowadzi do karty konsultanta w /care.
    expect(within(tile).getByRole("link", { name: /^Zapisz rozmowę/ })).toHaveAttribute(
      "href",
      "/care?contract=10",
    );
    const caseTile = screen.getByRole("listitem", { name: "Negocjacje stawki: Karolina Przykładowa" });
    // K1: „Telekom Wzorcowy · Uwaga · opiekun NO” i link do karty konsultanta.
    expect(within(caseTile).getByText("Uwaga")).toBeInTheDocument();
    expect(within(caseTile).getByText(/opiekun NO/)).toBeInTheDocument();
    expect(within(caseTile).getByRole("link", { name: /Karta konsultanta/ })).toHaveAttribute(
      "href",
      "/care?contract=11",
    );
    expect(screen.getByRole("button", { name: "Opieka 1" })).toBeInTheDocument();
    // „Zrobione”: jedna liczba (4 sprawy z miesiąca + 2 z opieki z tygodnia).
    expect(screen.getByText("4 sprawy w miesiącu · 2 rozmowy i opinie w tym tygodniu")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Bez osoby/ })).toBeInTheDocument();

    // 3 sprawy moich konsultantów (serwer) + moja karta opieki.
    await user.click(screen.getByRole("button", { name: "Moi podopieczni 4" }));
    await waitFor(() =>
      expect(mocks.apiGet).toHaveBeenCalledWith("/api/cases", {
        params: { mine_care: "true" },
      }),
    );
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/care/board", { params: { scope: "mine" } });
  });

  it("osoba bez dostępu do opieki nie pyta o tablicę opieki i nie widzi obszaru „Opieka”", async () => {
    asUser("user", 77);
    route({ cases: list([caseCard({ id: 2, title: "Faktura za szkolenie" })]) });
    renderBoard();

    expect(await screen.findByText("Faktura za szkolenie")).toBeInTheDocument();
    expect(mocks.apiGet).not.toHaveBeenCalledWith("/api/care/board", expect.anything());
    expect(screen.queryByRole("button", { name: /^Opieka/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Moi podopieczni/ })).toBeNull();
  });

  it("chip „Opieka” zostawia same karty opieki", async () => {
    asUser("delivery_lead");
    route({
      cases: list([caseCard({ id: 3, title: "Post na LinkedIn" })]),
      board: board([careCard({})]),
    });
    const user = userEvent.setup();
    renderBoard();

    await screen.findByText("Post na LinkedIn");
    await user.click(screen.getByRole("button", { name: "Opieka 1" }));
    expect(screen.queryByText("Post na LinkedIn")).toBeNull();
    expect(screen.getByText("Rozmowa: Anna Przykładowa")).toBeInTheDocument();
  });

  it("„Przenieś do…” zmienia status sprawy z wersją karty; 409 mówi, że ktoś zmienił sprawę", async () => {
    asUser("user", 77);
    route({ cases: list([caseCard({ id: 4, title: "Ubezpieczenie OC", updated_at: "2026-10-21T10:00:00Z" })]) });
    mocks.apiPatch.mockRejectedValue({ response: { status: 409 } });
    const user = userEvent.setup();
    renderBoard();

    await screen.findByText("Ubezpieczenie OC");
    await user.click(screen.getByRole("button", { name: "Przenieś do…: Ubezpieczenie OC" }));
    await user.click(await screen.findByRole("menuitem", { name: "Czeka na kogoś" }));
    await waitFor(() =>
      expect(mocks.apiPatch).toHaveBeenCalledWith("/api/cases/4", {
        status: "waiting",
        expected_updated_at: "2026-10-21T10:00:00Z",
      }),
    );
    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith(
        "Ktoś zmienił tę sprawę w międzyczasie — odśwież i spróbuj jeszcze raz.",
        "error",
      ),
    );
  });

  it("osoba przypisana bez uprawnienia nie przesuwa spraw (bez menu)", async () => {
    asUser("user", 77);
    route({ cases: list([caseCard({ id: 5, title: "Moja sprawa" })], { can_manage: false }) });
    renderBoard({}, config(false));

    await screen.findByText("Moja sprawa");
    expect(screen.queryByRole("button", { name: /^Przenieś do…/ })).toBeNull();
  });
});

describe("tablica pracy — Opieka → Do zrobienia", () => {
  it("brak dostępu do spraw (403) nie zasłania kart opieki; akcja otwiera okno rozmowy", async () => {
    asUser("talent_community_manager");
    route({ cases: { error: 403 }, board: board([careCard({})]) });
    const onOpenConversation = vi.fn();
    const user = userEvent.setup();
    renderBoard({ scope: "care", onOpenConversation }, config(false));

    const tile = await screen.findByRole("listitem", { name: "Rozmowa: Anna Przykładowa" });
    expect(
      screen.queryByText("Sprawy widzą osoby z uprawnieniem „Sprawy” i osoby przypisane do sprawy."),
    ).toBeNull();
    await user.click(within(tile).getByRole("button", { name: /^Zapisz rozmowę/ }));
    expect(onOpenConversation).toHaveBeenCalledWith(10, 1);
  });

  it("link z dzwonka przy otwartej tablicy (nowy `initialSelectedKey`) otwiera panel; zamknięcie zdejmuje kartę z adresu", async () => {
    asUser("talent_community_manager");
    route({
      cases: { error: 403 },
      board: board([careCard({}), careCard({ key: "contact:plan:2", title: "Rozmowa: Beata Wzorcowa" })]),
    });
    const onCloseSelected = vi.fn();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const view = (key: string | null) => (
      <QueryClientProvider client={queryClient}>
        <WorkBoard scope="care" config={config(false)} initialSelectedKey={key} onCloseSelected={onCloseSelected} />
      </QueryClientProvider>
    );
    const { rerender } = render(view(null));
    await screen.findByRole("listitem", { name: "Rozmowa: Beata Wzorcowa" });
    expect(screen.queryByRole("dialog")).toBeNull();

    rerender(view("contact:plan:2"));
    const panel = await screen.findByRole("dialog");
    expect(within(panel).getByText("Rozmowa: Beata Wzorcowa")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(onCloseSelected).toHaveBeenCalled();
  });

  it("„W toku” pyta o dzień i godzinę i zapisuje stan karty", async () => {
    asUser("talent_community_manager");
    route({ cases: { error: 403 }, board: board([careCard({})]) });
    mocks.apiPut.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderBoard({ scope: "care" }, config(false));

    await screen.findByText("Rozmowa: Anna Przykładowa");
    await user.click(screen.getByRole("button", { name: "Przenieś do…: Rozmowa: Anna Przykładowa" }));
    await user.click(await screen.findByRole("menuitem", { name: "W toku" }));
    expect(await screen.findByRole("dialog", { name: "Kiedy rozmowa?" })).toBeInTheDocument();
    const day = screen.getByLabelText(/^Dzień/);
    await user.clear(day);
    await user.type(day, "2026-10-23");
    await user.click(screen.getByRole("button", { name: "Umów" }));
    await waitFor(() =>
      expect(mocks.apiPut).toHaveBeenCalledWith("/api/care/board/state", {
        key: "contact:plan:1",
        column: "in_progress",
        scheduled_at: new Date("2026-10-23T10:00:00").toISOString(),
        note: null,
      }),
    );
  });

  it("upuszczenie rozmowy na „Zrobione” otwiera okno zapisu zamiast zmiany stanu", async () => {
    asUser("talent_community_manager");
    route({ cases: { error: 403 }, board: board([careCard({})]) });
    const onOpenConversation = vi.fn();
    const user = userEvent.setup();
    renderBoard({ scope: "care", onOpenConversation }, config(false));

    await screen.findByText("Rozmowa: Anna Przykładowa");
    await user.click(screen.getByRole("button", { name: "Przenieś do…: Rozmowa: Anna Przykładowa" }));
    await user.click(await screen.findByRole("menuitem", { name: "Zrobione" }));
    expect(onOpenConversation).toHaveBeenCalledWith(10, 1);
    expect(mocks.apiPut).not.toHaveBeenCalled();
  });

  it("Lista grupuje kolejkę i zapamiętuje wybór", async () => {
    asUser("talent_community_manager", 5);
    route({
      cases: { error: 403 },
      board: board([
        careCard({}),
        careCard({ key: "decision:4", kind: "decision", title: "Decyzja: Bartosz Testowy", due_on: null, overdue_days: 0 }),
      ]),
    });
    const user = userEvent.setup();
    renderBoard({ scope: "care" }, config(false));

    await screen.findByText("Rozmowa: Anna Przykładowa");
    await user.click(screen.getByRole("radio", { name: "Lista" }));
    expect(screen.getByRole("heading", { name: /^Po terminie/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /^Decyzje/ })).toBeInTheDocument();
    expect(window.localStorage.getItem("nexus:work-board:view:care:5")).toBe("list");
  });

  it("awaria tablicy opieki nie wygląda jak pusta tablica", async () => {
    asUser("talent_community_manager");
    mocks.apiGet.mockImplementation((url: string) =>
      url === "/api/cases"
        ? Promise.reject({ response: { status: 403 } })
        : Promise.reject({ response: { status: 500 } }),
    );
    renderBoard({ scope: "care" }, config(false));

    expect(await screen.findByText("Nie udało się wczytać tablicy opieki.")).toBeInTheDocument();
    expect(screen.queryByText(/Nic nie czeka/)).toBeNull();
  });
});

describe("panel boczny karty", () => {
  function detail(overrides: Partial<CaseDetail>): CaseDetail {
    return {
      ...caseCard({ id: 6, title: "Pytanie o fakturę" }),
      description: "Konsultant pyta o termin płatności.",
      checklist: [{ text: "Sprawdzić w księgowości", done: true }],
      lifecycle_case_id: null,
      created_by: null,
      messages: [],
      comments: [
        { id: 1, author: { id: 3, name: "Zofia Recepcyjna" }, body: "Czekam na księgowość.", created_at: "2026-10-21T09:00:00Z" },
      ],
      can_manage: true,
      can_comment: true,
      ...overrides,
    };
  }

  it("sprawa z konsultantem: skrót, „Konsultant” i „Przypisz opiekunowi”", async () => {
    asUser("delivery_lead", 9);
    const contract = {
      id: 11,
      candidate_name: "Karolina Przykładowa",
      client_name: "Telekom Wzorcowy",
      start_date: null,
      end_date: null,
      care_owner_user_id: 5,
      care_owner_name: "Natalia Opiekuńcza",
      health: null,
    };
    const card = caseCard({ id: 6, title: "Pytanie o fakturę", contract, updated_at: "2026-10-21T08:00:00Z" });
    route({
      cases: list([card]),
      board: board([]),
      detail: detail({
        contract,
        updated_at: "2026-10-21T08:00:00Z",
        consultant: {
          contract_id: 11,
          candidate_name: "Karolina Przykładowa",
          client_name: "Telekom Wzorcowy",
          role: "Java Developer",
          form: "B2B",
          order_end_on: "2026-12-31",
          owner_user_id: 5,
          owner_name: "Natalia Opiekuńcza",
          cadence_label: "co miesiąc",
          last_conversation: { on: "2026-10-01", excerpt: "Wszystko w porządku." },
          other_open_cases: 2,
          health: { level: "ok", label: "Dobrze", reasons: [] },
        },
      }),
    });
    mocks.apiPatch.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderBoard();

    await user.click(await screen.findByRole("button", { name: "Sprawa: Pytanie o fakturę" }));
    const panel = await screen.findByRole("dialog");
    expect(await within(panel).findByText("Czekam na księgowość.")).toBeInTheDocument();
    expect(within(panel).getByText("Sprawdzić w księgowości")).toBeInTheDocument();
    expect(within(panel).getByText(/rytm: co miesiąc/)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: /Otwórz kartę konsultanta/ })).toHaveAttribute(
      "href",
      "/care?contract=11",
    );
    expect(within(panel).getByRole("link", { name: /Pełny widok sprawy/ })).toHaveAttribute(
      "href",
      "/people/cases/6",
    );
    await user.click(within(panel).getByRole("button", { name: /Przypisz opiekunowi/ }));
    await waitFor(() =>
      expect(mocks.apiPatch).toHaveBeenCalledWith("/api/cases/6", {
        assignee_user_id: 5,
        expected_updated_at: "2026-10-21T08:00:00Z",
      }),
    );
  });

  it("sprawa bez kontraktu: „Kogo dotyczy?” wiąże dopiero po kliknięciu", async () => {
    asUser("user", 77);
    const card = caseCard({ id: 7, title: "Mail z firmy klienta", source: "mail" });
    route({
      cases: list([card]),
      detail: detail({
        ...card,
        link_suggestions: [
          { contract_id: 15, candidate_name: "Anna Kontraktorska", client_name: "Ubezpieczenia Fikcyjne", reason: "nadawca z firmy klienta" },
        ],
      }),
    });
    mocks.apiPatch.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderBoard();

    await user.click(await screen.findByRole("button", { name: "Sprawa: Mail z firmy klienta" }));
    const panel = await screen.findByRole("dialog");
    expect(await within(panel).findByText("Kogo dotyczy?")).toBeInTheDocument();
    expect(mocks.apiPatch).not.toHaveBeenCalled();
    await user.click(within(panel).getByRole("button", { name: /^Powiąż/ }));
    await waitFor(() =>
      expect(mocks.apiPatch).toHaveBeenCalledWith("/api/cases/7", {
        contract_id: 15,
        expected_updated_at: "2026-10-16T08:00:00Z",
      }),
    );
  });
});

describe("domknięcie makiet 22.10.2026", () => {
  it("„Moi podopieczni” bez uprawnienia „Sprawy” pyta o sprawy moich konsultantów, nie o moje", async () => {
    asUser("talent_community_manager");
    route({ cases: list([], { can_manage: false }), board: board([careCard({})]) });
    const user = userEvent.setup();
    renderBoard({}, config(false));

    await user.click(await screen.findByRole("button", { name: /^Moi podopieczni/ }));
    await waitFor(() =>
      expect(mocks.apiGet).toHaveBeenCalledWith("/api/cases", { params: { mine_care: "true" } }),
    );
  });

  it("w Opiece opiekun bez „Spraw” widzi sprawę tylko z terminem do piątku albo po terminie", async () => {
    asUser("talent_community_manager");
    route({
      cases: list(
        [
          caseCard({ id: 21, title: "Zaległa sprawa", due_on: "2026-10-19", overdue: true }),
          caseCard({ id: 22, title: "Sprawa na listopad", due_on: "2026-11-20" }),
        ],
        { can_manage: false },
      ),
      board: board([]),
    });
    renderBoard({ scope: "care" });

    expect(await screen.findByText("Zaległa sprawa")).toBeInTheDocument();
    expect(screen.queryByText("Sprawa na listopad")).toBeNull();
  });

  it("w Opiece obsługa skrzynki ma pełny kanban spraw (od #2567 Sprawy są tylko tu)", async () => {
    asUser("talent_community_manager");
    route({
      cases: list([
        caseCard({ id: 21, title: "Zaległa sprawa", due_on: "2026-10-19", overdue: true }),
        caseCard({ id: 22, title: "Sprawa na listopad", due_on: "2026-11-20" }),
      ]),
      board: board([]),
    });
    renderBoard({ scope: "care" });

    expect(await screen.findByText("Zaległa sprawa")).toBeInTheDocument();
    expect(screen.getByText("Sprawa na listopad")).toBeInTheDocument();
  });

  it("`?filter=rozmowy` na liście: chip aktywny, tylko rozmowy; postęp tygodnia", async () => {
    asUser("talent_community_manager", 5);
    route({
      cases: { error: 403 },
      board: {
        ...board([
          careCard({}),
          careCard({ key: "decision:4", kind: "decision", title: "Bartosz Testowy", due_on: null, overdue_days: 0 }),
        ]),
        week_progress: { done: 2, total: 6 },
      },
    });
    renderBoard({ scope: "care", initialView: "list", initialFilter: "contact" }, config(false));

    expect(await screen.findByRole("button", { name: "Rozmowy 1" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Wszystko 2" })).toBeInTheDocument();
    expect(screen.queryByText("Bartosz Testowy")).toBeNull();
    expect(screen.getByText(/Ten tydzień:/).textContent).toBe("Ten tydzień: 2 z 6 zapisane");
  });

  it("klik w osobę na liście otwiera kartę konsultanta, klient prowadzi do „Ludzie i technologie”", async () => {
    asUser("talent_community_manager", 5);
    route({ cases: { error: 403 }, board: board([careCard({ title: "Anna Przykładowa" })]) });
    const onOpenContract = vi.fn();
    const user = userEvent.setup();
    renderBoard({ scope: "care", initialView: "list", onOpenContract }, config(false));

    await user.click(await screen.findByRole("button", { name: "Karta konsultanta: Anna Przykładowa" }));
    expect(onOpenContract).toHaveBeenCalledWith(10);
    expect(screen.getByRole("link", { name: "Bank Przykładowy" })).toHaveAttribute("href", "/clients/30?tab=ludzie");
  });

  it("decyzja na „Zrobione”: wybór „Nie dotyczy” odrzuca wpis „Do przepięcia”", async () => {
    asUser("talent_community_manager");
    route({
      cases: { error: 403 },
      board: board([careCard({ key: "decision:4", kind: "decision", title: "Bartosz Testowy", due_on: null, overdue_days: 0 })]),
    });
    mocks.apiPatch.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderBoard({ scope: "care" }, config(false));

    await user.click(await screen.findByRole("button", { name: "Przenieś do…: Decyzja: Bartosz Testowy" }));
    await user.click(await screen.findByRole("menuitem", { name: "Zrobione" }));
    const dialog = await screen.findByRole("dialog", { name: "Jak zamknąć decyzję?" });
    await user.click(within(dialog).getByRole("button", { name: /Nie dotyczy/ }));
    await waitFor(() =>
      expect(mocks.apiPatch).toHaveBeenCalledWith("/api/care/redeploy/4", { status: "dismissed" }),
    );
  });

  it("decyzja z samego końca zamówienia: najpierw wpis (PUT), potem „Przekazana”", async () => {
    asUser("talent_community_manager");
    route({
      cases: { error: 403 },
      board: board([
        careCard({ key: "decision:end:10", kind: "decision", title: "Bartosz Testowy", due_on: "2026-11-30", overdue_days: 0 }),
      ]),
    });
    mocks.apiPut.mockResolvedValue({ data: { key: "decision:77", column: "in_progress" } });
    mocks.apiPatch.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderBoard({ scope: "care" }, config(false));

    await user.click(await screen.findByRole("button", { name: "Przenieś do…: Decyzja: Bartosz Testowy" }));
    await user.click(await screen.findByRole("menuitem", { name: "Zrobione" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: /Przekazana/ }));
    await waitFor(() =>
      expect(mocks.apiPatch).toHaveBeenCalledWith("/api/care/redeploy/77", { status: "done" }),
    );
    expect(mocks.apiPut).toHaveBeenCalledWith("/api/care/board/state", {
      key: "decision:end:10",
      column: "in_progress",
    });
  });

  it("decyzja „Czeka” zapisuje się bez pytania o datę (czeka na front office)", async () => {
    asUser("talent_community_manager");
    route({
      cases: { error: 403 },
      board: board([careCard({ key: "decision:4", kind: "decision", title: "Bartosz Testowy", due_on: null, overdue_days: 0 })]),
    });
    mocks.apiPut.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderBoard({ scope: "care" }, config(false));

    await user.click(await screen.findByRole("button", { name: "Przenieś do…: Decyzja: Bartosz Testowy" }));
    await user.click(await screen.findByRole("menuitem", { name: "Czeka na kogoś" }));
    await waitFor(() =>
      expect(mocks.apiPut).toHaveBeenCalledWith("/api/care/board/state", { key: "decision:4", column: "waiting" }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("panel karty rozmowy (K2): przeniesienie z podpowiedzią, skrót osoby, jej sprawy otwierają ten sam panel", async () => {
    asUser("talent_community_manager");
    const summary: CareContractCardSummary = {
      contract_id: 10,
      candidate_id: 20,
      candidate_name: "Anna Przykładowa",
      client_id: 30,
      client_name: "Bank Przykładowy",
      role: "QA",
      form: "B2B",
      start_on: "2026-01-01",
      end_on: null,
      owner: { user_id: 5, name: "Natalia Opiekuńcza", source: "contract" },
      cadence: { level: "biweekly", label: "co 2 tygodnie", until_on: null },
      health: null,
      kpis: {
        last_contact: { on: "2026-09-26", days_ago: 26 },
        satisfaction: { value: 5, previous: null },
        order_end: { on: "2026-11-15", days: 24 },
      },
      known_project: { manager: { contact_id: 3, name: "Katarzyna Kierownicza", position: null } },
      cases: [
        {
          id: 931,
          title: "Negocjacje stawki",
          area: "negotiation",
          area_label: "Negocjacje",
          status: "in_progress",
          status_label: "W toku",
          due_on: "2026-10-27",
          follow_up_on: null,
          assignee_name: "Natalia Opiekuńcza",
          source: "manual",
          content_hidden: true,
        },
      ],
    };
    route({
      cases: { error: 403 },
      board: board([careCard({ title: "Anna Przykładowa", role_label: "QA" })]),
      summary,
    });
    const user = userEvent.setup();
    renderBoard({ scope: "care", initialSelectedKey: "contact:plan:1" }, config(false));

    const panel = await screen.findByRole("dialog");
    expect(within(panel).getByText("Opieka · rozmowa · dzień 30 · 2 dni po terminie")).toBeInTheDocument();
    expect(within(panel).getByText("QA · Bank Przykładowy · opiekun Natalia O.")).toBeInTheDocument();
    const move = within(panel).getByRole("group", { name: "Przenieś na tablicy" });
    expect(within(move).getAllByRole("button").map((button) => button.textContent)).toEqual([
      "Nowado zrobienia",
      "W toku · Umówionapodaj dzień i godzinę",
      "Czeka · Nie odbieraspróbować ponownie dnia…",
    ]);
    expect(within(panel).queryByRole("button", { name: "Zrobione" })).toBeNull();
    expect(await within(panel).findByText("Konsultant w skrócie")).toBeInTheDocument();
    expect(within(panel).getByText("15.11 · za 24 dni")).toBeInTheDocument();
    expect(within(panel).getByText("Sprawy tej osoby · 1")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Pomiń z powodem" })).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Zmień rytm" })).toBeInTheDocument();

    await user.click(within(panel).getByRole("button", { name: "Sprawa: Negocjacje stawki" }));
    await waitFor(() => expect(mocks.apiGet).toHaveBeenCalledWith("/api/cases/931"));
    expect(await screen.findByRole("link", { name: /Pełny widok sprawy/ })).toHaveAttribute("href", "/people/cases/931");
  });
});

describe("tablica pracy — poprawki po audycie 22.10", () => {
  function summaryWith(cases: CareContractCardSummary["cases"]): CareContractCardSummary {
    return {
      contract_id: 10,
      candidate_id: 20,
      candidate_name: "Anna Przykładowa",
      client_id: 30,
      client_name: "Bank Przykładowy",
      role: "QA",
      form: "B2B",
      start_on: "2026-01-01",
      end_on: null,
      owner: { user_id: 5, name: "Natalia Opiekuńcza", source: "contract" },
      cadence: { level: "biweekly", label: "co 2 tygodnie", until_on: null },
      health: null,
      kpis: {
        last_contact: { on: "2026-09-26", days_ago: 26 },
        satisfaction: { value: 5, previous: null },
        order_end: { on: "2026-11-15", days: 24 },
      },
      known_project: { manager: { contact_id: 3, name: "Katarzyna Kierownicza", position: null } },
      cases,
    };
  }

  it("F6/F90: sprawa spoza listy otwarta z karty opieki przesuwa się z wersją ze szczegółu, nie z pustą", async () => {
    asUser("talent_community_manager");
    const detail: CaseDetail = {
      ...caseCard({ id: 932, title: "Laptop dla konsultanta", updated_at: "2026-10-20T10:00:00Z" }),
      description: null,
      checklist: [],
      lifecycle_case_id: null,
      created_by: null,
      messages: [],
      comments: [],
      can_manage: true,
      can_comment: true,
    } as CaseDetail;
    route({
      cases: list([]),
      board: board([careCard({ title: "Anna Przykładowa", role_label: "QA" })]),
      summary: summaryWith([
        {
          id: 932,
          title: "Laptop dla konsultanta",
          area: "administration",
          area_label: "Administracja",
          status: "new",
          status_label: "Nowa",
          due_on: null,
          follow_up_on: null,
          assignee_name: "Natalia Opiekuńcza",
          source: "manual",
          content_hidden: false,
        },
      ]),
      detail,
    });
    mocks.apiPatch.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderBoard({ scope: "care", initialSelectedKey: "contact:plan:1" });

    const panel = await screen.findByRole("dialog");
    await user.click(await within(panel).findByRole("button", { name: "Sprawa: Laptop dla konsultanta" }));
    const move = await screen.findByRole("group", { name: "Przenieś do" });
    await user.click(within(move).getByRole("button", { name: "W toku" }));
    await waitFor(() =>
      expect(mocks.apiPatch).toHaveBeenCalledWith("/api/cases/932", {
        status: "in_progress",
        expected_updated_at: "2026-10-20T10:00:00Z",
      }),
    );
  });
});
