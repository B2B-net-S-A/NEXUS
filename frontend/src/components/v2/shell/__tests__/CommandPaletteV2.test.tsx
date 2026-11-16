import { act, fireEvent, render } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiGet, routerPush, hrNav } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  routerPush: vi.fn(),
  hrNav: { people: false },
}));

vi.mock("@/lib/api", () => ({ default: { get: apiGet } }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: routerPush }) }));
vi.mock("@/hooks/useCapability", () => ({
  useCapabilities: () => new Proxy({}, { get: () => true }),
}));
// Mocki są CZĘŚCIOWE: grupa „Nawigacja" powstaje z `lib/nav-registry`, który
// czyta też `rolesWithSectionAccess` i `hasRole` — pełna podmiana modułu
// wywracałaby import rejestru.
vi.mock("@/lib/section-access", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/section-access")>()),
  hasSectionAccess: () => true,
}));
vi.mock("@/store/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/store/auth")>()),
  useAuthStore: (selector: (state: { user: unknown }) => unknown) =>
    selector({ user: { id: 1, role: "admin", roles: ["admin"] } }),
}));
// Flaga kolejki telefonów idzie z react-query; test nie montuje providera.
vi.mock("@/hooks/useCandidateContactFeature", () => ({
  useCandidateContactFeature: () => ({ enabled: false }),
}));
// Stan modułu „Ludzie w NEXUSIE” też idzie z react-query — moduł wyłączony.
// Księgowość (K1): pozycja z `/api/accounting/config` — tu zamknięta.
vi.mock("@/lib/api/accounting", () => ({ useAccountingNavOpen: () => false }));
vi.mock("@/lib/api/hr", () => ({
  useHrNavState: () => ({ myTime: false, people: hrNav.people, equipment: false }),
  useHrProgram: () => false,
}));
// cmdk w jsdom wymaga ResizeObserver/scrollIntoView — test dotyczy wyłącznie
// zapytań palety, więc prymitywy renderujemy jako zwykłe elementy.
vi.mock("@/components/ui/command", () => {
  const Pass = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return {
    CommandDialog: Pass,
    CommandEmpty: Pass,
    CommandGroup: ({ heading, children }: { heading?: string; children?: ReactNode }) => (
      <div>
        <div>{heading}</div>
        {children}
      </div>
    ),
    CommandItem: ({
      children,
      onSelect,
      disabled,
    }: {
      children?: ReactNode;
      onSelect?: () => void;
      disabled?: boolean;
    }) => (
      <div role="option" aria-disabled={disabled} onClick={onSelect}>
        {children}
      </div>
    ),
    CommandList: Pass,
    CommandSeparator: () => null,
    CommandShortcut: Pass,
    CommandInput: ({
      value,
      onValueChange,
      placeholder,
    }: {
      value: string;
      onValueChange: (v: string) => void;
      placeholder?: string;
    }) => (
      <input
        placeholder={placeholder}
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
      />
    ),
  };
});

import { CommandPaletteV2 } from "@/components/v2/shell/CommandPaletteV2";

beforeEach(() => {
  vi.useFakeTimers();
  apiGet.mockResolvedValue({ data: { items: [], total: 0 } });
});

afterEach(() => {
  vi.useRealTimers();
  apiGet.mockReset();
  routerPush.mockReset();
  hrNav.people = false;
});

/** Wpisuje frazę i czeka na odpowiedzi wszystkich zapytań palety. */
async function search(term: string) {
  const view = render(<CommandPaletteV2 open onOpenChange={() => {}} />);
  fireEvent.change(view.getByPlaceholderText(/Szukaj kandydatów/), {
    target: { value: term },
  });
  await act(async () => {
    vi.advanceTimersByTime(300);
  });
  return view;
}

const JOB_HIT = {
  data: { items: [{ id: 11, title: "Java Developer", client_name: "Bank Przykładowy" }], total: 1 },
};
const PORCJA_MESSAGE = "Najpierw porcja od Nexusa: zostało 32 z 50 decyzji.";

function candidatesFailWith(error: unknown) {
  apiGet.mockImplementation((url: string) =>
    url === "/api/candidates"
      ? Promise.reject(error)
      : Promise.resolve(url === "/api/jobs" ? JOB_HIT : { data: { items: [], total: 0 } }),
  );
}

describe("CommandPaletteV2 — odmowa i awaria kandydatów (audyt S1)", () => {
  const blocked = {
    response: {
      status: 423,
      data: {
        detail: {
          code: "REVIEW_MINIMUM_PENDING",
          message: PORCJA_MESSAGE,
          remaining: 32,
          required: 50,
        },
      },
    },
  };

  it("423 porcji: notka z treścią serwera i droga do /porcja, rekrutacje zostają", async () => {
    candidatesFailWith(blocked);
    const { getByText, queryByText } = await search("java");

    expect(getByText("Kandydaci")).toBeTruthy();
    expect(getByText(PORCJA_MESSAGE)).toBeTruthy();
    expect(getByText("Java Developer")).toBeTruthy();
    expect(queryByText("Nie udało się wczytać kandydatów")).toBeNull();

    fireEvent.click(getByText("Otwórz porcję →"));
    expect(routerPush).toHaveBeenCalledWith("/porcja");
  });

  it("inny błąd: „Nie udało się wczytać kandydatów”, nie wygląda jak pusta lista", async () => {
    candidatesFailWith({ response: { status: 500, data: {} } });
    const { getByText, queryByText } = await search("java");

    expect(getByText("Nie udało się wczytać kandydatów")).toBeTruthy();
    expect(getByText("Java Developer")).toBeTruthy();
    expect(queryByText("Otwórz porcję →")).toBeNull();
  });

  it("423 z innym kodem to zwykła awaria, nie blokada porcji", async () => {
    candidatesFailWith({
      response: { status: 423, data: { detail: { code: "INNA_BLOKADA", message: "x" } } },
    });
    const { getByText, queryByText } = await search("java");

    expect(getByText("Nie udało się wczytać kandydatów")).toBeTruthy();
    expect(queryByText("Otwórz porcję →")).toBeNull();
  });

  it("gdy padło wszystko, zostaje ogólny komunikat bez wiersza kandydatów", async () => {
    apiGet.mockRejectedValue({ response: { status: 500, data: {} } });
    const { getByText, queryByText } = await search("java");

    expect(getByText("Nie udało się wyszukać — spróbuj ponownie za chwilę.")).toBeTruthy();
    expect(queryByText("Nie udało się wczytać kandydatów")).toBeNull();
  });

  it("anulowane zapytanie (zmiana frazy) nie zostawia notki o awarii", async () => {
    apiGet.mockImplementation(
      (url: string, config: { signal: AbortSignal }) =>
        new Promise((resolve, reject) => {
          if (url !== "/api/candidates") {
            resolve({ data: { items: [], total: 0 } });
            return;
          }
          config.signal.addEventListener("abort", () =>
            reject(new Error("canceled")),
          );
        }),
    );
    const view = await search("java");
    fireEvent.change(view.getByPlaceholderText(/Szukaj kandydatów/), {
      target: { value: "j" },
    });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });

    expect(view.queryByText("Nie udało się wczytać kandydatów")).toBeNull();
  });
});

describe("CommandPaletteV2 — sekcja Ludzie (audyt S3)", () => {
  const PEOPLE = [1, 2, 3, 4, 5, 6].map((id) => ({
    id: 100 + id,
    name: `Anna Przykładowa ${id}`,
    subtitle: "Specjalistka ds. płac",
    url: `/people/${100 + id}`,
  }));

  function respond(people: unknown[]) {
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({
        data: url === "/api/search/global" ? { people } : { items: [], total: 0 },
      }),
    );
  }

  it("konto z Ludźmi: najwyżej 5 osób, wiersz prowadzi do /people/{id}", async () => {
    hrNav.people = true;
    respond(PEOPLE);
    const { getByText, queryByText } = await search("Przykładowa");

    expect(getByText("Ludzie")).toBeTruthy();
    expect(getByText("Anna Przykładowa 5")).toBeTruthy();
    expect(queryByText("Anna Przykładowa 6")).toBeNull();
    expect(
      apiGet.mock.calls.find(([url]) => url === "/api/search/global")?.[1]?.params,
    ).toEqual({ q: "Przykładowa" });

    fireEvent.click(getByText("Anna Przykładowa 1"));
    expect(routerPush).toHaveBeenCalledWith("/people/101");
  });

  it("konto bez Ludzi nie pyta o /api/search/global", async () => {
    respond(PEOPLE);
    const { queryByText } = await search("Przykładowa");

    expect(apiGet.mock.calls.some(([url]) => url === "/api/search/global")).toBe(false);
    expect(queryByText("Anna Przykładowa 1")).toBeNull();
  });

  it("awaria wyszukiwarki ludzi nie wygląda jak brak osoby", async () => {
    hrNav.people = true;
    apiGet.mockImplementation((url: string) =>
      url === "/api/search/global"
        ? Promise.reject({ response: { status: 500, data: {} } })
        : Promise.resolve(url === "/api/jobs" ? JOB_HIT : { data: { items: [], total: 0 } }),
    );
    const { getByText } = await search("Przykładowa");

    expect(getByText("Nie udało się wczytać ludzi")).toBeTruthy();
    expect(getByText("Java Developer")).toBeTruthy();
  });
});

describe("CommandPaletteV2 — wyszukiwanie kandydatów", () => {
  it("pyta o kandydatów z sortowaniem po trafności (UAT M00-B01)", async () => {
    const { getByPlaceholderText } = render(
      <CommandPaletteV2 open onOpenChange={() => {}} />,
    );

    fireEvent.change(getByPlaceholderText(/Szukaj kandydatów/), {
      target: { value: "jan.kowalski@example.com" },
    });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });

    const candidateCall = apiGet.mock.calls.find(
      ([url]) => url === "/api/candidates",
    );
    expect(candidateCall).toBeDefined();
    expect(candidateCall?.[1]?.params).toMatchObject({
      q: "jan.kowalski@example.com",
      page_size: 5,
      sort: "relevance",
    });
  });
});

describe("CommandPaletteV2 — podpis kandydata", () => {
  it("pokazuje stanowisko z LinkedIna i miasto, żeby odróżnić imienników", async () => {
    apiGet.mockImplementation((url: string) =>
      Promise.resolve({
        data:
          url === "/api/candidates"
            ? {
                items: [
                  { id: 7, name: "Jan", lastname: "Kowalski", linkedin_current_title: "Java Developer", city: "Kraków" },
                  {
                    id: 8,
                    name: "Jan",
                    lastname: "Kowalski",
                    linkedin_current_title: null,
                    city: "Gdańsk",
                    employment_marker: {
                      phase: "working",
                      source: "contract",
                      clients: [{ client_id: 3, client_name: "Bank Przykładowy", contract_id: 30, phase: "working" }],
                    },
                  },
                ],
                total: 2,
              }
            : { items: [], total: 0 },
      }),
    );
    const { getByPlaceholderText, getByText } = render(
      <CommandPaletteV2 open onOpenChange={() => {}} />,
    );
    fireEvent.change(getByPlaceholderText(/Szukaj kandydatów/), {
      target: { value: "Jan Kowalski" },
    });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(getByText("· Java Developer · Kraków")).toBeTruthy();
    // Podpis zostaje bez zmian; znacznik zatrudnienia to osobny element obok.
    expect(getByText("· Gdańsk")).toBeTruthy();
    expect(getByText("Aktywne zamówienie · nie dzwoń")).toBeTruthy();
  });
});

describe("CommandPaletteV2 — nawigacja po wpisaniu zapytania (UAT M00-B03)", () => {
  it.each([
    ["kand", "Kandydaci"],
    ["rekr", "Rekrutacje"],
    ["klien", "Klienci"],
    ["ustaw", "Ustawienia"],
    ["talent radar", "Szukaj z treści requestu (Talent Radar)"],
    ["radar", "Szukaj z treści requestu (Talent Radar)"],
    ["wyszukiwarka", "Wyszukiwarka kandydatów"],
  ])("'%s' podpowiada pozycję %s", async (term, label) => {
    const { getByPlaceholderText, getByText } = render(
      <CommandPaletteV2 open onOpenChange={() => {}} />,
    );
    fireEvent.change(getByPlaceholderText(/Szukaj kandydatów/), {
      target: { value: term },
    });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(getByText(label)).toBeTruthy();
  });

  it("grupa Nawigacja pochodzi z rejestru sidebara, nie z własnej listy", () => {
    const { getByText, queryByText } = render(
      <CommandPaletteV2 open onOpenChange={() => {}} />,
    );
    // Pozycje, których stara, ręczna lista palety nie miała.
    for (const label of [
      "Wyszukiwarka kandydatów",
      "Szukaj z treści requestu (Talent Radar)",
      "Generator Umów B2B",
      "Pomoc",
    ]) {
      expect(getByText(label)).toBeTruthy();
    }
    // „Panel managera" zdjęty 22.09.2026 — `/manager` przekierowuje na pulpit.
    expect(queryByText("Panel managera")).toBeNull();
    // Flaga kolejki telefonów wyłączona (i admin nie jest w jej rolach).
    expect(queryByText("Do przedzwonienia")).toBeNull();
    // Talenty i Targ zdjęte z nawigacji 21.09.2026.
    expect(queryByText("Targ / Dostępni")).toBeNull();
    expect(queryByText("Talenty")).toBeNull();
    // Generator CV zdjęty 13.10.2026 — CV powstaje w ścieżce rekrutacji.
    expect(queryByText("Generator CV")).toBeNull();
  });

  it("dopasowanie ignoruje polskie znaki i wielkość liter", async () => {
    const { navMatches } = await import(
      "@/components/v2/shell/CommandPaletteV2"
    );
    expect(navMatches("Kalendarz", "KALE")).toBe(true);
    expect(navMatches("Ustawienia", "ustąw")).toBe(true);
    expect(navMatches("Klienci", "kontr")).toBe(false);
  });
});
