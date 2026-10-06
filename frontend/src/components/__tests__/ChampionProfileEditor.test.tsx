/**
 * `ChampionProfileEditor` — krok 02 „Zlecenie i Champion" (program „flow w
 * języku C2", PR 5/7): pełna szerokość (bez `max-w`) + chip stanu (pusta /
 * wypełniona / z AI) przy każdej z sześciu sekcji.
 *
 * Testy renderują z `canEdit={false}` (widok recruitera) — to CELOWO omija
 * `ChampionProfileSourcesPanel` i panel „Wygeneruj z opisu klienta (AI)"
 * (oba `{canEdit && (...)}`, więc się nie montują), dzięki czemu jedyne
 * zapytanie sieciowe to `GET …/champion-profile`. Weryfikacja dwustronna +
 * briefing NIE renderują się tutaj — od 04.10.2026 mieszkają w pasku
 * „Do dopięcia” nad Briefem (`ChampionTodoStrip.test.tsx`).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChampionProfileEditor } from "@/components/ChampionProfileEditor";
import { ToastProvider } from "@/components/Toast";
import { CHAMPION_SECTIONS } from "@/lib/champion-section-state";
import { useAuthStore, type User } from "@/store/auth";

/** Etykiety sekcji mają JEDNO źródło — test nie może mieć własnej kopii. */
const BASICS_LABEL = CHAMPION_SECTIONS.find((s) => s.id === "basics")!.label;

const getMock = vi.fn();
const putMock = vi.fn();
const listMock = vi.fn();
const generateFromJdMock = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    championApi: {
      ...actual.championApi,
      get: (...args: unknown[]) => getMock(...args),
      put: (...args: unknown[]) => putMock(...args),
    },
    championSuggestionsApi: {
      ...actual.championSuggestionsApi,
      generateFromJd: (...args: unknown[]) => generateFromJdMock(...args),
    },
  };
});

// Liczba osób w bazie przy wymaganiach do wyszukiwania (sekcja 2) idzie
// kanoniczną funkcją listy kandydatów.
vi.mock("@/components/v2/pages/candidate-list-query", () => ({
  fetchCandidateListPage: (...args: unknown[]) => listMock(...args),
}));

// Edytor wierszy wymagań pyta serwer o to, które słowa są technologiami,
// i o liczbę osób — w teście odpowiada atrapa (ma osobne testy).
const legacyRowsMock = vi.fn();
vi.mock("@/lib/requirement-rows-api", () => ({
  useRowCriticalInfo: (rows: { key: string; words: string[]; level: string }[]) => ({
    info: Object.fromEntries(
      rows
        .filter((row) => row.level !== "nice")
        .map((row) => [row.key, { label: row.words[0], eligible: true, suggested: false }]),
    ),
    isLoading: false,
    isError: false,
    retry: () => undefined,
  }),
  useRowCounts: () => ({ perRow: {}, required: undefined, critical: undefined, failed: false }),
  fetchRowsFromLegacy: (...args: unknown[]) => legacyRowsMock(...args),
}));

// Panel źródeł ma WŁASNE zapytania (notatki, oczekujące propozycje) — dla
// testu zapisu wystarczy, że się nie montuje z siecią.
vi.mock("@/components/ChampionProfileSourcesPanel", () => ({
  ChampionProfileSourcesPanel: () => null,
}));
// Układ „workspace” montuje historię zapytań klienta (router Next.js, własne
// zapytania) — ma osobne testy.
vi.mock("@/components/RequestHistorySection", () => ({
  RequestHistorySection: () => null,
}));

const recruiter = {
  id: 7,
  name: "Marta Kowalska",
  email: "marta@example.com",
  role: "recruiter",
  roles: ["recruiter"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
  effective_section_access: { pipeline: "read" },
} satisfies User;

function renderEditor(jobId: number, canEdit = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ChampionProfileEditor jobId={jobId} canEdit={canEdit} clientId={null} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  getMock.mockReset();
  putMock.mockReset();
  generateFromJdMock.mockReset();
  legacyRowsMock.mockReset();
  useAuthStore.setState({
    user: recruiter,
    realUser: null,
    token: "token",
    hydrated: true,
  });
});

// Audyt B47 (retest 15.09.2026): klik w ostrzeżenie o stawce przewijał do
// sekcji 1, ale fokus lądował na PIERWSZYM polu sekcji („Nazwa roli”).
describe("ChampionProfileEditor — ostrzeżenie prowadzi do SWOJEGO pola", () => {
  it("„Maksymalna stawka PLN/h” ustawia fokus na polu stawki, nie na „Nazwa roli”", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 1,
        champion_profile: {},
        validation: {
          status: "draft",
          blocked_operations: [],
          issues: [
            {
              code: "missing",
              path: "basics.rate_value",
              message: "brak stawki",
              severity: "warning",
              blocked_operations: [],
            },
          ],
        },
      },
    });
    renderEditor(1, true);
    const link = await screen.findByRole("link", { name: "Maksymalna stawka PLN/h" });
    await userEvent.click(link);
    const rate = screen.getByLabelText(/Maksymalna stawka PLN\/h — twardy sufit/);
    await waitFor(() => expect(rate).toHaveFocus());
    expect(screen.getByLabelText("Nazwa roli")).not.toHaveFocus();
  });
});

describe("ChampionProfileEditor — pełna szerokość", () => {
  it("kontener sekcji NIE ma już `max-w-4xl` (krok 02 renderuje edytor na pełną szerokość środka)", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 1, champion_profile: {} },
    });
    const { container } = renderEditor(1);
    await screen.findByText("Profil Championa");
    expect(container.querySelector(".max-w-4xl")).not.toBeInTheDocument();
  });
});

describe("ChampionProfileEditor — chip stanu sekcji", () => {
  it("profil pusty — sześć kart z chipem „puste” plus chip grupy „3 z 3 sekcji puste”", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 1, champion_profile: {} },
    });
    renderEditor(1);
    await screen.findByText(BASICS_LABEL);
    // Karty samodzielne: 1 · Podstawowe, 3 · Stack, 4 · Doświadczenie,
    // Wymagania do wyszukiwania (25.09.2026), 7 · O kliencie, 8 · Wiedza z rozmów.
    expect(screen.getAllByText("puste")).toHaveLength(6);
    // Sekcje 2 · 5 · 6 mają JEDEN wspólny chip.
    expect(screen.getByText("3 z 3 sekcji puste")).toBeInTheDocument();
    expect(screen.queryByText("wypełnione")).not.toBeInTheDocument();
    expect(screen.queryByText("Z importu (AI)")).not.toBeInTheDocument();
  });

  it("profil wypełniony BEZ znacznika pochodzenia — wypełnione sekcje dostają „wypełnione”, nigdy „Z AI”", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 2,
        champion_profile: {
          basics: { role_name: "Senior Python Developer" },
          stack: { must: [{ name: "Python" }], nice: [], notes: "" },
        },
      },
    });
    renderEditor(2);
    await screen.findByText(BASICS_LABEL);
    // Sekcje 1 i 3 wypełnione; 4, wymagania do wyszukiwania, 7 i 8 puste;
    // grupa 2·5·6 pusta w całości.
    expect(screen.getAllByText("wypełnione")).toHaveLength(2);
    expect(screen.getAllByText("puste")).toHaveLength(4);
    expect(screen.getByText("3 z 3 sekcji puste")).toBeInTheDocument();
    expect(screen.queryByText("Z importu (AI)")).not.toBeInTheDocument();
  });

  it("profil wypełniony ZE znacznikiem pochodzenia (import dokumentu) — jeden chip „Z importu (AI)” na nagłówku, sekcje tylko „wypełnione”", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 3,
        champion_profile: {
          basics: { role_name: "Senior Python Developer" },
          _source: "champion_upload",
        },
      },
    });
    renderEditor(3);
    await screen.findByText(BASICS_LABEL);
    // Znacznik pochodzenia jest całoprofilowy: JEDEN chip na nagłówku, sekcje
    // dostają tylko „wypełnione" (backend nie wie, które sekcje przepisano).
    expect(screen.getAllByText("Z importu (AI)")).toHaveLength(1);
    expect(screen.getAllByText("puste")).toHaveLength(5);
    // Sekcja „Podstawowe informacje" jest wypełniona — chip mówi TYLKO tyle;
    // pochodzenie nie jest stanem sekcji.
    expect(screen.getAllByText("wypełnione")).toHaveLength(1);
    expect(screen.queryByText("Z AI")).not.toBeInTheDocument();
  });
});

describe("ChampionProfileEditor — układ makiety kroku 02", () => {
  it("stack stoi PRZED prozą: to on zasila must_skills/nice_skills", async () => {
    getMock.mockResolvedValue({ data: { job_id: 1, champion_profile: {} } });
    const { container } = renderEditor(1);
    await screen.findByText(BASICS_LABEL);

    const headings = Array.from(container.querySelectorAll("h3")).map(
      (h) => h.textContent ?? "",
    );
    const stackAt = headings.findIndex((h) => h.includes("Stack technologiczny"));
    const proseAt = headings.findIndex((h) => h.includes("Co wpisać (search)"));
    expect(stackAt).toBeGreaterThanOrEqual(0);
    expect(proseAt).toBeGreaterThan(stackAt);
  });

  it("gdy 2 · 4 · 5 są PUSTE — skrót z opisem projektu i „Rozwiń pełne sekcje”, kotwice sekcji zostają", async () => {
    getMock.mockResolvedValue({ data: { job_id: 1, champion_profile: {} } });
    const { container } = renderEditor(1);
    await screen.findByText(BASICS_LABEL);

    // „Frazy do LinkedIna” usunięte 02.10.2026 — ani w skrócie, ani w pełnej sekcji.
    expect(screen.queryByLabelText(/Frazy do LinkedIna/i)).not.toBeInTheDocument();
    // Wymagania do wyszukiwania (sekcja 2, 25.09.2026) — widoczne także w skrócie.
    expect(screen.getByText(/Wymagania do wyszukiwania w bazie/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/O projekcie \(2 zdania\)/i)).toBeInTheDocument();
    // Pełne sekcje jeszcze się nie renderują…
    expect(screen.queryByText(/Obowiązki na stanowisku/i)).not.toBeInTheDocument();
    // …ale link z nawigacji ma dokąd prowadzić.
    expect(container.querySelector("#champion-section-project")).not.toBeNull();
    expect(container.querySelector("#champion-section-screening")).not.toBeNull();
  });

  it("„Rozwiń pełne sekcje” pokazuje trzy pełne formularze", async () => {
    const user = userEvent.setup();
    getMock.mockResolvedValue({ data: { job_id: 1, champion_profile: {} } });
    renderEditor(1);
    await screen.findByText(BASICS_LABEL);

    await user.click(screen.getByTestId("expand-champion-prose"));

    expect(await screen.findByText(/Obowiązki na stanowisku/i)).toBeInTheDocument();
    expect(screen.getByText(/Firmy docelowe/i)).toBeInTheDocument();
  });

  it("gdy KTÓRAKOLWIEK z 2 · 4 · 5 jest wypełniona — pełne sekcje od razu, bez chowania danych", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 1,
        champion_profile: { project: { about: "Migracja płatności.", responsibilities: "" } },
      },
    });
    renderEditor(1);
    await screen.findByText(BASICS_LABEL);

    expect(screen.getByText(/Obowiązki na stanowisku/i)).toBeInTheDocument();
    expect(screen.queryByTestId("expand-champion-prose")).not.toBeInTheDocument();
    expect(screen.getByText("2 z 3 sekcji puste")).toBeInTheDocument();
  });

  it("etykiety stacku niosą liczniki i wyjaśniają alternatywy", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 1,
        champion_profile: {
          stack: { must: [{ name: "Python" }, { name: "Kafka" }], nice: [{ name: "AWS" }], notes: "" },
        },
      },
    });
    const { container } = renderEditor(1);
    await screen.findByText(BASICS_LABEL);

    expect(screen.getByText("Musi mieć · 2")).toBeInTheDocument();
    expect(screen.getByText("Mile widziane · 1")).toBeInTheDocument();
    expect(container.textContent).toContain("wystarczy jedna z tych umiejętności");
  });
});

describe("ChampionProfileEditor — wymagania do wyszukiwania (sekcja 2)", () => {
  it("wiersze wpisane przez DL idą w zapisie profilu; obok liczba osób w bazie", async () => {
    useAuthStore.setState({ user: { ...recruiter, role: "admin", roles: ["admin"] } as User });
    getMock.mockResolvedValue({ data: { job_id: 15, champion_profile: {} } });
    putMock.mockResolvedValue({ data: { job_id: 15, champion_profile: {} } });
    listMock.mockResolvedValue({ total: 46, items: [] });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ChampionProfileEditor jobId={15} canEdit clientId={null} />
      </QueryClientProvider>,
    );
    const first = await screen.findByLabelText("Wymaganie 1 — słowo albo wariant");
    fireEvent.change(first, { target: { value: "Kafka" } });
    fireEvent.keyDown(first, { key: "Enter" });
    fireEvent.change(first, { target: { value: "RabbitMQ" } });
    fireEvent.keyDown(first, { key: "Enter" });

    // Liczba idzie za wierszami (debounce 500 ms) — ostatnie liczenie to oba warianty.
    await waitFor(
      () =>
        expect(listMock).toHaveBeenLastCalledWith(
          expect.objectContaining({ q_any_group: ["Kafka|RabbitMQ"], page_size: 1 }),
          expect.anything(),
        ),
      { timeout: 3000 },
    );
    expect(await screen.findByText("~46 osób w bazie")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const payload = putMock.mock.calls[0][1] as { search: { requirements: string[][] } };
    expect(payload.search.requirements).toEqual([["Kafka", "RabbitMQ"]]);
  });

  it("bez prawa edycji — samo zdanie, bez pól", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 16, champion_profile: { search: { requirements: [["Java"]] } } },
    });
    renderEditor(16);
    expect(
      await screen.findByText("Szukamy osób, które mają Java."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Wymaganie 1 — słowo albo wariant")).not.toBeInTheDocument();
  });
});

describe("ChampionProfileEditor — wymagania jako wiersze słów kluczowych (02.10.2026)", () => {
  const ROWS_PROFILE = {
    stack: {
      must: [{ name: "Java" }, { name: "Kafka lub RabbitMQ" }],
      nice: [{ name: "Kubernetes" }],
      critical: ["Kafka lub RabbitMQ"],
      notes: "",
      rows: [
        { words: ["Java"], level: "must" },
        { words: ["Kafka", "RabbitMQ"], level: "must" },
        { words: ["Kubernetes"], level: "nice" },
      ],
    },
    search: { requirements: [["Java"], ["Kafka", "RabbitMQ"]] },
  };

  function renderAdmin(jobId: number) {
    useAuthStore.setState({ user: { ...recruiter, role: "admin", roles: ["admin"] } as User });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <ChampionProfileEditor jobId={jobId} canEdit clientId={null} />
      </QueryClientProvider>,
    );
  }

  it("profil z wierszami: jedna lista zamiast pól must / krytyczne / wyszukiwanie", async () => {
    getMock.mockResolvedValue({ data: { job_id: 21, champion_profile: ROWS_PROFILE } });
    renderAdmin(21);
    expect(await screen.findByTestId("champion-requirement-rows")).toBeInTheDocument();
    expect(screen.queryByTestId("champion-stack-must")).not.toBeInTheDocument();
    expect(screen.queryByText("Wymagania do wyszukiwania w bazie")).not.toBeInTheDocument();
    // Krytyczne z zapisu wracają jako poziom wiersza.
    expect(
      screen
        .getByRole("radiogroup", { name: "Poziom wymagania: Kafka" })
        .querySelector('[aria-checked="true"]'),
    ).toHaveTextContent("Krytyczne");
    expect(screen.queryByTestId("champion-simplify-requirements")).not.toBeInTheDocument();
  });

  it("zapis wysyła wiersze z poziomami (bez kluczy Reacta), a zmiana poziomu zdejmuje krytyczne", async () => {
    getMock.mockResolvedValue({ data: { job_id: 22, champion_profile: ROWS_PROFILE } });
    putMock.mockResolvedValue({ data: { job_id: 22, champion_profile: ROWS_PROFILE } });
    renderAdmin(22);
    await screen.findByTestId("champion-requirement-rows");
    const kafka = screen.getByRole("radiogroup", { name: "Poziom wymagania: Kafka" });
    await userEvent.click(
      Array.from(kafka.querySelectorAll("button")).find((b) => b.textContent === "Musi mieć")!,
    );
    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const payload = putMock.mock.calls[0][1] as {
      stack: { rows: Record<string, unknown>[]; critical: unknown };
      search: { requirements: string[][] };
    };
    expect(payload.stack.rows).toEqual([
      { words: ["Java"], level: "must" },
      { words: ["Kafka", "RabbitMQ"], level: "must" },
      { words: ["Kubernetes"], level: "nice" },
    ]);
    // Nikt nie zaznaczył „Brak krytycznych”, więc decyzji nie ma.
    expect(payload.stack.critical).toBeNull();
    // Audyt 06.10.2026 (N2): krytyczne → „musi mieć” nie zmienia wierszy
    // wyszukiwania, więc sekcja `search` nie jedzie (serwer i tak wyprowadza
    // ją z wierszy).
    expect(payload).not.toHaveProperty("search");
  });

  it("„Uprość do słów kluczowych” zamienia stare pola na wiersze, a zdania klienta idą do niuansów", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 23,
        champion_profile: {
          stack: {
            must: [{ name: "Java 17+" }, { name: "Doświadczenie w dużych projektach bankowych" }],
            nice: [],
            notes: "",
          },
          search: { requirements: [["bankow*", "banking"]] },
        },
      },
    });
    legacyRowsMock.mockResolvedValue({
      rows: [
        { words: ["bankow*", "banking"], level: "must" },
        { words: ["Java"], level: "must" },
      ],
      descriptive: ["Java 17+", "Doświadczenie w dużych projektach bankowych"],
      no_critical: false,
    });
    putMock.mockResolvedValue({ data: { job_id: 23, champion_profile: {} } });
    renderAdmin(23);
    await userEvent.click(await screen.findByTestId("champion-simplify-requirements"));
    expect(await screen.findByTestId("champion-requirement-rows")).toBeInTheDocument();
    expect(legacyRowsMock).toHaveBeenCalledWith({
      must: ["Java 17+", "Doświadczenie w dużych projektach bankowych"],
      nice: [],
      requirements: [["bankow*", "banking"]],
      critical: null,
    });
    // Nic nie jest zapisane, dopóki DL nie kliknie „Zapisz”.
    expect(putMock).not.toHaveBeenCalled();
    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const payload = putMock.mock.calls[0][1] as {
      stack: { rows: unknown[]; notes: string };
    };
    expect(payload.stack.rows).toEqual([
      { words: ["bankow*", "banking"], level: "must" },
      { words: ["Java"], level: "must" },
    ]);
    expect(payload.stack.notes).toBe("Java 17+\nDoświadczenie w dużych projektach bankowych");
  });

  it("bez prawa edycji — lista wymagań z poziomami, bez pól", async () => {
    getMock.mockResolvedValue({ data: { job_id: 24, champion_profile: ROWS_PROFILE } });
    renderEditor(24);
    expect(await screen.findByText("Kafka lub RabbitMQ")).toBeInTheDocument();
    expect(screen.queryByLabelText("Wymaganie 1 — słowo albo wariant")).not.toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: /Poziom wymagania/ })).not.toBeInTheDocument();
  });
});

describe("ChampionProfileEditor — zapis odświeża werdykt gotowości", () => {
  it("„Zapisz” unieważnia `[\"job-readiness\", jobId]` — inaczej „Przekaż do searchu” zostaje wyszarzone po uzupełnieniu braków", async () => {
    getMock.mockResolvedValue({ data: { job_id: 12, champion_profile: {} } });
    putMock.mockResolvedValue({ data: { job_id: 12, champion_profile: {} } });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    render(
      <QueryClientProvider client={client}>
        <ChampionProfileEditor jobId={12} canEdit clientId={null} />
      </QueryClientProvider>,
    );

    await userEvent.click(await screen.findByTestId("save-champion-profile"));

    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["job-readiness", 12] }),
    );
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["champion-profile", 12] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["job", "12"] });
  });
});

describe("ChampionProfileEditor — weryfikacja/briefing/wyszukiwania przeniesione do doku", () => {
  it("NIE renderuje już checklisty weryfikacji ani rekomendowanych wyszukiwań (przeniesione do JobReadinessDock)", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 1, champion_profile: {} },
    });
    renderEditor(1);
    await screen.findByText(BASICS_LABEL);
    expect(
      screen.queryByTestId("champion-verification-checklist"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("champion-recommended-searches"),
    ).not.toBeInTheDocument();
  });
});

describe("ChampionProfileEditor — sekcja 6 „Pełna karta klienta →”", () => {
  it("prowadzi do Pomocy, nie do profilu klienta bramkowanego sekcją Delivery (M03-B02)", async () => {
    getMock.mockResolvedValue({ data: {} });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <ChampionProfileEditor jobId={51} canEdit={false} clientId={12} />
      </QueryClientProvider>,
    );
    const link = await screen.findByTestId(
      "champion-client-section-full-card-link",
    );
    expect(link.getAttribute("href")).toBe("/help?tab=clients&client=12");
  });
});

describe("ChampionProfileEditor — stary profil bez stacku (M04-B02)", () => {
  it("pokazuje wymagania z kolumn rekrutacji, a zapis bez zmian nie wysyła stacku", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 14,
        champion_profile: { stack: { must: [], nice: [], notes: "" } },
        job_values: { must: "Python\nPostgreSQL", nice: "Kafka" },
      },
    });
    putMock.mockResolvedValue({ data: { job_id: 14, champion_profile: {} } });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <ChampionProfileEditor jobId={14} canEdit clientId={null} />
      </QueryClientProvider>,
    );

    expect(
      await screen.findByTestId("champion-stack-seeded-from-job"),
    ).toBeInTheDocument();
    expect(screen.getByText("Musi mieć · 2")).toBeInTheDocument();
    expect(screen.getByText("Mile widziane · 1")).toBeInTheDocument();

    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const payload = putMock.mock.calls[0][1] as Record<string, unknown>;
    expect("stack" in payload).toBe(false);
  });

  it("okno „Uzgodnij profil i pola rekrutacji” pokazuje wymagania wczytane z kolumn, nie pustą listę", async () => {
    // Pusta lista MUST w tym oknie + zaznaczone „Uzgodnij też pole rekrutacji”
    // wyczyściłyby `must_skills` rekrutacji — okno ma pokazywać to, co edytor.
    getMock.mockResolvedValue({
      data: {
        job_id: 15,
        champion_profile: { stack: { must: [], nice: [], notes: "" } },
        job_values: { must: "Python\nPostgreSQL", nice: "Kafka" },
      },
    });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <ChampionProfileEditor jobId={15} canEdit clientId={null} />
      </QueryClientProvider>,
    );

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Uzgodnij profil i pola rekrutacji",
      }),
    );
    const must = (await screen.findByLabelText(
      "MUST — jeden wpis na wiersz; alternatywy: A lub B",
    )) as HTMLTextAreaElement;
    expect(must.value).toBe("Python\nPostgreSQL");
  });
});

// PR 5 (program „proces tworzenia rekrutacji dla Delivery Leada"): sekcja 1
// „Podstawowe informacje" startuje z pól rekrutacji, per pole — patrz
// `lib/champion-job-seed.ts`.
describe("ChampionProfileEditor — sekcja 1 startuje z pól rekrutacji (PR 5)", () => {
  it("pokazuje notatkę z etykietami wczytanych pól, a zapis bez zmian nie wysyła ich", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 20,
        job_title: "Senior Java Developer",
        champion_profile: {},
        // `role_name` NIEOBECNE — backend sprzed PR 1: degradacja łagodna,
        // sekcja 1 spada na `job_title`.
        job_values: { rate_value: 120, work_mode: "remote" },
      },
    });
    putMock.mockResolvedValue({ data: { job_id: 20, champion_profile: {} } });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <ChampionProfileEditor jobId={20} canEdit clientId={null} />
      </QueryClientProvider>,
    );

    const notice = await screen.findByTestId("champion-basics-seeded-from-job");
    expect(notice.textContent).toContain("Nazwa roli");
    expect(notice.textContent).toContain("Maksymalna stawka PLN/h — twardy sufit");
    expect(notice.textContent).toContain("Tryb pracy");
    // Pola bez odpowiednika w kolumnach (dni w biurze, lokalizacja, deadline)
    // NIE są wymienione.
    expect(notice.textContent).not.toContain("Dni stacjonarne");

    expect(screen.getByLabelText("Nazwa roli")).toHaveValue("Senior Java Developer");
    expect(screen.getByLabelText(/Maksymalna stawka PLN\/h — twardy sufit/)).toHaveValue(120);
    expect(screen.getByLabelText("Tryb pracy")).toHaveValue("zdalnie");

    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const payload = putMock.mock.calls[0][1] as {
      basics?: Record<string, unknown>;
    };
    // Audyt 06.10.2026 (N2): nietknięta sekcja nie jedzie wcale — tym
    // bardziej pola wczytane z rekrutacji.
    const basics = payload.basics ?? {};
    expect("role_name" in basics).toBe(false);
    expect("rate_value" in basics).toBe(false);
    expect("work_mode" in basics).toBe(false);
  });

  it("edycja JEDNEGO wczytanego pola (stawki) wysyła TYLKO tę zmianę", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 21,
        job_title: "Senior Java Developer",
        champion_profile: {},
        job_values: { rate_value: 120, work_mode: "remote" },
      },
    });
    putMock.mockResolvedValue({ data: { job_id: 21, champion_profile: {} } });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <ChampionProfileEditor jobId={21} canEdit clientId={null} />
      </QueryClientProvider>,
    );

    const rate = await screen.findByLabelText(
      /Maksymalna stawka PLN\/h — twardy sufit/,
    );
    fireEvent.change(rate, { target: { value: "150" } });

    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const payload = putMock.mock.calls[0][1] as {
      basics: Record<string, unknown>;
    };
    expect(payload.basics.rate_value).toBe(150);
    // Reszta pól wczytanych z kolumn i nietkniętych — nazwa roli, tryb pracy —
    // zostaje pominięta.
    expect("role_name" in payload.basics).toBe(false);
    expect("work_mode" in payload.basics).toBe(false);
  });

  it("bez pól do wczytania (kolumny puste, profil pusty) notatka się nie renderuje", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 22, champion_profile: {}, job_values: {} },
    });
    renderEditor(22);
    await screen.findByText(BASICS_LABEL);
    expect(
      screen.queryByTestId("champion-basics-seeded-from-job"),
    ).not.toBeInTheDocument();
  });
});

describe("ChampionProfileEditor — intake seedowany z `CreateJobModal` (?intake=1)", () => {
  it("intakeDefaultOpen/intakeSeedText otwierają panel „Wklej opis” od razu z treścią rekrutacji", async () => {
    getMock.mockResolvedValue({ data: { job_id: 42, champion_profile: {} } });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <ChampionProfileEditor
          jobId={42}
          canEdit
          clientId={null}
          intakeDefaultOpen
          intakeSeedText="Szukamy Senior Java Developera do zespołu płatności."
        />
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId("toggle-ai-intake")).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByTestId("jd-intake-textarea")).toHaveValue(
      "Szukamy Senior Java Developera do zespołu płatności.",
    );
  });

  it("bez propsów panel zostaje domyślnie zwinięty i pusty (zachowanie sprzed PR 2)", async () => {
    getMock.mockResolvedValue({ data: { job_id: 43, champion_profile: {} } });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <ChampionProfileEditor jobId={43} canEdit clientId={null} />
      </QueryClientProvider>,
    );

    expect(await screen.findByTestId("toggle-ai-intake")).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByTestId("jd-intake-textarea")).not.toBeInTheDocument();
  });

  // Serwer odrzuca opis spoza limitu zdaniem, które mówi, co poprawić (422) —
  // do 02.10.2026 każda porażka kończyła się tym samym ogólnym komunikatem.
  it("odmowę serwera pokazuje jej zdaniem, a awarię bez odpowiedzi — ogólnym", async () => {
    getMock.mockResolvedValue({ data: { job_id: 44, champion_profile: {} } });
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <ChampionProfileEditor
          jobId={44}
          canEdit
          clientId={null}
          intakeDefaultOpen
          intakeSeedText={"Opis stanowiska od klienta. ".repeat(3)}
        />
      </QueryClientProvider>,
    );
    const generate = await screen.findByTestId("generate-champion-from-jd");

    generateFromJdMock.mockRejectedValueOnce({
      response: {
        status: 422,
        data: { detail: "Opis stanowiska musi mieć od 50 do 50 000 znaków." },
      },
    });
    await userEvent.click(generate);
    expect(
      await screen.findByText("Opis stanowiska musi mieć od 50 do 50 000 znaków."),
    ).toBeInTheDocument();

    generateFromJdMock.mockRejectedValueOnce(new Error("Network Error"));
    await userEvent.click(generate);
    expect(
      await screen.findByText("Nie udało się wygenerować draftu."),
    ).toBeInTheDocument();
  });
});

describe("ChampionProfileEditor — sekcje 4 i 8 (09.2026)", () => {
  const PROFILE = {
    client: { consultant_insight: "Zespół 6 osób, dużo spotkań" },
    insights: [
      {
        id: "verification:client",
        source: "client",
        topic: "needs",
        audience: "team",
        text: "Naprawdę szukają acquiringu",
        origin: "verification",
        editable: false,
        author_name: "Delivery Lead",
      },
      {
        id: "legacy:client.consultant_insight",
        source: "consultant",
        topic: "team",
        audience: "team",
        text: "Zespół 6 osób, dużo spotkań",
        origin: "legacy",
        editable: true,
      },
    ],
  };

  function savedPayload() {
    expect(putMock).toHaveBeenCalled();
    return putMock.mock.calls.at(-1)![1] as Record<string, any>;
  }

  it("wpis z weryfikacji jest tylko do odczytu, a edycja wpisu „z importu” zapisuje stare pole", async () => {
    getMock.mockResolvedValue({ data: { job_id: 11, champion_profile: PROFILE } });
    putMock.mockResolvedValue({ data: {} });
    renderEditor(11, true);
    await screen.findByText("Naprawdę szukają acquiringu");

    const cards = screen.getAllByTestId("champion-insight-card");
    const verificationCard = cards.find((c) => c.textContent?.includes("acquiringu"))!;
    expect(verificationCard.querySelector('[aria-label="Edytuj notatkę"]')).toBeNull();
    expect(verificationCard.textContent).toContain("z weryfikacji");

    const legacyCard = cards.find((c) => c.textContent?.includes("Zespół 6 osób"))!;
    fireEvent.click(legacyCard.querySelector('[aria-label="Edytuj notatkę"]')!);
    const textarea = screen.getByLabelText("Treść notatki");
    fireEvent.change(textarea, { target: { value: "Zespół 8 osób" } });
    fireEvent.click(screen.getByTestId("save-champion-profile"));

    await waitFor(() => expect(putMock).toHaveBeenCalled());
    expect(savedPayload().client.consultant_insight).toBe("Zespół 8 osób");
  });

  it("podpowiedź „O co zapytać” dodaje notatkę z tematem, a przełącznik widoczności ją oznacza", async () => {
    getMock.mockResolvedValue({ data: { job_id: 12, champion_profile: {} } });
    putMock.mockResolvedValue({ data: {} });
    renderEditor(12, true);
    const column = await screen.findByTestId("champion-insights-client");
    fireEvent.click(
      Array.from(column.querySelectorAll("button")).find((b) =>
        b.textContent?.startsWith("O co zapytać"),
      )!,
    );
    fireEvent.click(screen.getByText("Kto decyduje i jak prowadzi rozmowę techniczną?"));
    fireEvent.change(screen.getByLabelText("Treść notatki"), {
      target: { value: "Decyduje CTO, rozmowa 90 min" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Widoczność: Tylko zespół/ }));
    fireEvent.click(screen.getByTestId("save-champion-profile"));

    await waitFor(() => expect(putMock).toHaveBeenCalled());
    const [note] = savedPayload().insights;
    expect(note).toMatchObject({
      source: "client",
      topic: "decision",
      audience: "candidate",
      text: "Decyduje CTO, rozmowa 90 min",
    });
    expect(note.id.startsWith("new-")).toBe(true);
  });

  it("dziedzina dopisana w sekcji 4 trafia do zapisu jako wymóg z latami", async () => {
    getMock.mockResolvedValue({ data: { job_id: 13, champion_profile: {} } });
    putMock.mockResolvedValue({ data: {} });
    renderEditor(13, true);
    const domains = await screen.findByTestId("champion-experience-domains");
    const input = domains.querySelector("input:not([type=number])") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "płatności kartowe" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.change(
      screen.getByLabelText("Minimalna liczba lat w dziedzinie płatności kartowe"),
      { target: { value: "2" } },
    );
    fireEvent.click(screen.getByTestId("save-champion-profile"));

    await waitFor(() => expect(putMock).toHaveBeenCalled());
    expect(savedPayload().experience.domains).toEqual([
      { name: "płatności kartowe", level: "must", min_years: 2, note: "" },
    ]);
  });

  it("historia klienta w stanie „failed” mówi o awarii, nie pokazuje pustki", async () => {
    getMock.mockResolvedValue({
      data: {
        job_id: 14,
        champion_profile: {
          client_history: {
            status: "failed",
            items: [],
            debrief_questions: [],
            message: "Nie udało się podsumować historii klienta — spróbuj „Odśwież”.",
          },
        },
      },
    });
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ChampionProfileEditor jobId={14} canEdit clientId={5} />
      </QueryClientProvider>,
    );
    expect(
      await screen.findByText("Nie udało się podsumować historii klienta — spróbuj „Odśwież”."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Odśwież" })).toBeInTheDocument();
  });
});

// Do 28.09.2026 nieudany zapis ustawiał stan „error”, którego nic nie
// renderowało — DL widział zwolniony przycisk „Zapisz” i myślał, że zapisał.
describe("ChampionProfileEditor — nieudany zapis nie jest cichy", () => {
  function axiosError(status: number, detail: unknown) {
    return Object.assign(new Error(`Request failed with status code ${status}`), {
      isAxiosError: true,
      response: { status, data: { detail } },
    });
  }

  it("odrzucony PUT pokazuje komunikat serwera przy „Zapisz”, a zmiany zostają w formularzu", async () => {
    getMock.mockResolvedValue({ data: { job_id: 21, champion_profile: {} } });
    putMock.mockRejectedValue(
      axiosError(422, "Profil Championa ma zły kształt sekcji „basics”."),
    );
    renderEditor(21, true);

    const role = await screen.findByLabelText("Nazwa roli");
    await userEvent.type(role, "Java Developer");
    await userEvent.click(screen.getByTestId("save-champion-profile"));

    const alert = await screen.findByTestId("champion-profile-save-error");
    expect(alert).toHaveAttribute("role", "alert");
    expect(alert).toHaveTextContent("Nie zapisano profilu");
    expect(alert).toHaveTextContent("Profil Championa ma zły kształt sekcji „basics”.");
    expect(screen.queryByText("Zapisano")).toBeNull();
    expect(screen.getByLabelText("Nazwa roli")).toHaveValue("Java Developer");
  });

  it("409 mówi zdaniem, że ktoś zmienił rekrutację w międzyczasie", async () => {
    getMock.mockResolvedValue({ data: { job_id: 22, champion_profile: {} } });
    putMock.mockRejectedValue(
      axiosError(409, { message: "Rekrutacja zmieniła się. Sprawdź aktualne różnice." }),
    );
    renderEditor(22, true);

    await userEvent.click(await screen.findByTestId("save-champion-profile"));

    const alert = await screen.findByTestId("champion-profile-save-error");
    expect(alert).toHaveTextContent(
      "Ktoś zmienił tę rekrutację w międzyczasie",
    );
  });

  it("komunikat znika po udanym ponownym zapisie", async () => {
    getMock.mockResolvedValue({ data: { job_id: 23, champion_profile: {} } });
    putMock
      .mockRejectedValueOnce(axiosError(500, "Internal Server Error"))
      .mockResolvedValueOnce({ data: { job_id: 23, champion_profile: {} } });
    renderEditor(23, true);

    await userEvent.click(await screen.findByTestId("save-champion-profile"));
    await screen.findByTestId("champion-profile-save-error");
    await userEvent.click(screen.getByTestId("save-champion-profile"));

    await screen.findByText("Zapisano");
    expect(screen.queryByTestId("champion-profile-save-error")).toBeNull();
  });
});

// Pełny formularz Profilu Championa (menu „⋯”, `?mode=edit`; do 04.10.2026 tryb „Edytuj”).
describe("ChampionProfileEditor — układ workspace", () => {
  function renderWorkspace(jobId: number) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <ChampionProfileEditor jobId={jobId} canEdit clientId={null} layout="workspace" />
      </QueryClientProvider>,
    );
  }

  it("licznik niezapisanych zmian i „Anuluj” przywracające wczytany profil", async () => {
    getMock.mockResolvedValue({ data: { job_id: 31, champion_profile: {} } });
    renderWorkspace(31);
    await screen.findByTestId("champion-editor-workspace");
    expect(screen.queryByTestId("champion-unsaved-count")).toBeNull();
    expect(screen.getByTestId("cancel-champion-profile")).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Nazwa roli"), "QA");
    expect(screen.getByTestId("champion-unsaved-count")).toHaveTextContent("1 niezapisana zmiana");

    await userEvent.click(screen.getByTestId("cancel-champion-profile"));
    expect(screen.getByLabelText("Nazwa roli")).toHaveValue("");
    expect(screen.queryByTestId("champion-unsaved-count")).toBeNull();
  });

  it("pasek sekcji w kolejności wyświetlania, z „Wyszukiwaniem w bazie”", async () => {
    getMock.mockResolvedValue({ data: { job_id: 32, champion_profile: {} } });
    renderWorkspace(32);
    const nav = await screen.findByRole("navigation", { name: "Sekcje Profilu Championa" });
    const labels = Array.from(nav.querySelectorAll("a")).map((a) =>
      a.textContent?.replace(/,.*$/, "").trim(),
    );
    expect(labels).toEqual([
      "Podstawy",
      "Stack",
      "Poza stackiem",
      "Wyszukiwanie w bazie",
      "Frazy i firmy",
      "Projekt",
      "Screening",
      "Klient",
      "Wiedza z rozmów",
    ]);
    expect(screen.getByRole("complementary", { name: "Wypełnij szybciej" })).toBeInTheDocument();
  });
});

// Szuflada edycji bloku Briefu „Profilu Championa” (04.10.2026).
describe("ChampionProfileEditor — szuflada bloku (`onlySections`)", () => {
  function renderDrawerEditor(
    jobId: number,
    onlySections: Parameters<typeof ChampionProfileEditor>[0]["onlySections"],
    extra: { onSaved?: () => void; onCancel?: () => void } = {},
  ) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <ChampionProfileEditor
          jobId={jobId}
          canEdit
          clientId={null}
          layout="drawer"
          onlySections={onlySections}
          {...extra}
        />
      </QueryClientProvider>,
    );
  }

  it("rysuje tylko sekcje bloku — bez paska sekcji, grupy „proza” i „Wypełnij szybciej”", async () => {
    getMock.mockResolvedValue({ data: { job_id: 41, champion_profile: {} } });
    renderDrawerEditor(41, ["screening_questions"]);
    await screen.findByTestId("champion-editor-drawer");
    const ids = Array.from(document.querySelectorAll('section[id^="champion-section-"]')).map(
      (el) => el.id,
    );
    expect(ids).toEqual(["champion-section-screening"]);
    expect(screen.queryByRole("navigation", { name: "Sekcje Profilu Championa" })).toBeNull();
    expect(screen.queryByRole("complementary", { name: "Wypełnij szybciej" })).toBeNull();
    expect(screen.queryByTestId("expand-champion-prose")).toBeNull();
  });

  it("„Zapisz” wysyła profil i woła `onSaved`; bez zmian przycisk jest nieaktywny", async () => {
    getMock.mockResolvedValue({ data: { job_id: 42, champion_profile: {} } });
    putMock.mockResolvedValue({ data: { job_id: 42, champion_profile: {} } });
    const onSaved = vi.fn();
    renderDrawerEditor(42, ["basics"], { onSaved });
    await screen.findByTestId("champion-editor-drawer");
    expect(screen.getByTestId("save-champion-profile")).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Nazwa roli"), "QA");
    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    expect((putMock.mock.calls[0][1] as { basics: { role_name: string } }).basics.role_name).toBe("QA");
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
  });

  it("„Anuluj” cofa szkic i woła `onCancel`", async () => {
    getMock.mockResolvedValue({ data: { job_id: 43, champion_profile: {} } });
    const onCancel = vi.fn();
    renderDrawerEditor(43, ["basics"], { onCancel });
    await screen.findByTestId("champion-editor-drawer");
    await userEvent.type(screen.getByLabelText("Nazwa roli"), "QA");
    await userEvent.click(screen.getByTestId("cancel-champion-profile"));
    expect(onCancel).toHaveBeenCalled();
    expect(putMock).not.toHaveBeenCalled();
  });
});

// Audyt 06.10.2026: odświeżenie profilu nie kasuje niezapisanych zmian (N1),
// zapis wysyła tylko zmienione sekcje z odciskiem profilu (N2/N5), 409
// `champion_profile_conflict` daje wybór, a 422 `handoff_regression` listę
// braków z sekcjami (N4).
describe("ChampionProfileEditor — zapis zmienionych sekcji i konflikty (06.10.2026)", () => {
  const PROFILE = {
    basics: { role_name: "QA" },
    project: { about: "Migracja płatności." },
    insights: [],
  };

  function renderWithClient(jobId: number, withToasts = false) {
    useAuthStore.setState({ user: { ...recruiter, role: "admin", roles: ["admin"] } as User });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const editor = (
      <QueryClientProvider client={client}>
        <ChampionProfileEditor jobId={jobId} canEdit clientId={null} />
      </QueryClientProvider>
    );
    render(withToasts ? <ToastProvider>{editor}</ToastProvider> : editor);
    return client;
  }

  const lastPayload = () => putMock.mock.calls.at(-1)![1] as Record<string, unknown>;

  function axiosError(status: number, detail: unknown) {
    return Object.assign(new Error(`Request failed with status code ${status}`), {
      isAxiosError: true,
      response: { status, data: { detail } },
    });
  }

  it("zapis wysyła tylko zmienione sekcje i odcisk wczytanego profilu", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 61, champion_profile: PROFILE, profile_hash: "h1" },
    });
    putMock.mockResolvedValue({
      data: { job_id: 61, champion_profile: PROFILE, profile_hash: "h2", notices: [] },
    });
    renderWithClient(61);
    const role = await screen.findByLabelText("Nazwa roli");
    fireEvent.change(role, { target: { value: "QA Lead" } });
    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    expect(Object.keys(lastPayload()).sort()).toEqual(["basics", "expected_profile_hash"]);
    expect(lastPayload()).toMatchObject({
      basics: { role_name: "QA Lead" },
      expected_profile_hash: "h1",
    });
  });

  it("odświeżony profil przy niezapisanych zmianach: szkic zostaje, baner „Przeładuj”", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 62, champion_profile: PROFILE, profile_hash: "h1" },
    });
    const client = renderWithClient(62);
    const role = await screen.findByLabelText("Nazwa roli");
    fireEvent.change(role, { target: { value: "QA Lead" } });

    act(() => {
      client.setQueryData(["champion-profile", 62], {
        job_id: 62,
        champion_profile: { ...PROFILE, basics: { role_name: "Tester" } },
        profile_hash: "h2",
      });
    });
    const banner = await screen.findByTestId("champion-profile-conflict");
    expect(banner).toHaveTextContent("Profil zmienił się w międzyczasie");
    expect(screen.getByLabelText("Nazwa roli")).toHaveValue("QA Lead");

    await userEvent.click(within(banner).getByRole("button", { name: "Przeładuj" }));
    expect(screen.getByLabelText("Nazwa roli")).toHaveValue("Tester");
    expect(screen.queryByTestId("champion-profile-conflict")).toBeNull();
  });

  it("„Zostaw moje”: szkic zostaje, zapis idzie z nowym odciskiem i tylko zmienionymi sekcjami", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 63, champion_profile: PROFILE, profile_hash: "h1" },
    });
    putMock.mockResolvedValue({ data: { job_id: 63, champion_profile: PROFILE, profile_hash: "h3" } });
    const client = renderWithClient(63);
    fireEvent.change(await screen.findByLabelText("Nazwa roli"), { target: { value: "QA Lead" } });
    act(() => {
      client.setQueryData(["champion-profile", 63], {
        job_id: 63,
        champion_profile: { ...PROFILE, project: { about: "Nowy opis od kolegi." } },
        profile_hash: "h2",
      });
    });
    const banner = await screen.findByTestId("champion-profile-conflict");
    await userEvent.click(within(banner).getByRole("button", { name: "Zostaw moje" }));
    expect(screen.queryByTestId("champion-profile-conflict")).toBeNull();
    expect(screen.getByLabelText("Nazwa roli")).toHaveValue("QA Lead");

    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    // Opis projektu kolegi nie jedzie z powrotem — tylko sekcja zmieniona przez DL-a.
    expect(Object.keys(lastPayload()).sort()).toEqual(["basics", "expected_profile_hash"]);
    expect(lastPayload().expected_profile_hash).toBe("h2");
  });

  it("odświeżony profil bez niezapisanych zmian: pola po prostu się odświeżają", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 64, champion_profile: PROFILE, profile_hash: "h1" },
    });
    const client = renderWithClient(64);
    await screen.findByLabelText("Nazwa roli");
    act(() => {
      client.setQueryData(["champion-profile", 64], {
        job_id: 64,
        champion_profile: { ...PROFILE, basics: { role_name: "Tester" } },
        profile_hash: "h2",
      });
    });
    await waitFor(() => expect(screen.getByLabelText("Nazwa roli")).toHaveValue("Tester"));
    expect(screen.queryByTestId("champion-profile-conflict")).toBeNull();
  });

  it("ten sam profil (np. zmienił się tylko termin rekrutacji) nie zakłóca edycji", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 65, champion_profile: PROFILE, profile_hash: "h1" },
    });
    const client = renderWithClient(65);
    fireEvent.change(await screen.findByLabelText("Nazwa roli"), { target: { value: "QA Lead" } });
    act(() => {
      client.setQueryData(["champion-profile", 65], {
        job_id: 65,
        champion_profile: PROFILE,
        profile_hash: "h1",
        job_values: { deadline: "2026-11-01" },
      });
    });
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByTestId("champion-profile-conflict")).toBeNull();
    expect(screen.getByLabelText("Nazwa roli")).toHaveValue("QA Lead");
  });

  it("409 `champion_profile_conflict`: baner zamiast błędu, szkic zostaje, „Zostaw moje” bierze nowy odcisk", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 66, champion_profile: PROFILE, profile_hash: "h1" },
    });
    putMock
      .mockRejectedValueOnce(
        axiosError(409, {
          code: "champion_profile_conflict",
          message: "Ktoś zmienił Profil Championa, gdy go edytowałeś.",
          champion_profile: { ...PROFILE, basics: { role_name: "Tester" } },
          profile_hash: "h9",
        }),
      )
      .mockResolvedValueOnce({ data: { job_id: 66, champion_profile: PROFILE, profile_hash: "h10" } });
    renderWithClient(66);
    fireEvent.change(await screen.findByLabelText("Nazwa roli"), { target: { value: "QA Lead" } });
    await userEvent.click(screen.getByTestId("save-champion-profile"));
    const banner = await screen.findByTestId("champion-profile-conflict");
    expect(banner).toHaveTextContent("Ktoś zmienił Profil Championa");
    expect(screen.queryByTestId("champion-profile-save-error")).toBeNull();
    expect(screen.getByLabelText("Nazwa roli")).toHaveValue("QA Lead");

    await userEvent.click(within(banner).getByRole("button", { name: "Zostaw moje" }));
    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(2));
    expect(lastPayload()).toMatchObject({
      basics: { role_name: "QA Lead" },
      expected_profile_hash: "h9",
    });
  });

  it("wiersze wymagań: `stack` jedzie w całości, nietknięte sekcje i notatki — nie", async () => {
    const rowsProfile = {
      ...PROFILE,
      stack: {
        must: [{ name: "Java" }],
        nice: [],
        critical: [],
        notes: "Zdanie klienta.",
        rows: [{ words: ["Java"], level: "must" }],
      },
      search: { requirements: [["Java"]] },
    };
    getMock.mockResolvedValue({
      data: { job_id: 67, champion_profile: rowsProfile, profile_hash: "h1" },
    });
    putMock.mockResolvedValue({ data: { job_id: 67, champion_profile: rowsProfile } });
    renderWithClient(67);
    const java = await screen.findByRole("radiogroup", { name: "Poziom wymagania: Java" });
    await userEvent.click(
      Array.from(java.querySelectorAll("button")).find((b) => b.textContent === "Mile widziane")!,
    );
    await userEvent.click(screen.getByTestId("save-champion-profile"));
    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    const payload = lastPayload() as { stack: Record<string, unknown> };
    expect(payload).not.toHaveProperty("insights");
    expect(payload).not.toHaveProperty("project");
    expect(payload).not.toHaveProperty("basics");
    expect(payload.stack).toMatchObject({
      rows: [{ words: ["Java"], level: "nice" }],
      critical: [],
      notes: "Zdanie klienta.",
    });
  });

  it("uwagi zapisu (`notices`) idą do powiadomienia", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 68, champion_profile: PROFILE, profile_hash: "h1" },
    });
    putMock.mockResolvedValue({
      data: {
        job_id: 68,
        champion_profile: PROFILE,
        profile_hash: "h2",
        notices: ["„Ansible” nie jest już technologią ze słownika — zostaje „musi mieć”."],
      },
    });
    renderWithClient(68, true);
    fireEvent.change(await screen.findByLabelText("Nazwa roli"), { target: { value: "QA Lead" } });
    await userEvent.click(screen.getByTestId("save-champion-profile"));
    expect(
      await screen.findByText(
        "„Ansible” nie jest już technologią ze słownika — zostaje „musi mieć”.",
      ),
    ).toBeInTheDocument();
  });

  it("422 `handoff_regression`: lista braków z sekcjami, w których się je usuwa", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 69, champion_profile: PROFILE, profile_hash: "h1" },
    });
    putMock.mockRejectedValue(
      axiosError(422, {
        code: "handoff_regression",
        message: "Tej zmiany nie da się zapisać — rekrutacja w pracy straciłaby wymaganą informację.",
        blockers: [
          { code: "questions", message: "Dodaj co najmniej 2 pytania screeningowe w Profilu Championa." },
          { code: "hiring_manager", message: "Wskaż hiring managera albo zaznacz „Klient nie podał”." },
        ],
      }),
    );
    renderWithClient(69);
    fireEvent.change(await screen.findByLabelText("Nazwa roli"), { target: { value: "QA Lead" } });
    await userEvent.click(screen.getByTestId("save-champion-profile"));
    const alert = await screen.findByTestId("champion-profile-save-error");
    expect(alert).toHaveTextContent("rekrutacja w pracy straciłaby wymaganą informację");
    const items = within(alert).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Dodaj co najmniej 2 pytania screeningowe");
    expect(within(items[0]).getByRole("link", { name: "6 · Pytania screeningowe" })).toHaveAttribute(
      "href",
      "#champion-section-screening",
    );
    // Brak spoza profilu — bez linku do sekcji.
    expect(within(items[1]).queryByRole("link")).toBeNull();
    expect(screen.getByLabelText("Nazwa roli")).toHaveValue("QA Lead");
  });
});
