import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const showSuccess = vi.fn();
const showError = vi.fn();
const showInfo = vi.fn();
const router = { replace: vi.fn(), push: vi.fn() };
/** Parametry widziane przez `useSearchParams`, gdy mają się różnić od adresu okna. */
let staleSearch: string | null = null;

vi.mock("@/lib/api", () => {
  const client = { get: (...a: unknown[]) => get(...a), post: vi.fn(), put: vi.fn() };
  return { __esModule: true, default: client, api: client };
});
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError, showInfo }),
}));
// Adres czytany z okna — po `replaceUrl` kolejny render widzi go już bez parametru.
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(staleSearch ?? window.location.search),
  usePathname: () => window.location.pathname,
  useRouter: () => router,
}));
// Przegląd ma własne testy (`DlReviewPanel.test`). Tu atrapa oddaje to, czym
// pas nim steruje: osobę, prawo wysyłki, licznik kolejki i wyjścia.
vi.mock("@/components/v2/recruitment/DlReviewPanel", () => ({
  DlReviewPanel: ({
    task,
    open,
    onOpenChange,
    canSendToClient,
    onDecided,
    sequence,
  }: {
    task: { candidate_name: string } | null;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    canSendToClient?: boolean;
    onDecided?: (action: string, task: { candidate_name: string }) => void;
    sequence?: { position: number; total: number; onSkip: () => void; onFinish: () => void };
  }) =>
    open && task ? (
      <div role="dialog" aria-label="Przegląd DL">
        <p>
          {task.candidate_name} · wysyłka {canSendToClient ? "tak" : "nie"}
        </p>
        {sequence ? (
          <p data-testid="sequence">
            {sequence.position} z {sequence.total}
          </p>
        ) : null}
        {sequence ? (
          <button type="button" onClick={sequence.onSkip}>
            Pomiń
          </button>
        ) : null}
        {sequence ? (
          <button type="button" onClick={sequence.onFinish}>
            Zakończ kolejkę
          </button>
        ) : null}
        {/* Jak `DlReviewBody`: po decyzji `onDecided` ZAMIAST zamknięcia. */}
        <button type="button" onClick={() => (onDecided ? onDecided("send", task) : onOpenChange(false))}>
          Decyzja
        </button>
        <button type="button" onClick={() => onOpenChange(false)}>
          Zamknij okno
        </button>
      </div>
    ) : null,
}));

import { DlSendQueueBand, showsDlSendBand } from "@/components/v2/dashboard/DlSendQueueBand";
import type { DashboardPanelKey } from "@/lib/dashboard-panels";
import { useAuthStore } from "@/store/auth";

// Dzień kalendarza w Warszawie N dni temu (10:00 UTC), a nie N × 24 h: w tygodniu
// po zmianie czasu (25.10.2026, doba 25 h) „24 h temu” o 23:30 to jeszcze ten sam
// dzień i „od wczoraj” zamieniało się w „od dziś”. Zero = teraz.
const calendarDaysAgo = (days: number): string => {
  if (days === 0) return new Date().toISOString();
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/Warsaw" }).format(new Date());
  const day = new Date(`${today}T10:00:00Z`);
  day.setUTCDate(day.getUTCDate() - days);
  return day.toISOString();
};
const daysAgo = calendarDaysAgo;

function row(over: Record<string, unknown> = {}) {
  return {
    kind: "dl_review",
    stage_id: 11,
    candidate_id: 21,
    candidate_name: "Anna Nowak",
    job_id: 31,
    job_title: "Java Developer",
    client_id: 5,
    client_name: "Bank Kappa",
    since: daysAgo(3),
    process_state_version: 4,
    target_stage_def_id: 303,
    assignee_id: null,
    assignee_name: null,
    qc_status: "passed",
    ready: true,
    ready_since: daysAgo(1),
    waiting_workdays: 1,
    urgency: "fresh",
    imported: false,
    ...over,
  };
}

/** Trzy gotowe osoby: najstarsza „Ola”, potem „Piotr”, najświeższa „Solo”. */
function threeReady() {
  return [
    row({ stage_id: 13, candidate_id: 23, job_id: 32, job_title: "QA", candidate_name: "Solo", ready_since: daysAgo(0) }),
    row({ stage_id: 11, candidate_name: "Ola Pierwsza", ready_since: daysAgo(6), urgency: "late" }),
    row({ stage_id: 12, candidate_id: 22, candidate_name: "Piotr Drugi", ready_since: daysAgo(2), urgency: "due" }),
  ];
}

function mockQueue(queue: Record<string, unknown>) {
  get.mockImplementation((url: string) => {
    if (url === "/api/board-tasks")
      return Promise.resolve({
        data: { window_days: 14, cpro_to_send: [], cpro_sent: [], can_send_to_client: true, ...queue },
      });
    return Promise.resolve({ data: [] });
  });
}

function renderBand(hiddenPanels?: ReadonlySet<DashboardPanelKey>) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={qc}>
      <DlSendQueueBand hiddenPanels={hiddenPanels} />
    </QueryClientProvider>,
  );
  return { ...view, qc };
}

const band = () => screen.findByRole("region", { name: "Do wysłania do klienta" });

describe("DlSendQueueBand — „Do wysłania do klienta” nad pulpitem", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    staleSearch = null;
    window.history.replaceState(null, "", "/dashboard");
    useAuthStore.setState({ user: { id: 1, role: "delivery_lead" }, realUser: null } as never);
  });

  it("osoba bez roli Delivery Leada: pasa nie ma i nie pyta o kolejkę", () => {
    useAuthStore.setState({ user: { id: 1, role: "recruiter" }, realUser: null } as never);
    mockQueue({ dl_review: [row()] });
    const { container } = renderBand();
    expect(container).toBeEmptyDOMElement();
    expect(get).not.toHaveBeenCalled();
    expect(showsDlSendBand({ role: "head_of_recruitment" }, new Set<DashboardPanelKey>())).toBe(false);
  });

  it("lista usunięta z pulpitu („Listy nad pulpitem”) → pasa nie ma", () => {
    // Listę może usunąć tylko Head of Recruitment albo admin — tu z rolą DL.
    const user = { id: 1, role: "head_of_recruitment" as const, roles: ["delivery_lead" as const] };
    useAuthStore.setState({ user, realUser: null } as never);
    mockQueue({ dl_review: [row()] });
    const hidden = new Set<DashboardPanelKey>(["dl_review"]);
    const { container } = renderBand(hidden);
    expect(container).toBeEmptyDOMElement();
    expect(showsDlSendBand(user, hidden)).toBe(false);
    expect(showsDlSendBand(user, new Set<DashboardPanelKey>(["cpro"]))).toBe(true);
  });

  it("pusta kolejka po udanym odczycie → jedno zdanie z kotwicą, bez ramki pasa", async () => {
    mockQueue({ dl_review: [] });
    renderBand();
    const line = await screen.findByRole("status");
    expect(line).toHaveTextContent("Nikt nie czeka teraz na wysyłkę do klienta.");
    expect(line).toHaveAttribute("id", "do-wyslania");
    expect(screen.queryByRole("region", { name: "Do wysłania do klienta" })).toBeNull();
  });

  it("awaria odczytu → pas milczy (komunikat z „Spróbuj ponownie” pokazuje panel pod spodem)", async () => {
    get.mockRejectedValue(new Error("boom"));
    const { container } = renderBand();
    await waitFor(() => expect(get).toHaveBeenCalledWith("/api/board-tasks"));
    // Ani pustego zdania, ani drugiego komunikatu o błędzie.
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it("trzy grupy z liczbami: gotowi w tabeli, „u rekrutera” i „z Traffita” zwinięte do linii", async () => {
    mockQueue({
      dl_review: [
        ...threeReady(),
        row({ stage_id: 14, candidate_id: 24, candidate_name: "Paweł Poprawka", ready: false, qc_status: "failed", qc_blocking_failed: 2 }),
        row({ stage_id: 15, candidate_id: 25, candidate_name: "Kasia Niesprawdzona", ready: false, qc_status: "unchecked" }),
        row({ stage_id: 16, candidate_id: 26, candidate_name: "Igor Zaimportowany", imported: true, since: daysAgo(40) }),
      ],
    });
    renderBand();
    const region = await band();
    expect(region).toHaveAttribute("id", "do-wyslania");
    expect(within(region).getByRole("heading", { level: 2 })).toHaveTextContent("Do wysłania do klienta");
    // Licznik = tylko gotowi; karty u rekrutera i z importu do niego nie wchodzą.
    expect(within(region).getByText("3 gotowe")).toBeTruthy();
    const ready = within(region).getByRole("table", { name: "Gotowi do wysłania do klienta" });
    // Najdłużej czekająca osoba pierwsza, niezależnie od kolejności z serwera.
    expect(within(ready).getAllByTestId("dl-send-row").map((r) => r.querySelector("button")?.textContent)).toEqual([
      "Ola Pierwsza",
      "Piotr Drugi",
      "Solo",
    ]);

    const notReady = within(region).getByRole("group", { name: "Jeszcze u rekrutera" });
    expect(notReady).toHaveTextContent("Jeszcze u rekrutera — CV do poprawy albo bez sprawdzenia QC: 2");
    expect(within(notReady).getByRole("button", { name: "Pokaż" })).toHaveAttribute("aria-expanded", "false");
    const imported = within(region).getByRole("group", { name: "Z Traffita" });
    expect(imported).toHaveTextContent("Z Traffita — nikt nie ruszył karty w NEXUSIE: 1");
    expect(screen.queryByText("Paweł Poprawka")).toBeNull();
    expect(screen.queryByText("Igor Zaimportowany")).toBeNull();

    await userEvent.click(within(notReady).getByRole("button", { name: "Pokaż" }));
    const rows = within(within(notReady).getByRole("table", { name: "Jeszcze u rekrutera" })).getAllByTestId("dl-send-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("QC: 2 do poprawy");
    expect(within(notReady).getByRole("button", { name: "Zwiń" })).toHaveAttribute("aria-expanded", "true");
    // Podgląd, nie „Przejrzyj i wyślij” — to jeszcze nie jest ruch Delivery Leada.
    await userEvent.click(within(rows[0]).getByRole("button", { name: "Podgląd: Paweł Poprawka" }));
    expect(screen.getByRole("dialog", { name: "Przegląd DL" })).toHaveTextContent("Paweł Poprawka");
    await userEvent.click(screen.getByRole("button", { name: "Zamknij okno" }));

    await userEvent.click(within(imported).getByRole("button", { name: "Pokaż" }));
    expect(within(imported).getByRole("button", { name: "Podgląd: Igor Zaimportowany" })).toHaveTextContent("Podgląd");
  });

  it("nagłówek: liczba gotowych w trzech formach, najdłużej czekająca osoba i spóźnione na czerwono", async () => {
    mockQueue({
      dl_review: [
        row({ stage_id: 11, candidate_name: "A", ready_since: daysAgo(6), urgency: "late" }),
        row({ stage_id: 12, candidate_id: 22, candidate_name: "B", ready_since: daysAgo(4), urgency: "late" }),
        row({ stage_id: 13, candidate_id: 23, candidate_name: "C", ready_since: daysAgo(1), urgency: "due" }),
        row({ stage_id: 14, candidate_id: 24, candidate_name: "D", ready_since: daysAgo(0) }),
        row({ stage_id: 15, candidate_id: 25, candidate_name: "E", ready_since: daysAgo(0) }),
      ],
    });
    renderBand();
    const region = await band();
    expect(within(region).getByText("5 gotowych")).toHaveClass("bg-primary");
    expect(region).toHaveTextContent("najdłużej czeka od 6 dni · 2 osoby 2+ dni robocze");
    expect(within(region).getByText(/2 osoby 2\+ dni robocze/)).toHaveClass("text-destructive");
    expect(within(region).getByRole("button", { name: "Przejrzyj po kolei (5)" })).toBeTruthy();
  });

  it("jedna gotowa osoba: „1 gotowa”, bez „po kolei” i bez wzmianki o spóźnieniu", async () => {
    mockQueue({ dl_review: [row({ ready_since: daysAgo(1) })] });
    renderBand();
    const region = await band();
    expect(within(region).getByText("1 gotowa")).toBeTruthy();
    expect(region).toHaveTextContent("najdłużej czeka od wczoraj");
    expect(region).not.toHaveTextContent("dni robocze");
    expect(within(region).queryByRole("button", { name: /Przejrzyj po kolei/ })).toBeNull();
  });

  it("Nordea (14.10.2026): wiersz akceptacji do Cpro ma plakietkę „do Cpro” poza ucinaną linią i „Przejrzyj → Cpro”", async () => {
    mockQueue({
      dl_review: [
        row({ client_name: "Nordea Przykładowa", cpro: true, target_stage_def_id: 404 }),
        row({ stage_id: 12, candidate_id: 22, candidate_name: "Piotr Drugi" }),
      ],
    });
    renderBand();
    const region = await band();
    const [nordea, other] = ["Anna Nowak", "Piotr Drugi"].map(
      (name) => within(region).getAllByTestId("dl-send-row").find((tr) => tr.textContent?.includes(name))!,
    );
    // Linia rekrutacji ucina się wielokropkiem przy 1280 px — znacznik Cpro nie
    // może w niej stać, bo wtedy go nie widać (pomiar na `/preview/dl-send`).
    expect(within(nordea).getByText("Java Developer · Nordea Przykładowa")).toHaveClass("truncate");
    const badge = within(nordea).getByText("do Cpro");
    expect(badge.closest(".truncate")).toBeNull();
    expect(within(nordea).getByRole("button", { name: "Przejrzyj: Anna Nowak" })).toHaveTextContent(
      "Przejrzyj → Cpro",
    );

    expect(within(other).queryByText("do Cpro")).toBeNull();
    expect(within(other).getByRole("button", { name: "Przejrzyj: Piotr Drugi" })).toHaveTextContent(
      "Przejrzyj i wyślij",
    );
  });

  it("Nordea bez prawa wysyłki: zostaje sam „Przejrzyj”, plakietka „do Cpro” dalej stoi", async () => {
    mockQueue({
      can_send_to_client: false,
      dl_review: [row({ client_name: "Nordea Przykładowa", cpro: true, target_stage_def_id: 404 })],
    });
    renderBand();
    const region = await band();
    expect(within(region).getByRole("button", { name: "Przejrzyj: Anna Nowak" })).toHaveTextContent(/^Przejrzyj$/);
    expect(within(region).getByText("do Cpro")).toBeTruthy();
  });

  it("sami „u rekrutera”: „0 gotowych”, bez tabeli gotowych", async () => {
    mockQueue({ dl_review: [row({ ready: false, qc_status: "failed" })] });
    renderBand();
    const region = await band();
    expect(within(region).getByText("0 gotowych")).not.toHaveClass("bg-primary");
    expect(within(region).queryByRole("table")).toBeNull();
    expect(within(region).getByRole("group", { name: "Jeszcze u rekrutera" })).toBeTruthy();
  });

  it("wiersz: rekrutacja z terminem, kto przekazał, stawka wobec budżetu, QC i screening, czas w kolorze pilności", async () => {
    mockQueue({
      dl_review: [
        row({
          stage_id: 11,
          candidate_name: "Ola W Budżecie",
          job_working_title: "Java · Spring",
          deadline: "2026-10-24",
          handed_over_by_name: "Marek Dąb",
          expected_rate_value: 150,
          expected_rate_unit: "hourly",
          expected_rate_currency: "PLN",
          budget_max_hourly: 170,
          card_status: "partial",
          card_missing: 3,
          ready_since: daysAgo(6),
          urgency: "late",
        }),
        row({
          stage_id: 12,
          candidate_id: 22,
          job_id: 32,
          job_title: "Analityk",
          client_name: null,
          candidate_name: "Jan Ponad Budżet",
          expected_rate_value: 135,
          expected_rate_unit: "hourly",
          expected_rate_currency: "PLN",
          budget_min_hourly: 110,
          budget_max_hourly: 130,
          qc_status: "overridden",
          card_status: null,
          ready_since: daysAgo(2),
          urgency: "due",
        }),
        row({
          stage_id: 13,
          candidate_id: 23,
          job_id: 33,
          job_title: "Tester",
          candidate_name: "Ewa Dzienna",
          expected_rate_value: 1200,
          expected_rate_unit: "daily",
          expected_rate_currency: "PLN",
          budget_min_hourly: 110,
          budget_max_hourly: 130,
          ready_since: daysAgo(0),
        }),
        row({ stage_id: 14, candidate_id: 24, job_id: 34, job_title: "DevOps", candidate_name: "Bez Stawki", ready_since: daysAgo(0) }),
      ],
    });
    renderBand();
    const table = within(await band()).getByRole("table", { name: "Gotowi do wysłania do klienta" });
    expect(within(table).getAllByRole("columnheader").map((th) => th.textContent)).toEqual([
      "Osoba",
      "Rekrutacja",
      "Przekazał(a)",
      "Stawka kandydata",
      "CV i screening",
      "Czeka",
      "Akcje",
    ]);
    const [inBudget, over, daily, noRate] = within(table).getAllByTestId("dl-send-row");

    // Tytuł roboczy przed nazwą od klienta — jak na ekranach wewnętrznych.
    expect(within(inBudget).getByText("Java · Spring · Bank Kappa")).toBeTruthy();
    expect(inBudget).toHaveTextContent("termin 24.10");
    expect(inBudget).toHaveTextContent("Marek Dąb");
    expect(within(inBudget).getByText("150 zł/h")).toBeTruthy();
    expect(within(inBudget).getByText("budżet do 170 zł/h")).toHaveClass("text-muted-foreground");
    expect(within(inBudget).getByText("QC ✓")).toBeTruthy();
    expect(within(inBudget).getByText("Screening: brakuje 3")).toBeTruthy();
    expect(within(inBudget).getByText("od 6 dni")).toHaveClass("text-destructive", "font-semibold");

    expect(within(over).getByText("Analityk")).toBeTruthy();
    expect(over).not.toHaveTextContent("termin");
    expect(within(over).getByText("ponad budżet 110–130 zł/h")).toHaveClass("text-warning-muted-foreground");
    expect(within(over).getByText("Przepuszczone mimo QC")).toBeTruthy();
    expect(within(over).getByText("Screening: puste pola")).toBeTruthy();
    expect(within(over).getByText("od 2 dni")).toHaveClass("text-warning-muted-foreground", "font-semibold");

    // Stawka dzienna nie jest przeliczana na godzinę w wierszu listy — bez oceny.
    expect(within(daily).getByText(/zł\/MD$/)).toBeTruthy();
    expect(within(daily).getByText("budżet 110–130 zł/h")).toHaveClass("text-muted-foreground");
    expect(within(daily).getByText("od dziś")).toHaveClass("text-muted-foreground");

    // Brak stawki i brak przekazującego to dwie kreski, nie puste komórki.
    expect(within(noRate).getAllByText("—")).toHaveLength(2);
    expect(noRate).not.toHaveTextContent("budżet");
  });

  it("„Przejrzyj: …” otwiera przegląd z prawem wysyłki z serwera; po decyzji okno się zamyka", async () => {
    mockQueue({ can_send_to_client: true, dl_review: [row({ candidate_name: "Ola Przegląd" })] });
    renderBand();
    const region = await band();
    const action = within(region).getByRole("button", { name: "Przejrzyj: Ola Przegląd" });
    expect(action).toHaveTextContent("Przejrzyj i wyślij");
    await userEvent.click(action);
    const dialog = screen.getByRole("dialog", { name: "Przegląd DL" });
    expect(dialog).toHaveTextContent("Ola Przegląd · wysyłka tak");
    // Pojedynczy przegląd to nie kolejka — bez licznika.
    expect(within(dialog).queryByTestId("sequence")).toBeNull();
    await userEvent.click(within(dialog).getByRole("button", { name: "Decyzja" }));
    expect(screen.queryByRole("dialog", { name: "Przegląd DL" })).toBeNull();
    expect(showInfo).not.toHaveBeenCalled();

    // Nazwisko też otwiera przegląd.
    await userEvent.click(within(region).getByRole("button", { name: "Ola Przegląd" }));
    expect(screen.getByRole("dialog", { name: "Przegląd DL" })).toHaveTextContent("Ola Przegląd");
  });

  it("bez prawa wysyłki przycisk mówi „Przejrzyj”, a przegląd dostaje odmowę z serwera", async () => {
    mockQueue({ can_send_to_client: false, dl_review: [row({ candidate_name: "Ola Przegląd" })] });
    renderBand();
    const action = within(await band()).getByRole("button", { name: "Przejrzyj: Ola Przegląd" });
    expect(action).toHaveTextContent(/^Przejrzyj$/);
    await userEvent.click(action);
    expect(screen.getByRole("dialog", { name: "Przegląd DL" })).toHaveTextContent("Ola Przegląd · wysyłka nie");
  });

  it("D10: 2+ gotowe osoby z jednej rekrutacji — „porównaj” otwiera tabelę porównania", async () => {
    mockQueue({ dl_review: threeReady() });
    const base = get.getMockImplementation() as (url: string) => Promise<unknown>;
    get.mockImplementation((url: string) =>
      url === "/api/dl-review/jobs/31/queue"
        ? Promise.resolve({
            data: {
              job_id: 31,
              cpro_client: false,
              total: 1,
              limit: 50,
              items: [
                {
                  candidate_id: 21,
                  candidate_name: "Ola Pierwsza",
                  stage_id: 11,
                  since: daysAgo(6),
                  qc_status: "passed",
                  overall_fit: "fit",
                  overall_fit_label: "Pasuje",
                  requirements_met: 3,
                  requirements_total: 4,
                  candidate_rate: { amount: 140, unit: "hourly", currency: "PLN", hourly_pln: 140 },
                  start: "od zaraz",
                  risks: [{ code: "qc_failed", label: "CV nie przeszło QC", severity: "high" }],
                  fix_rounds: 1,
                  task: row({ candidate_name: "Ola Pierwsza" }),
                },
              ],
            },
          })
        : base(url),
    );
    renderBand();
    const region = await band();
    // Tylko rekrutacja z dwiema gotowymi osobami ma „porównaj” — w obu jej wierszach.
    const compare = within(region).getAllByRole("button", { name: /^porównaj/ });
    expect(compare).toHaveLength(2);
    expect(compare[0]).toHaveTextContent(/^porównaj$/);
    const [first, , solo] = within(region).getAllByTestId("dl-send-row");
    expect(first).toHaveTextContent("2 osoby · porównaj");
    expect(solo).not.toHaveTextContent("porównaj");

    await userEvent.click(compare[0]);
    const dialog = await screen.findByRole("dialog", { name: /Porównaj kandydatów — Java Developer/ });
    const table = await within(dialog).findByRole("table", { name: "Porównanie kandydatów w przeglądzie" });
    expect(within(table).getByText("3/4")).toBeTruthy();
    expect(within(table).getByText("140 zł/h")).toBeTruthy();
    await userEvent.click(within(table).getByRole("button", { name: "Przejrzyj: Ola Pierwsza" }));
    expect(await screen.findByRole("dialog", { name: "Przegląd DL" })).toHaveTextContent("Ola Pierwsza");
  });

  it("„Przejrzyj po kolei (N)”: pierwsza gotowa osoba „1 z N”, decyzja i „Pomiń” prowadzą dalej, na końcu komunikat", async () => {
    mockQueue({ dl_review: threeReady() });
    renderBand();
    await userEvent.click(within(await band()).getByRole("button", { name: "Przejrzyj po kolei (3)" }));
    const dialog = () => screen.getByRole("dialog", { name: "Przegląd DL" });
    expect(dialog()).toHaveTextContent("Ola Pierwsza");
    expect(within(dialog()).getByTestId("sequence")).toHaveTextContent("1 z 3");

    await userEvent.click(within(dialog()).getByRole("button", { name: "Decyzja" }));
    expect(dialog()).toHaveTextContent("Piotr Drugi");
    expect(within(dialog()).getByTestId("sequence")).toHaveTextContent("2 z 3");
    expect(showInfo).not.toHaveBeenCalled();

    await userEvent.click(within(dialog()).getByRole("button", { name: "Pomiń" }));
    expect(dialog()).toHaveTextContent("Solo");
    expect(within(dialog()).getByTestId("sequence")).toHaveTextContent("3 z 3");

    await userEvent.click(within(dialog()).getByRole("button", { name: "Decyzja" }));
    // Pominięta osoba dalej czeka — koniec kolejki nie mówi, że nikogo nie ma.
    await waitFor(() =>
      expect(showInfo).toHaveBeenCalledWith("Koniec kolejki — pominięte osoby dalej czekają: 1."),
    );
    expect(showInfo).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog", { name: "Przegląd DL" })).toBeNull();
  });

  it("po kolei bez pominięć: na końcu „nikt więcej nie czeka”", async () => {
    mockQueue({ dl_review: threeReady() });
    renderBand();
    await userEvent.click(within(await band()).getByRole("button", { name: "Przejrzyj po kolei (3)" }));
    const dialog = () => screen.getByRole("dialog", { name: "Przegląd DL" });
    await userEvent.click(within(dialog()).getByRole("button", { name: "Decyzja" }));
    await userEvent.click(within(dialog()).getByRole("button", { name: "Decyzja" }));
    await userEvent.click(within(dialog()).getByRole("button", { name: "Decyzja" }));
    await waitFor(() =>
      expect(showInfo).toHaveBeenCalledWith("Kolejka przejrzana — nikt więcej nie czeka na wysyłkę."),
    );
    expect(showInfo).toHaveBeenCalledTimes(1);
  });

  it("po kolei: zamknięcie okna i „Zakończ kolejkę” kończą przegląd bez komunikatu o końcu", async () => {
    mockQueue({ dl_review: threeReady() });
    renderBand();
    const region = await band();
    await userEvent.click(within(region).getByRole("button", { name: "Przejrzyj po kolei (3)" }));
    await userEvent.click(screen.getByRole("button", { name: "Zamknij okno" }));
    expect(screen.queryByRole("dialog", { name: "Przegląd DL" })).toBeNull();

    // Po zamknięciu kolejki zwykły przegląd znów jest pojedynczy.
    await userEvent.click(within(region).getByRole("button", { name: "Przejrzyj: Piotr Drugi" }));
    expect(screen.getByRole("dialog", { name: "Przegląd DL" })).toHaveTextContent("Piotr Drugi");
    expect(screen.queryByTestId("sequence")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Zamknij okno" }));

    await userEvent.click(within(region).getByRole("button", { name: "Przejrzyj po kolei (3)" }));
    await userEvent.click(screen.getByRole("button", { name: "Zakończ kolejkę" }));
    expect(screen.queryByRole("dialog", { name: "Przegląd DL" })).toBeNull();
    expect(showInfo).not.toHaveBeenCalled();
  });

  it("link z górnego paska `?wysylka=po-kolei` uruchamia przegląd po kolei raz i znika z adresu", async () => {
    window.history.replaceState(null, "", "/dashboard?wysylka=po-kolei&rb_prio=p1#do-wyslania");
    mockQueue({ dl_review: threeReady() });
    renderBand();
    const dialog = await screen.findByRole("dialog", { name: "Przegląd DL" });
    expect(dialog).toHaveTextContent("Ola Pierwsza");
    expect(within(dialog).getByTestId("sequence")).toHaveTextContent("1 z 3");
    // Pozostałe parametry i kotwica zostają; adres zmienia natywna historia, nie router.
    expect(`${window.location.pathname}${window.location.search}${window.location.hash}`).toBe(
      "/dashboard?rb_prio=p1#do-wyslania",
    );
    expect(router.replace).not.toHaveBeenCalled();

    // Dalsze kroki nie zaczynają kolejki od nowa.
    await userEvent.click(within(dialog).getByRole("button", { name: "Decyzja" }));
    expect(screen.getByTestId("sequence")).toHaveTextContent("2 z 3");
  });

  it("link z górnego paska: lista odświeżona po decyzji nie zaczyna kolejki od nowa, choć router jeszcze trzyma parametr", async () => {
    // Next przenosi adres do `useSearchParams` klatkę po zapisie w historii —
    // w tym oknie pas widzi jeszcze `?wysylka=po-kolei`.
    staleSearch = "?wysylka=po-kolei";
    window.history.replaceState(null, "", "/dashboard?wysylka=po-kolei");
    let sent = false;
    get.mockImplementation((url: string) =>
      Promise.resolve({
        data:
          url === "/api/board-tasks"
            ? {
                window_days: 14,
                cpro_to_send: [],
                cpro_sent: [],
                can_send_to_client: true,
                dl_review: sent ? threeReady().filter((r) => r.candidate_name !== "Ola Pierwsza") : threeReady(),
              }
            : [],
      }),
    );
    const { qc } = renderBand();
    const dialog = await screen.findByRole("dialog", { name: "Przegląd DL" });
    expect(within(dialog).getByTestId("sequence")).toHaveTextContent("1 z 3");
    expect(window.location.search).toBe("");

    sent = true;
    await userEvent.click(within(dialog).getByRole("button", { name: "Decyzja" }));
    await qc.invalidateQueries({ queryKey: ["board-tasks"] });
    await waitFor(() => expect(screen.getByText("2 gotowe")).toBeTruthy());
    // Migawka kolejki zostaje: druga osoba z trzech, nie „1 z 2”.
    expect(screen.getByRole("dialog", { name: "Przegląd DL" })).toHaveTextContent("Piotr Drugi");
    expect(screen.getByTestId("sequence")).toHaveTextContent("2 z 3");
  });

  it("link z górnego paska przy pustej kolejce: parametr znika, nic się nie otwiera i nie ma komunikatu", async () => {
    window.history.replaceState(null, "", "/dashboard?wysylka=po-kolei");
    mockQueue({ dl_review: [] });
    renderBand();
    expect(await screen.findByRole("status")).toHaveTextContent("Nikt nie czeka teraz na wysyłkę do klienta.");
    await waitFor(() => expect(window.location.search).toBe(""));
    expect(screen.queryByRole("dialog", { name: "Przegląd DL" })).toBeNull();
    expect(showInfo).not.toHaveBeenCalled();
  });

  it("więcej niż 8 gotowych osób: najpierw 8 i „Pokaż wszystkie (N)”", async () => {
    mockQueue({
      dl_review: Array.from({ length: 10 }, (_, i) =>
        row({ stage_id: 100 + i, candidate_id: 200 + i, job_id: 300 + i, candidate_name: `Osoba ${i + 1}` }),
      ),
    });
    renderBand();
    const region = await band();
    const table = within(region).getByRole("table", { name: "Gotowi do wysłania do klienta" });
    expect(within(table).getAllByTestId("dl-send-row")).toHaveLength(8);
    await userEvent.click(within(region).getByRole("button", { name: "Pokaż wszystkie (10)" }));
    expect(within(table).getAllByTestId("dl-send-row")).toHaveLength(10);
    expect(within(region).getByRole("button", { name: "Zwiń" })).toHaveAttribute("aria-expanded", "true");
    // „Po kolei” bierze wszystkich gotowych, nie tylko widocznych.
    expect(within(region).getByRole("button", { name: "Przejrzyj po kolei (10)" })).toBeTruthy();
  });
});
