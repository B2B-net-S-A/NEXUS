import type { AnchorHTMLAttributes } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
const showSuccess = vi.fn();
let urlParams = new URLSearchParams();
let listItems: Array<Record<string, unknown> & { id: number }> = [];
let listTotal = 0;
let listExtra: Record<string, unknown> = {};

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => urlParams,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  const get = vi.fn((url: string) => {
    if (url === "/api/candidates") {
      return Promise.resolve({
        data: {
          items: listItems,
          total: listTotal,
          page: 1,
          page_size: 50,
          ...listExtra,
        },
      });
    }
    return Promise.resolve({ data: [] });
  });
  return {
    ...original,
    default: { get, post: vi.fn(), put: vi.fn() },
    competenceCategoriesApi: {
      list: vi.fn(() => Promise.resolve([])),
    },
  };
});

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess, showError: vi.fn(), showToast: vi.fn() }),
}));
vi.mock("@/hooks/useCandidateContactFeature", () => ({
  useCandidateContactFeature: () => ({ enabled: false }),
}));
vi.mock("@/components/AppShell", () => ({ AddCandidateModal: () => null }));
vi.mock("@/components/v2/modals/ImportCandidatesV2", () => ({
  ImportCandidatesV2: () => null,
}));
vi.mock("@/components/v2/modals/AddCandidateFromCVModal", () => ({
  AddCandidateFromCVModal: () => null,
}));
vi.mock("@/components/v2/modals/QuickAssignV2", () => ({ QuickAssignV2: () => null }));
vi.mock("@/components/v2/modals/GenerateInviteLinkV2", () => ({
  GenerateInviteLinkV2: () => null,
}));
vi.mock("@/components/v2/pages/CandidateQuickView", () => ({
  CandidateQuickView: () => null,
}));
vi.mock("@/components/v2/filters/PinnedCandidatesBar", () => ({
  PinnedCandidatesBar: () => null,
}));
vi.mock("@/components/v2/filters/SavedSearchesMenu", () => ({
  SavedSearchesMenu: () => null,
}));
vi.mock("@/components/v2/filters/CompetenceCategoryMultiSelect", () => ({
  CompetenceCategoryMultiSelect: () => null,
}));
// jsdom nie ma wymiarów — wirtualizacja renderuje wszystkie wiersze strony.
vi.mock("@tanstack/react-virtual", () => ({
  useVirtualizer: ({ count }: { count: number }) => ({
    getTotalSize: () => count * 64,
    getVirtualItems: () =>
      Array.from({ length: count }, (_, index) => ({ index, start: index * 64, size: 64 })),
    measure: () => undefined,
  }),
}));
vi.mock("@/components/v2/candidates/RequestSearchDialog", () => ({
  RequestSearchDialog: ({
    open,
    initialText,
    onSubmit,
  }: {
    open: boolean;
    initialText?: string;
    onSubmit: (r: unknown) => void;
  }) =>
    open ? (
      <div role="dialog" aria-label="Szukaj z requestu">
        <span data-testid="request-initial-text">{initialText}</span>
        <button type="button" onClick={() => onSubmit({ source: "text", text: "x" })}>
          Dalej
        </button>
      </div>
    ) : null,
}));
vi.mock("@/components/v2/recruitment/AddToRecruitmentDialog", () => ({
  addToRecruitmentSummary: () => "Dodano 4 osoby.",
  AddToRecruitmentDialog: ({
    open,
    candidateIds,
    source,
    onAdded,
  }: {
    open: boolean;
    candidateIds: number[];
    source: string;
    onAdded?: (result: unknown) => void;
  }) =>
    open ? (
      <div role="dialog" aria-label="Dodaj do rekrutacji">
        <span>
          {source}:{candidateIds.join(",")}
        </span>
        <button type="button" onClick={() => onAdded?.({})}>
          Potwierdź dodanie
        </button>
      </div>
    ) : null,
}));

import { useAuthStore } from "@/store/auth";
import { useUiStore } from "@/store/ui";
import {
  CandidatesListV2,
  isHistoryNeutralChange,
} from "@/components/v2/pages/CandidatesListV2";
import { DEFAULT_FILTERS } from "@/lib/url-filters";

function renderList(props: Parameters<typeof CandidatesListV2>[0] = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CandidatesListV2 {...props} />
    </QueryClientProvider>,
  );
}

function rail() {
  return screen.getByRole("complementary", { name: "Filtry kandydatów" });
}

async function pickStatus(option: string) {
  fireEvent.click(within(rail()).getByRole("button", { name: option }));
}

async function candidateCalls() {
  const api = (await import("@/lib/api")).default as unknown as {
    get: ReturnType<typeof vi.fn>;
  };
  return api.get.mock.calls
    .filter(
      (call) =>
        call[0] === "/api/candidates" &&
        (call[1] as { params: { page_size?: number } }).params.page_size !== 1,
    )
    .map((call) => (call[1] as { params: Record<string, unknown> }).params);
}

describe("CandidatesListV2", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    urlParams = new URLSearchParams();
    listItems = [];
    listTotal = 0;
    listExtra = {};
    window.history.replaceState(null, "", "/candidates");
    useUiStore.setState({ candidatesPageSize: 50 });
    useAuthStore.setState({
      user: {
        id: 7,
        email: "rekruterka@example.com",
        name: "Rekruterka",
        role: "recruiter",
        roles: ["recruiter"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
        capabilities: [],
        analytics_capabilities: [],
      },
      hydrated: true,
    } as never);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  describe("układ (22.09.2026)", () => {
    it("jeden ekran: nagłówek, stała kolumna filtrów, pole wyszukiwania i stałe kolumny tabeli", async () => {
      listTotal = 12481;
      renderList({ onRequestSearch: vi.fn() });
      expect(screen.getByRole("heading", { level: 1, name: "Kandydaci" })).toBeTruthy();
      expect(await screen.findByText("12 481 w bazie")).toBeTruthy();
      expect(screen.getByLabelText("Szukaj kandydatów")).toHaveAttribute(
        "placeholder",
        "Nazwisko, e-mail, telefon albo opis, kogo szukasz…",
      );
      expect(screen.getByRole("button", { name: /Z requestu/ })).toBeTruthy();
      const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
      expect(headers).toEqual([
        "Kandydat",
        "Lokalizacja",
        "Dostępność",
        "Stawka B2B",
        "W procesie",
        "CV",
      ]);
      // Sekcje zawsze widoczne w kolumnie filtrów.
      expect(within(rail()).getByRole("radiogroup", { name: "Kogo pokazać" })).toBeTruthy();
      expect(within(rail()).getByText("Status")).toBeTruthy();
      expect(within(rail()).getByText("Dostępność")).toBeTruthy();
      expect(within(rail()).getByText("Umiejętności")).toBeTruthy();
      // Grupy zwinięte, dopóki nic w nich nie ustawiono.
      expect(
        within(rail()).getByRole("button", { name: /Lokalizacja i tryb pracy/ }),
      ).toHaveAttribute("aria-expanded", "false");
      // Bez konfiguracji kolumn, gęstości i widoku kafelków.
      expect(screen.queryByLabelText("Konfiguracja kolumn")).toBeNull();
      expect(screen.queryByLabelText("Widok kafelków")).toBeNull();
    });

    it("wiersz pokazuje „brak” tam, gdzie nie ma danych, i podsumowanie procesów", async () => {
      listItems = [
        {
          id: 1,
          name: "Marta",
          lastname: "Kowalczyk",
          skills: ["Java", "Spring", "Kafka", "AWS"],
          cv_filename: "CV_Marta.pdf",
          city: "Warszawa",
          availability_date: "2026-10-01",
          expected_rate_hourly: 160,
          active_recruitments: [
            { job_id: 1, job_title: "A", stage: "verified", moved_at: "2026-09-01T10:00:00Z" },
            { job_id: 2, job_title: "B", stage: "cv_sent", moved_at: "2026-09-10T10:00:00Z" },
            { job_id: 3, job_title: "C", stage: "rejected", moved_at: "2026-09-12T10:00:00Z" },
          ],
        },
        { id: 2, name: "Tomasz", lastname: "Nowicki" },
      ];
      listTotal = 2;
      renderList();
      const row = await screen.findByTestId("candidate-row-1");
      expect(within(row).getByText("od 01.10")).toBeTruthy();
      expect(within(row).getByText("160 zł/h")).toBeTruthy();
      expect(within(row).getByText("2 procesy · CV wysłane")).toBeTruthy();
      // Kolumna „CV”: przycisk podglądu tylko u osoby z plikiem CV.
      expect(
        within(row).getByRole("button", { name: "Podgląd CV: Marta Kowalczyk" }),
      ).toBeTruthy();
      const empty = screen.getByTestId("candidate-row-2");
      // Lokalizacja, dostępność, stawka i CV — cztery „brak”.
      expect(within(empty).getAllByText("brak")).toHaveLength(4);
      expect(within(empty).queryByRole("button", { name: /Podgląd CV/ })).toBeNull();
      expect(
        within(empty).getByRole("button", { name: "Przypisz Tomasz Nowicki do rekrutacji" }),
      ).toBeTruthy();
    });

    it("zapytanie prosi o aktywne rekrutacje (kolumna „W procesie”), bez statystyk dopasowania", async () => {
      renderList();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ include_active_recruitments: true });
        expect(calls.at(-1)?.include_match_stats).toBeUndefined();
      });
    });
  });

  describe("historia przeglądarki", () => {
    it("pierwszy zapis podmienia wpis, zmiana filtra dodaje nowy", async () => {
      const pushState = vi.spyOn(window.history, "pushState");
      const replaceState = vi.spyOn(window.history, "replaceState");
      renderList();

      await waitFor(() => expect(replaceState).toHaveBeenCalled());
      expect(pushState).not.toHaveBeenCalled();

      await pickStatus("Aktywni");

      await waitFor(() => expect(pushState).toHaveBeenCalledTimes(1));
      expect(String(pushState.mock.calls[0][2])).toContain("status=active");
      expect(await screen.findByText("Status: Aktywni")).toBeTruthy();
    });

    it("pisanie w polu wyszukiwania tylko podmienia wpis", async () => {
      const pushState = vi.spyOn(window.history, "pushState");
      const replaceState = vi.spyOn(window.history, "replaceState");
      renderList();
      await waitFor(() => expect(replaceState).toHaveBeenCalled());
      replaceState.mockClear();

      fireEvent.change(screen.getByLabelText("Szukaj kandydatów"), {
        target: { value: "tester" },
      });

      await waitFor(() =>
        expect(
          replaceState.mock.calls.some((call) => String(call[2]).includes("q=tester")),
        ).toBe(true),
      );
      expect(pushState).not.toHaveBeenCalled();
    });

    it("popstate przywraca filtr z adresu bez nowego wpisu", async () => {
      const pushState = vi.spyOn(window.history, "pushState");
      renderList();

      await pickStatus("Aktywni");
      expect(await screen.findByText("Status: Aktywni")).toBeTruthy();
      expect(pushState).toHaveBeenCalledTimes(1);

      await act(async () => {
        window.history.replaceState(null, "", "/candidates");
        window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
      });

      await waitFor(() => expect(screen.queryByText("Status: Aktywni")).toBeNull());
      expect(pushState).toHaveBeenCalledTimes(1);
      expect(window.location.search).toBe("");
    });
  });

  describe("kolumna filtrów", () => {
    it("„Moi kandydaci” zawęża do dodanych przez zalogowaną osobę", async () => {
      renderList();
      fireEvent.click(within(rail()).getByRole("radio", { name: "Moi kandydaci" }));
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ added_by_user_id: [7] });
      });
      expect(within(rail()).getByRole("radio", { name: "Moi kandydaci" })).toHaveAttribute(
        "aria-checked",
        "true",
      );
      fireEvent.click(within(rail()).getByRole("radio", { name: "Wszyscy" }));
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)?.added_by_user_id).toBeUndefined();
      });
    });

    it("języki z adresu idą do API, a ich grupa jest rozwinięta", async () => {
      urlParams = new URLSearchParams("lang=en:B2");
      renderList();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ languages: ["en:B2"] });
      });
      expect(within(rail()).getByRole("button", { name: /Języki/ })).toHaveAttribute(
        "aria-expanded",
        "true",
      );
      expect(screen.getByText("Język: angielski min. B2")).toBeTruthy();
    });

    it("„Wyczyść (n)” zdejmuje wszystkie filtry", async () => {
      urlParams = new URLSearchParams("status=active&lang=de");
      renderList();
      fireEvent.click(await within(rail()).findByRole("button", { name: "Wyczyść (2)" }));
      await waitFor(() => expect(screen.queryByText("Status: Aktywni")).toBeNull());
    });
  });

  describe("wyszukiwanie tekstem", () => {
    it("tekst bez wybranego sortowania idzie po trafności z trybem automatycznym", async () => {
      urlParams = new URLSearchParams("q=java%20kafka");
      renderList();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ q: "java kafka", sort: "relevance", text_mode: "auto" });
      });
    });

    it("po znaczeniu: zdanie pod polem i przełączenie na dosłowne", async () => {
      urlParams = new URLSearchParams("q=backend%20z%20kafk%C4%85");
      listExtra = { text_mode_applied: "semantic", result_cap_reached: true };
      renderList();
      expect(
        await screen.findByText("Szukamy po znaczeniu — podobne profile też się liczą."),
      ).toBeTruthy();
      expect(screen.getByText("Pokazujemy najtrafniejsze wyniki (pula ograniczona).")).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Szukaj dosłownie" }));
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ text_mode: "literal" });
      });
    });

    it("osoba: dosłownie, bez przełącznika po znaczeniu", async () => {
      urlParams = new URLSearchParams("q=Jan%20Kowalski");
      listExtra = {
        text_mode_applied: "literal",
        interpretation: {
          kind: "name",
          mode: "literal",
          rule: "multi_token_name",
          name: ["Jan", "Kowalski"],
          email: null,
          phone: null,
          skills: [],
          locations: [],
          other: [],
        },
      };
      renderList();
      expect(
        await screen.findByText("Szukamy dosłownie (nazwisko, e-mail, telefon lub fraza)."),
      ).toBeTruthy();
      expect(screen.queryByRole("button", { name: "Szukaj po znaczeniu" })).toBeNull();
    });

    it("awaria wyszukiwania po znaczeniu jest ostrzeżeniem, nie pustką", async () => {
      urlParams = new URLSearchParams("q=backend");
      listExtra = { text_mode_applied: "literal", search_degraded: true };
      renderList();
      expect(
        await screen.findByText(
          "Wyszukiwanie po znaczeniu chwilowo niedostępne — pokazujemy dopasowania dosłowne.",
        ),
      ).toBeTruthy();
    });

    it("„Z requestu” otwiera okno, a „Dalej” oddaje dane rodzicowi", async () => {
      const onRequestSearch = vi.fn();
      renderList({ onRequestSearch });
      fireEvent.click(screen.getByRole("button", { name: /Z requestu/ }));
      const dialog = await screen.findByRole("dialog", { name: "Szukaj z requestu" });
      fireEvent.click(within(dialog).getByRole("button", { name: "Dalej" }));
      expect(onRequestSearch).toHaveBeenCalledWith({ source: "text", text: "x" });
    });

    it("bez rodzica przycisk „Z requestu” się nie renderuje", () => {
      renderList();
      expect(screen.queryByRole("button", { name: /Z requestu/ })).toBeNull();
    });
  });

  describe("pasek zbiorczy", () => {
    beforeEach(() => {
      listItems = [1, 2, 3, 4].map((id) => ({
        id,
        name: `Osoba${id}`,
        lastname: "Testowa",
      }));
      listTotal = 4;
    });

    it("„Porównaj” jest wyłączone powyżej 3 zaznaczonych, bez ucinania listy", async () => {
      renderList();
      await screen.findByRole("combobox", { name: "Liczba kandydatów na stronie" });
      fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz stronę" }));

      const bar = await screen.findByRole("region", { name: "Akcje zaznaczonych kandydatów" });
      expect(within(bar).getByText("zaznaczonych")).toBeTruthy();
      const compare = within(bar).getByRole("button", { name: /Porównaj/ });
      expect((compare as HTMLButtonElement).disabled).toBe(true);
      expect(within(bar).getByText("Maks. 3 — odznacz 1")).toBeTruthy();
      fireEvent.click(compare);
      expect(push).not.toHaveBeenCalled();
    });

    it("„Dodaj do rekrutacji” przekazuje całe zaznaczenie i czyści je po sukcesie", async () => {
      renderList();
      await screen.findByRole("combobox", { name: "Liczba kandydatów na stronie" });
      fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz stronę" }));
      const bar = await screen.findByRole("region", { name: "Akcje zaznaczonych kandydatów" });
      fireEvent.click(within(bar).getByRole("button", { name: /Dodaj do rekrutacji/ }));

      const dialog = await screen.findByRole("dialog", { name: "Dodaj do rekrutacji" });
      expect(within(dialog).getByText("candidate_list:1,2,3,4")).toBeTruthy();
      fireEvent.click(within(dialog).getByRole("button", { name: "Potwierdź dodanie" }));

      expect(showSuccess).toHaveBeenCalledWith("Dodano 4 osoby.");
      await waitFor(() =>
        expect(screen.queryByRole("region", { name: "Akcje zaznaczonych kandydatów" })).toBeNull(),
      );
    });

    it("„Odznacz” czyści zaznaczenie", async () => {
      renderList();
      await screen.findByRole("combobox", { name: "Liczba kandydatów na stronie" });
      fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz stronę" }));
      fireEvent.click(await screen.findByRole("button", { name: "Odznacz" }));
      expect(screen.queryByRole("region", { name: "Akcje zaznaczonych kandydatów" })).toBeNull();
    });
  });

  describe("pusty stan", () => {
    it("przy aktywnych filtrach proponuje ich wyczyszczenie", async () => {
      urlParams = new URLSearchParams("status=active");
      renderList();

      expect(await screen.findByText("Brak kandydatów spełniających filtry.")).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Wyczyść filtry" }));
      await waitFor(() => expect(screen.queryByText("Status: Aktywni")).toBeNull());
    });

    it("bez filtrów zostaje zachęta do dodania kandydata", async () => {
      renderList();
      expect(await screen.findByText("dodaj nowego kandydata")).toBeTruthy();
      expect(screen.queryByRole("button", { name: "Wyczyść filtry" })).toBeNull();
    });
  });

  it("stara zakładka bez sv idzie w v2 z jawnymi kubełkami", async () => {
    urlParams = new URLSearchParams(
      "skills_q=Java%20Spring%20-PHP&skills_pref=Docker&hu=1",
    );
    renderList();
    await waitFor(async () => {
      const calls = await candidateCalls();
      expect(calls.at(-1)).toMatchObject({
        semantics_version: 2,
        skills_required: ["Java", "Spring"],
        skills_excluded: ["PHP"],
        skills_preferred: ["Docker"],
        hide_unknown: true,
      });
      expect(calls.at(-1)?.skills).toBeUndefined();
    });
  });

  it("zapytanie listy niesie wybrany rozmiar strony", async () => {
    useUiStore.setState({ candidatesPageSize: 100 });
    renderList();
    await waitFor(async () => {
      const calls = await candidateCalls();
      expect(calls.some((p) => p.page_size === 100)).toBe(true);
    });
  });
});

describe("isHistoryNeutralChange", () => {
  it("pole wyszukiwania, strona i widok nie są krokiem historii", () => {
    expect(
      isHistoryNeutralChange(DEFAULT_FILTERS, {
        ...DEFAULT_FILTERS,
        q: "java",
        page: 4,
        view: "tiles",
      }),
    ).toBe(true);
  });

  it("filtr, sortowanie i tryb tekstu są krokiem historii", () => {
    expect(
      isHistoryNeutralChange(DEFAULT_FILTERS, { ...DEFAULT_FILTERS, status: ["active"] }),
    ).toBe(false);
    expect(
      isHistoryNeutralChange(DEFAULT_FILTERS, { ...DEFAULT_FILTERS, sort: "name" }),
    ).toBe(false);
    expect(
      isHistoryNeutralChange(DEFAULT_FILTERS, { ...DEFAULT_FILTERS, textMode: "semantic" }),
    ).toBe(false);
  });
});
