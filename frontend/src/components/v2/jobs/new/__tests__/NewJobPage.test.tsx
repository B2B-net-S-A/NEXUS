/**
 * Strona `/jobs/new`: request → odczyt AI → przegląd → „Utwórz i przekaż do
 * searchu”. Zapis idzie ZWYKŁYMI trasami w stałej kolejności (rekrutacja →
 * Champion → handoff → publikacja); awaria po utworzeniu nie gubi pracy.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <NewJobPage />
    </QueryClientProvider>,
  );
}

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
      data: url === "/api/users" ? [{ id: 31, name: "Rekruterka Ola" }] : {},
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
    fireEvent.change(screen.getByLabelText("Rekruter prowadzący"), {
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

  it("awaria podsumowania historii klienta nie blokuje utworzenia rekrutacji", async () => {
    mocks.refreshClientHistory.mockRejectedValue(new Error("503"));
    await readRequest();
    await screen.findByRole("option", { name: "Rekruterka Ola" });
    fireEvent.change(screen.getByLabelText("Rekruter prowadzący"), {
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
    fireEvent.change(screen.getByLabelText("Rekruter prowadzący"), {
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
    fireEvent.change(screen.getByLabelText("Rekruter prowadzący"), { target: { value: "31" } });
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
