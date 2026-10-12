/**
 * Strona `/jobs/new`: jeden ekran (10.10.2026) — klient, „Wypełnij z: Wklej
 * treść | Wgraj plik | Inna rekrutacja” i formularz w sześciu sekcjach, który
 * stoi na stronie od wejścia. Odczyt wypełnia tylko puste pola. Od 04.10.2026
 * jedno `POST /api/jobs` niesie całość (profil, hiring manager, przekazanie,
 * podobne, kategoria); odmowa serwera to lista braków, a praca w toku żyje na
 * koncie jako formularz.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  configure,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Każdy test to pełny formularz w jsdom i trzy zapytania czekające na chwilę
// ciszy w polach (kategoria, krytyczne, podobne rekrutacje). Na obciążonej
// maszynie domyślna sekunda oczekiwania i 5 s na test dawały fałszywą czerwień.
configure({ asyncUtilTimeout: 15_000 });
vi.setConfig({ testTimeout: 60_000 });

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
  handoff: vi.fn(),
  listJobs: vi.fn(),
  refreshClientHistory: vi.fn(),
  push: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
  searchParams: new URLSearchParams(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mocks.push }),
  useSearchParams: () => mocks.searchParams,
}));

vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
    put: (...a: unknown[]) => mocks.put(...a),
    delete: (...a: unknown[]) => mocks.del(...a),
  };
  return {
    default: client,
    // `similarJobsApi` (podobne rekrutacje) i edytor wymagań wołają nazwany eksport `api`.
    api: client,
    jobsApi: {
      handoff: (...a: unknown[]) => mocks.handoff(...a),
      // „Inna rekrutacja”: lista rekrutacji do wyboru szablonu.
      list: (...a: unknown[]) => mocks.listJobs(...a),
    },
    championApi: {
      refreshClientHistory: (...a: unknown[]) => mocks.refreshClientHistory(...a),
    },
  };
});

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: mocks.showSuccess,
    showError: mocks.showError,
  }),
}));

vi.mock("@/components/clients/ClientSinglePicker", () => ({
  ClientSinglePicker: ({
    onChange,
    disabled,
  }: {
    onChange: (c: unknown) => void;
    disabled?: boolean;
  }) => (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange({ id: 7, name: "Alior Bank" })}
    >
      wybierz klienta
    </button>
  ),
}));

vi.mock("@/components/v2/jobs/SimilarRequestsBanner", () => ({
  SimilarRequestsBanner: () => null,
}));

import { NewJobPage } from "@/components/v2/jobs/new/NewJobPage";
import { DEAL_BREAKER_REQUIRED_TEXT } from "@/components/v2/jobs/new/NewJobReviewForm";
import { CLIENT_REQUIRED_TEXT } from "@/components/v2/jobs/new/NewJobSourceBar";
import { BOARD_TASKS_QUERY_KEY } from "@/lib/api/boardTasks";
import { REQUEST_BOARD_QUERY_KEY } from "@/lib/api/requestAllocation";
import type { RequestIntakeResponse } from "@/lib/job-request-intake";

const REQUEST =
  "Szukamy Senior Java Developera. Java 17+, Spring Boot. Hybrydowo 2 dni w Warszawie. Do 170 zł/h netto.";

/** Odczyt v10: wymagania jako wiersze słów kluczowych, pytania z deal breakerem. */
const INTAKE: RequestIntakeResponse = {
  role_name: "Senior Java Developer",
  // Audyt 06.10.2026, P9: tytuł rekrutacji to wyłącznie nazwa od klienta.
  client_title: "Senior Java Developer",
  must: ["Java 17+", "Spring Boot"],
  nice: [],
  seniority_min_years: null,
  rate_budget_hourly: 170,
  rate_quote: "Do 170 zł/h netto",
  rate_note: null,
  remote_policy: "hybrid",
  onsite_days_per_week: 2,
  office_city: "Warszawa",
  start_date: null,
  project_about: "Migracja płatności.",
  responsibilities: null,
  screening_questions: [
    { question: "Kafka?", ideal_answer: "", deal_breaker: "Nie zna Kafki.", from_request: true },
    { question: "Biuro?", ideal_answer: "", deal_breaker: "Tylko zdalnie.", from_request: false },
  ],
  requirements: [
    { words: ["Java"], level: "must" },
    { words: ["Spring Boot", "Spring"], level: "must" },
    { words: ["Kubernetes"], level: "nice" },
  ],
  descriptive_requirements: ["Doświadczenie w bankowości"],
  evidence: ["Java 17+"],
  missing: [],
  // Hiring manager i termin to od 04.10.2026 wymagana decyzja — odczyt ma oba.
  hiring_manager_name: "Anna Nowak",
  hiring_manager_contact_id: 501,
  hiring_manager_contact_name: "Anna Nowak",
  deadline: "2026-10-20",
  deadline_time: null,
  headcount: 2,
  provenance: { deadline: "request", headcount: "request" },
};

/** Odczyt starszego serwera: must, nice, wiersze wyszukiwania, pytania bez deal breakera. */
const LEGACY_INTAKE: RequestIntakeResponse = {
  ...INTAKE,
  requirements: undefined,
  descriptive_requirements: undefined,
  screening_questions: [
    { question: "Kafka?", ideal_answer: "", from_request: true },
    { question: "Biuro?", ideal_answer: "", from_request: false },
  ],
  search_requirements: [["Java 17+"], ["Spring Boot"]],
};

const CATEGORIES = [
  { id: 1, slug: "infrastructure_operations", name: "Infra & Operations", participants: 7 },
  { id: 2, slug: "software_development", name: "Development", participants: 7 },
  { id: 4, slug: "security_quality", name: "QA", participants: 3 },
];

const RECRUITERS = [
  { id: 31, name: "Rekruterka Ola", role: "recruiter", roles: [] },
  { id: 32, name: "Rekruterka Iza", role: "recruiter", roles: [] },
];

interface ServerSetup {
  intake?: RequestIntakeResponse;
  /** Podpowiedzi podobnych rekrutacji. */
  suggestions?: unknown[];
  /** Wiersze, które serwer zna jako technologie ze słownika (po pierwszym słowie). */
  eligible?: string[];
  /** Podpowiedź krytycznych z historii. */
  suggested?: string[];
  category?: { suggested_id: number | null; categories: typeof CATEGORIES };
}

/** Odpowiedzi serwera na POST-y strony; reszta tras oddaje pusty obiekt. */
function serve({
  intake = INTAKE,
  suggestions = [],
  eligible = [],
  suggested = [],
  category = { suggested_id: 2, categories: CATEGORIES },
}: ServerSetup = {}) {
  mocks.post.mockImplementation((url: string, body?: unknown) => {
    switch (url) {
      case "/api/job-intake/read":
      case "/api/job-intake/read-file":
        return Promise.resolve({ data: { text: REQUEST, intake } });
      case "/api/job-intake/category-suggestion":
        return Promise.resolve({ data: category });
      case "/api/job-intake/critical-suggestion":
        return Promise.resolve({
          data: {
            labels: (body as { rows: string[][] }).rows.map((row) => row[0]),
            eligible,
            suggested,
            stats: {},
          },
        });
      case "/api/jobs":
        return Promise.resolve({ data: { id: 900 } });
      case "/api/job-intake/forms":
        return Promise.resolve({ data: { id: 55, updated_at: "2026-10-04T10:42:00Z" } });
      case "/api/job-similarity/preview":
        return Promise.resolve({ data: { suggestions } });
      case "/api/jobs/900/similar":
        return Promise.resolve({
          data: { reassigned_now: 0, linked_now: 1, linked: [], suggestions: [] },
        });
      default:
        return Promise.resolve({ data: {} });
    }
  });
}

/** Klient zapytań ostatnio wyrenderowanej strony — do sprawdzania unieważnień. */
let lastQueryClient: QueryClient | null = null;

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  lastQueryClient = client;
  vi.spyOn(client, "invalidateQueries");
  return render(
    <QueryClientProvider client={client}>
      <NewJobPage />
    </QueryClientProvider>,
  );
}

function invalidatedKeys(): unknown[] {
  return vi
    .mocked(lastQueryClient!.invalidateQueries)
    .mock.calls.map((call) => (call[0] as { queryKey: unknown[] })?.queryKey);
}

const postsTo = (url: string) => mocks.post.mock.calls.filter(([called]) => called === url);

const bodiesOf = (url: string) =>
  postsTo(url).map(([, body]) => body as Record<string, unknown>);

const jobPostBody = () => bodiesOf("/api/jobs")[0] as Record<string, unknown> | undefined;

const championBody = () =>
  jobPostBody()?.champion_profile as
    | {
        stack: { rows: { words: string[]; level: string }[]; critical: unknown; notes?: string };
        search: Record<string, unknown>;
        screening_questions: Record<string, string>[];
        project: Record<string, string>;
      }
    | undefined;

const SIMILAR = [
  {
    id: 4556,
    title: "Java Developer (zamknięta)",
    reference_number: "REK/4556",
    status: "closed",
    closed_at: "2026-05-01T00:00:00Z",
    client_name: "Alior Bank",
    similarity: 81,
    sent_count: 12,
    linked: false,
  },
  {
    id: 205137,
    title: "Senior Java — płatności",
    reference_number: null,
    status: "closed",
    closed_at: "2026-06-01T00:00:00Z",
    client_name: "Alior Bank",
    similarity: 74,
    sent_count: 29,
    linked: false,
  },
];

/** Akcja z paska „Wypełnij z:” nad formularzem. */
const sourceAction = (name: string) =>
  within(screen.getByRole("group", { name: "Wypełnij z:" })).getByRole("button", { name });

const pickClient = () => fireEvent.click(screen.getByRole("button", { name: "wybierz klienta" }));

const readButton = () => screen.getByRole("button", { name: "Odczytaj" });

/**
 * Wkleja treść w panelu „Wklej treść” i czyta ją. Formularz stoi na stronie od
 * wejścia, więc sygnałem końca odczytu jest zamknięcie panelu, nie pole „Rola”.
 */
async function pasteAndRead(text = REQUEST) {
  fireEvent.click(sourceAction("Wklej treść"));
  fireEvent.change(screen.getByLabelText("Treść requestu"), { target: { value: text } });
  fireEvent.click(readButton());
  await waitFor(() => expect(screen.queryByLabelText("Treść requestu")).toBeNull());
}

/** Wybiera plik w panelu „Wgraj plik” i czyta go. */
async function uploadAndRead(name = "request.docx") {
  fireEvent.click(sourceAction("Wgraj plik"));
  const file = new File(["treść requestu"], name, {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
  fireEvent.change(screen.getByLabelText(/Plik z requestem/), { target: { files: [file] } });
  fireEvent.click(readButton());
  await waitFor(() => expect(screen.queryByLabelText(/Plik z requestem/)).toBeNull());
  return file;
}

/** Odczyt wklejonej treści w nietkniętym formularzu — formularz bierze go w całości. */
async function readRequest(intake = INTAKE, setup: Omit<ServerSetup, "intake"> = {}) {
  serve({ intake, ...setup });
  renderPage();
  pickClient();
  await pasteAndRead();
}

const offerChips = () => screen.queryAllByTestId("intake-offer");

/**
 * Braki nie wyłączają przycisku (10.10.2026): kliknięcie pokazuje, czego
 * brakuje. O tym, że publikacja jeszcze nie przejdzie, mówi stopka i podpowiedź.
 */
function expectNotReady() {
  expect(screen.queryByText("Gotowa do publikacji")).toBeNull();
  expect(handoffButton()).toBeEnabled();
  expect(handoffButton()).toHaveAttribute("title", "Uzupełnij braki, żeby opublikować rekrutację");
}

/**
 * Kategorię serwer podpowiada po chwili ciszy w polu roli. Testy, które
 * czytają listę kategorii z ekranu, czekają na odpowiedź dla roli z odczytu —
 * do tego czasu lista potrafi jeszcze zniknąć na czas ponownego zapytania.
 */
async function categorySettled(role: string | null = INTAKE.role_name) {
  await waitFor(() =>
    expect(
      bodiesOf("/api/job-intake/category-suggestion").some((body) => body.role === role),
    ).toBe(true),
  );
  await screen.findByRole("radiogroup", { name: "Kategoria kompetencji" });
}

const handoffButton = () => screen.getByRole("button", { name: "Utwórz i opublikuj" });

/**
 * Potwierdza kategorię i czeka na skutek. Klik idzie w TEJ SAMEJ próbie,
 * w której przycisk jest widoczny: po zmianie roli podpowiedź wczytuje się
 * ponownie (600 ms ciszy) i przycisk na chwilę znika, a `findBy` / `waitFor`
 * oddają sterowanie dopiero po przerwie — na wolnym runnerze klik trafiał
 * wtedy w pustkę i formularz zostawał z „potwierdzeniem kategorii” w brakach
 * (kolejka merge'ów, 11.10.2026).
 */
async function confirmCategory(name: string | RegExp = "Development") {
  const button = typeof name === "string" ? `Potwierdzam: ${name}` : name;
  await waitFor(() => {
    if (screen.queryByText(/Kategoria potwierdzona/)) return;
    fireEvent.click(screen.getByRole("button", { name: button }));
    expect(screen.getByText(/Kategoria potwierdzona/)).toBeInTheDocument();
  });
}

async function pickRecruiter() {
  await screen.findByRole("option", { name: "Rekruterka Ola" });
  fireEvent.change(screen.getByLabelText("Wybierz rekrutera prowadzącego"), {
    target: { value: "31" },
  });
}

/** To, co po odczycie zostaje Delivery Leadowi: zatwierdzić pytania i potwierdzić kategorię. */
async function closeGaps() {
  fireEvent.click(screen.getByRole("button", { name: "Zatwierdź wszystkie" }));
  await confirmCategory();
}

async function handoffTo(target = "/jobs/900") {
  fireEvent.click(handoffButton());
  await waitFor(() => expect(mocks.push).toHaveBeenCalledWith(target));
}

const footerLink = (name: string) => screen.queryByRole("link", { name });

/**
 * Utworzenie z domknięciem braków, których dany test nie sprawdza: decyzje
 * „Klient nie podał”, zatwierdzenie pytań, potwierdzenie kategorii, rekruter.
 */
async function createJob() {
  if (footerLink("hiring manager (albo „Klient nie podał”)")) {
    fireEvent.click(
      within(screen.getByTestId("new-job-hiring-manager")).getByRole("checkbox", {
        name: "Klient nie podał",
      }),
    );
  }
  if (footerLink("termin (albo „Klient nie podał”)")) {
    fireEvent.click(
      within(screen.getByTestId("new-job-deadline")).getByRole("checkbox", {
        name: "Klient nie podał",
      }),
    );
  }
  const approve = screen.queryByRole("button", { name: "Zatwierdź wszystkie" });
  if (approve && !(approve as HTMLButtonElement).disabled) fireEvent.click(approve);
  await confirmCategory(/^Potwierdzam:/);
  if (screen.queryByLabelText("Wybierz rekrutera prowadzącego")) await pickRecruiter();
  // Przycisk jest aktywny także przy brakach — czekamy, aż formularz jest gotowy.
  await waitFor(() => {
    expect(screen.getByText("Gotowa do publikacji")).toBeInTheDocument();
    expect(handoffButton()).toBeEnabled();
  });
  await handoffTo();
}

function serveGets(extra: (url: string) => unknown = () => undefined) {
  mocks.get.mockImplementation((url: string) => {
    const data = extra(url);
    if (data instanceof Error) return Promise.reject(data);
    if (data !== undefined) return Promise.resolve({ data });
    return Promise.resolve({ data: url === "/api/users" ? RECRUITERS : {} });
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.searchParams = new URLSearchParams();
  mocks.refreshClientHistory.mockReturnValue(Promise.resolve({ data: {} }));
  serveGets();
  serve();
  mocks.put.mockReset().mockResolvedValue({ data: {} });
  mocks.handoff.mockResolvedValue({ data: {} });
  mocks.listJobs.mockResolvedValue({ data: { items: [], total: 0 } });
});

describe("NewJobPage — jeden ekran: klient i „Wypełnij z…”", () => {
  it("formularz stoi na stronie od wejścia; źródła to trzy akcje nad nim", () => {
    renderPage();
    expect(screen.getByLabelText("Rola")).toHaveValue("");
    for (const heading of ["1 · Nazwa", "3 · Warunki", "6 · Kategoria i zespół"]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    const actions = within(screen.getByRole("group", { name: "Wypełnij z:" })).getAllByRole(
      "button",
    );
    expect(actions.map((button) => button.textContent?.trim())).toEqual([
      "Wklej treść",
      "Wgraj plik",
      "Inna rekrutacja",
    ]);
    for (const button of actions) expect(button).toHaveAttribute("aria-pressed", "false");
    // Kroków, kafli i pustego miejsca po requeście już nie ma.
    expect(screen.queryByRole("list", { name: "Kroki" })).toBeNull();
    expect(screen.queryByRole("radiogroup", { name: "Skąd bierzemy dane?" })).toBeNull();
    expect(screen.queryByTestId("new-job-source-pane")).toBeNull();
    expect(screen.queryByText("Wypełniasz ręcznie — bez requestu.")).toBeNull();
    expect(screen.queryByLabelText("Treść requestu")).toBeNull();
    // Stopka z przyciskami też jest od razu.
    expect(handoffButton()).toBeInTheDocument();
  });

  it("pusta strona nie wysyła żadnego POST-a — także po samym wyborze klienta", async () => {
    renderPage();
    // Listy do sekcji 6 to odczyty; kategoria i krytyczne czekają na treść.
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 900));
    expect(mocks.post).not.toHaveBeenCalled();
    expect(
      screen.getByText(/Kategorie pojawią się, gdy zaczniesz wypełniać formularz/),
    ).toBeInTheDocument();

    // Sam klient to jeszcze nie praca: autozapis (3 s) nie zakłada formularza.
    pickClient();
    await new Promise((resolve) => setTimeout(resolve, 3_400));
    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.put).not.toHaveBeenCalled();
    expect(screen.queryByTestId("new-job-autosave")).toBeNull();
  });

  it("bez klienta akcja źródła pokazuje komunikat przy polu klienta i nie otwiera panelu", () => {
    renderPage();
    expect(screen.queryByRole("alert")).toBeNull();

    fireEvent.click(sourceAction("Wklej treść"));

    expect(screen.getByRole("alert")).toHaveTextContent(CLIENT_REQUIRED_TEXT);
    expect(screen.queryByLabelText("Treść requestu")).toBeNull();
    expect(postsTo("/api/job-intake/read")).toHaveLength(0);

    // Po wyborze klienta komunikat znika, a akcja otwiera panel.
    pickClient();
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(sourceAction("Wklej treść"));
    expect(sourceAction("Wklej treść")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Treść requestu")).toBeInTheDocument();
    // Druga akcja zamienia panel, to samo kliknięcie drugi raz go zamyka.
    fireEvent.click(sourceAction("Wgraj plik"));
    expect(screen.queryByLabelText("Treść requestu")).toBeNull();
    expect(screen.getByLabelText(/Plik z requestem/)).toBeInTheDocument();
    fireEvent.click(sourceAction("Wgraj plik"));
    expect(screen.queryByLabelText(/Plik z requestem/)).toBeNull();
  });

  it("za krótka treść: „Odczytaj” nieaktywne z podpowiedzią", () => {
    renderPage();
    pickClient();
    fireEvent.click(sourceAction("Wklej treść"));
    expect(readButton()).toBeDisabled();
    expect(
      screen.getByText("Wklej treść requestu (co najmniej 30 znaków)."),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Treść requestu"), { target: { value: REQUEST } });
    expect(readButton()).toBeEnabled();
  });

  it("ręcznie: formularz jest pusty i gotowy do wpisywania, bez wołania odczytu", () => {
    renderPage();
    pickClient();
    expect(screen.getByLabelText("Rola")).toHaveValue("");
    expect(postsTo("/api/job-intake/read")).toHaveLength(0);
    expect(postsTo("/api/job-intake/read-file")).toHaveLength(0);
    // Wszystko poza biurem (tryb nieznany) jest do uzupełnienia — od 06.10.2026
    // także liczba osób (N6: bez domyślnej „1”).
    expect(screen.getByText("Brakuje 10 rzeczy do publikacji")).toBeInTheDocument();
    // Zanim ktoś kliknie „Utwórz”, o brakach mówi pasek sekcji i stopka, nie pola.
    expect(screen.queryByText("Uzupełnij przed publikacją")).toBeNull();
  });

  it("ręcznie: dwa must-have z klawiatury to dwa wiersze, a frazę da się oznaczyć jako krytyczną", () => {
    renderPage();
    pickClient();

    const row = (n: number) => screen.getByLabelText(`Wymaganie ${n} — słowo albo wariant`);
    const type = (n: number, text: string) => {
      fireEvent.focus(row(n));
      fireEvent.change(row(n), { target: { value: text } });
      fireEvent.keyDown(row(n), { key: "Enter" });
    };
    type(1, "Java");
    // Zgłoszenie 09.10.2026: po Enterze kursor zostawał w tym samym wierszu
    // i drugie must-have stawało się wariantem „lub”.
    expect(row(2)).toHaveFocus();
    type(2, "bankowość");
    const level = (head: string, name: string) =>
      within(screen.getByRole("radiogroup", { name: `Poziom wymagania: ${head}` })).getByRole(
        "radio",
        { name },
      );
    expect(level("Java", "Musi mieć")).toBeChecked();
    // Fraza spoza technologii: decyduje Delivery Lead, przycisk nie czeka na serwer.
    expect(level("bankowość", "Krytyczne")).toBeEnabled();
    fireEvent.click(level("bankowość", "Krytyczne"));
    expect(level("bankowość", "Krytyczne")).toBeChecked();
    expect(
      screen.getByText(/Krytyczne: bankowość — propozycje AI ukrywają osoby/),
    ).toBeInTheDocument();
  });

  // D1 (10.10.2026): przecinek w pustym wierszu to kolejne wymaganie, nie wariant.
  it("ręcznie: must-have wpisane po przecinku to osobne wiersze, „A lub B” to jeden", () => {
    renderPage();
    pickClient();
    const row = (n: number) => screen.getByLabelText(`Wymaganie ${n} — słowo albo wariant`);
    const type = (n: number, text: string) => {
      fireEvent.focus(row(n));
      fireEvent.change(row(n), { target: { value: text } });
      fireEvent.keyDown(row(n), { key: "Enter" });
    };
    type(1, "Java, Spring Boot");
    type(3, "Kafka lub RabbitMQ");
    // Po wpisie kursor stoi w pustym wierszu na końcu — on wymaganiem nie jest.
    const groups = within(screen.getByRole("group", { name: "Wymagania — słowa kluczowe" }))
      .getAllByRole("radiogroup")
      .map((group) => group.getAttribute("aria-label"))
      .filter((label) => !/: wiersz \d+$/.test(label ?? ""));
    expect(groups).toEqual([
      "Poziom wymagania: Java",
      "Poziom wymagania: Spring Boot",
      "Poziom wymagania: Kafka",
    ]);
    expect(screen.getByText("RabbitMQ")).toBeInTheDocument();
  });

  it("„Wgraj plik” wysyła plik do odczytu razem z klientem", async () => {
    renderPage();
    pickClient();
    fireEvent.click(sourceAction("Wgraj plik"));
    expect(readButton()).toBeDisabled();
    expect(screen.getByText("Wybierz plik z requestem.")).toBeInTheDocument();
    fireEvent.click(sourceAction("Wgraj plik"));

    await uploadAndRead();

    expect(screen.getByLabelText("Rola")).toHaveValue("Senior Java Developer");
    const [[, body, config]] = postsTo("/api/job-intake/read-file");
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("client_id")).toBe("7");
    expect(((body as FormData).get("file") as File).name).toBe("request.docx");
    expect(config).toMatchObject({ timeout: 120_000 });
    expect(postsTo("/api/job-intake/read")).toHaveLength(0);
    // Treść odczytana z pliku stoi obok formularza, a pasek mówi, skąd są pola.
    expect(screen.getByTestId("new-job-source-pane")).toHaveTextContent("Java 17+");
    expect(screen.getByTestId("new-job-fill-summary")).toHaveTextContent(
      /^Z pliku request\.docx: wypełniono \d+ pól\./,
    );
  });

  it("po zamknięciu panelu źródła fokus wraca na jego przycisk", async () => {
    renderPage();
    pickClient();
    fireEvent.click(sourceAction("Wklej treść"));
    const close = screen.getByRole("button", { name: "Zamknij" });
    close.focus();
    fireEvent.click(close);
    await waitFor(() => expect(document.activeElement).toBe(sourceAction("Wklej treść")));
  });

  it("po odczycie fokus wraca na przycisk źródła, z którego czytano", async () => {
    renderPage();
    pickClient();
    fireEvent.click(sourceAction("Wklej treść"));
    fireEvent.change(screen.getByLabelText("Treść requestu"), { target: { value: REQUEST } });
    readButton().focus();
    fireEvent.click(readButton());
    await waitFor(() => expect(screen.queryByLabelText("Treść requestu")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(sourceAction("Wklej treść")));
  });

  it("w trakcie odczytu nie da się zmienić klienta ani utworzyć rekrutacji", async () => {
    serve();
    const base = mocks.post.getMockImplementation()!;
    let release: (value: unknown) => void = () => undefined;
    mocks.post.mockImplementation((url: string, body?: unknown) =>
      url === "/api/job-intake/read"
        ? new Promise((resolve) => {
            release = resolve;
          })
        : base(url, body),
    );
    renderPage();
    pickClient();
    fireEvent.click(sourceAction("Wklej treść"));
    fireEvent.change(screen.getByLabelText("Treść requestu"), { target: { value: REQUEST } });
    fireEvent.click(readButton());

    await waitFor(() => expect(handoffButton()).toBeDisabled());
    expect(screen.getByRole("button", { name: "Dokończę później" })).toBeDisabled();
    // Odczyt klienta A nie może wylądować w formularzu klienta B.
    expect(screen.getByRole("button", { name: "wybierz klienta" })).toBeDisabled();

    release({ data: { text: REQUEST, intake: INTAKE } });
    await waitFor(() => expect(screen.getByLabelText("Rola")).toHaveValue("Senior Java Developer"));
    expect(handoffButton()).toBeEnabled();
  });

  describe("plik Profilu Championa (D4)", () => {
    const EXTRAS = {
      search: { keywords: ["java developer bank"], notes: "Zacznij od byłych pracowników banków." },
      client: { consultant_insight: "Zespół ceni samodzielność.", sectors: ["bankowość"] },
      insights: [
        {
          id: "doc-1",
          source: "client",
          topic: "other",
          audience: "team",
          text: "Klient odrzuca osoby bez doświadczenia w regulacjach.",
          done: false,
          origin: "document",
        },
      ],
    };

    function serveChampionFile(extras: unknown = EXTRAS) {
      serve();
      const base = mocks.post.getMockImplementation()!;
      mocks.post.mockImplementation((url: string, body?: unknown) =>
        url === "/api/job-intake/read-file"
          ? Promise.resolve({
              data: {
                text: REQUEST,
                intake: { ...INTAKE, provenance: { role: "document", rate: "document" } },
                reader: "champion_form",
                champion_extras: extras,
              },
            })
          : base(url, body),
      );
    }

    it("pola dostają źródło „z dokumentu”, a pasek mówi, że plik przepisano bez AI", async () => {
      serveChampionFile();
      renderPage();
      pickClient();
      await uploadAndRead("profil.docx");

      expect(screen.getByLabelText("Rola")).toHaveValue("Senior Java Developer");
      expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue("170");
      expect(screen.getByTestId("champion-form-note")).toHaveTextContent(
        "To formularz Profilu Championa — przepisany bez AI.",
      );
      const chips = screen.getAllByTestId("provenance-chip").map((chip) => chip.textContent);
      expect(chips).toContain("z dokumentu");
      expect(chips).not.toContain("z maila");
    });

    it("sekcje pliku bez pola w formularzu idą do profilu w POST /api/jobs", async () => {
      serveChampionFile();
      renderPage();
      pickClient();
      await uploadAndRead("profil.docx");
      await createJob();

      const champion = championBody() as unknown as {
        search: Record<string, unknown>;
        client: Record<string, unknown>;
        insights: Record<string, unknown>[];
      };
      expect(champion.search).toMatchObject(EXTRAS.search);
      expect(champion.client).toMatchObject(EXTRAS.client);
      expect(champion.insights).toContainEqual(EXTRAS.insights[0]);
    });

    it("„Cofnij wypełnienie” zdejmuje też sekcje pliku", async () => {
      serveChampionFile();
      renderPage();
      pickClient();
      await uploadAndRead("profil.docx");
      fireEvent.click(screen.getByRole("button", { name: "Cofnij wypełnienie" }));

      expect(screen.getByLabelText("Rola")).toHaveValue("");
      expect(screen.queryByTestId("champion-form-note")).not.toBeInTheDocument();
    });

    it("drugi plik Championa nie obiecuje sekcji, których formularz nie wziął", async () => {
      serveChampionFile();
      renderPage();
      pickClient();
      await uploadAndRead("profil.docx");
      expect(screen.getByTestId("champion-form-note")).toHaveTextContent(
        "trafią do profilu rekrutacji",
      );

      await uploadAndRead("profil-2.docx");
      const note = screen.getByTestId("champion-form-note");
      expect(note).toHaveTextContent("przepisany bez AI");
      expect(note).toHaveTextContent("zostają z pierwszego pliku");
      expect(note).not.toHaveTextContent("trafią do profilu rekrutacji");
    });

    it("plik Championa bez dodatkowych sekcji mówi tylko, że przepisano go bez AI", async () => {
      serveChampionFile({ search: {}, client: {}, insights: [] });
      renderPage();
      pickClient();
      await uploadAndRead("profil.docx");
      const note = screen.getByTestId("champion-form-note");
      expect(note).toHaveTextContent("przepisany bez AI");
      expect(note).not.toHaveTextContent("trafią do profilu rekrutacji");
    });

    it("zwykły plik requestu nie dostaje notki ani sekcji Championa", async () => {
      renderPage();
      pickClient();
      await uploadAndRead();
      expect(screen.queryByTestId("champion-form-note")).not.toBeInTheDocument();
      await createJob();
      expect(
        (championBody() as unknown as { insights: { origin: string }[] }).insights.some(
          (note) => note.origin === "document",
        ),
      ).toBe(false);
    });
  });

  describe("pliki rekrutacji (0428)", () => {
    const FORM_FILES = "/api/job-intake/forms/55/files";

    async function readRequestFile() {
      renderPage();
      pickClient();
      return uploadAndRead();
    }

    it("plik requestu zapisuje się sam: najpierw formularz, potem plik jako „request”", async () => {
      const file = await readRequestFile();
      await waitFor(() => expect(postsTo(FORM_FILES)).toHaveLength(1));
      const [[, body]] = postsTo(FORM_FILES);
      expect(((body as FormData).get("file") as File).name).toBe(file.name);
      expect((body as FormData).get("source")).toBe("request");
      // Formularz powstał przed plikiem i ma już odczytane pola.
      const order = mocks.post.mock.calls.map(([url]) => url);
      expect(order.indexOf("/api/job-intake/forms")).toBeLessThan(order.indexOf(FORM_FILES));
      const [[, saved]] = postsTo("/api/job-intake/forms");
      expect((saved as { form: { step: string } }).form.step).toBe("review");
      expect((saved as { source: string }).source).toBe("file");
      expect(mocks.showError).not.toHaveBeenCalled();
    });

    it("jeden odczyt pliku to jeden zapis pliku — także po kolejnych zmianach i odczycie treści", async () => {
      await readRequestFile();
      await waitFor(() => expect(postsTo(FORM_FILES)).toHaveLength(1));
      // Zmiany w formularzu i odczyt wklejonej treści nie wysyłają pliku drugi raz.
      fireEvent.change(screen.getByLabelText("Rola"), { target: { value: "Java Developer" } });
      fireEvent.change(screen.getByLabelText("Budżet PLN/h"), { target: { value: "175" } });
      await pasteAndRead("Dodatkowa wiadomość od klienta: start najlepiej od listopada.");
      await new Promise((resolve) => setTimeout(resolve, 300));
      expect(postsTo(FORM_FILES)).toHaveLength(1);

      // Drugi plik to drugi odczyt — i drugi zapis, nie więcej.
      await uploadAndRead("aneks.docx");
      await waitFor(() => expect(postsTo(FORM_FILES)).toHaveLength(2));
      await new Promise((resolve) => setTimeout(resolve, 300));
      expect(postsTo(FORM_FILES)).toHaveLength(2);
      expect(
        postsTo(FORM_FILES).map(([, body]) => ((body as FormData).get("file") as File).name),
      ).toEqual(["request.docx", "aneks.docx"]);
    });

    it("nieudany zapis pliku requestu nie cofa odczytu — toast i formularz zostaje", async () => {
      serve();
      const base = mocks.post.getMockImplementation()!;
      mocks.post.mockImplementation((url: string, body?: unknown) =>
        url === FORM_FILES ? Promise.reject(new Error("413")) : base(url, body),
      );
      await readRequestFile();
      await waitFor(() =>
        expect(mocks.showError).toHaveBeenCalledWith(
          expect.stringContaining("Plik requestu nie zapisał się"),
        ),
      );
      expect(screen.getByLabelText("Rola")).toHaveValue("Senior Java Developer");
    });

    it("bez requestu karta „Pliki” stoi po sekcji 6 i przyjmuje załączniki", async () => {
      renderPage();
      pickClient();
      const card = screen.getByTestId("new-job-files-card");
      expect(within(card).getByTestId("job-files-empty")).toBeInTheDocument();
      // Po sekcji „Kategoria i zespół”, przed „Dodatkowe”.
      const team = screen.getByRole("heading", { name: "6 · Kategoria i zespół" });
      const extra = screen.getByTestId("new-job-additional");
      expect(team.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(card.compareDocumentPosition(extra) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(postsTo(FORM_FILES)).toHaveLength(0);

      const attachment = new File(["x"], "opis.pdf", { type: "application/pdf" });
      fireEvent.change(within(card).getByLabelText("Dodaj pliki do rekrutacji"), {
        target: { files: [attachment] },
      });
      await waitFor(() => expect(postsTo(FORM_FILES)).toHaveLength(1));
      const [[, body]] = postsTo(FORM_FILES);
      expect((body as FormData).get("source")).toBe("upload");
      // Rekrutacji jeszcze nie ma — plik wisi na formularzu, który zapisał się przed nim.
      expect(postsTo("/api/job-intake/forms")).toHaveLength(1);
      expect(postsTo("/api/jobs")).toHaveLength(0);
    });

    it("po odczycie karta „Pliki” stoi pod treścią requestu", async () => {
      await readRequestFile();
      const pane = screen.getByTestId("new-job-source-pane");
      expect(within(pane).getByTestId("new-job-files-card")).toBeInTheDocument();
      expect(screen.getAllByTestId("new-job-files-card")).toHaveLength(1);
    });
  });

  it("awaria odczytu AI zostawia treść w panelu, a formularz dalej da się wypełnić", async () => {
    mocks.post.mockRejectedValueOnce({
      response: {
        status: 503,
        data: { detail: "Model AI chwilowo niedostępny — spróbuj za chwilę." },
      },
    });
    renderPage();
    pickClient();
    fireEvent.click(sourceAction("Wklej treść"));
    fireEvent.change(screen.getByLabelText("Treść requestu"), {
      target: { value: REQUEST },
    });
    fireEvent.click(readButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Model AI chwilowo niedostępny",
    );
    expect(screen.getByLabelText("Treść requestu")).toHaveValue(REQUEST);
    // Formularz stoi obok — nic nie trzeba przełączać, żeby pisać ręcznie.
    fireEvent.change(screen.getByLabelText("Rola"), { target: { value: "Java Developer" } });
    expect(screen.getByLabelText("Rola")).toHaveValue("Java Developer");

    // Zamknięcie panelu zdejmuje błąd odczytu, a treść czeka na ponowną próbę.
    fireEvent.click(screen.getByRole("button", { name: "Zamknij" }));
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(sourceAction("Wklej treść"));
    expect(screen.getByLabelText("Treść requestu")).toHaveValue(REQUEST);
  });
});

describe("NewJobPage — odczyt wypełnia tylko puste pola", () => {
  /** Delivery Lead zaczął pisać ręcznie, a potem wkleił maila. */
  async function readIntoDirtyForm() {
    renderPage();
    pickClient();
    fireEvent.change(screen.getByLabelText("Rola"), { target: { value: "Java Developer" } });
    fireEvent.change(screen.getByLabelText("Budżet PLN/h"), { target: { value: "160" } });
    await pasteAndRead();
  }

  it("wpisane pola zostają, puste się wypełniają, a różnica to propozycja przy polu", async () => {
    await readIntoDirtyForm();

    expect(screen.getByLabelText("Rola")).toHaveValue("Java Developer");
    expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue("160");
    // Puste pola wzięły wartości z maila.
    expect(screen.getByLabelText("Co to za projekt")).toHaveValue("Migracja płatności.");
    expect(screen.getByLabelText("Liczba osób")).toHaveValue(2);
    expect(screen.getByLabelText("Treść pytania 1")).toHaveValue("Kafka?");

    expect(offerChips().map((chip) => chip.textContent)).toEqual([
      expect.stringContaining("W mailu: Senior Java Developer"),
      expect.stringContaining("W mailu: 170 PLN/h"),
    ]);
    expect(screen.getByTestId("new-job-fill-summary")).toHaveTextContent(
      /^Z wklejonej treści: wypełniono \d+ pól · 2 propozycje czekają na „Użyj”\./,
    );
    // Brak z odczytu nazywa się jak dotąd.
    expect(screen.queryByText("Uzupełnij przed publikacją")).toBeNull();
  });

  it("„Użyj” bierze wartość z maila, „Zostaw” zostawia wpisaną", async () => {
    await readIntoDirtyForm();

    fireEvent.click(screen.getByRole("button", { name: "Użyj — Rola" }));
    expect(screen.getByLabelText("Rola")).toHaveValue("Senior Java Developer");
    expect(offerChips()).toHaveLength(1);

    fireEvent.click(screen.getByRole("button", { name: "Zostaw — Budżet PLN/h" }));
    expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue("160");
    expect(offerChips()).toHaveLength(0);
    // Pasek zostaje dla „Cofnij wypełnienie”, ale o propozycjach już nie mówi.
    expect(screen.getByTestId("new-job-fill-summary")).not.toHaveTextContent("propozycj");
  });

  // Przegląd kodu 11.10.2026: kliknięty przycisk znika z ekranu, więc bez
  // przeniesienia fokusu klawiatura wracała na początek strony.
  it("fokus po „Użyj” i „Zostaw” trafia do pola, którego dotyczyła propozycja", async () => {
    await readIntoDirtyForm();

    const use = screen.getByRole("button", { name: "Użyj — Rola" });
    use.focus();
    fireEvent.click(use);
    expect(document.activeElement).toBe(screen.getByLabelText("Rola"));

    // Budżet ma dwa pola („od” i „do”) — fokus trafia w pierwsze z nich.
    const keep = screen.getByRole("button", { name: "Zostaw — Budżet PLN/h" });
    keep.focus();
    fireEvent.click(keep);
    expect(document.activeElement).toBe(screen.getByLabelText("Budżet PLN/h od (opcjonalnie)"));
  });

  it("fokus po „Cofnij wypełnienie” zostaje na pasku źródeł, nie spada na początek strony", async () => {
    await readIntoDirtyForm();
    const undo = screen.getByRole("button", { name: "Cofnij wypełnienie" });
    undo.focus();
    fireEvent.click(undo);
    expect(document.activeElement).toBe(
      screen.getByRole("region", { name: "Klient i źródło danych" }),
    );
  });

  it("propozycja znika sama, gdy ktoś wpisze tę samą wartość", async () => {
    await readIntoDirtyForm();
    fireEvent.change(screen.getByLabelText("Budżet PLN/h"), { target: { value: "170" } });
    expect(offerChips().map((chip) => chip.getAttribute("data-unit"))).toEqual(["title"]);
  });

  it("propozycje jadą w zapisie formularza i wracają po „Dokończ”", async () => {
    await readIntoDirtyForm();
    fireEvent.click(screen.getByRole("button", { name: "Dokończę później" }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs"));
    const saved = bodiesOf("/api/job-intake/forms").at(-1) as unknown as {
      request_text: string;
      form: { step: string; requestRead: boolean; offers: { unit: string; source: string }[] };
    };
    expect(saved.request_text).toBe(REQUEST);
    expect(saved.form).toMatchObject({ step: "review", requestRead: true });
    expect(saved.form.offers.map((offer) => [offer.unit, offer.source])).toEqual([
      ["title", "request"],
      ["budget", "request"],
    ]);

    // Ten sam zapis wczytany na nowej stronie: propozycje stoją przy polach.
    cleanup();
    serveGets((url) =>
      url === "/api/job-intake/forms/55"
        ? {
            id: 55,
            label: "x",
            client_id: 7,
            client_name: "Alior Bank",
            source: "text",
            request_text: saved.request_text,
            updated_at: "2026-10-10T10:00:00Z",
            form: saved.form,
          }
        : undefined,
    );
    mocks.searchParams = new URLSearchParams("form=55");
    renderPage();
    await waitFor(() => expect(offerChips()).toHaveLength(2));
    expect(screen.getByLabelText("Rola")).toHaveValue("Java Developer");
    // Cofnięcie dotyczy wypełnienia z tej samej sesji — po wczytaniu go nie ma.
    expect(screen.queryByRole("button", { name: "Cofnij wypełnienie" })).toBeNull();
    expect(screen.getByTestId("new-job-fill-summary")).toHaveTextContent(
      "2 propozycje czekają na „Użyj”",
    );
  });

  it("„Cofnij wypełnienie” zdejmuje odczyt, a późniejsze poprawki zostają", async () => {
    await readIntoDirtyForm();
    expect(screen.getByTestId("new-job-source-pane")).toBeInTheDocument();
    // Poprawka po odczycie.
    fireEvent.change(screen.getByLabelText("Co to za projekt"), {
      target: { value: "Poprawiony opis." },
    });

    fireEvent.click(screen.getByRole("button", { name: "Cofnij wypełnienie" }));

    expect(screen.getByLabelText("Rola")).toHaveValue("Java Developer");
    expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue("160");
    expect(screen.getByLabelText("Co to za projekt")).toHaveValue("Poprawiony opis.");
    // To, co wpisał odczyt i czego nikt nie ruszył, znika.
    expect(screen.getByLabelText("Liczba osób")).toHaveValue(null);
    expect(screen.queryByLabelText("Treść pytania 1")).toBeNull();
    expect(offerChips()).toHaveLength(0);
    expect(screen.queryByTestId("new-job-fill-summary")).toBeNull();
    // Treść requestu też wraca do stanu sprzed odczytu.
    expect(screen.queryByTestId("new-job-source-pane")).toBeNull();
  });

  it("drugi odczyt dopisuje treść i wypełnia tylko to, co nadal puste", async () => {
    await readRequest({ ...INTAKE, rate_budget_hourly: null, rate_quote: null, deadline: null });
    expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue("");

    const second = "Uzupełnienie: budżet do 180 zł/h, kandydaci do 5 listopada.";
    const secondIntake: RequestIntakeResponse = {
      ...INTAKE,
      role_name: "Lead Java Developer",
      rate_budget_hourly: 180,
      deadline: "2026-11-05",
      evidence: ["180 zł/h"],
    };
    const base = mocks.post.getMockImplementation()!;
    mocks.post.mockImplementation((url: string, body?: unknown) =>
      url === "/api/job-intake/read"
        ? Promise.resolve({ data: { text: second, intake: secondIntake } })
        : base(url, body),
    );
    await pasteAndRead(second);

    // Puste z pierwszego odczytu — wypełnione z drugiego.
    expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue("180");
    expect(within(screen.getByTestId("new-job-deadline")).getByLabelText("Termin")).toHaveValue(
      "2026-11-05",
    );
    // Rola z pierwszego odczytu zostaje; drugi daje propozycję.
    expect(screen.getByLabelText("Rola")).toHaveValue("Senior Java Developer");
    expect(offerChips().map((chip) => chip.getAttribute("data-unit"))).toEqual(["title"]);
    // Obie treści stoją obok formularza, podświetlenia z obu odczytów.
    const pane = screen.getByTestId("new-job-source-pane");
    expect(pane).toHaveTextContent("Szukamy Senior Java Developera");
    expect(pane).toHaveTextContent("Uzupełnienie: budżet do 180 zł/h");
    expect(within(pane).getByText("Java 17+", { selector: "mark" })).toBeInTheDocument();
    expect(within(pane).getByText("180 zł/h", { selector: "mark" })).toBeInTheDocument();
  });
});

describe("NewJobPage — „Inna rekrutacja” jako źródło", () => {
  const JOBS = [
    {
      id: 55,
      title: "Java Developer (zamknięta)",
      client_name: "Alior Bank",
      status: "closed",
      opened_at: "2026-05-04T09:00:00Z",
    },
    { id: 56, title: "Tester automatyzujący", client_name: "Alior Bank", status: "published" },
  ];
  const TEMPLATE = {
    id: 55,
    title: "Java Developer (zamknięta)",
    client_id: 7,
    description: "Stary request klienta.",
    rate_budget_hourly: 160,
    remote_policy: "remote",
    headcount: 3,
  };
  const PROFILE = {
    stack: { rows: [{ words: ["Go", "Golang"], level: "must" }] },
    project: { about: "Migracja płatności." },
  };

  function serveTemplates() {
    mocks.listJobs.mockResolvedValue({ data: { items: JOBS, total: 2 } });
    serveGets((url) => {
      if (url === "/api/jobs/55") return TEMPLATE;
      if (url === "/api/jobs/55/champion-profile?mark_read=false")
        return { job_id: 55, champion_profile: PROFILE };
      return undefined;
    });
  }

  it("lista szuka w rekrutacjach klienta (także zamkniętych); „Także inni klienci” zdejmuje zawężenie", async () => {
    serveTemplates();
    renderPage();
    pickClient();
    fireEvent.click(sourceAction("Inna rekrutacja"));

    expect(
      await screen.findByRole("button", { name: "Użyj jako szablon: Java Developer (zamknięta)" }),
    ).toBeInTheDocument();
    expect(mocks.listJobs).toHaveBeenLastCalledWith({ q: undefined, client_id: 7, page_size: 20 });
    expect(screen.getByText(/zamknięta · 04\.05\.2026/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox", { name: "Także inni klienci" }));
    await waitFor(() =>
      expect(mocks.listJobs).toHaveBeenLastCalledWith({
        q: undefined,
        client_id: undefined,
        page_size: 20,
      }),
    );
    fireEvent.change(screen.getByLabelText("Szukaj rekrutacji-szablonu"), {
      target: { value: "tester" },
    });
    await waitFor(() =>
      expect(mocks.listJobs).toHaveBeenLastCalledWith({
        q: "tester",
        client_id: undefined,
        page_size: 20,
      }),
    );
  });

  it("„Użyj jako szablon” wypełnia puste pola, wpisane zostawia i daje propozycję „W szablonie”", async () => {
    serveTemplates();
    renderPage();
    pickClient();
    fireEvent.change(screen.getByLabelText("Rola"), { target: { value: "Go Developer" } });
    fireEvent.change(screen.getByLabelText("Budżet PLN/h"), { target: { value: "200" } });
    fireEvent.click(sourceAction("Inna rekrutacja"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Użyj jako szablon: Java Developer (zamknięta)" }),
    );

    await waitFor(() => expect(screen.getByLabelText("Liczba osób")).toHaveValue(3));
    // Panel się zamyka; rola i budżet zostają takie, jak wpisał człowiek.
    expect(screen.queryByTestId("new-job-template-picker")).toBeNull();
    expect(screen.getByLabelText("Rola")).toHaveValue("Go Developer");
    expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue("200");
    expect(screen.getByLabelText("Co to za projekt")).toHaveValue("Migracja płatności.");
    expect(offerChips().map((chip) => chip.textContent)).toEqual([
      expect.stringContaining("W szablonie: 160 PLN/h"),
    ]);
    expect(screen.getByTestId("new-job-fill-summary")).toHaveTextContent(
      "Z rekrutacji „Java Developer (zamknięta)”",
    );
    // Opis szablonu staje obok formularza jako treść requestu.
    expect(screen.getByTestId("new-job-source-pane")).toHaveTextContent("Stary request klienta.");
    // Braki przy szablonie nazywają się po swojemu.
    expect(screen.getAllByText("Brak w szablonie — uzupełnij").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Dokończę później" }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs"));
    const saved = bodiesOf("/api/job-intake/forms").at(-1) as unknown as {
      source: string;
      form: { templateJobId: number };
    };
    // Szablon to nie odczyt — źródło zapisu zostaje „ręcznie”.
    expect(saved).toMatchObject({ source: "manual" });
    expect(saved.form.templateJobId).toBe(55);
  });

  it("awaria listy rekrutacji nie udaje pustej listy — komunikat z „Ponów”", async () => {
    mocks.listJobs.mockRejectedValueOnce(new Error("boom"));
    renderPage();
    pickClient();
    fireEvent.click(sourceAction("Inna rekrutacja"));
    const alert = await screen.findByText(/Nie udało się wczytać rekrutacji\./);
    expect(screen.queryByText(/nie ma rekrutacji pasujących/)).toBeNull();
    mocks.listJobs.mockResolvedValue({ data: { items: JOBS, total: 2 } });
    fireEvent.click(within(alert).getByRole("button", { name: "Ponów" }));
    expect(
      await screen.findByRole("button", { name: "Użyj jako szablon: Tester automatyzujący" }),
    ).toBeInTheDocument();
  });
});

describe("NewJobPage — braki po próbie utworzenia", () => {
  it("przy brakach przycisk jest aktywny: kliknięcie podświetla pola, przewija do pierwszej sekcji i nic nie wysyła", async () => {
    const scrolled: string[] = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function scrollIntoView(this: Element) {
      scrolled.push(this.id);
    };
    try {
      renderPage();
      pickClient();
      // Sekcja 1 jest kompletna — pierwszy brak stoi w „Wymaganiach”.
      fireEvent.change(screen.getByLabelText("Rola"), { target: { value: "Java Developer" } });
      fireEvent.click(
        within(screen.getByTestId("new-job-hiring-manager")).getByRole("checkbox", {
          name: "Klient nie podał",
        }),
      );
      expect(screen.queryByText("Uzupełnij przed publikacją")).toBeNull();
      expectNotReady();

      fireEvent.click(handoffButton());

      expect(screen.getAllByText("Uzupełnij przed publikacją").length).toBeGreaterThan(2);
      expect(scrolled).toEqual(["new-job-section-requirements"]);
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(postsTo("/api/jobs")).toHaveLength(0);
      expect(mocks.push).not.toHaveBeenCalled();
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  it("bez klienta „Utwórz i opublikuj” pokazuje komunikat przy polu klienta", () => {
    renderPage();
    expect(screen.getByRole("link", { name: "klient" })).toHaveAttribute("href", "#new-job-client");
    expect(screen.getByText("Brakuje 11 rzeczy do publikacji")).toBeInTheDocument();
    expect(handoffButton()).toBeEnabled();

    fireEvent.click(handoffButton());

    expect(screen.getByRole("alert")).toHaveTextContent(CLIENT_REQUIRED_TEXT);
    expect(postsTo("/api/jobs")).toHaveLength(0);
    pickClient();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("link", { name: "klient" })).toBeNull();
  });
});

describe("NewJobPage", () => {
  it("odczytuje request dla wybranego klienta i pokazuje wypełnione pola", async () => {
    await readRequest();
    expect(mocks.post).toHaveBeenCalledWith(
      "/api/job-intake/read",
      { client_id: 7, text: REQUEST },
      { timeout: 120_000 },
    );
    expect(screen.getByLabelText("Rola")).toHaveValue("Senior Java Developer");
    expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue("170");
    // Fragment z requestu jest podświetlony.
    expect(
      screen.getByText("Java 17+", { selector: "mark" }),
    ).toBeInTheDocument();
  });

  it("formularz ma sześć sekcji z paskiem nawigacji i zwinięte „Dodatkowe”", async () => {
    await readRequest();
    for (const heading of [
      "1 · Nazwa",
      "2 · Wymagania — słowa kluczowe",
      "3 · Warunki",
      "4 · O projekcie",
      "5 · Pytania do kandydata",
      "6 · Kategoria i zespół",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(
      within(screen.getByRole("navigation", { name: "Sekcje formularza" })).getAllByRole("link"),
    ).toHaveLength(6);
    expect(
      screen.getByRole("button", { name: /Dodatkowe — nie blokuje utworzenia/ }),
    ).toHaveAttribute("aria-expanded", "false");
    // Pola sprzed 02.10.2026 nie wracają.
    for (const gone of [
      "Must-have",
      "Frazy do LinkedIna",
      "Numer u klienta",
      "Tytuł dla rekrutera",
      "Tytuł dla zespołu",
    ]) {
      expect(screen.queryByLabelText(gone)).toBeNull();
    }
    for (const gone of ["Kolejne osoby", "Współpracownicy", "Rekruter i priorytet"]) {
      expect(screen.queryByText(gone)).toBeNull();
    }
  });

  it("wymagania to jedna lista wierszy z poziomami; zdania opisowe stoją osobno", async () => {
    await readRequest();
    const editor = screen.getByRole("group", { name: "Wymagania — słowa kluczowe" });
    const level = (head: string, name: string) =>
      within(
        within(editor).getByRole("radiogroup", { name: `Poziom wymagania: ${head}` }),
      ).getByRole("radio", { name });
    expect(level("Java", "Musi mieć")).toBeChecked();
    expect(level("Spring Boot", "Musi mieć")).toBeChecked();
    expect(level("Kubernetes", "Mile widziane")).toBeChecked();
    // Wariant stoi w wierszu swojego wymagania.
    expect(within(editor).getByText("Spring")).toBeInTheDocument();
    expect(
      screen.getByText("Zdania klienta, które nie są słowami kluczowymi (1)"),
    ).toBeInTheDocument();
    expect(screen.getByText("„Doświadczenie w bankowości”")).toBeInTheDocument();
  });

  it("starszy kształt odpowiedzi odczytu: wiersze z must i wierszy wyszukiwania, deal breakery do wpisania", async () => {
    await readRequest(LEGACY_INTAKE);
    const editor = screen.getByRole("group", { name: "Wymagania — słowa kluczowe" });
    expect(
      within(editor).getAllByRole("radiogroup").map((group) => group.getAttribute("aria-label")),
    ).toEqual(["Poziom wymagania: Java 17+", "Poziom wymagania: Spring Boot"]);

    // Pytania bez odpowiedzi, która odpada: nie da się ich zatwierdzić hurtem.
    expect(screen.getAllByText(DEAL_BREAKER_REQUIRED_TEXT)).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Zatwierdź wszystkie" })).toBeDisabled();
    expect(
      screen.getByRole("link", { name: "odpowiedź, która odpada, przy każdym pytaniu" }),
    ).toBeInTheDocument();

    // Wpisana odpowiedź jest decyzją człowieka — pytanie jest od razu zatwierdzone.
    fireEvent.change(screen.getByLabelText("Odpowiedź, która odpada, na pytanie 1"), {
      target: { value: "Nie zna Kafki." },
    });
    fireEvent.change(screen.getByLabelText("Odpowiedź, która odpada, na pytanie 2"), {
      target: { value: "Tylko zdalnie." },
    });
    expect(screen.queryByText(DEAL_BREAKER_REQUIRED_TEXT)).toBeNull();
    expect(screen.getByText("2 pytania — wszystkie zatwierdzone")).toBeInTheDocument();

    await confirmCategory();
    await pickRecruiter();
    await handoffTo();
    expect(championBody()?.stack.rows).toEqual([
      { words: ["Java 17+"], level: "must" },
      { words: ["Spring Boot"], level: "must" },
    ]);
    expect(championBody()?.screening_questions.map((q) => q.deal_breaker)).toEqual([
      "Nie zna Kafki.",
      "Tylko zdalnie.",
    ]);
  });

  it("utworzenie wymaga rekrutera, a potem idzie JEDNYM POST /api/jobs z całością", async () => {
    await readRequest();
    await closeGaps();
    expect(handoffButton()).toBeDisabled();
    expect(
      screen.getByText(/Wybierz rekrutera prowadzącego w sekcji „Kategoria i zespół”/),
    ).toBeInTheDocument();

    await pickRecruiter();
    await handoffTo();

    expect(jobPostBody()).toMatchObject({
      title: "Senior Java Developer",
      client_id: 7,
      rate_budget_hourly: 170,
      remote_policy: "hybrid",
      competence_category_id: 2,
      must_skills: ["Java", "Spring Boot"],
      nice_skills: ["Kubernetes"],
      priority: "urgent",
      hiring_manager: { contact_id: 501 },
      deadline: "2026-10-20",
      deadline_time: null,
      deadline_not_provided: false,
      headcount: 2,
      handoff: { recruiter_id: 31, channel: "linkedin" },
      similar_job_ids: [],
      cc_override: null,
    });
    // Bez statusu: rekrutacja nigdy nie jest szkicem.
    expect(jobPostBody()).not.toHaveProperty("status");
    expect(championBody()).toMatchObject({
      project: { about: "Migracja płatności.", responsibilities: "" },
    });
    // Wymagania jadą wierszami; starych pól (frazy, wiersze wyszukiwania) nie ma.
    expect(championBody()?.stack).toEqual({
      rows: [
        { words: ["Java"], level: "must" },
        { words: ["Spring Boot", "Spring"], level: "must" },
        { words: ["Kubernetes"], level: "nice" },
      ],
      critical: null,
      notes: "Doświadczenie w bankowości",
    });
    expect(championBody()?.search).toEqual({
      target_companies: "",
      disqualifiers: [],
      exclude: [],
    });
    expect(championBody()?.screening_questions).toEqual([
      { id: "q1", question: "Kafka?", ideal_answer: "", deal_breaker: "Nie zna Kafki." },
      { id: "q2", question: "Biuro?", ideal_answer: "", deal_breaker: "Tylko zdalnie." },
    ]);
    // Żadnych osobnych tras po utworzeniu — wszystko w jednej transakcji.
    expect(postsTo("/api/jobs")).toHaveLength(1);
    expect(mocks.put).not.toHaveBeenCalled();
    expect(mocks.handoff).not.toHaveBeenCalled();
    const urls = mocks.post.mock.calls.map(([url]) => String(url));
    for (const tail of ["/handoff", "/publish", "/cc-override", "/similar"]) {
      expect(urls.some((url) => url.startsWith("/api/jobs/900") && url.endsWith(tail))).toBe(
        false,
      );
    }
    expect(mocks.showSuccess).toHaveBeenCalledWith("Rekrutacja utworzona i opublikowana.");
    // Podsumowanie historii klienta rusza w tle — bez czekania na wynik.
    expect(mocks.refreshClientHistory).toHaveBeenCalledWith(900);
    // Uczestników (cała kategoria) dopisuje serwer — strona nikogo nie zapisuje.
    expect(
      mocks.post.mock.calls.some(([url]) => String(url).includes("/collaborators")),
    ).toBe(false);
  });

  describe("numer u klienta i tytuł dla zespołu — bez osobnych pól", () => {
    const TITLED: RequestIntakeResponse = {
      ...INTAKE,
      client_title: "Programista Java (ZOB 48213)",
      client_reference: "ZOB 48213",
    };

    it("numer rozpoznany w nazwie od klienta idzie do rekrutacji bez wpisywania", async () => {
      await readRequest(TITLED);
      expect(screen.getByTestId("client-reference")).toHaveTextContent(
        "Numer u klienta rozpoznany: ZOB 48213 — trafi do CV i nazwy pliku.",
      );
      expect(screen.queryByLabelText("Numer u klienta")).toBeNull();

      await createJob();
      expect(jobPostBody()).toMatchObject({
        title: "Programista Java (ZOB 48213)",
        client_reference: "ZOB 48213",
      });
    });

    it("„To nie ten numer” pozwala wpisać inny albo żaden", async () => {
      await readRequest(TITLED);
      fireEvent.click(screen.getByRole("button", { name: "To nie ten numer" }));
      const input = screen.getByLabelText("Numer u klienta");
      expect(input).toHaveValue("ZOB 48213");

      // Puste pole jedzie jako pusty napis: bez pola w żądaniu serwer wziąłby
      // numer z nazwy i „bez numeru” nie dałoby się zapisać.
      fireEvent.change(input, { target: { value: "" } });
      await createJob();
      expect(jobPostBody()).toMatchObject({ client_reference: "" });
    });

    it("nazwa bez numeru: strona mówi to wprost i daje „Wpisz numer”", async () => {
      await readRequest();
      expect(screen.getByTestId("client-reference")).toHaveTextContent(
        "Nie widzę numeru zapytania w nazwie.",
      );
      fireEvent.click(screen.getByRole("button", { name: "Wpisz numer" }));
      fireEvent.change(screen.getByLabelText("Numer u klienta"), {
        target: { value: "REQ-9" },
      });
      await createJob();
      expect(jobPostBody()).toMatchObject({ client_reference: "REQ-9" });
    });

    it("tytuł dla zespołu składa się sam; pole pojawia się dopiero po „Zmień”", async () => {
      await readRequest();
      const field = screen.getByTestId("working-title-field");
      expect(field).toHaveTextContent("Senior Java Developer · Java, Spring Boot");
      expect(within(field).queryByRole("textbox")).toBeNull();

      fireEvent.click(within(field).getByRole("button", { name: "Zmień" }));
      const input = screen.getByLabelText("Tytuł dla zespołu");
      expect(input).toHaveValue("Senior Java Developer · Java, Spring Boot");
      fireEvent.change(input, { target: { value: "Java do płatności" } });

      await createJob();
      expect(jobPostBody()).toMatchObject({ working_title: "Java do płatności" });
    });

    it("bez ręcznej zmiany tytuł dla zespołu nie jedzie — składa go serwer", async () => {
      await readRequest();
      await createJob();
      expect(jobPostBody()).not.toHaveProperty("working_title");
    });
  });

  describe("krytyczne (wiersze wymagań)", () => {
    const TECH = { eligible: ["Java", "Spring Boot"], suggested: ["Java"] };

    async function readWithTechnologies() {
      await readRequest(INTAKE, TECH);
      await closeGaps();
      await pickRecruiter();
      // Serwer odpowiada po chwili ciszy na liście wymagań.
      await screen.findByRole("link", { name: "krytyczne (albo „Brak krytycznych”)" });
    }

    it("pyta serwer o bieżące wiersze obowiązkowe i rolę", async () => {
      await readWithTechnologies();
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/job-intake/critical-suggestion",
        { rows: [["Java"], ["Spring Boot", "Spring"]], title: "Senior Java Developer" },
        expect.anything(),
      );
    });

    it("brak decyzji blokuje przekazanie; „Brak krytycznych” jedzie jako pusta lista", async () => {
      await readWithTechnologies();
      expectNotReady();
      expect(screen.getByText("Brakuje 1 rzeczy do publikacji")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("checkbox", { name: "Brak krytycznych" }));
      expect(screen.getByText("Gotowa do publikacji")).toBeInTheDocument();
      await handoffTo();
      expect(championBody()?.stack.critical).toEqual([]);
      expect(championBody()?.stack.rows.map((row) => row.level)).toEqual([
        "must",
        "must",
        "nice",
      ]);
    });

    it("podpowiedź z historii oznacza wiersz — poziom jedzie w wierszu, `critical` zostaje null", async () => {
      await readWithTechnologies();
      fireEvent.click(
        screen.getByRole("button", { name: "Oznacz krytyczne z historii: Java" }),
      );
      expect(handoffButton()).toBeEnabled();
      await handoffTo();
      expect(championBody()?.stack.rows[0]).toEqual({ words: ["Java"], level: "critical" });
      expect(championBody()?.stack.critical).toBeNull();
    });

    it("lista bez technologii ze słownika nie wymaga decyzji", async () => {
      await readRequest();
      await closeGaps();
      await pickRecruiter();
      await waitFor(() =>
        expect(postsTo("/api/job-intake/critical-suggestion")).not.toHaveLength(0),
      );
      expect(await screen.findByText("Gotowa do publikacji")).toBeInTheDocument();
      expect(handoffButton()).toBeEnabled();
    });
  });

  describe("pytania do kandydata: odpowiedź, która odpada, i zatwierdzenie", () => {
    it("propozycje AI czekają na zatwierdzenie — bez niego nie ma przekazania", async () => {
      await readRequest();
      await confirmCategory();
      await pickRecruiter();
      expect(screen.getByText("Zatwierdzone 0 z 2")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "zatwierdzenie pytań" })).toBeInTheDocument();
      expectNotReady();

      fireEvent.click(screen.getByRole("button", { name: "Zatwierdź pytanie 1" }));
      expect(screen.getByText("Zatwierdzone 1 z 2")).toBeInTheDocument();
      expectNotReady();

      fireEvent.click(screen.getByRole("button", { name: "Zatwierdź wszystkie" }));
      expect(screen.getByText("2 pytania — wszystkie zatwierdzone")).toBeInTheDocument();
      expect(screen.getByText("Gotowa do publikacji")).toBeInTheDocument();
      expect(handoffButton()).toBeEnabled();
    });

    it("usunięty deal breaker blokuje, choć pytanie było zatwierdzone", async () => {
      await readRequest();
      await closeGaps();
      await pickRecruiter();
      expect(screen.getByText("Gotowa do publikacji")).toBeInTheDocument();
      expect(handoffButton()).toBeEnabled();

      fireEvent.change(screen.getByLabelText("Odpowiedź, która odpada, na pytanie 2"), {
        target: { value: " " },
      });
      expectNotReady();
      expect(screen.getByText(DEAL_BREAKER_REQUIRED_TEXT)).toBeInTheDocument();
      expect(
        screen.getByRole("link", { name: "odpowiedź, która odpada, przy każdym pytaniu" }),
      ).toBeInTheDocument();
    });

    it("pytanie dopisane ręcznie potrzebuje tylko deal breakera", async () => {
      await readRequest();
      await closeGaps();
      await pickRecruiter();
      fireEvent.click(screen.getByRole("button", { name: /Dodaj pytanie$/ }));
      fireEvent.change(screen.getByLabelText("Treść pytania 3"), {
        target: { value: "Umowa B2B?" },
      });
      expectNotReady();
      fireEvent.change(screen.getByLabelText("Odpowiedź, która odpada, na pytanie 3"), {
        target: { value: "Tylko umowa o pracę." },
      });
      expect(screen.getByText("Gotowa do publikacji")).toBeInTheDocument();
      expect(handoffButton()).toBeEnabled();
      await handoffTo();
      expect(championBody()?.screening_questions.at(-1)).toEqual({
        id: "q3",
        question: "Umowa B2B?",
        ideal_answer: "",
        deal_breaker: "Tylko umowa o pracę.",
      });
    });
  });

  describe("kategoria kompetencji", () => {
    const categoryOption = (name: RegExp) =>
      within(screen.getByRole("radiogroup", { name: "Kategoria kompetencji" })).getByRole(
        "radio",
        { name },
      );
    const override = () => jobPostBody()?.cc_override;

    it("podpowiedź liczy serwer z roli, opisu i wymagań", async () => {
      await readRequest();
      await categorySettled();
      expect(bodiesOf("/api/job-intake/category-suggestion").at(-1)).toEqual({
        role: "Senior Java Developer",
        client_title: "Senior Java Developer",
        description: REQUEST,
        must_skills: ["Java", "Spring Boot"],
      });
      await screen.findByRole("button", { name: "Potwierdzam: Development" });
      expect(categoryOption(/^Development/)).toBeChecked();
      expect(categoryOption(/^Development/)).toHaveTextContent("propozycja");
    });

    it("pyta tylko o rolę, która stoi w polu — nie o puste pole sprzed odczytu", async () => {
      // Podpowiedź dla pustej roli mignęłaby i zniknęła po chwili: przycisk
      // „Potwierdzam” kliknięty w tym oknie nie potwierdzał niczego.
      await readRequest();
      await categorySettled();
      await screen.findByRole("button", { name: "Potwierdzam: Development" });
      expect(
        bodiesOf("/api/job-intake/category-suggestion").map((body) => body.role),
      ).toEqual(["Senior Java Developer"]);
    });

    it("podpowiedź trzeba potwierdzić — dopiero wtedy da się przekazać", async () => {
      await readRequest();
      await categorySettled();
      fireEvent.click(screen.getByRole("button", { name: "Zatwierdź wszystkie" }));
      await pickRecruiter();
      await screen.findByRole("button", { name: "Potwierdzam: Development" });
      expect(screen.getByRole("link", { name: "potwierdzenie kategorii" })).toBeInTheDocument();
      expectNotReady();

      await confirmCategory();
      expect(
        screen.getByText(/Kategoria potwierdzona: Development\. Uczestnikami zostaną wszyscy z tej\s+kategorii \(7 osób\)/),
      ).toBeInTheDocument();
      expect(handoffButton()).toBeEnabled();

      await handoffTo();
      expect(jobPostBody()).toMatchObject({ competence_category_id: 2 });
      // Kategoria zgodna z podpowiedzią — nie ma czego zgłaszać regułom klasyfikacji.
      expect(override()).toBeNull();
    });

    it("inna kategoria niż podpowiedź: wybór ją potwierdza i zgłasza różnicę w tym samym żądaniu", async () => {
      await readRequest();
      await categorySettled();
      fireEvent.click(screen.getByRole("button", { name: "Zatwierdź wszystkie" }));
      await pickRecruiter();
      await screen.findByRole("button", { name: "Potwierdzam: Development" });

      fireEvent.click(categoryOption(/^QA/));
      expect(categoryOption(/^QA/)).toBeChecked();
      expect(screen.getByText(/Kategoria potwierdzona: QA\./)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^Potwierdzam/ })).toBeNull();

      await handoffTo();
      expect(jobPostBody()).toMatchObject({ competence_category_id: 4 });
      expect(override()).toEqual({ suggested_cc_id: 2, suggested_score: null });
    });

    it("system bez podpowiedzi: kategorię wybiera Delivery Lead, różnicy nie ma z czym porównać", async () => {
      await readRequest(INTAKE, { category: { suggested_id: null, categories: CATEGORIES } });
      await categorySettled();
      expect(
        await screen.findByText(/System nie rozpoznał kategorii z nazwy roli — wybierz ją\./),
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Zatwierdź wszystkie" }));
      await pickRecruiter();
      expectNotReady();

      fireEvent.click(categoryOption(/^Infra/));
      await handoffTo();
      expect(jobPostBody()).toMatchObject({ competence_category_id: 1 });
      expect(override()).toBeNull();
    });

    it("niedokończony formularz pamięta podpowiedzianą kategorię bez potwierdzenia", async () => {
      await readRequest();
      await screen.findByRole("button", { name: "Potwierdzam: Development" });
      fireEvent.click(screen.getByRole("button", { name: "Dokończę później" }));
      await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs"));
      const saved = bodiesOf("/api/job-intake/forms").at(-1) as unknown as {
        form: { form: { competenceCategoryId: number; categoryConfirmed: boolean } };
      };
      expect(saved.form.form).toMatchObject({ competenceCategoryId: 2, categoryConfirmed: false });
      expect(postsTo("/api/jobs")).toHaveLength(0);
    });

    it("awaria listy kategorii → komunikat z „Ponów”", async () => {
      serve();
      const base = mocks.post.getMockImplementation()!;
      let failing = true;
      mocks.post.mockImplementation((url: string, ...rest: unknown[]) =>
        url === "/api/job-intake/category-suggestion" && failing
          ? Promise.reject(new Error("boom"))
          : base(url, ...rest),
      );
      renderPage();
      pickClient();
      // Pusty formularz o kategorie nie pyta — pyta po pierwszym wpisanym polu.
      fireEvent.change(screen.getByLabelText("Rola"), { target: { value: "Tester" } });

      const alert = (await screen.findByText(/Nie udało się wczytać kategorii/)).closest(
        "[role=alert]",
      ) as HTMLElement;
      failing = false;
      fireEvent.click(within(alert).getByRole("button", { name: "Ponów" }));
      expect(
        await screen.findByRole("button", { name: "Potwierdzam: Development" }),
      ).toBeInTheDocument();
      expect(screen.queryByText(/Nie udało się wczytać kategorii/)).toBeNull();
    });
  });

  describe("„Rekruter prowadzący”: automat albo wskażę sam (decyzje 29.09 i 02.10.2026)", () => {
    function allocationOptions(automatic_enabled: boolean, mode: string) {
      serveGets((url) =>
        url === "/api/job-intake/handoff-options" ? { automatic_enabled, mode } : undefined,
      );
    }

    const recruiterGroup = () =>
      screen.findByRole("radiogroup", { name: "Rekruter prowadzący" });
    const automatOption = (group: HTMLElement, name = "Zaproponuje automat") =>
      within(group).getByRole("radio", { name });
    const personOption = (group: HTMLElement) =>
      within(group).getByRole("radio", { name: "Wskażę sam" });

    it("przy wyłączonym automacie opcja jest widoczna, ale nieaktywna — z powodem", async () => {
      allocationOptions(false, "off");
      await readRequest();
      await closeGaps();
      const group = await recruiterGroup();
      expect(
        await screen.findByText(
          "Automatyczny przydział jest wyłączony — włącza go administrator.",
        ),
      ).toBeInTheDocument();
      expect(automatOption(group)).toBeDisabled();
      expect(automatOption(group)).toHaveAccessibleDescription(
        "Automatyczny przydział jest wyłączony — włącza go administrator.",
      );
      expect(personOption(group)).toBeChecked();
      expect(handoffButton()).toBeDisabled();
      expect(handoffButton()).toHaveAttribute(
        "title",
        "Wybierz rekrutera prowadzącego, żeby opublikować rekrutację",
      );
    });

    it("tryb „off” przy włączonej fladze też nie pozwala wybrać automatu", async () => {
      allocationOptions(true, "off");
      await readRequest();
      const group = await recruiterGroup();
      await screen.findByText(
        "Automatyczny przydział jest wyłączony — włącza go administrator.",
      );
      expect(automatOption(group)).toBeDisabled();
      expect(personOption(group)).toBeChecked();
    });

    it("włączony automat jest wyborem DOMYŚLNYM: bez żadnego kliknięcia handoff idzie z assignment_mode automatic", async () => {
      allocationOptions(true, "shadow");
      await readRequest();
      await closeGaps();
      const group = await recruiterGroup();
      await waitFor(() => expect(automatOption(group)).toBeChecked());
      expect(automatOption(group)).toBeEnabled();
      expect(
        screen.getByText(
          "Automat zaproponuje osobę według kategorii i obłożenia. Propozycję zatwierdza Head of Recruitment — do tego czasu nikt nie jest przypisany.",
        ),
      ).toBeInTheDocument();
      // Listy osób nie ma — nie ma czego wybierać.
      expect(screen.queryByLabelText("Wybierz rekrutera prowadzącego")).toBeNull();

      expect(handoffButton()).toBeEnabled();
      await handoffTo();

      expect(jobPostBody()).toMatchObject({
        handoff: { assignment_mode: "automatic", channel: "linkedin" },
      });
      expect(mocks.handoff).not.toHaveBeenCalled();
      expect(mocks.showSuccess).toHaveBeenCalledWith(
        "Rekrutacja utworzona i opublikowana. Rekrutera zaproponuje automat, a zatwierdzi Head of Recruitment.",
      );
    });

    it("tryb „auto”: opcja nazywa się „Przydzieli automat” i mówi, co się stanie", async () => {
      allocationOptions(true, "auto");
      await readRequest();
      await closeGaps();
      const group = await recruiterGroup();
      await waitFor(() => expect(automatOption(group, "Przydzieli automat")).toBeChecked());
      expect(within(group).queryByRole("radio", { name: "Zaproponuje automat" })).toBeNull();
      expect(
        screen.getByText(
          "Automat przydzieli jedną osobę z kategorii — tę z najmniejszą liczbą requestów. Head rekrutacji zobaczy to na pulpicie i może zmienić.",
        ),
      ).toBeInTheDocument();
      // Stopka mówi to samo jednym zdaniem jeszcze przed kliknięciem.
      expect(
        screen.getByText("Rekrutera prowadzącego przydzieli automat — zwykle w ciągu minuty."),
      ).toBeInTheDocument();

      await handoffTo();
      expect(mocks.showSuccess).toHaveBeenCalledWith(
        "Rekrutacja utworzona i opublikowana. Rekrutera prowadzącego przydzieli automat — zwykle w ciągu minuty.",
      );
    });

    it("„Wskażę sam” przy włączonym automacie: lista osób, przypisanie od razu, bez automatu", async () => {
      allocationOptions(true, "shadow");
      await readRequest();
      await closeGaps();
      const group = await recruiterGroup();
      await waitFor(() => expect(automatOption(group)).toBeChecked());

      fireEvent.click(personOption(group));

      expect(personOption(group)).toBeChecked();
      expect(
        screen.getByText("Wskazana osoba prowadzi rekrutację od razu, bez akceptacji."),
      ).toBeInTheDocument();
      // Sam wybór trybu to za mało — trzeba wskazać osobę.
      expect(handoffButton()).toBeDisabled();
      expect(handoffButton()).toHaveAttribute(
        "title",
        "Wybierz rekrutera prowadzącego albo zostaw to automatowi",
      );
      await pickRecruiter();
      await handoffTo();

      expect(jobPostBody()).toMatchObject({
        handoff: { recruiter_id: 31, channel: "linkedin" },
      });
    });

    it.each([
      ["Bez priorytetu", "medium"],
      ["Przyjmujemy kandydatów", "low"],
    ])("priorytet „%s” przy automacie: mówi wprost, że automat dobiera rekrutera tylko do P1", async (label, raw) => {
      allocationOptions(true, "shadow");
      await readRequest();
      await closeGaps();
      const group = await recruiterGroup();
      await waitFor(() => expect(automatOption(group)).toBeChecked());

      fireEvent.click(
        within(screen.getByRole("radiogroup", { name: "Priorytet" })).getByRole("radio", {
          name: label,
        }),
      );

      expect(
        screen.getByText(
          "Automat dobiera rekrutera tylko przy priorytecie P1 — ta rekrutacja zostanie bez rekrutera, dopóki ktoś jej nie weźmie albo nie wskażesz osoby.",
        ),
      ).toBeInTheDocument();
      expect(screen.queryByText(/Propozycję zatwierdza Head of Recruitment/)).toBeNull();

      await handoffTo();
      expect(jobPostBody()).toMatchObject({ priority: raw });
      expect(mocks.showSuccess).toHaveBeenCalledWith(
        "Rekrutacja utworzona i opublikowana. Rekrutacja zostaje bez rekrutera — automat dobiera go tylko przy priorytecie P1.",
      );
    });

    it("odmowa serwera bez listy braków: zdanie przy przycisku, nic nie powstaje", async () => {
      allocationOptions(true, "auto");
      await readRequest();
      await closeGaps();
      const fallback = mocks.post.getMockImplementation()!;
      mocks.post.mockImplementation((url: string, ...rest: unknown[]) =>
        url === "/api/jobs"
          ? Promise.reject({
              response: {
                status: 409,
                data: { detail: "Automat przydziału jest wyłączony — wybierz rekrutera ręcznie." },
              },
            })
          : fallback(url, ...rest),
      );
      const group = await recruiterGroup();
      await waitFor(() => expect(automatOption(group, "Przydzieli automat")).toBeChecked());
      fireEvent.click(handoffButton());
      expect(
        await screen.findByText(
          "Automat przydziału jest wyłączony — wybierz rekrutera ręcznie.",
        ),
      ).toBeInTheDocument();
      expect(mocks.push).not.toHaveBeenCalled();
      expect(mocks.showSuccess).not.toHaveBeenCalled();
    });
  });

  describe("Delivery Lead widoczny przed zapisem (08.10.2026)", () => {
    const DELIVERY_LEADS = [
      { id: 41, name: "Daria Delivery" },
      { id: 42, name: "Marek Delivery" },
    ];

    /** Serwer mówi, kto będzie DL-em; katalog osób odróżniamy po rolach. */
    function serveDeliveryLead(defaultLead: unknown) {
      mocks.get.mockImplementation((url: string, config?: { params?: { roles?: string[] } }) => {
        if (url === "/api/job-intake/delivery-lead") {
          return Promise.resolve({ data: { default: defaultLead } });
        }
        if (url === "/api/users") {
          const forDeliveryLead = config?.params?.roles?.includes("delivery_lead");
          return Promise.resolve({ data: forDeliveryLead ? DELIVERY_LEADS : RECRUITERS });
        }
        return Promise.resolve({ data: {} });
      });
    }

    const field = () => screen.findByTestId("new-job-delivery-lead");

    it("Delivery Lead, który zakłada rekrutację, widzi siebie — i żądanie nie niesie DL-a", async () => {
      serveDeliveryLead({ user_id: 41, name: "Daria Delivery", source: "creator" });
      await readRequest();

      const box = await field();
      expect(await within(box).findByText("Daria Delivery (Ty)")).toBeInTheDocument();
      expect(
        within(box).getByText(/Zakładasz tę rekrutację, więc jesteś jej Delivery Leadem/),
      ).toBeInTheDocument();
      expect(mocks.get).toHaveBeenCalledWith("/api/job-intake/delivery-lead", {
        params: { client_id: 7 },
      });

      await createJob();
      expect(jobPostBody()).not.toHaveProperty("delivery_lead_id");
    });

    it("admin widzi głównego DL-a klienta, a „Zmień” wysyła wskazaną osobę", async () => {
      serveDeliveryLead({ user_id: 42, name: "Marek Delivery", source: "client_head" });
      await readRequest();

      const box = await field();
      expect(await within(box).findByText("Marek Delivery")).toBeInTheDocument();
      expect(within(box).getByText(/Główny Delivery Lead klienta/)).toBeInTheDocument();

      fireEvent.click(within(box).getByRole("button", { name: "Zmień" }));
      await within(box).findByRole("option", { name: "Daria Delivery" });
      fireEvent.change(within(box).getByRole("combobox", { name: "Delivery Lead" }), {
        target: { value: "41" },
      });
      expect(
        within(box).getByText("Wybrano ręcznie. Bez zmiany byłby to: Marek Delivery."),
      ).toBeInTheDocument();

      await createJob();
      expect(jobPostBody()).toMatchObject({ delivery_lead_id: 41 });
    });

    it("powrót do osoby domyślnej zdejmuje wybór — serwer wpisuje ją sam", async () => {
      serveDeliveryLead({ user_id: 42, name: "Marek Delivery", source: "client_head" });
      await readRequest();

      const box = await field();
      fireEvent.click(await within(box).findByRole("button", { name: "Zmień" }));
      await within(box).findByRole("option", { name: "Daria Delivery" });
      const select = within(box).getByRole("combobox", { name: "Delivery Lead" });
      fireEvent.change(select, { target: { value: "41" } });
      fireEvent.change(select, { target: { value: "42" } });

      await createJob();
      expect(jobPostBody()).not.toHaveProperty("delivery_lead_id");
    });

    it("klient bez głównego DL-a: formularz mówi to wprost zamiast milczeć", async () => {
      serveDeliveryLead(null);
      await readRequest();

      const box = await field();
      expect(await within(box).findByText("nie przypisano")).toBeInTheDocument();
      expect(
        within(box).getByText(/Klient nie ma głównego Delivery Leada/),
      ).toBeInTheDocument();
    });

    it("awaria odczytu nie udaje „nie przypisano” — komunikat z „Ponów”", async () => {
      mocks.get.mockImplementation((url: string) =>
        url === "/api/job-intake/delivery-lead"
          ? Promise.reject(new Error("boom"))
          : Promise.resolve({ data: url === "/api/users" ? RECRUITERS : {} }),
      );
      await readRequest();

      const box = await field();
      expect(
        await within(box).findByText(/Nie udało się sprawdzić, kto będzie Delivery Leadem/),
      ).toBeInTheDocument();
      expect(within(box).queryByText("nie przypisano")).toBeNull();
      expect(within(box).getByRole("button", { name: "Ponów" })).toBeInTheDocument();
    });
  });

  describe("priorytet (02.10.2026)", () => {
    const priorityOption = (name: string) =>
      within(screen.getByRole("radiogroup", { name: "Priorytet" })).getByRole("radio", {
        name,
      });

    async function pickRecruiterAndHandoff() {
      await closeGaps();
      await pickRecruiter();
      await handoffTo();
    }

    // Decyzja Artura 08.10.2026: nowa rekrutacja dostaje P1 z automatu.
    it("nowa rekrutacja zaczyna od P1 i tak idzie do POST /api/jobs", async () => {
      await readRequest();
      expect(
        within(screen.getByRole("radiogroup", { name: "Priorytet" }))
          .getAllByRole("radio")
          .map((radio) => radio.textContent),
      ).toEqual(["P1 Pilne", "Bez priorytetu", "Przyjmujemy kandydatów"]);
      expect(priorityOption("P1 Pilne")).toBeChecked();

      await pickRecruiterAndHandoff();

      expect(jobPostBody()).toMatchObject({ priority: "urgent" });
    });

    it("„Bez priorytetu” wybrane ręcznie idzie jako „medium”", async () => {
      await readRequest();
      fireEvent.click(priorityOption("Bez priorytetu"));
      expect(priorityOption("Bez priorytetu")).toBeChecked();

      await createJob();
      expect(jobPostBody()).toMatchObject({ priority: "medium" });
    });

    it("po utworzeniu odświeża listę, liczniki i pulpit „Requesty i obłożenie”", async () => {
      await readRequest();
      await pickRecruiterAndHandoff();

      const keys = invalidatedKeys();
      for (const key of [
        ["jobs-v2"],
        ["jobs-quick-counts"],
        REQUEST_BOARD_QUERY_KEY,
        BOARD_TASKS_QUERY_KEY,
      ]) {
        expect(keys).toContainEqual(key);
      }
    });
  });

  it("awaria listy rekruterów → komunikat z „Ponów” przy polu „Rekruter prowadzący” (R8-N14-6)", async () => {
    let calls = 0;
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/users") {
        calls += 1;
        return calls === 1
          ? Promise.reject(new Error("boom"))
          : Promise.resolve({ data: [{ id: 31, name: "Rekruterka Ola" }] });
      }
      return Promise.resolve({ data: {} });
    });
    await readRequest();
    const alert = await screen.findByText(/Nie udało się wczytać listy rekruterów/);
    fireEvent.click(within(alert.closest("[role=alert]") as HTMLElement).getByRole("button", { name: "Ponów" }));
    expect(await screen.findByRole("option", { name: "Rekruterka Ola" })).toBeInTheDocument();
    expect(screen.queryByText(/Nie udało się wczytać listy rekruterów/)).toBeNull();
  });

  it("awaria podsumowania historii klienta nie blokuje utworzenia rekrutacji", async () => {
    mocks.refreshClientHistory.mockRejectedValue(new Error("503"));
    await readRequest();
    await closeGaps();
    await pickRecruiter();
    await handoffTo();
    expect(mocks.showSuccess).toHaveBeenCalledWith(
      "Rekrutacja utworzona i opublikowana.",
    );
  });

  it("422 `job_not_ready`: lista braków w stopce z linkami do sekcji, formularz zostaje zapisany", async () => {
    await readRequest();
    const fallback = mocks.post.getMockImplementation()!;
    mocks.post.mockImplementation((url: string, ...rest: unknown[]) =>
      url === "/api/jobs"
        ? Promise.reject({
            response: {
              status: 422,
              data: {
                detail: {
                  code: "job_not_ready",
                  message: "Rekrutacja nie jest gotowa.",
                  blockers: [
                    {
                      code: "office_city",
                      message: "Podaj miasto biura w lokalizacji oferty (tryb hybrydowy/stacjonarny).",
                    },
                    { code: "champion:rate_unresolved", message: "Stawka w profilu nie jest kwotą." },
                  ],
                },
              },
            },
          })
        : fallback(url, ...rest),
    );
    await closeGaps();
    await pickRecruiter();
    fireEvent.click(handoffButton());

    const alert = await screen.findByTestId("new-job-server-blockers");
    expect(alert).toHaveTextContent("Rekrutacja nie powstała. Uzupełnij 2 rzeczy:");
    expect(
      within(alert).getByRole("link", {
        name: "Podaj miasto biura w lokalizacji oferty (tryb hybrydowy/stacjonarny).",
      }),
    ).toHaveAttribute("href", "#new-job-section-terms");
    // Kod spoza formularza trafia na listę bez linku.
    expect(within(alert).queryByRole("link", { name: "Stawka w profilu nie jest kwotą." })).toBeNull();
    expect(within(alert).getByText("Stawka w profilu nie jest kwotą.")).toBeInTheDocument();
    // Nic nie powstało — formularz trafia na konto autora.
    await waitFor(() =>
      expect(alert).toHaveTextContent("Formularz jest zapisany, nic nie przepadło."),
    );
    expect(postsTo("/api/job-intake/forms")).not.toHaveLength(0);
    expect(mocks.push).not.toHaveBeenCalled();
    expect(mocks.showSuccess).not.toHaveBeenCalled();
  });

  it("braki w requeście: kliknięcie „Utwórz” niczego nie wysyła, a formularz da się odłożyć na później", async () => {
    await readRequest({
      ...INTAKE,
      rate_budget_hourly: null,
      rate_quote: null,
    });
    // Po odczycie: budżet + zatwierdzenie pytań + potwierdzenie kategorii.
    expect(
      await screen.findByText("Brakuje 3 rzeczy do publikacji"),
    ).toBeInTheDocument();
    await closeGaps();
    await pickRecruiter();
    expect(screen.getByText("Brakuje 1 rzeczy do publikacji")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "budżet PLN/h" })).toHaveAttribute(
      "href",
      "#new-job-section-terms",
    );
    // Brak z odczytu jest podświetlony w polu od razu, bez klikania „Utwórz”.
    expect(screen.getByText("Brak w requeście — uzupełnij")).toBeInTheDocument();
    // Przycisk zostaje aktywny i mówi, czego brakuje; kliknięcie nic nie wysyła.
    expectNotReady();
    fireEvent.click(handoffButton());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(postsTo("/api/jobs")).toHaveLength(0);
    expect(mocks.push).not.toHaveBeenCalled();
    // „Zapisz szkic” zniknął — rekrutacja nie powstaje niekompletna.
    expect(screen.queryByRole("button", { name: "Zapisz szkic" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Dokończę później" }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs"));
    const saved = bodiesOf("/api/job-intake/forms").at(-1) as unknown as {
      label: string;
      client_id: number;
      source: string;
      request_text: string;
      form: { step: string; missing: string[] };
    };
    expect(saved).toMatchObject({
      label: "Senior Java Developer",
      client_id: 7,
      source: "text",
      request_text: REQUEST,
    });
    expect(saved.form).toMatchObject({ step: "review", missing: ["budget"] });
    expect(postsTo("/api/jobs")).toHaveLength(0);
  });

  it("formularz zapisuje się sam po chwili ciszy, a stopka mówi kiedy", async () => {
    await readRequest();
    await waitFor(() => expect(postsTo("/api/job-intake/forms")).toHaveLength(1));
    expect(await screen.findByTestId("new-job-autosave")).toHaveTextContent(
      /^Formularz zapisany \d{2}:\d{2}$/,
    );
    // Kolejna zmiana idzie PUT-em na ten sam formularz (etykieta = nazwa od klienta).
    fireEvent.change(screen.getByLabelText("Nazwa od klienta, razem z numerem"), {
      target: { value: "Java Developer" },
    });
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith(
        "/api/job-intake/forms/55",
        expect.objectContaining({ label: "Java Developer" }),
      ),
    );
    // Utworzenie podaje id formularza — serwer kasuje go w tej samej transakcji.
    await createJob();
    expect(jobPostBody()).toMatchObject({ intake_form_id: 55 });
  });

  it("zmiana sprzed końca odliczania autozapisu zapisuje się przy wyjściu ze strony", async () => {
    await readRequest();
    await waitFor(() => expect(postsTo("/api/job-intake/forms")).toHaveLength(1));
    fireEvent.change(screen.getByLabelText("Nazwa od klienta, razem z numerem"), {
      target: { value: "Kotlin Developer" },
    });
    // Wyjście przed upływem 3 s — bez zapisu przy odmontowaniu zmiana by przepadła.
    cleanup();
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith(
        "/api/job-intake/forms/55",
        expect.objectContaining({ label: "Kotlin Developer" }),
      ),
    );
  });

  // Audyt 06.10.2026, N7: ukrycie karty w trakcie `POST /api/jobs` zakładało
  // nowy formularz na koncie (serwer kasował stary w tej samej transakcji).
  it("autozapis stoi od „Utwórz” do końca POST /api/jobs; po odmowie wraca", async () => {
    await readRequest();
    await waitFor(() => expect(postsTo("/api/job-intake/forms")).toHaveLength(1));
    let rejectCreate: (reason: unknown) => void = () => undefined;
    const fallback = mocks.post.getMockImplementation()!;
    mocks.post.mockImplementation((url: string, ...rest: unknown[]) =>
      url === "/api/jobs"
        ? new Promise((_, reject) => {
            rejectCreate = reject;
          })
        : fallback(url, ...rest),
    );
    await closeGaps();
    await pickRecruiter();
    // Niezapisana zmiana tuż przed „Utwórz”.
    fireEvent.change(screen.getByLabelText("Budżet PLN/h"), { target: { value: "175" } });
    fireEvent.click(handoffButton());
    await waitFor(() => expect(postsTo("/api/jobs")).toHaveLength(1));
    const formWrites = () => postsTo("/api/job-intake/forms").length + mocks.put.mock.calls.length;
    const before = formWrites();
    Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(formWrites()).toBe(before);
    // Odmowa: nic nie powstało — autozapis wraca i zapisuje formularz.
    rejectCreate({ response: { status: 500, data: { detail: "awaria" } } });
    await waitFor(() => expect(formWrites()).toBeGreaterThan(before));
    Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
  });

  it("po odczycie źródła zostają pod ręką: panel jest pusty, a treść requestu stoi obok formularza", async () => {
    await readRequest();
    // „Zmień źródło” zniknęło razem z krokami — nie ma dokąd wracać.
    expect(screen.queryByRole("button", { name: /Zmień źródło/ })).toBeNull();
    expect(
      screen.getByRole("heading", { name: "Request od klienta · Alior Bank" }),
    ).toBeInTheDocument();
    fireEvent.click(sourceAction("Wklej treść"));
    expect(screen.getByLabelText("Treść requestu")).toHaveValue("");
    // Otwarcie panelu niczego w formularzu nie zmienia.
    expect(screen.getByLabelText("Rola")).toHaveValue("Senior Java Developer");
  });

  describe("podobne rekrutacje (test na produkcji 23.09.2026)", () => {
    const similarIds = () => jobPostBody()?.similar_job_ids;

    it("podpowiedzi z osobami u klienta NIE są zaznaczone i utworzenie ich nie łączy", async () => {
      await readRequest(INTAKE, { suggestions: SIMILAR });
      const first = await screen.findByRole(
        "checkbox",
        { name: "Java Developer (zamknięta)" },
        { timeout: 3000 },
      );
      const second = screen.getByRole("checkbox", {
        name: "Senior Java — płatności",
      });
      expect(first).toHaveAttribute("aria-checked", "false");
      expect(second).toHaveAttribute("aria-checked", "false");
      expect(screen.getByTestId("similar-jobs-selected-count")).toHaveTextContent(
        "Zaznaczone: 0 z 2",
      );
      expect(
        screen.getByText(/nie zostanie połączona z żadną z nich/),
      ).toBeInTheDocument();
      // Podpowiedź liczy się z roli i pierwszych słów wierszy obowiązkowych.
      expect(bodiesOf("/api/job-similarity/preview").at(-1)).toMatchObject({
        title: "Senior Java Developer",
        must_skills: ["Java", "Spring Boot"],
        client_id: 7,
      });

      await createJob();
      expect(similarIds()).toEqual([]);
    });

    it("łączy WYŁĄCZNIE rekrutacje zaznaczone ręcznie", async () => {
      await readRequest(INTAKE, { suggestions: SIMILAR });
      const first = await screen.findByRole(
        "checkbox",
        { name: "Java Developer (zamknięta)" },
        { timeout: 3000 },
      );
      fireEvent.click(first);
      expect(first).toHaveAttribute("aria-checked", "true");
      expect(screen.getByTestId("similar-jobs-selected-count")).toHaveTextContent(
        "Zaznaczone: 1 z 2",
      );

      await createJob();
      expect(similarIds()).toEqual([4556]);
    });

    it("odznaczenie cofa wybór — zapis znowu niczego nie łączy", async () => {
      await readRequest(INTAKE, { suggestions: SIMILAR });
      const first = await screen.findByRole(
        "checkbox",
        { name: "Java Developer (zamknięta)" },
        { timeout: 3000 },
      );
      fireEvent.click(first);
      fireEvent.click(first);
      expect(first).toHaveAttribute("aria-checked", "false");
      await createJob();
      expect(similarIds()).toEqual([]);
    });
  });
});

// Audyt 06.10.2026: nazwa od klienta (P9), liczba osób (N6), uwagi odczytu (N3).
describe("NewJobPage — nazwa od klienta, liczba osób i uwagi z odczytu (06.10.2026)", () => {
  it("odczyt bez nazwy od klienta: pole puste, „Utwórz” zatrzymuje się z komunikatem przy polu", async () => {
    await readRequest({ ...INTAKE, client_title: null, client_reference: "ZOB-9905" });
    const field = screen.getByLabelText("Nazwa od klienta, razem z numerem") as HTMLInputElement;
    // Nie „Senior Java Developer (ZOB-9905)” złożone z roli.
    expect(field.value).toBe("");
    // Numer z odczytu obowiązuje bez nazwy.
    expect(screen.getByTestId("client-reference")).toHaveTextContent("ZOB-9905");
    await closeGaps();
    await pickRecruiter();
    await waitFor(() => expect(handoffButton()).toBeEnabled());
    fireEvent.click(handoffButton());
    expect(await screen.findByTestId("new-job-client-title-error")).toHaveTextContent(
      "Wpisz nazwę stanowiska tak, jak podał klient",
    );
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(postsTo("/api/jobs")).toHaveLength(0);

    fireEvent.change(field, { target: { value: "Python Developer (ZOB-9905)" } });
    expect(screen.queryByTestId("new-job-client-title-error")).toBeNull();
    await handoffTo();
    expect(jobPostBody()).toMatchObject({
      title: "Python Developer (ZOB-9905)",
      client_reference: "ZOB-9905",
    });
  });

  it("mail bez liczby osób: pole puste i brak na liście — bez domyślnej „1”", async () => {
    await readRequest({ ...INTAKE, headcount: null });
    expect(screen.getByLabelText("Liczba osób")).toHaveValue(null);
    expect(screen.getByRole("link", { name: "liczba osób" })).toHaveAttribute(
      "href",
      "#new-job-section-terms",
    );
    fireEvent.change(screen.getByLabelText("Liczba osób"), { target: { value: "4" } });
    await createJob();
    expect(jobPostBody()).toMatchObject({ headcount: 4 });
  });

  it("uwagi z odczytu i wiersze, które się nie zmieściły, stoją na wierzchu przy wymaganiach", async () => {
    await readRequest({
      ...INTAKE,
      advisories: ["„Ansible” nie stoi w treści requestu — wiersz pominięty."],
      dropped: ["Terraform", "Helm"],
    });
    const notes = screen.getByTestId("new-job-intake-advisories");
    expect(notes.closest("details")).toBeNull();
    expect(notes).toHaveTextContent("„Ansible” nie stoi w treści requestu — wiersz pominięty.");
    expect(notes).toHaveTextContent("Nie zmieściło się w wymaganiach: Terraform, Helm.");
  });
});

describe("NewJobPage — szablon z podobnej rekrutacji (`?from=`)", () => {
  const TEMPLATE_JOB = {
    id: 55,
    title: "Java Developer (zamknięta)",
    client_id: 7,
    client: { id: 7, name: "Alior Bank" },
    description: "Stary request klienta.",
    rate_budget_hourly: 160,
    remote_policy: "remote",
    must_skills: ["z kolumny rekrutacji"],
    // N6 (06.10.2026): kopia przenosi liczbę osób do pustego pola.
    headcount: 3,
  };
  const QUESTIONS = [
    { question: "Kafka w produkcji?", ideal_answer: "tak", deal_breaker: "Brak Kafki." },
    { question: "Umowa B2B?", ideal_answer: "tak", deal_breaker: "Tylko UoP." },
  ];
  const LEGACY_PROFILE = {
    stack: { must: [{ name: "Java 17+" }, { name: "Kafka" }], nice: [{ name: "Docker" }] },
    search: { requirements: [["Java", "JVM"]], exclude: ["junior"] },
    project: { about: "Migracja płatności." },
    screening_questions: QUESTIONS,
  };
  const ROWS_PROFILE = {
    ...LEGACY_PROFILE,
    stack: {
      rows: [
        { words: ["Go", "Golang"], level: "must" },
        { words: ["Docker"], level: "nice" },
      ],
      must: [{ name: "Go lub Golang" }],
      critical: ["Go lub Golang"],
    },
  };
  const CONVERTED = {
    rows: [
      { words: ["Java", "JVM"], level: "critical" },
      { words: ["Kafka"], level: "must" },
      { words: ["Docker"], level: "nice" },
    ],
    descriptive: ["Doświadczenie w bankowości"],
    no_critical: false,
  };

  function openTemplate(profile: unknown, converted: unknown = CONVERTED) {
    mocks.searchParams = new URLSearchParams("from=55");
    serveGets((url) => {
      if (url === "/api/jobs/55") return profile instanceof Error ? profile : TEMPLATE_JOB;
      if (url === "/api/jobs/55/champion-profile?mark_read=false")
        return { job_id: 55, champion_profile: profile };
      return undefined;
    });
    const base = mocks.post.getMockImplementation()!;
    mocks.post.mockImplementation((url: string, ...rest: unknown[]) => {
      if (url !== "/api/job-intake/requirement-rows") return base(url, ...rest);
      return converted instanceof Error
        ? Promise.reject(converted)
        : Promise.resolve({ data: converted });
    });
    renderPage();
    // Formularz stoi na stronie od wejścia — czekamy na szablon albo na błąd.
    return waitFor(() =>
      expect(
        screen.queryByTestId("new-job-fill-summary") ?? screen.queryByRole("alert"),
      ).not.toBeNull(),
    );
  }

  const rowGroups = () =>
    within(screen.getByRole("group", { name: "Wymagania — słowa kluczowe" }))
      .getAllByRole("radiogroup")
      .map((group) => [
        group.getAttribute("aria-label"),
        within(group).getByRole("radio", { checked: true }).textContent,
      ]);

  it("wypełnia formularz z klientem szablonu; stare pola wymagań zamienia na wiersze serwer", async () => {
    await openTemplate(LEGACY_PROFILE);
    // Rola zostaje pusta — nowa rekrutacja nie udaje starej.
    expect(await screen.findByLabelText("Rola")).toHaveValue("");
    expect(
      screen.getByRole("heading", { name: "Request od klienta · Alior Bank" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue("160");
    // Rola jest do wpisania — przy szablonie brak nazywa się po swojemu.
    expect(screen.getAllByText("Brak w szablonie — uzupełnij").length).toBeGreaterThan(0);
    expect(postsTo("/api/job-intake/read")).toHaveLength(0);
    expect(bodiesOf("/api/job-intake/requirement-rows")).toEqual([
      {
        must: ["Java 17+", "Kafka"],
        nice: ["Docker"],
        requirements: [["Java", "JVM"]],
        critical: null,
      },
    ]);
    // Krytyczne wybiera Delivery Lead od nowa — zamiana ich nie przenosi.
    expect(rowGroups()).toEqual([
      ["Poziom wymagania: Java", "Musi mieć"],
      ["Poziom wymagania: Kafka", "Musi mieć"],
      ["Poziom wymagania: Docker", "Mile widziane"],
    ]);
    // Pytania z szablonu przychodzą z deal breakerem, ale czekają na zatwierdzenie.
    expect(screen.getByLabelText("Treść pytania 1")).toHaveValue("Kafka w produkcji?");
    expect(screen.getByLabelText("Odpowiedź, która odpada, na pytanie 1")).toHaveValue(
      "Brak Kafki.",
    );
    expect(screen.getByText("Zatwierdzone 0 z 2")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Rola"), { target: { value: "Java Developer" } });
    // P9 (06.10.2026): tytuł rekrutacji to nazwa od klienta — szablon jej nie podaje.
    expect(
      (screen.getByLabelText("Nazwa od klienta, razem z numerem") as HTMLInputElement).value,
    ).toBe("");
    fireEvent.change(screen.getByLabelText("Nazwa od klienta, razem z numerem"), {
      target: { value: "Java Developer" },
    });
    expect(screen.getByLabelText("Liczba osób")).toHaveValue(3);
    await createJob();
    expect(jobPostBody()).toMatchObject({
      title: "Java Developer",
      headcount: 3,
      client_id: 7,
      from_job_id: 55,
      copy_questions: true,
      description: "Stary request klienta.",
      must_skills: ["Java", "Kafka"],
    });
    expect(championBody()?.stack.notes).toBe("Doświadczenie w bankowości");
    expect(championBody()?.search).toMatchObject({ exclude: ["junior"] });
  });

  it("szablon prowadzony wierszami nie pyta o zamianę", async () => {
    await openTemplate(ROWS_PROFILE);
    await screen.findByLabelText("Rola");
    expect(rowGroups()).toEqual([
      ["Poziom wymagania: Go", "Musi mieć"],
      ["Poziom wymagania: Docker", "Mile widziane"],
    ]);
    expect(postsTo("/api/job-intake/requirement-rows")).toHaveLength(0);
    expect(screen.getByRole("checkbox", { name: "Brak krytycznych" })).not.toBeChecked();
  });

  it("awaria zamiany nie blokuje szablonu — każde wymaganie to wiersz", async () => {
    await openTemplate(LEGACY_PROFILE, new Error("503"));
    await screen.findByLabelText("Rola");
    expect(rowGroups()).toEqual([
      ["Poziom wymagania: Java", "Musi mieć"],
      ["Poziom wymagania: Java 17+", "Musi mieć"],
      ["Poziom wymagania: Kafka", "Musi mieć"],
      ["Poziom wymagania: Docker", "Mile widziane"],
    ]);
  });

  it("nieudane wczytanie szablonu zostawia pusty formularz z komunikatem", async () => {
    await openTemplate(new Error("404"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się wczytać rekrutacji-szablonu.",
    );
    // Formularz jest na stronie i da się go wypełnić ręcznie albo z innego źródła.
    expect(screen.getByLabelText("Rola")).toHaveValue("");
    expect(screen.queryByTestId("new-job-source-pane")).toBeNull();
    expect(screen.queryByTestId("new-job-fill-summary")).toBeNull();
  });
});

describe("NewJobPage — ogłoszenie na portalach", () => {
  const CONFIG = {
    any_ready: true,
    portals: [
      { portal: "rocketjobs", label: "RocketJobs", state: "ready", enabled: true },
      { portal: "justjoinit", label: "JustJoin.IT", state: "not_connected", enabled: true },
    ],
  };
  const DICTIONARY = {
    categories: [{ key: "java", name: "Java" }],
    experience_levels: [],
    working_times: [],
    workplace_types: [],
  };

  function withPortals() {
    mocks.get.mockImplementation((url: string) => {
      if (url === "/api/users") return Promise.resolve({ data: [{ id: 31, name: "Rekruterka Ola" }] });
      if (url === "/api/job-portals/config") return Promise.resolve({ data: CONFIG });
      if (url === "/api/job-boards/rocketjobs/dictionaries") return Promise.resolve({ data: DICTIONARY });
      return Promise.resolve({ data: {} });
    });
  }

  async function readWithPortals(extra: (url: string) => Promise<unknown> | null = () => null) {
    withPortals();
    await readRequest();
    const base = mocks.post.getMockImplementation()!;
    mocks.post.mockImplementation((url: string, ...rest: unknown[]) => {
      if (url === "/api/job-intake/public-draft") {
        return Promise.resolve({
          data: {
            public_title: "Senior Java Developer",
            subtitle: "Płatności",
            about: "Migracja na mikroserwisy.",
            findings: [{ code: "money", message: "Kwota w opisie.", excerpt: "170 zł/h" }],
          },
        });
      }
      return extra(url) ?? base(url, ...rest);
    });
    await closeGaps();
    await pickRecruiter();
  }

  it("bez gotowego portalu sekcji nie ma", async () => {
    await readRequest();
    expect(screen.queryByText("Ogłoszenie na portalach")).toBeNull();
  });

  it("zaznaczony portal blokuje „Utwórz” do przygotowania i uzupełnienia ogłoszenia", async () => {
    await readWithPortals();
    expect(await screen.findByText("Ogłoszenie na portalach")).toBeInTheDocument();
    // Tylko gotowe portale.
    expect(screen.queryByRole("checkbox", { name: "JustJoin.IT" })).toBeNull();
    const create = screen.getByRole("button", { name: "Utwórz i opublikuj" });
    expect(create).toBeEnabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "RocketJobs" }));
    expect(create).toBeDisabled();
    expect(create).toHaveAttribute("title", expect.stringContaining("Przygotuj ogłoszenie"));

    fireEvent.click(screen.getByRole("button", { name: "Przygotuj ogłoszenie" }));
    expect(await screen.findByDisplayValue("Migracja na mikroserwisy.")).toBeInTheDocument();
    expect(screen.getByText("Kwota w opisie.")).toBeInTheDocument();
    const draftCall = mocks.post.mock.calls.find(([url]) => url === "/api/job-intake/public-draft");
    expect(draftCall?.[1]).toMatchObject({
      client_id: 7,
      location: "Warszawa",
      remote_policy: "hybrid",
      must_skills: ["Java", "Spring Boot"],
    });
    // Miasto i tryb z pól rekrutacji, kategoria jeszcze pusta.
    expect(screen.getByLabelText("Miasto")).toHaveValue("Warszawa");
    expect(create).toBeDisabled();
    fireEvent.change(await screen.findByLabelText("Kategoria"), { target: { value: "java" } });
    fireEvent.change(screen.getByLabelText("Poziom doświadczenia"), { target: { value: "senior" } });
    expect(create).toBeEnabled();
  });

  it("po publikacji rekrutacji: opis → zatwierdzenie → link → portal", async () => {
    await readWithPortals();
    fireEvent.click(await screen.findByRole("checkbox", { name: "RocketJobs" }));
    fireEvent.click(screen.getByRole("button", { name: "Przygotuj ogłoszenie" }));
    fireEvent.change(await screen.findByLabelText("Kategoria"), { target: { value: "java" } });
    fireEvent.change(screen.getByLabelText("Poziom doświadczenia"), { target: { value: "senior" } });
    fireEvent.click(screen.getByRole("button", { name: "Utwórz i opublikuj" }));

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs/900"));
    const urls = mocks.post.mock.calls.map(([url]) => url);
    const order = [
      "/api/jobs",
      "/api/jobs/900/public-profile/approve",
      "/api/invite-links",
      "/api/jobs/900/portals/rocketjobs/publish",
    ].map((u) => urls.indexOf(u));
    expect(order.every((i) => i >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(mocks.put).toHaveBeenCalledWith("/api/jobs/900/public-profile", {
      public_title: "Senior Java Developer",
      subtitle: "Płatności",
      about: "Migracja na mikroserwisy.",
    });
    const publish = mocks.post.mock.calls.find(([url]) => url === "/api/jobs/900/portals/rocketjobs/publish");
    expect(publish?.[1]).toEqual({
      options: expect.objectContaining({ category: "java", city: "Warszawa", workplace_type: "hybrid", office_days: 2, salary: null }),
    });
    expect(mocks.showSuccess).toHaveBeenCalledWith(expect.stringContaining("Ogłoszenie w kolejce: RocketJobs"));
  });

  it("awaria portalu po utworzeniu: toast i okno zlecenia, rekrutacja zostaje", async () => {
    await readWithPortals((url) =>
      url === "/api/jobs/900/portals/rocketjobs/publish"
        ? Promise.reject({ response: { status: 409, data: { detail: "Konto portalu niepołączone." } } })
        : null,
    );
    fireEvent.click(await screen.findByRole("checkbox", { name: "RocketJobs" }));
    fireEvent.click(screen.getByRole("button", { name: "Przygotuj ogłoszenie" }));
    fireEvent.change(await screen.findByLabelText("Kategoria"), { target: { value: "java" } });
    fireEvent.change(screen.getByLabelText("Poziom doświadczenia"), { target: { value: "senior" } });
    fireEvent.click(screen.getByRole("button", { name: "Utwórz i opublikuj" }));

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs/900?tab=portals"));
    expect(mocks.showError).toHaveBeenCalledWith(expect.stringContaining("Konto portalu niepołączone."));
    expect(mocks.showSuccess).not.toHaveBeenCalled();
  });
});

describe("NewJobPage — hiring manager z maila", () => {
  const WITH_HM: RequestIntakeResponse = {
    ...INTAKE,
    hiring_manager_name: "Anna Nowak",
    hiring_manager_position: "Kierownik Zespołu",
    hiring_manager_email: null,
    hiring_manager_contact_id: null,
    provenance: { hiring_manager: "request" },
  };

  async function handoff() {
    await closeGaps();
    await pickRecruiter();
    await handoffTo();
  }

  it("podpowiada osobę z podpisu i wysyła ją razem z rekrutacją", async () => {
    await readRequest(WITH_HM);
    expect(screen.getByRole("combobox", { name: "Hiring manager" })).toHaveTextContent(
      "Anna Nowak",
    );
    await handoff();
    expect(jobPostBody()).toMatchObject({
      hiring_manager: {
        new_person: { name: "Anna Nowak", position: "Kierownik Zespołu", email: null },
      },
    });
    expect(
      mocks.put.mock.calls.some(([url]) => url === "/api/jobs/900/hiring-manager"),
    ).toBe(false);
  });

  it("bez hiring managera trzeba zdecydować: osoba albo „Klient nie podał”", async () => {
    await readRequest({ ...INTAKE, hiring_manager_name: null, hiring_manager_contact_id: null });
    expect(
      screen.getByRole("link", { name: "hiring manager (albo „Klient nie podał”)" }),
    ).toHaveAttribute("href", "#new-job-section-name");
    await closeGaps();
    await pickRecruiter();
    expectNotReady();

    fireEvent.click(
      within(screen.getByTestId("new-job-hiring-manager")).getByRole("checkbox", {
        name: "Klient nie podał",
      }),
    );
    await waitFor(() => expect(screen.getByText("Gotowa do publikacji")).toBeInTheDocument());
    await handoffTo();
    expect(jobPostBody()).toMatchObject({ hiring_manager: { not_provided: true } });
  });
});

describe("NewJobPage — termin i liczba osób", () => {
  it("termin i liczba osób z maila mają chip źródła i jadą w POST", async () => {
    await readRequest({ ...INTAKE, deadline_time: "16:00" });
    const deadline = screen.getByTestId("new-job-deadline");
    expect(within(deadline).getByLabelText("Termin")).toHaveValue("2026-10-20");
    expect(within(deadline).getByLabelText("Godzina terminu (opcjonalnie)")).toHaveValue("16:00");
    expect(within(deadline).getByText("z maila")).toBeInTheDocument();
    expect(screen.getByLabelText("Liczba osób")).toHaveValue(2);
    expect(
      screen.getByText(
        "Jedna stawka — wpisz tylko „do”. Plakietka „ponad budżet” liczy się od górnej granicy i nikogo nie ukrywa.",
      ),
    ).toBeInTheDocument();
    await createJob();
    expect(jobPostBody()).toMatchObject({
      deadline: "2026-10-20",
      deadline_time: "16:00",
      deadline_not_provided: false,
      headcount: 2,
    });
  });

  it("bez terminu w mailu: „Klient nie podał” zamiast daty", async () => {
    await readRequest({ ...INTAKE, deadline: null, headcount: null });
    expect(
      screen.getByRole("link", { name: "termin (albo „Klient nie podał”)" }),
    ).toHaveAttribute("href", "#new-job-section-terms");
    // Liczba osób bez maila: pole puste, wpisuje DL (audyt 06.10.2026, N6).
    expect(screen.getByLabelText("Liczba osób")).toHaveValue(null);
    fireEvent.change(screen.getByLabelText("Liczba osób"), { target: { value: "1" } });

    fireEvent.click(
      within(screen.getByTestId("new-job-deadline")).getByRole("checkbox", {
        name: "Klient nie podał",
      }),
    );
    expect(screen.queryByRole("link", { name: "termin (albo „Klient nie podał”)" })).toBeNull();
    await createJob();
    expect(jobPostBody()).toMatchObject({
      deadline: null,
      deadline_time: null,
      deadline_not_provided: true,
      headcount: 1,
    });
  });

  it("liczba osób poniżej 1 to brak", async () => {
    await readRequest();
    fireEvent.change(screen.getByLabelText("Liczba osób"), { target: { value: "0" } });
    expect(screen.getByRole("link", { name: "liczba osób" })).toBeInTheDocument();
  });
});

describe("NewJobPage — niedokończone formularze", () => {
  const FORMS = [
    {
      id: 91,
      label: "Programista Java (ZOB 48213)",
      client_id: 7,
      client_name: "Alior Bank",
      source: "text",
      updated_at: "2026-10-03T14:12:00Z",
      expires_at: new Date(Date.now() + 5 * 86_400_000).toISOString(),
      missing_count: 3,
    },
  ];

  function withForms(saved: unknown = null) {
    serveGets((url) => {
      if (url === "/api/job-intake/forms") return { items: FORMS };
      if (url === "/api/job-intake/forms/91") return saved;
      return undefined;
    });
  }

  it("pusta strona pokazuje listę z „Dokończ” i „Usuń” (potwierdzenie w wierszu)", async () => {
    withForms();
    renderPage();
    const list = await screen.findByTestId("unfinished-intake-forms");
    expect(list).toHaveTextContent("Masz 1 niedokończony formularz");
    expect(list).toHaveTextContent("brakuje 3");
    expect(list).toHaveTextContent("usunie się sam za 5 dni");
    fireEvent.click(within(list).getByRole("button", { name: /Usuń formularz/ }));
    expect(within(list).getByText("Usunąć formularz?")).toBeInTheDocument();
    fireEvent.click(within(list).getByRole("button", { name: "Anuluj" }));
    expect(within(list).queryByText("Usunąć formularz?")).toBeNull();
    // Gdy na stronie jest już praca, lista ustępuje formularzowi.
    pickClient();
    fireEvent.change(screen.getByLabelText("Rola"), { target: { value: "Tester" } });
    expect(screen.queryByTestId("unfinished-intake-forms")).toBeNull();
  });

  it("po usunięciu formularza przy limicie bieżący zapisuje się od razu — bez kolejnej edycji", async () => {
    withForms();
    const base = mocks.post.getMockImplementation()!;
    let limitHit = true;
    mocks.post.mockImplementation((url: string, ...rest: unknown[]) => {
      if (url !== "/api/job-intake/forms" || !limitHit) return base(url, ...rest);
      return Promise.reject({
        response: { status: 409, data: { detail: { code: "forms_limit" } } },
      });
    });
    mocks.del.mockResolvedValue({ data: {} });
    renderPage();
    pickClient();
    fireEvent.change(screen.getByLabelText("Rola"), { target: { value: "Tester" } });
    // Autozapis odbija się od limitu — lista wraca, żeby było co usunąć.
    await waitFor(() => expect(postsTo("/api/job-intake/forms")).toHaveLength(1));
    const list = await screen.findByTestId("unfinished-intake-forms");
    limitHit = false;
    fireEvent.click(within(list).getByRole("button", { name: /Usuń formularz/ }));
    fireEvent.click(within(list).getByRole("button", { name: "Usuń" }));
    await waitFor(() => expect(mocks.del).toHaveBeenCalledWith("/api/job-intake/forms/91"));
    // Miejsce się zwolniło: zapis idzie od razu, a nie przy następnej zmianie w formularzu.
    await waitFor(() => expect(postsTo("/api/job-intake/forms")).toHaveLength(2));
    expect(await screen.findByTestId("new-job-autosave")).toHaveTextContent(/^Formularz zapisany/);
    expect(screen.queryByTestId("unfinished-intake-forms")).toBeNull();
  });

  it("„Dokończ” wczytuje formularz z konta — pola, treść requestu i stan zapisu", async () => {
    const saved = {
      id: 91,
      label: "Programista Java (ZOB 48213)",
      client_id: 7,
      client_name: "Alior Bank",
      source: "text",
      request_text: REQUEST,
      updated_at: "2026-10-03T14:12:00Z",
      form: {
        version: 1,
        step: "review",
        // Zapis sprzed nowych pól: brakujące dostają wartości domyślne.
        form: { title: "Java Developer", rateBudget: "150", rows: [] },
        evidence: [],
        readByAi: true,
        templateJobId: null,
        recruiterId: 31,
        assignment: "person",
        priorityLevel: "p1",
        similarJobIds: [],
        missing: [],
      },
    };
    withForms(saved);
    renderPage();
    const list = await screen.findByTestId("unfinished-intake-forms");
    fireEvent.click(within(list).getByRole("button", { name: "Dokończ" }));
    await waitFor(() => expect(screen.getByLabelText("Rola")).toHaveValue("Java Developer"));
    expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue("150");
    // Zapis bez liczby osób wraca z pustym polem (N6, 06.10.2026: bez domyślnej „1”).
    expect(screen.getByLabelText("Liczba osób")).toHaveValue(null);
    expect(
      screen.getByRole("heading", { name: "Request od klienta · Alior Bank" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("new-job-autosave")).toHaveTextContent(/^Formularz zapisany/);
    // Treść była już odczytana (`step: "review"`), więc panel źródła jest zamknięty.
    expect(screen.queryByLabelText("Treść requestu")).toBeNull();
    expect(screen.queryByTestId("unfinished-intake-forms")).toBeNull();
  });

  // Zapis sprzed 10.10.2026: w kroku 1 wpisano treść, ale jej nie odczytano.
  it("stary zapis z kroku 1 (`step: \"request\"`) wraca do panelu „Wklej treść”, nie obok formularza", async () => {
    withForms({
      id: 91,
      label: "Rekrutacja bez nazwy",
      client_id: 7,
      client_name: "Alior Bank",
      source: "text",
      request_text: REQUEST,
      updated_at: "2026-10-03T14:12:00Z",
      form: {
        version: 1,
        step: "request",
        form: {},
        evidence: [],
        readByAi: false,
        templateJobId: null,
        recruiterId: null,
        assignment: null,
        priorityLevel: "p1",
        similarJobIds: [],
        missing: [],
      },
    });
    renderPage();
    const list = await screen.findByTestId("unfinished-intake-forms");
    fireEvent.click(within(list).getByRole("button", { name: "Dokończ" }));

    await waitFor(() => expect(screen.getByLabelText("Treść requestu")).toHaveValue(REQUEST));
    expect(sourceAction("Wklej treść")).toHaveAttribute("aria-pressed", "true");
    // Nieodczytana treść nie udaje requestu, z którego powstały pola.
    expect(screen.queryByTestId("new-job-source-pane")).toBeNull();
    expect(screen.getByLabelText("Rola")).toHaveValue("");
    expect(readButton()).toBeEnabled();
    // Kolejny zapis niesie tę treść dalej jako nieodczytaną.
    fireEvent.click(screen.getByRole("button", { name: "Dokończę później" }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs"));
    expect(mocks.put).toHaveBeenCalledWith(
      "/api/job-intake/forms/91",
      expect.objectContaining({
        request_text: REQUEST,
        form: expect.objectContaining({ step: "review", requestRead: false }),
      }),
    );
  });
});
