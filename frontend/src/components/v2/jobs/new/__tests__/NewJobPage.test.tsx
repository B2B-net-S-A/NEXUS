/**
 * Strona `/jobs/new`: request → odczyt AI → przegląd → „Utwórz i przekaż do
 * searchu”. Zapis idzie ZWYKŁYMI trasami w stałej kolejności (rekrutacja →
 * Champion → handoff → publikacja); awaria po utworzeniu nie gubi pracy.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
    // `similarJobsApi` (podobne rekrutacje) woła nazwany eksport `api`.
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
import { BOARD_TASKS_QUERY_KEY } from "@/lib/api/boardTasks";
import { REQUEST_BOARD_QUERY_KEY } from "@/lib/api/requestAllocation";
import type { RequestIntakeResponse } from "@/lib/job-request-intake";

const REQUEST =
  "Szukamy Senior Java Developera. Java 17+, Spring Boot. Hybrydowo 2 dni w Warszawie. Do 170 zł/h netto.";

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
    { question: "Kafka?", ideal_answer: "", from_request: true },
    { question: "Biuro?", ideal_answer: "", from_request: false },
  ],
  evidence: ["Java 17+"],
  missing: [],
  // v5: wymagania do wyszukiwania w bazie (bramka handoffu od 25.09.2026).
  search_requirements: [["Java 17+"], ["Spring Boot"]],
};

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

const jobPostBody = () =>
  mocks.post.mock.calls.find(([url]) => url === "/api/jobs")?.[1] as
    | Record<string, unknown>
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

async function readRequest(intake = INTAKE, suggestions: unknown[] = []) {
  mocks.post.mockImplementation((url: string) => {
    if (url === "/api/job-intake/read") {
      return Promise.resolve({ data: { text: REQUEST, intake } });
    }
    if (url === "/api/jobs") return Promise.resolve({ data: { id: 900 } });
    if (url === "/api/job-similarity/preview") {
      return Promise.resolve({ data: { suggestions } });
    }
    if (url === "/api/jobs/900/similar") {
      return Promise.resolve({
        data: { reassigned_now: 0, linked_now: 1, linked: [], suggestions: [] },
      });
    }
    return Promise.resolve({ data: {} });
  });
  renderPage();
  fireEvent.click(screen.getByRole("button", { name: "wybierz klienta" }));
  fireEvent.change(screen.getByLabelText("Request od klienta"), {
    target: { value: REQUEST },
  });
  fireEvent.click(screen.getByRole("button", { name: /Odczytaj request/ }));
  await screen.findByLabelText("Rola");
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.refreshClientHistory.mockReturnValue(Promise.resolve({ data: {} }));
  mocks.get.mockImplementation((url: string) =>
    Promise.resolve({
      data:
        url === "/api/users"
          ? [
              { id: 31, name: "Rekruterka Ola", role: "recruiter", roles: [] },
              { id: 32, name: "Sourcerka Iza", role: "sourcer", roles: [] },
            ]
          : {},
    }),
  );
  mocks.put.mockResolvedValue({ data: {} });
  mocks.handoff.mockResolvedValue({ data: {} });
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

  it("przekazanie do searchu wymaga rekrutera, potem zapisuje w stałej kolejności", async () => {
    await readRequest();
    const handoffButton = screen.getByRole("button", {
      name: "Utwórz i przekaż do searchu",
    });
    expect(handoffButton).toBeDisabled();

    await screen.findByRole("option", { name: "Rekruterka Ola" });
    fireEvent.change(screen.getByLabelText("Wybierz rekrutera"), {
      target: { value: "31" },
    });
    fireEvent.click(handoffButton);

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs/900"));
    const jobPost = mocks.post.mock.calls.find(([url]) => url === "/api/jobs");
    expect(jobPost?.[1]).toMatchObject({
      title: "Senior Java Developer",
      client_id: 7,
      rate_budget_hourly: 170,
      remote_policy: "hybrid",
    });
    expect(mocks.put).toHaveBeenCalledWith(
      "/api/jobs/900/champion-profile",
      expect.objectContaining({
        project: { about: "Migracja płatności.", responsibilities: "" },
      }),
    );
    expect(mocks.handoff).toHaveBeenCalledWith(900, 31, undefined, "linkedin");
    expect(mocks.post).toHaveBeenCalledWith("/api/jobs/900/publish");
    expect(mocks.showSuccess).toHaveBeenCalled();
    // Podsumowanie historii klienta rusza w tle — bez czekania na wynik.
    expect(mocks.refreshClientHistory).toHaveBeenCalledWith(900);
  });

  describe("„Rekruter”: zaproponuje automat albo wybieram sam (decyzje 29.09 i 02.10.2026)", () => {
    function allocationOptions(automatic_enabled: boolean, mode: string) {
      mocks.get.mockImplementation((url: string) => {
        if (url === "/api/users") {
          return Promise.resolve({
            data: [
              { id: 31, name: "Rekruterka Ola", role: "recruiter", roles: [] },
              { id: 32, name: "Sourcerka Iza", role: "sourcer", roles: [] },
            ],
          });
        }
        if (url === "/api/job-intake/handoff-options") {
          return Promise.resolve({ data: { automatic_enabled, mode } });
        }
        return Promise.resolve({ data: {} });
      });
    }

    const recruiterGroup = () => screen.findByRole("radiogroup", { name: "Rekruter" });
    const automatOption = (group: HTMLElement) =>
      within(group).getByRole("radio", { name: "Zaproponuje automat" });
    const personOption = (group: HTMLElement) =>
      within(group).getByRole("radio", { name: "Wybieram sam" });

    it("przy wyłączonym automacie opcja jest widoczna, ale nieaktywna — z powodem", async () => {
      allocationOptions(false, "off");
      await readRequest();
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
      expect(
        screen.getByRole("button", { name: "Utwórz i przekaż do searchu" }),
      ).toBeDisabled();
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
      const group = await recruiterGroup();
      await waitFor(() => expect(automatOption(group)).toBeChecked());
      expect(automatOption(group)).toBeEnabled();
      expect(
        screen.getByText(
          "Automat zaproponuje osobę według kategorii i obłożenia. Propozycję zatwierdza Head of Recruitment — do tego czasu nikt nie jest przypisany.",
        ),
      ).toBeInTheDocument();
      // Listy osób ani „Kolejnych osób” nie ma — nie ma czego wybierać.
      expect(screen.queryByLabelText("Wybierz rekrutera")).toBeNull();
      expect(screen.queryByText("Kolejne osoby")).toBeNull();

      const handoffButton = screen.getByRole("button", {
        name: "Utwórz i przekaż do searchu",
      });
      expect(handoffButton).toBeEnabled();
      fireEvent.click(handoffButton);

      await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs/900"));
      expect(mocks.post).toHaveBeenCalledWith("/api/jobs/900/handoff", {
        assignment_mode: "automatic",
        channel: "linkedin",
      });
      expect(mocks.handoff).not.toHaveBeenCalled();
      expect(mocks.post).toHaveBeenCalledWith("/api/jobs/900/publish");
      expect(
        mocks.post.mock.calls.some(([url]) => url === "/api/jobs/900/collaborators"),
      ).toBe(false);
      expect(mocks.showSuccess).toHaveBeenCalledWith(
        "Rekrutacja utworzona i przekazana do searchu. Rekrutera zaproponuje automat, a zatwierdzi Head of Recruitment.",
      );
    });

    it("tryb „auto” mówi, że automat sam przydzieli osobę", async () => {
      allocationOptions(true, "auto");
      await readRequest();
      const group = await recruiterGroup();
      await waitFor(() => expect(automatOption(group)).toBeChecked());
      expect(
        screen.getByText("Automat przydzieli osobę według kategorii i obłożenia."),
      ).toBeInTheDocument();
    });

    it("„Wybieram sam” przy włączonym automacie: lista osób, przypisanie od razu, bez automatu", async () => {
      allocationOptions(true, "shadow");
      await readRequest();
      const group = await recruiterGroup();
      await waitFor(() => expect(automatOption(group)).toBeChecked());

      fireEvent.click(personOption(group));

      expect(personOption(group)).toBeChecked();
      expect(
        screen.getByText("Wskazane osoby są przypisane od razu, bez akceptacji."),
      ).toBeInTheDocument();
      const handoffButton = screen.getByRole("button", {
        name: "Utwórz i przekaż do searchu",
      });
      // Sam wybór trybu to za mało — trzeba wskazać osobę.
      expect(handoffButton).toBeDisabled();
      await screen.findByRole("option", { name: "Rekruterka Ola" });
      fireEvent.change(screen.getByLabelText("Wybierz rekrutera"), {
        target: { value: "31" },
      });
      fireEvent.click(handoffButton);

      await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs/900"));
      expect(mocks.handoff).toHaveBeenCalledWith(900, 31, undefined, "linkedin");
      expect(
        mocks.post.mock.calls.some(([url]) => url === "/api/jobs/900/handoff"),
      ).toBe(false);
    });

    it("priorytet „Przyjmujemy kandydatów” przy automacie: mówi wprost, że nikt nie zostanie zaproponowany", async () => {
      allocationOptions(true, "shadow");
      await readRequest();
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

      fireEvent.click(screen.getByRole("button", { name: "Utwórz i przekaż do searchu" }));

      await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs/900"));
      expect(jobPostBody()).toMatchObject({ priority: "low" });
      expect(mocks.showSuccess).toHaveBeenCalledWith(
        "Rekrutacja utworzona i przekazana do searchu. Rekrutacja zostaje bez rekrutera — przy priorytecie „Przyjmujemy kandydatów” automat nikogo nie proponuje.",
      );
    });

    it("odmowa automatycznego handoffu: rekrutacja zostaje, przejście do Championa", async () => {
      allocationOptions(true, "auto");
      await readRequest();
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
      await waitFor(() => expect(automatOption(group)).toBeChecked());
      fireEvent.click(
        screen.getByRole("button", { name: "Utwórz i przekaż do searchu" }),
      );
      await waitFor(() =>
        expect(mocks.push).toHaveBeenCalledWith("/jobs/900?tab=champion"),
      );
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
      await screen.findByRole("option", { name: "Rekruterka Ola" });
      fireEvent.change(screen.getByLabelText("Wybierz rekrutera"), {
        target: { value: "31" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Utwórz i przekaż do searchu" }));
      await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs/900"));
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

      fireEvent.click(screen.getByRole("button", { name: "Zapisz szkic" }));

      await waitFor(() =>
        expect(mocks.push).toHaveBeenCalledWith("/jobs/900?tab=champion"),
      );
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

  it("awaria listy rekruterów → komunikat z „Ponów” przy polu „Rekruter” (R8-N14-6)", async () => {
    let calls = 0;
    mocks.get.mockImplementation((url: string, config?: { params?: unknown }) => {
      // Lista pola „Rekruter” pyta z `params.roles`; katalog pola „Kolejne
      // osoby” (ten sam adres, bez parametrów) nie jest tu testowany.
      if (url === "/api/users" && !config?.params) {
        return Promise.resolve({ data: [] });
      }
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
    await screen.findByRole("option", { name: "Rekruterka Ola" });
    fireEvent.change(screen.getByLabelText("Wybierz rekrutera"), {
      target: { value: "31" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Utwórz i przekaż do searchu" }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs/900"));
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
    await screen.findByRole("option", { name: "Rekruterka Ola" });
    fireEvent.change(screen.getByLabelText("Wybierz rekrutera"), {
      target: { value: "31" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Utwórz i przekaż do searchu" }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs/900"));
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
    expect(
      await screen.findByText("Brakuje 1 rzeczy do searchu"),
    ).toBeInTheDocument();
    expect(screen.getByText("budżet PLN/h")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Zapisz szkic" }));
    await waitFor(() =>
      expect(mocks.push).toHaveBeenCalledWith("/jobs/900?tab=champion"),
    );
    expect(mocks.handoff).not.toHaveBeenCalled();
  });

  it("nieudany zapis Championa nie gubi rekrutacji — prowadzi do jej profilu", async () => {
    mocks.put.mockRejectedValueOnce({
      response: { status: 500, data: { detail: "boom" } },
    });
    await readRequest();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz szkic" }));
    await waitFor(() =>
      expect(mocks.push).toHaveBeenCalledWith("/jobs/900?tab=champion"),
    );
    expect(mocks.showError).toHaveBeenCalledWith(
      expect.stringContaining("Rekrutacja zapisana"),
    );
  });

  it("awaria odczytu AI zostawia request i proponuje wypełnienie ręczne", async () => {
    mocks.post.mockRejectedValueOnce({
      response: {
        status: 503,
        data: { detail: "Model AI chwilowo niedostępny — spróbuj za chwilę." },
      },
    });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "wybierz klienta" }));
    fireEvent.change(screen.getByLabelText("Request od klienta"), {
      target: { value: REQUEST },
    });
    fireEvent.click(screen.getByRole("button", { name: /Odczytaj request/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Model AI chwilowo niedostępny",
    );
    expect(screen.getByLabelText("Request od klienta")).toHaveValue(REQUEST);
    fireEvent.click(
      screen.getByRole("button", { name: "Wypełnij ręcznie, bez AI" }),
    );
    expect(await screen.findByLabelText("Rola")).toHaveValue("");
  });

  describe("podobne rekrutacje (test na produkcji 23.09.2026)", () => {
    const similarPosts = () =>
      mocks.post.mock.calls.filter(([url]) => url === "/api/jobs/900/similar");

    it("podpowiedzi z osobami u klienta NIE są zaznaczone i szkic ich nie łączy", async () => {
      await readRequest(INTAKE, SIMILAR);
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

      fireEvent.click(screen.getByRole("button", { name: "Zapisz szkic" }));
      await waitFor(() =>
        expect(mocks.push).toHaveBeenCalledWith("/jobs/900?tab=champion"),
      );
      expect(similarPosts()).toHaveLength(0);
    });

    it("łączy WYŁĄCZNIE rekrutacje zaznaczone ręcznie", async () => {
      await readRequest(INTAKE, SIMILAR);
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

      fireEvent.click(screen.getByRole("button", { name: "Zapisz szkic" }));
      await waitFor(() =>
        expect(mocks.push).toHaveBeenCalledWith("/jobs/900?tab=champion"),
      );
      expect(similarPosts()).toEqual([
        ["/api/jobs/900/similar", { job_ids: [4556] }],
      ]);
    });

    it("odznaczenie cofa wybór — zapis znowu niczego nie łączy", async () => {
      await readRequest(INTAKE, SIMILAR);
      const first = await screen.findByRole(
        "checkbox",
        { name: "Java Developer (zamknięta)" },
        { timeout: 3000 },
      );
      fireEvent.click(first);
      fireEvent.click(first);
      expect(first).toHaveAttribute("aria-checked", "false");
      fireEvent.click(screen.getByRole("button", { name: "Zapisz szkic" }));
      await waitFor(() =>
        expect(mocks.push).toHaveBeenCalledWith("/jobs/900?tab=champion"),
      );
      expect(similarPosts()).toHaveLength(0);
    });
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
    await screen.findByRole("option", { name: "Rekruterka Ola" });
    fireEvent.change(screen.getByLabelText("Wybierz rekrutera"), { target: { value: "31" } });
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
    expect(draftCall?.[1]).toMatchObject({ client_id: 7, location: "Warszawa", remote_policy: "hybrid" });
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
    await screen.findByRole("option", { name: "Rekruterka Ola" });
    fireEvent.change(screen.getByLabelText("Wybierz rekrutera"), {
      target: { value: "31" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Utwórz i przekaż do searchu" }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs/900"));
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

describe("NewJobPage — kolejne osoby (29.09 i 02.10.2026)", () => {
  async function pickCollaboratorAndHandoff() {
    const user = userEvent.setup();
    await screen.findByRole("option", { name: "Rekruterka Ola" });
    fireEvent.change(screen.getByLabelText("Wybierz rekrutera"), {
      target: { value: "31" },
    });
    await user.click(screen.getByRole("button", { name: /^Kolejne osoby:/ }));
    // Pierwszej rekruterki nie da się wybrać drugi raz — serwer odpowiedziałby 409.
    const list = await screen.findByRole("listbox");
    expect(within(list).queryByText("Rekruterka Ola")).toBeNull();
    await user.click(within(list).getByText("Sourcerka Iza"));
    await user.keyboard("{Escape}");
    fireEvent.click(screen.getByRole("button", { name: "Utwórz i przekaż do searchu" }));
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith("/jobs/900"));
  }

  it("sekcja „Rekruter i priorytet” mówi nowymi nazwami", async () => {
    await readRequest();
    expect(
      screen.getByRole("heading", { name: "Rekruter i priorytet" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Kolejne osoby")).toBeInTheDocument();
    for (const gone of ["Rekruter prowadzący", "Współpracownicy", "Prowadzi"]) {
      expect(screen.queryByText(gone)).toBeNull();
    }
  });

  it("dopisuje wybranych po utworzeniu rekrutacji", async () => {
    await readRequest();
    await pickCollaboratorAndHandoff();
    expect(mocks.post).toHaveBeenCalledWith("/api/jobs/900/collaborators", {
      user_id: 32,
    });
    expect(mocks.handoff).toHaveBeenCalledWith(900, 31, undefined, "linkedin");
  });

  it("awaria dopisania nie zatrzymuje utworzenia rekrutacji", async () => {
    await readRequest();
    const base = mocks.post.getMockImplementation();
    mocks.post.mockImplementation((url: string, ...rest: unknown[]) =>
      url === "/api/jobs/900/collaborators"
        ? Promise.reject({ response: { status: 403, data: { detail: "brak" } } })
        : base!(url, ...rest),
    );
    await pickCollaboratorAndHandoff();
    expect(mocks.showError).toHaveBeenCalledWith(
      "Rekrutacja zapisana, ale nie zapisano kolejnych osób (brak). Dopisz je w zakładce „Zespół” rekrutacji.",
    );
    expect(mocks.handoff).toHaveBeenCalled();
  });
});
