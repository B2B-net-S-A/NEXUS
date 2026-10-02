/**
 * Strona `/jobs/new`: klient i źródło → odczyt AI → przegląd w sześciu
 * sekcjach → „Utwórz i przekaż do searchu”. Zapis idzie ZWYKŁYMI trasami
 * w stałej kolejności (rekrutacja → Champion → handoff → publikacja); awaria
 * po utworzeniu nie gubi pracy.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
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
  handoff: vi.fn(),
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
  };
  return {
    default: client,
    // `similarJobsApi` (podobne rekrutacje) i edytor wymagań wołają nazwany eksport `api`.
    api: client,
    jobsApi: { handoff: (...a: unknown[]) => mocks.handoff(...a) },
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
  ClientSinglePicker: ({ onChange }: { onChange: (c: unknown) => void }) => (
    <button
      type="button"
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
import { CLIENT_REQUIRED_TEXT } from "@/components/v2/jobs/new/NewJobSourceStep";
import { BOARD_TASKS_QUERY_KEY } from "@/lib/api/boardTasks";
import { REQUEST_BOARD_QUERY_KEY } from "@/lib/api/requestAllocation";
import type { RequestIntakeResponse } from "@/lib/job-request-intake";

const REQUEST =
  "Szukamy Senior Java Developera. Java 17+, Spring Boot. Hybrydowo 2 dni w Warszawie. Do 170 zł/h netto.";

/** Odczyt v10: wymagania jako wiersze słów kluczowych, pytania z deal breakerem. */
const INTAKE: RequestIntakeResponse = {
  role_name: "Senior Java Developer",
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
  { id: 32, name: "Sourcerka Iza", role: "sourcer", roles: [] },
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
  mocks.put.mock.calls.find(([url]) => url === "/api/jobs/900/champion-profile")?.[1] as
    | {
        stack: { rows: { words: string[]; level: string }[]; critical: unknown; notes?: string };
        search: Record<string, unknown>;
        screening_questions: Record<string, string>[];
        project: Record<string, string>;
      }
    | undefined;

/** Numer kolejny pierwszego wywołania — atrapy mają wspólny licznik. */
const callOrder = (mock: typeof mocks.post, match: (url: unknown) => boolean) =>
  mock.mock.invocationCallOrder[mock.mock.calls.findIndex(([url]) => match(url))];

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

const sourceTile = (name: RegExp) =>
  within(screen.getByRole("radiogroup", { name: "Skąd bierzemy dane?" })).getByRole("radio", {
    name,
  });

async function readRequest(intake = INTAKE, setup: Omit<ServerSetup, "intake"> = {}) {
  serve({ intake, ...setup });
  renderPage();
  fireEvent.click(screen.getByRole("button", { name: "wybierz klienta" }));
  fireEvent.change(screen.getByLabelText("Treść requestu"), {
    target: { value: REQUEST },
  });
  fireEvent.click(screen.getByRole("button", { name: "Odczytaj i przejdź dalej" }));
  await screen.findByLabelText("Rola");
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

const handoffButton = () =>
  screen.getByRole("button", { name: "Utwórz i przekaż do searchu" });

async function confirmCategory(name = "Development") {
  fireEvent.click(await screen.findByRole("button", { name: `Potwierdzam: ${name}` }));
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

async function saveDraft() {
  fireEvent.click(screen.getByRole("button", { name: "Zapisz szkic" }));
  await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs/900?tab=champion"));
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
});

describe("NewJobPage — krok 1: klient i źródło", () => {
  it("trzy kafle źródła, domyślnie „Wklej treść requestu”", () => {
    renderPage();
    const tiles = within(
      screen.getByRole("radiogroup", { name: "Skąd bierzemy dane?" }),
    ).getAllByRole("radio");
    expect(tiles).toHaveLength(3);
    expect(sourceTile(/Wklej treść requestu/)).toBeChecked();
    expect(sourceTile(/Wgraj plik/)).not.toBeChecked();
    expect(sourceTile(/Wpisz ręcznie/)).not.toBeChecked();
    expect(screen.getByLabelText("Treść requestu")).toBeInTheDocument();
  });

  it("bez klienta przycisk mówi, czego brakuje — kliknięcie pokazuje komunikat, nic nie czyta", () => {
    renderPage();
    fireEvent.change(screen.getByLabelText("Treść requestu"), { target: { value: REQUEST } });
    expect(screen.queryByRole("alert")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Najpierw wybierz klienta" }));

    expect(screen.getByRole("alert")).toHaveTextContent(CLIENT_REQUIRED_TEXT);
    expect(postsTo("/api/job-intake/read")).toHaveLength(0);
    expect(screen.queryByLabelText("Rola")).toBeNull();

    // Po wyborze klienta komunikat znika, a przycisk wraca do swojej nazwy.
    fireEvent.click(screen.getByRole("button", { name: "wybierz klienta" }));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("button", { name: "Odczytaj i przejdź dalej" })).toBeEnabled();
  });

  it("za krótka treść: przycisk nieaktywny z podpowiedzią", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "wybierz klienta" }));
    expect(screen.getByRole("button", { name: "Odczytaj i przejdź dalej" })).toBeDisabled();
    expect(
      screen.getByText("Wklej treść requestu (co najmniej 30 znaków)."),
    ).toBeInTheDocument();
  });

  it("„Wpisz ręcznie” prowadzi do pustego formularza bez wołania odczytu", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "wybierz klienta" }));
    fireEvent.click(sourceTile(/Wpisz ręcznie/));
    expect(sourceTile(/Wpisz ręcznie/)).toBeChecked();
    expect(screen.queryByLabelText("Treść requestu")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Przejdź do formularza" }));

    expect(await screen.findByLabelText("Rola")).toHaveValue("");
    expect(screen.getByText("Wypełniasz ręcznie — bez requestu.")).toBeInTheDocument();
    expect(postsTo("/api/job-intake/read")).toHaveLength(0);
    expect(postsTo("/api/job-intake/read-file")).toHaveLength(0);
    // Wszystko poza biurem (tryb nieznany) jest do uzupełnienia.
    expect(screen.getByText("Brakuje 7 rzeczy do searchu")).toBeInTheDocument();
  });

  it("„Wgraj plik” wysyła plik do odczytu razem z klientem", async () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "wybierz klienta" }));
    fireEvent.click(sourceTile(/Wgraj plik/));
    const read = screen.getByRole("button", { name: "Odczytaj i przejdź dalej" });
    expect(read).toBeDisabled();
    expect(screen.getByText("Wybierz plik z requestem.")).toBeInTheDocument();

    const file = new File(["treść requestu"], "request.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });
    fireEvent.change(screen.getByLabelText(/Plik z requestem/), { target: { files: [file] } });
    fireEvent.click(read);

    expect(await screen.findByLabelText("Rola")).toHaveValue("Senior Java Developer");
    const [[, body, config]] = postsTo("/api/job-intake/read-file");
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get("client_id")).toBe("7");
    expect(((body as FormData).get("file") as File).name).toBe("request.docx");
    expect(config).toMatchObject({ timeout: 120_000 });
    expect(postsTo("/api/job-intake/read")).toHaveLength(0);
  });

  it("awaria odczytu AI zostawia request i pozwala wypełnić ręcznie", async () => {
    mocks.post.mockRejectedValueOnce({
      response: {
        status: 503,
        data: { detail: "Model AI chwilowo niedostępny — spróbuj za chwilę." },
      },
    });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "wybierz klienta" }));
    fireEvent.change(screen.getByLabelText("Treść requestu"), {
      target: { value: REQUEST },
    });
    fireEvent.click(screen.getByRole("button", { name: "Odczytaj i przejdź dalej" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Model AI chwilowo niedostępny",
    );
    expect(screen.getByLabelText("Treść requestu")).toHaveValue(REQUEST);

    // Zmiana kafla zdejmuje błąd odczytu.
    fireEvent.click(sourceTile(/Wpisz ręcznie/));
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Przejdź do formularza" }));
    expect(await screen.findByLabelText("Rola")).toHaveValue("");
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

  it("przekazanie do searchu wymaga rekrutera, potem zapisuje w stałej kolejności", async () => {
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
    });
    expect(mocks.put).toHaveBeenCalledWith(
      "/api/jobs/900/champion-profile",
      expect.objectContaining({
        project: { about: "Migracja płatności.", responsibilities: "" },
      }),
    );
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
    expect(mocks.handoff).toHaveBeenCalledWith(900, 31, undefined, "linkedin");
    expect(mocks.post).toHaveBeenCalledWith("/api/jobs/900/publish");
    const steps = [
      callOrder(mocks.post, (url) => url === "/api/jobs"),
      callOrder(mocks.put, (url) => url === "/api/jobs/900/champion-profile"),
      mocks.handoff.mock.invocationCallOrder[0],
      callOrder(mocks.post, (url) => url === "/api/jobs/900/publish"),
    ];
    expect([...steps].sort((a, b) => a - b)).toEqual(steps);
    expect(mocks.showSuccess).toHaveBeenCalled();
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

      await saveDraft();
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
      await saveDraft();
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
      await saveDraft();
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

      await saveDraft();
      expect(jobPostBody()).toMatchObject({ working_title: "Java do płatności" });
    });

    it("bez ręcznej zmiany tytuł dla zespołu nie jedzie — składa go serwer", async () => {
      await readRequest();
      await saveDraft();
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
      expect(handoffButton()).toBeDisabled();
      expect(screen.getByText("Brakuje 1 rzeczy do searchu")).toBeInTheDocument();

      fireEvent.click(screen.getByRole("checkbox", { name: "Brak krytycznych" }));
      expect(screen.getByText("Gotowa do searchu")).toBeInTheDocument();
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
      expect(await screen.findByText("Gotowa do searchu")).toBeInTheDocument();
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
      expect(handoffButton()).toBeDisabled();

      fireEvent.click(screen.getByRole("button", { name: "Zatwierdź pytanie 1" }));
      expect(screen.getByText("Zatwierdzone 1 z 2")).toBeInTheDocument();
      expect(handoffButton()).toBeDisabled();

      fireEvent.click(screen.getByRole("button", { name: "Zatwierdź wszystkie" }));
      expect(screen.getByText("2 pytania — wszystkie zatwierdzone")).toBeInTheDocument();
      expect(handoffButton()).toBeEnabled();
    });

    it("usunięty deal breaker blokuje, choć pytanie było zatwierdzone", async () => {
      await readRequest();
      await closeGaps();
      await pickRecruiter();
      expect(handoffButton()).toBeEnabled();

      fireEvent.change(screen.getByLabelText("Odpowiedź, która odpada, na pytanie 2"), {
        target: { value: " " },
      });
      expect(handoffButton()).toBeDisabled();
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
      expect(handoffButton()).toBeDisabled();
      fireEvent.change(screen.getByLabelText("Odpowiedź, która odpada, na pytanie 3"), {
        target: { value: "Tylko umowa o pracę." },
      });
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
    const overrides = () => postsTo("/api/jobs/900/cc-override");

    it("podpowiedź liczy serwer z roli, opisu i wymagań", async () => {
      await readRequest();
      await categorySettled();
      expect(bodiesOf("/api/job-intake/category-suggestion").at(-1)).toEqual({
        role: "Senior Java Developer",
        client_title: undefined,
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
      expect(handoffButton()).toBeDisabled();

      await confirmCategory();
      expect(
        screen.getByText(/Kategoria potwierdzona: Development\. Uczestnikami zostaną wszyscy z tej\s+kategorii \(7 osób\)/),
      ).toBeInTheDocument();
      expect(handoffButton()).toBeEnabled();

      await handoffTo();
      expect(jobPostBody()).toMatchObject({ competence_category_id: 2 });
      // Kategoria zgodna z podpowiedzią — nie ma czego zgłaszać regułom klasyfikacji.
      expect(overrides()).toHaveLength(0);
    });

    it("inna kategoria niż podpowiedź: wybór ją potwierdza i zgłasza różnicę po utworzeniu", async () => {
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
      expect(overrides()).toEqual([
        ["/api/jobs/900/cc-override", { suggested_cc_id: 2, final_cc_id: 4 }],
      ]);
    });

    it("system bez podpowiedzi: kategorię wybiera Delivery Lead, różnicy nie ma z czym porównać", async () => {
      await readRequest(INTAKE, { category: { suggested_id: null, categories: CATEGORIES } });
      await categorySettled();
      expect(
        await screen.findByText(/System nie rozpoznał kategorii z nazwy roli — wybierz ją\./),
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Zatwierdź wszystkie" }));
      await pickRecruiter();
      expect(handoffButton()).toBeDisabled();

      fireEvent.click(categoryOption(/^Infra/));
      await handoffTo();
      expect(jobPostBody()).toMatchObject({ competence_category_id: 1 });
      expect(overrides()).toHaveLength(0);
    });

    it("szkic bez potwierdzenia zapisuje podpowiedzianą kategorię", async () => {
      await readRequest();
      await screen.findByRole("button", { name: "Potwierdzam: Development" });
      await saveDraft();
      expect(jobPostBody()).toMatchObject({ competence_category_id: 2 });
      expect(overrides()).toHaveLength(0);
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
      fireEvent.click(screen.getByRole("button", { name: "wybierz klienta" }));
      fireEvent.click(sourceTile(/Wpisz ręcznie/));
      fireEvent.click(screen.getByRole("button", { name: "Przejdź do formularza" }));

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
        "Wybierz rekrutera prowadzącego, żeby przekazać do searchu",
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

      expect(mocks.post).toHaveBeenCalledWith("/api/jobs/900/handoff", {
        assignment_mode: "automatic",
        channel: "linkedin",
      });
      expect(mocks.handoff).not.toHaveBeenCalled();
      expect(mocks.post).toHaveBeenCalledWith("/api/jobs/900/publish");
      expect(mocks.showSuccess).toHaveBeenCalledWith(
        "Rekrutacja utworzona i przekazana do searchu. Rekrutera zaproponuje automat, a zatwierdzi Head of Recruitment.",
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
        "Rekrutacja utworzona i przekazana do searchu. Rekrutera prowadzącego przydzieli automat — zwykle w ciągu minuty.",
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

      expect(mocks.handoff).toHaveBeenCalledWith(900, 31, undefined, "linkedin");
      expect(
        mocks.post.mock.calls.some(([url]) => url === "/api/jobs/900/handoff"),
      ).toBe(false);
    });

    it("priorytet „Przyjmujemy kandydatów” przy automacie: mówi wprost, że nikt nie zostanie zaproponowany", async () => {
      allocationOptions(true, "shadow");
      await readRequest();
      await closeGaps();
      const group = await recruiterGroup();
      await waitFor(() => expect(automatOption(group)).toBeChecked());

      fireEvent.click(
        within(screen.getByRole("radiogroup", { name: "Priorytet" })).getByRole("radio", {
          name: "Przyjmujemy kandydatów",
        }),
      );

      expect(
        screen.getByText(
          "Przy priorytecie „Przyjmujemy kandydatów” automat nikogo nie proponuje — rekrutacja zostanie bez rekrutera, dopóki ktoś jej nie weźmie albo nie wskażesz osoby.",
        ),
      ).toBeInTheDocument();
      expect(screen.queryByText(/Propozycję zatwierdza Head of Recruitment/)).toBeNull();

      await handoffTo();
      expect(jobPostBody()).toMatchObject({ priority: "low" });
      expect(mocks.showSuccess).toHaveBeenCalledWith(
        "Rekrutacja utworzona i przekazana do searchu. Rekrutacja zostaje bez rekrutera — przy priorytecie „Przyjmujemy kandydatów” automat nikogo nie proponuje.",
      );
    });

    it("odmowa automatycznego handoffu: rekrutacja zostaje, przejście do Championa", async () => {
      allocationOptions(true, "auto");
      await readRequest();
      await closeGaps();
      const fallback = mocks.post.getMockImplementation()!;
      mocks.post.mockImplementation((url: string, ...rest: unknown[]) =>
        url === "/api/jobs/900/handoff"
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
      await handoffTo("/jobs/900?tab=champion");
      expect(mocks.showError).toHaveBeenCalledWith(
        "Rekrutacja zapisana jako szkic — nie przekazano do searchu: Automat przydziału jest wyłączony — wybierz rekrutera ręcznie.",
      );
      expect(mocks.post).not.toHaveBeenCalledWith("/api/jobs/900/publish");
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

    it("nowa rekrutacja zaczyna od P2 i tak idzie do POST /api/jobs", async () => {
      await readRequest();
      expect(
        within(screen.getByRole("radiogroup", { name: "Priorytet" }))
          .getAllByRole("radio")
          .map((radio) => radio.textContent),
      ).toEqual(["P1 Pilne", "P2 Standard", "Przyjmujemy kandydatów"]);
      expect(priorityOption("P2 Standard")).toBeChecked();

      await pickRecruiterAndHandoff();

      expect(jobPostBody()).toMatchObject({ priority: "medium" });
    });

    it("P1 idzie jako „urgent” — także przy zapisie szkicu", async () => {
      await readRequest();
      fireEvent.click(priorityOption("P1 Pilne"));
      expect(priorityOption("P1 Pilne")).toBeChecked();

      await saveDraft();
      expect(jobPostBody()).toMatchObject({ priority: "urgent" });
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
      "Rekrutacja utworzona i przekazana do searchu.",
    );
  });

  it("nieudana publikacja — błąd bez toastu sukcesu (REC-04)", async () => {
    await readRequest();
    const fallback = mocks.post.getMockImplementation()!;
    mocks.post.mockImplementation((url: string, ...rest: unknown[]) =>
      url === "/api/jobs/900/publish"
        ? Promise.reject({ response: { status: 409, data: { detail: "nie" } } })
        : fallback(url, ...rest),
    );
    await closeGaps();
    await pickRecruiter();
    await handoffTo();
    expect(mocks.showError).toHaveBeenCalledWith(
      expect.stringContaining("nie opublikowana"),
    );
    expect(mocks.showSuccess).not.toHaveBeenCalledWith(
      "Rekrutacja utworzona i przekazana do searchu.",
    );
  });

  it("braki w requeście blokują przekazanie, a szkic da się zapisać", async () => {
    await readRequest({
      ...INTAKE,
      rate_budget_hourly: null,
      rate_quote: null,
    });
    // Po odczycie: budżet + zatwierdzenie pytań + potwierdzenie kategorii.
    expect(
      await screen.findByText("Brakuje 3 rzeczy do searchu"),
    ).toBeInTheDocument();
    await closeGaps();
    await pickRecruiter();
    expect(screen.getByText("Brakuje 1 rzeczy do searchu")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "budżet PLN/h" })).toHaveAttribute(
      "href",
      "#new-job-section-terms",
    );
    expect(handoffButton()).toBeDisabled();
    expect(handoffButton()).toHaveAttribute(
      "title",
      "Uzupełnij braki, żeby przekazać do searchu",
    );

    await saveDraft();
    expect(mocks.handoff).not.toHaveBeenCalled();
  });

  it("nieudany zapis Championa nie gubi rekrutacji — prowadzi do jej profilu", async () => {
    mocks.put.mockRejectedValueOnce({
      response: { status: 500, data: { detail: "boom" } },
    });
    await readRequest();
    await saveDraft();
    expect(mocks.showError).toHaveBeenCalledWith(
      expect.stringContaining("Rekrutacja zapisana"),
    );
  });

  it("„Zmień źródło” wraca do kroku 1 z zachowanym requestem", async () => {
    await readRequest();
    fireEvent.click(screen.getByRole("button", { name: /Zmień źródło/ }));
    expect(screen.getByLabelText("Treść requestu")).toHaveValue(REQUEST);
    expect(sourceTile(/Wklej treść requestu/)).toBeChecked();
  });

  describe("podobne rekrutacje (test na produkcji 23.09.2026)", () => {
    const similarPosts = () =>
      mocks.post.mock.calls.filter(([url]) => url === "/api/jobs/900/similar");

    it("podpowiedzi z osobami u klienta NIE są zaznaczone i szkic ich nie łączy", async () => {
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

      await saveDraft();
      expect(similarPosts()).toHaveLength(0);
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

      await saveDraft();
      expect(similarPosts()).toEqual([
        ["/api/jobs/900/similar", { job_ids: [4556] }],
      ]);
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
      await saveDraft();
      expect(similarPosts()).toHaveLength(0);
    });
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
  }

  const rowGroups = () =>
    within(screen.getByRole("group", { name: "Wymagania — słowa kluczowe" }))
      .getAllByRole("radiogroup")
      .map((group) => [
        group.getAttribute("aria-label"),
        within(group).getByRole("radio", { checked: true }).textContent,
      ]);

  it("otwiera od razu krok 2 z klientem szablonu; stare pola wymagań zamienia na wiersze serwer", async () => {
    openTemplate(LEGACY_PROFILE);
    // Rola zostaje pusta — nowa rekrutacja nie udaje starej.
    expect(await screen.findByLabelText("Rola")).toHaveValue("");
    expect(
      screen.getByRole("heading", { name: "Request od klienta · Alior Bank" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Budżet PLN/h")).toHaveValue("160");
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
    await saveDraft();
    expect(jobPostBody()).toMatchObject({
      title: "Java Developer",
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
    openTemplate(ROWS_PROFILE);
    await screen.findByLabelText("Rola");
    expect(rowGroups()).toEqual([
      ["Poziom wymagania: Go", "Musi mieć"],
      ["Poziom wymagania: Docker", "Mile widziane"],
    ]);
    expect(postsTo("/api/job-intake/requirement-rows")).toHaveLength(0);
    expect(screen.getByRole("checkbox", { name: "Brak krytycznych" })).not.toBeChecked();
  });

  it("awaria zamiany nie blokuje szablonu — każde wymaganie to wiersz", async () => {
    openTemplate(LEGACY_PROFILE, new Error("503"));
    await screen.findByLabelText("Rola");
    expect(rowGroups()).toEqual([
      ["Poziom wymagania: Java", "Musi mieć"],
      ["Poziom wymagania: Java 17+", "Musi mieć"],
      ["Poziom wymagania: Kafka", "Musi mieć"],
      ["Poziom wymagania: Docker", "Mile widziane"],
    ]);
  });

  it("nieudane wczytanie szablonu zostawia krok 1 z komunikatem", async () => {
    openTemplate(new Error("404"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Nie udało się wczytać rekrutacji-szablonu.",
    );
    expect(screen.queryByLabelText("Rola")).toBeNull();
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
    const create = screen.getByRole("button", { name: "Utwórz i przekaż do searchu" });
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
    fireEvent.click(screen.getByRole("button", { name: "Utwórz i przekaż do searchu" }));

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs/900"));
    const urls = mocks.post.mock.calls.map(([url]) => url);
    const order = [
      "/api/jobs/900/publish",
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
    fireEvent.click(screen.getByRole("button", { name: "Utwórz i przekaż do searchu" }));

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

  it("podpowiada osobę z podpisu i zapisuje ją po utworzeniu, przed Championem", async () => {
    await readRequest(WITH_HM);
    expect(screen.getByRole("combobox", { name: "Hiring manager" })).toHaveTextContent(
      "Anna Nowak",
    );
    await handoff();
    const putUrls = mocks.put.mock.calls.map(([url]) => url);
    expect(putUrls.indexOf("/api/jobs/900/hiring-manager")).toBeLessThan(
      putUrls.indexOf("/api/jobs/900/champion-profile"),
    );
    expect(mocks.put).toHaveBeenCalledWith("/api/jobs/900/hiring-manager", {
      new_person: { name: "Anna Nowak", position: "Kierownik Zespołu", email: null },
    });
  });

  it("awaria zapisu hiring managera nie zatrzymuje utworzenia rekrutacji", async () => {
    mocks.put.mockImplementation((url: string) =>
      url === "/api/jobs/900/hiring-manager"
        ? Promise.reject({ response: { status: 422, data: { detail: "zły" } } })
        : Promise.resolve({ data: {} }),
    );
    await readRequest(WITH_HM);
    await handoff();
    expect(mocks.showError).toHaveBeenCalledWith(
      expect.stringContaining("Rekrutacja zapisana, ale hiring manager nie"),
    );
    expect(mocks.handoff).toHaveBeenCalled();
  });

  it("bez hiring managera nie woła trasy", async () => {
    await readRequest();
    await handoff();
    expect(
      mocks.put.mock.calls.some(([url]) => url === "/api/jobs/900/hiring-manager"),
    ).toBe(false);
  });
});
