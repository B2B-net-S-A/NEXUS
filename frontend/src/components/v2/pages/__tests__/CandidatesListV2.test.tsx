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
import { clearSearchMemory, readRecentSearches, writeListSearch } from "@/lib/search-memory";

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

function bar() {
  return screen.getByRole("region", { name: "Filtry kandydatów" });
}

/** Otwiera okienko przycisku filtra na pasku („Lokalizacja”, „Historia z nami”…). */
async function openFilter(name: RegExp) {
  fireEvent.click(within(bar()).getByRole("button", { name }));
  return screen.findByRole("dialog");
}

/** Otwiera szufladę „Więcej filtrów” i rozwija wskazaną sekcję. */
async function openAdvanced(section: RegExp) {
  if (!screen.queryByTestId("candidate-more-filters")) {
    fireEvent.click(within(bar()).getByRole("button", { name: /Więcej filtrów/ }));
  }
  const more = await screen.findByTestId("candidate-more-filters");
  const toggle = within(more).getByRole("button", { name: section });
  if (toggle.getAttribute("aria-expanded") === "false") fireEvent.click(toggle);
  return more;
}

/** Status żyje w sekcji „Inne” szuflady „Więcej filtrów”. */
async function pickStatus(option: string) {
  const more = await openAdvanced(/^Inne/);
  fireEvent.click(within(more).getByRole("button", { name: option }));
}

/**
 * „Szukaj” — zmiany filtrów czekają na ten przycisk (25.09.2026). Przy otwartej
 * szufladzie „Więcej filtrów” klikamy przycisk w jej stopce (pasek pod nią
 * jest wtedy ukryty przed czytnikiem).
 */
function search() {
  const drawer = screen.queryByTestId("candidate-more-filters");
  if (drawer) {
    fireEvent.click(screen.getByRole("button", { name: /^Szukaj \(/ }));
    return;
  }
  fireEvent.click(within(bar()).getByRole("button", { name: /^Szukaj(?! w)/ }));
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
    // Pamięć ostatniego wyszukiwania (sessionStorage) przeżywa test — bez tego
    // goły adres następnego testu przywróciłby filtry poprzedniego.
    clearSearchMemory();
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
      const headers = Array.from(
        screen.getByTestId("candidate-list-header").querySelectorAll("[data-column-header]"),
      ).map((h) => h.textContent);
      // Bez połowicznych ról tabeli (axe: aria-required-parent/children).
      expect(screen.queryAllByRole("columnheader")).toHaveLength(0);
      expect(screen.queryAllByRole("row")).toHaveLength(0);
      expect(headers).toEqual([
        "Kandydat",
        "Ostatnie stanowisko",
        "Telefon",
        "Stawka B2B",
        "Dostępność",
        "W procesie",
        "CV",
        "Przypisz",
      ]);
      // Pasek nad tabelą (wariant A, 23.09.2026): słowa kluczowe jak w Traffit
      // (wszystkie / którekolwiek / żadne + „Szukaj w”) widać od razu.
      expect(within(bar()).getByLabelText("Zawiera wszystkie ze słów")).toBeTruthy();
      expect(within(bar()).getByLabelText("Zawiera którekolwiek ze słów")).toBeTruthy();
      expect(within(bar()).getByLabelText("Nie zawiera żadnego ze słów")).toBeTruthy();
      expect(within(bar()).getByLabelText("Szukaj w")).toBeTruthy();
      // Pozostałe grupy to przyciski; pola są dopiero w ich okienkach.
      for (const name of [
        /^Stawka/,
        /^Lokalizacja/,
        /^Tryb pracy/,
        /^Historia z nami/,
        /^Umiejętności/,
        /^Dostępność/,
        /^Więcej filtrów/,
      ]) {
        expect(within(bar()).getByRole("button", { name })).toBeTruthy();
      }
      expect(screen.queryByLabelText("Promień")).toBeNull();
      expect(screen.queryByText("Brał udział w rekrutacji")).toBeNull();
      const location = await openFilter(/^Lokalizacja/);
      expect(within(location).getByLabelText("Miasto")).toBeTruthy();
      expect(within(location).getByLabelText("Promień")).toBeTruthy();
      fireEvent.keyDown(location, { key: "Escape" });
      await waitFor(() => expect(screen.queryByLabelText("Promień")).toBeNull());
      const history = await openFilter(/^Historia z nami/);
      expect(within(history).getByText("Brał udział w rekrutacji")).toBeTruthy();
      fireEvent.keyDown(history, { key: "Escape" });
      await waitFor(() => expect(screen.queryByText("Brał udział w rekrutacji")).toBeNull());
      // Rzadsze grupy w szufladzie „Więcej filtrów”, zwinięte.
      expect(screen.queryByRole("radiogroup", { name: "Kogo pokazać" })).toBeNull();
      fireEvent.click(within(bar()).getByRole("button", { name: /Więcej filtrów/ }));
      const more = await screen.findByTestId("candidate-more-filters");
      expect(within(more).getByRole("button", { name: /^Inne/ })).toHaveAttribute(
        "aria-expanded",
        "false",
      );
      expect(within(more).queryByRole("button", { name: /Historia z nami/ })).toBeNull();
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
          phone: "+48 601 204 118",
          linkedin_current_title: "Senior Java Developer",
          linkedin_current_company: "Fikcyjny Bank",
          availability_date: "2026-10-01",
          expected_rate_hourly: 160,
          active_recruitments: [
            { job_id: 1, job_title: "A", client_name: "Klient A", stage: "verified", moved_at: "2026-09-01T10:00:00Z" },
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
      expect(within(row).getByText("Senior Java Developer")).toBeTruthy();
      expect(within(row).getByText("Fikcyjny Bank")).toBeTruthy();
      expect(within(row).getByRole("link", { name: "+48 601 204 118" })).toHaveAttribute(
        "href",
        "tel:+48601204118",
      );
      // „W procesie”: najechanie pokazuje rekrutacje w toku (bez zamkniętych).
      fireEvent.mouseEnter(within(row).getByText("2 procesy · CV wysłane"));
      expect(await screen.findByText("Rekrutacje w toku (2)")).toBeTruthy();
      expect(screen.getByRole("link", { name: /^B/ })).toHaveAttribute("href", "/jobs/2");
      expect(screen.getByRole("link", { name: /^A/ })).toHaveAttribute("href", "/jobs/1");
      expect(screen.queryByRole("link", { name: /^C/ })).toBeNull();
      // Kolumna „CV”: przycisk podglądu tylko u osoby z plikiem CV.
      expect(
        within(row).getByRole("button", { name: "Podgląd CV: Marta Kowalczyk" }),
      ).toBeTruthy();
      const empty = screen.getByTestId("candidate-row-2");
      // Stanowisko, telefon, stawka, dostępność i CV — pięć „brak”.
      expect(within(empty).getAllByText("brak")).toHaveLength(5);
      expect(within(empty).getByText("brak lokalizacji")).toBeTruthy();
      expect(within(empty).queryByRole("button", { name: /Podgląd CV/ })).toBeNull();
      expect(
        within(empty).getByRole("button", { name: "Przypisz Tomasz Nowicki do rekrutacji" }),
      ).toBeTruthy();
    });

    it("słowa kluczowe i wykluczenia z panelu idą do API", async () => {
      renderList();
      const must = within(bar()).getByLabelText("Zawiera wszystkie ze słów");
      fireEvent.change(must, { target: { value: "Kafka" } });
      fireEvent.keyDown(must, { key: "Enter" });
      const exclude = within(bar()).getByLabelText("Nie zawiera żadnego ze słów");
      fireEvent.change(exclude, { target: { value: "junior" } });
      fireEvent.keyDown(exclude, { key: "Enter" });
      search();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ q_all: ["Kafka"], q_none: ["junior"] });
      });
    });

    it("„którekolwiek” i „Szukaj w” z panelu idą do API", async () => {
      renderList();
      const any = within(bar()).getByLabelText("Zawiera którekolwiek ze słów");
      fireEvent.change(any, { target: { value: "Spring" } });
      fireEvent.keyDown(any, { key: "Enter" });
      fireEvent.change(any, { target: { value: "Quarkus" } });
      fireEvent.keyDown(any, { key: "Enter" });
      fireEvent.change(within(bar()).getByLabelText("Szukaj w"), { target: { value: "cv" } });
      search();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ q_any_group: ["Spring|Quarkus"], q_scope: "cv" });
      });
    });

    it("promień w km wysyła się razem z miastem", async () => {
      renderList();
      const popover = await openFilter(/^Lokalizacja/);
      fireEvent.change(within(popover).getByLabelText("Miasto"), { target: { value: "Kraków" } });
      fireEvent.keyDown(popover, { key: "Escape" });
      search();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ location: "Kraków" });
      });
      const again = await openFilter(/^Lokalizacja/);
      fireEvent.change(within(again).getByLabelText("Promień"), { target: { value: "25" } });
      fireEvent.keyDown(again, { key: "Escape" });
      search();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ location: "Kraków", location_radius_km: 25 });
      });
      // Przycisk niesie wartość, a ✕ obok czyści całą lokalizację.
      expect(
        within(bar()).getByRole("button", { name: /^Lokalizacja: Kraków \+25 km/ }),
      ).toBeTruthy();
    });

    it("miasto wpisane tuż przed zamknięciem okienka nie przepada", async () => {
      renderList();
      const popover = await openFilter(/^Lokalizacja/);
      fireEvent.change(within(popover).getByLabelText("Miasto"), { target: { value: "Gdańsk" } });
      fireEvent.keyDown(popover, { key: "Escape" });
      search();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ location: "Gdańsk" });
      });
    });

    it("stawka z okienka idzie do API, a ✕ na przycisku ją zdejmuje", async () => {
      renderList();
      const popover = await openFilter(/^Stawka/);
      fireEvent.change(within(popover).getByLabelText("Stawka B2B — do"), {
        target: { value: "160" },
      });
      fireEvent.keyDown(popover, { key: "Escape" });
      search();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ max_rate: 160 });
      });
      expect(
        within(bar()).getByRole("button", { name: /^Stawka: do 160 zł\/h/ }),
      ).toBeTruthy();
      fireEvent.click(within(bar()).getByRole("button", { name: "Wyczyść: Stawka" }));
      // Powrót do pierwszych parametrów trafia w cache react-query — sprawdzamy
      // przycisk i adres, nie kolejne wywołanie API.
      await waitFor(() =>
        expect(within(bar()).queryByRole("button", { name: "Wyczyść: Stawka" })).toBeNull(),
      );
      expect(within(bar()).getByRole("button", { name: /^Stawka$/ })).toBeTruthy();
    });

    it("kontakt z kandydatem w „Historii z nami”", async () => {
      renderList();
      const history = await openFilter(/^Historia z nami/);
      const group = within(history).getByRole("radiogroup", { name: "Kontakt z kandydatem" });
      fireEvent.click(within(group).getByRole("radio", { name: "Nie było kontaktu" }));
      fireEvent.change(within(history).getByLabelText("Kontakt — od"), {
        target: { value: "2026-08-01" },
      });
      fireEvent.keyDown(history, { key: "Escape" });
      search();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ contacted: "no", contacted_from: "2026-08-01" });
      });
    });

    it("wybrane kolumny z preferencji osoby", async () => {
      const { useUiStore } = await import("@/store/ui");
      useUiStore.getState().setColumnPreference("candidates-table-v2", ["phone", "cv"]);
      try {
        renderList();
        const headers = Array.from(
          screen.getByTestId("candidate-list-header").querySelectorAll("[data-column-header]"),
        ).map((h) => h.textContent);
        expect(headers).toEqual([
          "Kandydat",
          "Ostatnie stanowisko",
          "E-mail",
          "Lokalizacja",
          "Stawka B2B",
          "Dostępność",
          "Staż",
          "W procesie",
          "Ostatni kontakt",
          "Dodano",
          "Przypisz",
        ]);
      } finally {
        useUiStore.getState().clearColumnPreference("candidates-table-v2");
      }
    });

    it("dostępność łączy dostępność i zatrudnienie jedną odpowiedzią", async () => {
      renderList();
      const popover = await openFilter(/^Dostępność/);
      const group = within(popover).getByRole("radiogroup", {
        name: "Czy można go teraz zaproponować?",
      });
      fireEvent.click(within(group).getByRole("radio", { name: /Tak — szuka pracy/ }));
      fireEvent.keyDown(popover, { key: "Escape" });
      search();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({
          availability: ["actively_looking", "open_to_offers"],
          employment: ["available"],
        });
      });
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

  describe("przycisk „Szukaj” i pamięć wyszukiwania (25.09.2026)", () => {
    it("zmiana filtra czeka na „Szukaj”, a „Cofnij zmiany” wraca do zastosowanych", async () => {
      renderList();
      await waitFor(async () => expect((await candidateCalls()).length).toBeGreaterThan(0));
      const before = (await candidateCalls()).length;
      const must = within(bar()).getByLabelText("Zawiera wszystkie ze słów");
      fireEvent.change(must, { target: { value: "Kafka" } });
      fireEvent.keyDown(must, { key: "Enter" });
      expect(await screen.findByText("1 zmiana czeka na „Szukaj”")).toBeTruthy();
      expect((await candidateCalls()).length).toBe(before);

      fireEvent.click(screen.getByRole("button", { name: "Cofnij zmiany" }));
      await waitFor(() => expect(screen.queryByText(/czeka na „Szukaj”/)).toBeNull());

      fireEvent.change(must, { target: { value: "Kafka" } });
      fireEvent.keyDown(must, { key: "Enter" });
      // Enter w pustym polu = „Szukaj”.
      fireEvent.keyDown(must, { key: "Enter" });
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ q_all: ["Kafka"] });
      });
      expect(screen.queryByText(/czeka na „Szukaj”/)).toBeNull();
      expect(readRecentSearches(7)[0]).toMatchObject({ kind: "list", label: "Kafka", keywords: ["Kafka"] });
    });

    it("goły adres przywraca ostatnie wyszukiwanie z tej karty", async () => {
      writeListSearch({ query: "q_all=Kafka&rate_max=160" });
      renderList();
      expect(await screen.findByText("Wróciłeś do swojego wyszukiwania.")).toBeTruthy();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ q_all: ["Kafka"], max_rate: 160 });
      });

      fireEvent.click(screen.getByRole("button", { name: "Nowe wyszukiwanie" }));
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)?.q_all).toBeUndefined();
      });
      expect(screen.queryByText("Wróciłeś do swojego wyszukiwania.")).toBeNull();
    });

    it("adres z filtrami wygrywa z pamięcią", async () => {
      writeListSearch({ query: "q_all=Kafka" });
      urlParams = new URLSearchParams("q_all=Python");
      renderList();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ q_all: ["Python"] });
      });
      expect(screen.queryByText("Wróciłeś do swojego wyszukiwania.")).toBeNull();
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
      // Zmiana czeka na „Szukaj” — adres jeszcze stoi.
      expect(pushState).not.toHaveBeenCalled();
      search();

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
      fireEvent.keyDown(screen.getByLabelText("Szukaj kandydatów"), { key: "Enter" });

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
      search();
      expect(await screen.findByText("Status: Aktywni")).toBeTruthy();
      await waitFor(() => expect(pushState).toHaveBeenCalledTimes(1));

      await act(async () => {
        window.history.replaceState(null, "", "/candidates");
        window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
      });

      await waitFor(() => expect(screen.queryByText("Status: Aktywni")).toBeNull());
      expect(pushState).toHaveBeenCalledTimes(1);
      expect(window.location.search).toBe("");
    });
  });

  describe("pasek filtrów", () => {
    it("„Moi kandydaci” zawęża do dodanych przez zalogowaną osobę", async () => {
      renderList();
      const more = await openAdvanced(/Kto dodał/);
      fireEvent.click(within(more).getByRole("radio", { name: "Moi kandydaci" }));
      expect(within(more).getByRole("radio", { name: "Moi kandydaci" })).toHaveAttribute(
        "aria-checked",
        "true",
      );
      search();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ added_by_user_id: [7] });
      });
    });

    it("języki z adresu idą do API i podbijają licznik „Więcej filtrów”", async () => {
      urlParams = new URLSearchParams("lang=en:B2");
      renderList();
      await waitFor(async () => {
        const calls = await candidateCalls();
        expect(calls.at(-1)).toMatchObject({ languages: ["en:B2"] });
      });
      expect(within(bar()).getByRole("button", { name: /Więcej filtrów\s*1/ })).toBeTruthy();
      expect(screen.getByText("Język: angielski min. B2")).toBeTruthy();
    });

    it("„Wyczyść (n)” zdejmuje wszystkie filtry", async () => {
      urlParams = new URLSearchParams("status=active&lang=de");
      renderList();
      fireEvent.click(await within(bar()).findByRole("button", { name: "Wyczyść (2)" }));
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
