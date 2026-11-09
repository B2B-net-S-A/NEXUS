/** Spotkania: transkrypt, decyzja przy wierszu, filtry w adresie, okno „Załóż szansę”. */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Meeting, MeetingDraft } from "@/lib/api/sales";

const baseMeeting = {
  id: 1,
  kind: "meeting",
  subject: "Warsztat z klientem",
  body: "Notatka z Outlooka",
  occurred_at: "2026-10-22T10:00:00Z",
  created_at: "2026-10-22T10:00:00Z",
  company: { id: 7, name: "Firma Testowa SPÓŁKA AKCYJNA" },
  opportunity: null,
  external_source: "msgraph-event",
  transcript_status: null,
  transcript_summary: null,
  decision: "create",
  timing: "past",
  can_unpin: false,
  open_opportunities: [],
  client_name: null,
  delivery_lead: null,
} as unknown as Meeting;

const OPTION_A = { id: 11, title: "Migracja", stage_name: "Oferta wysłana", value: "60000", currency: "PLN" };
const OPTION_B = { id: 12, title: "Audyt", stage_name: "Lead", value: null, currency: "PLN" };

let items: Meeting[] = [];
let isSuccess = true;
let error: Error | null = null;
let canEdit = true;
let lastFilters: Record<string, unknown> = {};
let search = "";
let draft: MeetingDraft;
const pin = vi.fn();
const unpin = vi.fn();
const createFrom = vi.fn();
const createContact = vi.fn();
const replaceUrl = vi.fn();
const toast = {
  showSuccess: vi.fn(),
  showError: vi.fn(),
  showInfo: vi.fn(),
  showToast: vi.fn(),
  showActionToast: vi.fn(),
};

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/sales/meetings",
}));
vi.mock("@/lib/url-selection", () => ({ useUrlWriter: () => ({ replaceUrl }) }));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: () => canEdit,
}));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("../SalesSelect", () => ({
  SalesSelect: ({
    id,
    value,
    onValueChange,
    options,
  }: {
    id?: string;
    value: string;
    onValueChange: (next: string) => void;
    options: readonly { value: string; label: string }[];
  }) => (
    <select id={id} value={value} onChange={(event) => onValueChange(event.target.value)}>
      <option value="" />
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));
vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useSalesMeetings: (filters: Record<string, unknown>) => {
    lastFilters = filters;
    return {
      data: isSuccess ? { items, total: items.length, counts: { pin: 3, create: 2, upcoming: 1 } } : undefined,
      isLoading: false,
      error,
      isSuccess,
      refetch: vi.fn(),
    };
  },
  useMeetingTranscript: () => ({
    data: { subject: "Warsztat z klientem", summary: "Ustalono demo.", plain_text: "Handlowiec: Dzień dobry" },
    isLoading: false,
    error: null,
    isSuccess: true,
    refetch: vi.fn(),
  }),
  useMeetingDraft: () => ({ data: draft, isLoading: false, error: null, isSuccess: true, refetch: vi.fn() }),
  usePinActivity: () => ({ mutate: pin, isPending: false }),
  useUnpinActivity: () => ({ mutate: unpin, isPending: false }),
  useCreateOpportunityFromMeeting: () => ({ mutate: createFrom, isPending: false }),
  useCreateSalesContact: () => ({ mutate: createContact, isPending: false }),
}));

import { MeetingsView } from "../MeetingsView";
import { meetingWhen, shortCompanyName } from "../meeting-helpers";

function row(meeting: Partial<Meeting>): Meeting {
  return { ...baseMeeting, ...meeting } as Meeting;
}

beforeEach(() => {
  items = [];
  isSuccess = true;
  error = null;
  canEdit = true;
  search = "";
  lastFilters = {};
  vi.clearAllMocks();
  draft = {
    company: { id: 7, name: "Firma Testowa" },
    occurred_at: "2026-10-22T10:00:00Z",
    duration_minutes: 30,
    suggested_title: "Firma Testowa",
    attendees_known: true,
    people: [
      { id: 1, name: "Osoba Pierwsza", title: "CTO", attended: true },
      { id: 2, name: "Osoba Druga", title: null, attended: false },
    ],
  };
});

describe("Spotkania: to, co było", () => {
  it("bez transkryptu pokazuje notatkę i nie obiecuje transkryptu", () => {
    items = [row({ transcript_status: "missing" })];
    render(<MeetingsView />);
    expect(screen.getByTitle("Warsztat z klientem Notatka z Outlooka")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Czytaj transkrypt" })).toBeNull();
  });

  it("po pobraniu pokazuje podsumowanie i otwiera pełny tekst", () => {
    items = [row({ transcript_status: "fetched", transcript_summary: "Krótko: demo." })];
    render(<MeetingsView />);
    expect(screen.getByText("Krótko: demo.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Czytaj transkrypt" }));
    expect(screen.getByText("Handlowiec: Dzień dobry")).toBeInTheDocument();
    expect(screen.getByText("Ustalono demo.")).toBeInTheDocument();
  });

  it("zostają kolumna źródła, szukanie i zakres dat z przypisaniem pod Filtrami", () => {
    items = [row({})];
    search = "q=abc&od=2026-10-01&do=2026-10-31&przypisanie=company";
    render(<MeetingsView />);
    expect(screen.getByRole("columnheader", { name: "Źródło" })).toBeInTheDocument();
    expect(screen.getByText("Outlook")).toBeInTheDocument();
    expect(screen.getByLabelText("Szukaj spotkania")).toHaveValue("abc");
    expect(lastFilters).toMatchObject({
      q: "abc",
      date_from: "2026-10-01",
      date_to: "2026-10-31",
      linked: "company",
    });
    expect(screen.getByRole("button", { name: "Filtry (3)" })).toBeInTheDocument();
  });
});

describe("Spotkania: filtry", () => {
  it("domyślnie moje, a przycisk zapisuje wyłączenie w adresie", () => {
    render(<MeetingsView />);
    expect(lastFilters.mine).toBe(true);
    const mine = screen.getByRole("button", { name: "Moje" });
    expect(mine).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(mine);
    expect(replaceUrl.mock.calls.at(-1)?.[0]).toContain("moje=0");
  });

  it("czyta kolejkę i przyszłe z adresu, liczniki przychodzą z API", () => {
    search = "kolejka=przypiecie&przyszle=1&moje=0";
    items = [row({})];
    render(<MeetingsView />);
    expect(lastFilters).toMatchObject({ mine: false, queue: "pin", upcoming: true });
    expect(screen.getByRole("button", { name: "Do przypięcia 3" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Bez szansy 2" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Przyszłe 1" })).toHaveAttribute("aria-pressed", "true");
  });

  it("pusty stan wisi na isSuccess i awaria nie wygląda jak pustka", () => {
    isSuccess = false;
    error = new Error("500");
    render(<MeetingsView />);
    expect(screen.queryByText("Nic nie pasuje do filtrów")).toBeNull();
  });

  it("puste „Moje” proponuje spotkania wszystkich", () => {
    render(<MeetingsView />);
    expect(screen.getByText("Nic nie pasuje do filtrów")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż spotkania wszystkich" }));
    expect(replaceUrl.mock.calls.at(-1)?.[0]).toContain("moje=0");
  });
});

describe("Spotkania: co dalej", () => {
  it("jedna szansa: przycisk przypina do niej i daje cofnięcie przy kolejce", () => {
    search = "kolejka=przypiecie";
    items = [row({ decision: "pin", open_opportunities: [OPTION_A] })];
    pin.mockImplementation((_input, options) => options.onSuccess());
    render(<MeetingsView />);
    fireEvent.click(screen.getByRole("button", { name: "Przypnij: Migracja" }));
    expect(pin.mock.calls[0][0]).toEqual({ activityId: 1, opportunityId: 11 });
    expect(toast.showActionToast).toHaveBeenCalledWith(
      "Przypięte: Migracja",
      expect.objectContaining({ actionLabel: "Cofnij" }),
    );
  });

  it("kilka szans: lista z etapem i kwotą", async () => {
    items = [row({ decision: "choose", open_opportunities: [OPTION_A, OPTION_B] })];
    render(<MeetingsView />);
    fireEvent.pointerDown(screen.getByRole("button", { name: "Przypnij (2)" }), { button: 0, ctrlKey: false });
    const menu = await screen.findByRole("menu");
    expect(within(menu).getByText("Oferta wysłana · 60 000 zł")).toBeInTheDocument();
    expect(within(menu).getByText("Lead")).toBeInTheDocument();
    fireEvent.click(within(menu).getByText("Audyt"));
    expect(pin.mock.calls[0][0]).toEqual({ activityId: 1, opportunityId: 12 });
  });

  it("błąd przypięcia idzie komunikatem z API", () => {
    items = [row({ decision: "pin", open_opportunities: [OPTION_A] })];
    pin.mockImplementation((_input, options) =>
      options.onError({ response: { status: 409, data: { detail: "Ta szansa jest już zamknięta." } } }),
    );
    render(<MeetingsView />);
    fireEvent.click(screen.getByRole("button", { name: "Przypnij: Migracja" }));
    expect(toast.showError).toHaveBeenCalledWith("Ta szansa jest już zamknięta.");
  });

  it("przypięte: link do szansy i cofnięcie", () => {
    items = [
      row({ decision: "linked", can_unpin: true, opportunity: { id: 11, name: "Migracja" } as Meeting["opportunity"] }),
    ];
    render(<MeetingsView />);
    expect(screen.getByRole("link", { name: "Migracja" })).toHaveAttribute("href", "/sales/opportunities/11");
    fireEvent.click(screen.getByRole("button", { name: "Cofnij" }));
    expect(unpin.mock.calls[0][0]).toBe(1);
  });

  it("spotkanie spoza Outlooka przy szansie nie ma cofnięcia", () => {
    items = [
      row({
        decision: "linked",
        external_source: "fireflies",
        opportunity: { id: 11, name: "Migracja" } as Meeting["opportunity"],
      }),
    ];
    render(<MeetingsView />);
    expect(screen.queryByRole("button", { name: "Cofnij" })).toBeNull();
  });

  it("klient NEXUSA: wskazanie Delivery Leada bez przycisku szansy", () => {
    items = [row({ decision: "client", client_name: "Klient", delivery_lead: "Osoba Prowadząca" })];
    render(<MeetingsView />);
    expect(screen.getByText("Klient NEXUSA, przekaż do: Osoba Prowadząca")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Załóż szansę" })).toBeNull();
  });

  it("klient bez Delivery Leada idzie do Heada", () => {
    items = [row({ decision: "client", client_name: "Klient", delivery_lead: null })];
    render(<MeetingsView />);
    expect(screen.getByText("Klient bez Delivery Leada: zgłoś do Heada")).toBeInTheDocument();
  });

  it("spotkanie w naszej firmie: bez polecenia i bez przycisku szansy", () => {
    items = [row({ decision: "internal" })];
    render(<MeetingsView />);
    expect(screen.getByText("Spotkanie wewnętrzne")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Załóż szansę" })).toBeNull();
    expect(screen.queryByText(/zgłoś do Heada/)).toBeNull();
    expect(screen.queryByRole("link", { name: "Tylko przy firmie" })).toBeNull();
  });

  it("„Tylko przy firmie” prowadzi do karty firmy", () => {
    items = [row({ decision: "company_only", external_source: "pipedrive_activity" })];
    render(<MeetingsView />);
    expect(screen.getByRole("link", { name: "Tylko przy firmie" })).toHaveAttribute("href", "/sales/companies/7");
  });

  it("bez edycji widać stan, ale nie ma akcji", () => {
    canEdit = false;
    items = [
      row({ id: 1, decision: "create" }),
      row({ id: 2, decision: "pin", open_opportunities: [OPTION_A] }),
      row({ id: 3, decision: "linked", can_unpin: true, opportunity: { id: 11, name: "Migracja" } as Meeting["opportunity"] }),
    ];
    render(<MeetingsView />);
    expect(within(screen.getByRole("table")).getByText("Bez szansy")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Załóż szansę" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Przypnij/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cofnij" })).toBeNull();
  });
});

describe("Spotkania: okno „Załóż szansę”", () => {
  function openDialog() {
    items = [row({ decision: "create" })];
    render(<MeetingsView />);
    fireEvent.click(screen.getByRole("button", { name: "Załóż szansę" }));
    return screen.getByRole("dialog");
  }

  it("podpowiada tytuł, usługa bez domyślnej wartości blokuje zapis", () => {
    const dialog = openDialog();
    expect(within(dialog).getByLabelText("Nazwa szansy")).toHaveValue("Firma Testowa");
    expect(within(dialog).getByText("Firma Testowa", { selector: "p" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Załóż szansę" })).toBeDisabled();
    expect(within(dialog).getByLabelText("Osoba Pierwsza · CTO")).toBeChecked();
    expect(within(dialog).queryByLabelText("Osoba Druga")).toBeNull();
  });

  it("zakłada szansę z zaznaczonymi uczestnikami", () => {
    const dialog = openDialog();
    fireEvent.change(within(dialog).getByLabelText(/Usługa/), { target: { value: "bodyleasing" } });
    createFrom.mockImplementation((_input, options) => options.onSuccess({ id: 50, title: "Firma Testowa" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Załóż szansę" }));
    expect(createFrom.mock.calls[0][0]).toEqual({
      activityId: 1,
      title: "Firma Testowa",
      service_line: "bodyleasing",
      contact_ids: [1],
    });
    expect(toast.showSuccess).toHaveBeenCalledWith("Założono szansę: Firma Testowa");
  });

  it("bez wiedzy o uczestnikach pokazuje osoby z firmy, odznaczone", () => {
    draft = {
      ...draft,
      attendees_known: false,
      people: draft.people.map((person) => ({ ...person, attended: false })),
    };
    const dialog = openDialog();
    expect(within(dialog).getByText("Nie wiemy, kto był na spotkaniu. Zaznacz osoby z firmy.")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Osoba Druga")).not.toBeChecked();
  });

  it("firma bez kontaktów: dodany kontakt od razu jest zaznaczony", async () => {
    draft = { ...draft, attendees_known: false, people: [] };
    const dialog = openDialog();
    expect(within(dialog).getByText("Firma nie ma kontaktów.")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Dodaj kontakt" }));
    fireEvent.change(within(dialog).getByLabelText("Imię i nazwisko nowego kontaktu"), {
      target: { value: "Nowa Osoba" },
    });
    createContact.mockImplementation((_input, options) =>
      options.onSuccess({ id: 9, full_name: "Nowa Osoba", title: null }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Dodaj" }));
    expect(createContact.mock.calls[0][0]).toEqual({ company_id: 7, full_name: "Nowa Osoba" });
    await waitFor(() => expect(within(dialog).getByLabelText("Nowa Osoba")).toBeChecked());
  });

  it("409 z bramki klienta idzie komunikatem i okno zostaje", () => {
    const dialog = openDialog();
    fireEvent.change(within(dialog).getByLabelText(/Usługa/), { target: { value: "bodyleasing" } });
    createFrom.mockImplementation((_input, options) =>
      options.onError({ response: { status: 409, data: { detail: "Przekaż do: Osoba Prowadząca." } } }),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Załóż szansę" }));
    expect(toast.showError).toHaveBeenCalledWith("Przekaż do: Osoba Prowadząca.");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("Spotkania: daty i nazwy", () => {
  const NOW = new Date("2026-11-09T07:00:00Z");

  it("dziś i jutro w kalendarzu firmy, także tuż po północy", () => {
    expect(meetingWhen("2026-11-09T08:30:00Z", NOW)).toBe("Dziś 09:30");
    expect(meetingWhen("2026-11-10T09:00:00Z", NOW)).toBe("Jutro 10:00");
    expect(meetingWhen("2026-11-09T23:30:00Z", NOW)).toBe("Jutro 00:30");
  });

  it("inne dni bez roku, inny rok z rokiem", () => {
    expect(meetingWhen("2026-11-13T09:00:00Z", NOW)).toBe("13.11 10:00");
    expect(meetingWhen("2027-08-12T08:00:00Z", NOW)).toBe("12.08.2027 10:00");
    expect(meetingWhen(null, NOW)).toBe("—");
  });

  it("skraca formę prawną", () => {
    expect(shortCompanyName("Firma Testowa SPÓŁKA Z OGRANICZONĄ ODPOWIEDZIALNOŚCIĄ")).toBe("Firma Testowa sp. z o.o.");
    expect(shortCompanyName("Firma SPÓŁKA AKCYJNA")).toBe("Firma S.A.");
  });
});
