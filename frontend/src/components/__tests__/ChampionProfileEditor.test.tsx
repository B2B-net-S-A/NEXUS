/**
 * `ChampionProfileEditor` — krok 02 „Zlecenie i Champion" (program „flow w
 * języku C2", PR 5/7): pełna szerokość (bez `max-w`) + chip stanu (pusta /
 * wypełniona / z AI) przy każdej z sześciu sekcji.
 *
 * Testy renderują z `canEdit={false}` (widok recruitera) — to CELOWO omija
 * `ChampionProfileSourcesPanel` i panel „Wygeneruj z opisu klienta (AI)"
 * (oba `{canEdit && (...)}`, więc się nie montują), dzięki czemu jedyne
 * zapytanie sieciowe to `GET …/champion-profile`. Weryfikacja dwustronna +
 * briefing + rekomendowane wyszukiwania NIE renderują się już tutaj — od
 * tego PR-u mieszkają w `JobReadinessDock` (`variant="champion"`), patrz
 * `JobReadinessDock.test.tsx`.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChampionProfileEditor } from "@/components/ChampionProfileEditor";
import { CHAMPION_SECTIONS } from "@/lib/champion-section-state";
import { useAuthStore, type User } from "@/store/auth";

/** Etykiety sekcji mają JEDNO źródło — test nie może mieć własnej kopii. */
const BASICS_LABEL = CHAMPION_SECTIONS.find((s) => s.id === "basics")!.label;

const getMock = vi.fn();
const putMock = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    championApi: {
      ...actual.championApi,
      get: (...args: unknown[]) => getMock(...args),
      put: (...args: unknown[]) => putMock(...args),
    },
  };
});

// Panel źródeł ma WŁASNE zapytania (notatki, oczekujące propozycje) — dla
// testu zapisu wystarczy, że się nie montuje z siecią.
vi.mock("@/components/ChampionProfileSourcesPanel", () => ({
  ChampionProfileSourcesPanel: () => null,
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
  it("profil pusty — pięć kart z chipem „puste” plus chip grupy „3 z 3 sekcji puste”", async () => {
    getMock.mockResolvedValue({
      data: { job_id: 1, champion_profile: {} },
    });
    renderEditor(1);
    await screen.findByText(BASICS_LABEL);
    // Karty samodzielne: 1 · Podstawowe, 3 · Stack, 4 · Doświadczenie,
    // 7 · O kliencie, 8 · Wiedza z rozmów.
    expect(screen.getAllByText("puste")).toHaveLength(5);
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
    // Sekcje 1 i 3 wypełnione; 4, 7 i 8 puste; grupa 2·5·6 pusta w całości.
    expect(screen.getAllByText("wypełnione")).toHaveLength(2);
    expect(screen.getAllByText("puste")).toHaveLength(3);
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
    expect(screen.getAllByText("puste")).toHaveLength(4);
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

  it("gdy 2 · 4 · 5 są PUSTE — skrót z dwoma polami i „Rozwiń pełne sekcje”, kotwice sekcji zostają", async () => {
    getMock.mockResolvedValue({ data: { job_id: 1, champion_profile: {} } });
    const { container } = renderEditor(1);
    await screen.findByText(BASICS_LABEL);

    expect(screen.getByLabelText(/Frazy do searchu/i)).toBeInTheDocument();
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
      basics: Record<string, unknown>;
    };
    expect("role_name" in payload.basics).toBe(false);
    expect("rate_value" in payload.basics).toBe(false);
    expect("work_mode" in payload.basics).toBe(false);
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
