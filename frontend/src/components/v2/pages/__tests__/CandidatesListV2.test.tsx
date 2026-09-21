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
let listItems: Array<{
  id: number;
  name: string;
  lastname: string;
  unknown_fields?: string[];
}> = [];
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
    if (url === "/api/settings/candidates-columns") {
      return Promise.resolve({ data: { columns: ["candidate", "contact"] } });
    }
    return Promise.resolve({ data: [] });
  });
  return {
    ...original,
    default: { get, post: vi.fn(), put: vi.fn() },
    competenceCategoriesApi: {
      list: vi.fn(() => Promise.resolve({ data: [] })),
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
  normalizeHiddenColumnIds,
} from "@/components/v2/pages/CandidatesListV2";
import { DEFAULT_FILTERS } from "@/lib/url-filters";

function renderList() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CandidatesListV2 />
    </QueryClientProvider>,
  );
}

async function openStatusPillAndPick(option: string) {
  const toolbar = screen.getByRole("group", { name: "Szybkie filtry" });
  fireEvent.click(within(toolbar).getByRole("button", { name: /^Status/ }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: option }));
}

describe("CandidatesListV2", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    urlParams = new URLSearchParams();
    listItems = [];
    listTotal = 0;
    listExtra = {};
    window.history.replaceState(null, "", "/candidates");
    window.matchMedia =
      window.matchMedia ??
      ((query: string) =>
        ({
          matches: false,
          media: query,
          addEventListener: () => undefined,
          removeEventListener: () => undefined,
        }) as unknown as MediaQueryList);
    useUiStore.setState({
      candidatesView: "list",
      candidatesPageSize: 50,
      columnPreferences: {},
    });
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

  describe("historia przeglądarki", () => {
    it("pierwszy zapis podmienia wpis, zmiana filtra dodaje nowy", async () => {
      const pushState = vi.spyOn(window.history, "pushState");
      const replaceState = vi.spyOn(window.history, "replaceState");
      renderList();

      await waitFor(() => expect(replaceState).toHaveBeenCalled());
      expect(pushState).not.toHaveBeenCalled();

      await openStatusPillAndPick("Aktywni");

      await waitFor(() => expect(pushState).toHaveBeenCalledTimes(1));
      expect(String(pushState.mock.calls[0][2])).toContain("status=active");
      // Pigułka i szuflada dzielą stan z chipami aktywnych filtrów.
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

      await openStatusPillAndPick("Aktywni");
      expect(await screen.findByText("Status: Aktywni")).toBeTruthy();
      expect(pushState).toHaveBeenCalledTimes(1);

      // „Wstecz": przeglądarka przywraca adres sprzed filtra i emituje popstate.
      await act(async () => {
        window.history.replaceState(null, "", "/candidates");
        window.dispatchEvent(new PopStateEvent("popstate", { state: null }));
      });

      await waitFor(() => expect(screen.queryByText("Status: Aktywni")).toBeNull());
      expect(pushState).toHaveBeenCalledTimes(1);
      expect(window.location.search).toBe("");
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

      const compare = await screen.findByRole("button", { name: /Porównaj/ });
      expect((compare as HTMLButtonElement).disabled).toBe(true);
      expect(screen.getByText("Maks. 3 — odznacz 1")).toBeTruthy();
      fireEvent.click(compare);
      expect(push).not.toHaveBeenCalled();
    });

    it("„Dodaj do rekrutacji” przekazuje całe zaznaczenie i czyści je po sukcesie", async () => {
      renderList();
      await screen.findByRole("combobox", { name: "Liczba kandydatów na stronie" });
      fireEvent.click(screen.getByRole("checkbox", { name: "Zaznacz stronę" }));
      fireEvent.click(await screen.findByRole("button", { name: /Dodaj do rekrutacji/ }));

      const dialog = await screen.findByRole("dialog", { name: "Dodaj do rekrutacji" });
      expect(within(dialog).getByText("candidate_list:1,2,3,4")).toBeTruthy();
      fireEvent.click(within(dialog).getByRole("button", { name: "Potwierdź dodanie" }));

      expect(showSuccess).toHaveBeenCalledWith("Dodano 4 osoby.");
      await waitFor(() => expect(screen.queryByText(/Zaznaczono:/)).toBeNull());
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

  describe("semantyka v2 (21.09.2026)", () => {
    const candidateCalls = async () => {
      const api = (await import("@/lib/api")).default as unknown as {
        get: ReturnType<typeof vi.fn>;
      };
      return api.get.mock.calls
        .filter((call) => call[0] === "/api/candidates")
        .map((call) => (call[1] as { params: Record<string, unknown> }).params);
    };

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

    it("pod polem wyszukiwania widać „Rozumiem to jako…”", async () => {
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
      const line = await screen.findByTestId("text-interpretation");
      expect(line.textContent).toMatch(/Rozumiem to jako: osoba \(Jan Kowalski\)/);
    });
  });

  it("zapytanie listy niesie wybrany rozmiar strony", async () => {
    const api = (await import("@/lib/api")).default as unknown as {
      get: ReturnType<typeof vi.fn>;
    };
    useUiStore.setState({ candidatesPageSize: 100 });
    renderList();
    await waitFor(() =>
      expect(
        api.get.mock.calls.some(
          (call) =>
            call[0] === "/api/candidates" &&
            (call[1] as { params: { page_size?: number } }).params.page_size === 100,
        ),
      ).toBe(true),
    );
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

  it("filtr i sortowanie są krokiem historii", () => {
    expect(
      isHistoryNeutralChange(DEFAULT_FILTERS, { ...DEFAULT_FILTERS, status: ["active"] }),
    ).toBe(false);
    expect(
      isHistoryNeutralChange(DEFAULT_FILTERS, { ...DEFAULT_FILTERS, sort: "name" }),
    ).toBe(false);
  });
});

describe("normalizeHiddenColumnIds", () => {
  it("wycofane kolumny przenoszą widoczność na następczynie", () => {
    // Widoczne były: kandydat, CV, Rekrutacje, Status, Pozycja (reszta ukryta).
    const visibleLegacy = new Set(["candidate", "cv", "recruitments", "status", "position"]);
    const allIds = [
      "contact", "status_availability", "process", "rate", "activity", "phone",
      "email", "cv", "recruitments", "stage_moved", "title", "company", "location",
      "experience", "skills", "last_note", "rejection_reason", "position", "status",
      "match", "created", "added_by",
    ];
    const hidden = normalizeHiddenColumnIds(allIds.filter((id) => !visibleLegacy.has(id)));
    const visible = allIds.filter((id) => !hidden.includes(id as never));
    expect(visible.sort()).toEqual(["contact", "process", "status_availability"].sort());
  });
});
