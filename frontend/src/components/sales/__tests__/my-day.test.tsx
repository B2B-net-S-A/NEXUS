/**
 * „Mój dzień”: kolejka z API, prawdziwe przyciski w wierszach, rama i przekierowanie.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MyDay, MyDayRow } from "@/lib/api/sales";
import type { Handoff, Handoffs } from "@/lib/api/sales-handoffs";

const myDay = vi.fn();
const handoffs = vi.fn();
const logCall = vi.fn();
const logCompanyCall = vi.fn();
const createActivity = vi.fn();
const updateActivity = vi.fn();
const completeActivity = vi.fn();
const createContact = vi.fn();
const updateContact = vi.fn();
const askConfirm = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();
const companyPeople = vi.fn();
const bookProps = vi.fn();
const reminders = vi.fn();
let canEdit = true;

const mutation = (mutate: ReturnType<typeof vi.fn>) => ({ mutate, isPending: false });

vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useMyDay: () => myDay(),
  useLogCall: () => mutation(logCall),
  useLogCompanyCall: () => mutation(logCompanyCall),
  useCreateActivity: () => mutation(createActivity),
  useUpdateActivity: () => mutation(updateActivity),
  useCompleteActivity: () => mutation(completeActivity),
  useCreateSalesContact: () => mutation(createContact),
  useUpdateSalesContact: () => mutation(updateContact),
  useCompanyPeople: () => companyPeople(),
  useCompanyBriefing: () => ({ isSuccess: false }),
}));
vi.mock("@/lib/api/sales-calling", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-calling")>()),
  useCallReminders: (scope: string, callerId: number | null, until: string | null) => reminders(scope, callerId, until),
}));
vi.mock("@/lib/api/sales-handoffs", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-handoffs")>()),
  useHandoffs: () => handoffs(),
  useConfirmHandoff: () => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false }),
  useGiveVerdict: () => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false }),
  useSetHandoffTerm: () => ({ mutateAsync: vi.fn().mockResolvedValue({}), isPending: false }),
  useHostBusy: () => ({ isPending: true, isSuccess: false }),
}));
vi.mock("../handoff/BookMeetingForm", () => ({
  BookMeetingDialog: (props: object) => {
    bookProps(props);
    return <p>okno „Umów spotkanie”</p>;
  },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess }) }));
vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm, confirmDialog: null }),
}));
vi.mock("@/lib/permissions", async (original) => ({
  ...(await original<typeof import("@/lib/permissions")>()),
  hasPermission: () => canEdit,
}));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: object }) => unknown) => selector({ user: {} }),
}));

import { activeSection } from "../SalesShell";
import {
  dayHeading,
  dayLine,
  isDayEmpty,
  plural,
  replyHref,
  rowReason,
  salesLandingPath,
  telHref,
} from "../my-day";
import { MyDayRowItem } from "../MyDayRowItem";
import { MyDayView } from "../MyDayView";

function row(overrides: Partial<MyDayRow> = {}): MyDayRow {
  return {
    key: "offer-1",
    section: "offers",
    company: { id: 7, name: "Firma Testowa" },
    opportunity: { id: 21, title: "Zespół analityków" },
    activity_id: null,
    kind: null,
    subject: "Zespół analityków",
    at: "2026-10-01T10:00:00Z",
    days: 39,
    amount: "45000.00",
    currency: "PLN",
    open_opportunities: 1,
    duration_minutes: null,
    web_link: null,
    do_not_contact: false,
    person: { id: 3, name: "Jan Testowy", title: "CTO", phone: "+48 600 100 200", email: "jan@example.com" },
    people_without_phone: [],
    ...overrides,
  };
}

function day(overrides: Partial<MyDay> = {}): MyDay {
  return {
    today: "2026-11-09",
    counts: { meetings: 0, reply: 0, overdue: 0, offers: 0, older_tasks: 0 },
    meetings: [],
    reply: [],
    overdue: [],
    offers: [],
    prep: null,
    ...overrides,
  };
}

const ok = (data: MyDay) => ({ data, isLoading: false, error: null, isSuccess: true, refetch: vi.fn() });

const noHandoffs: Handoffs = { to_me: [], booked_by_me: [], weeks: [] };
const handoffsOk = (data: Handoffs) => ({ data, isError: false, isSuccess: true, refetch: vi.fn() });

function handoff(overrides: Partial<Handoff> = {}): Handoff {
  return {
    opportunity: { id: 21, name: "Automatyzacje: spotkanie kwalifikujące" },
    company: { id: 7, name: "Firma Testowa" },
    status: "open",
    stage_key: "qualifying-meeting",
    stage_name: "Spotkanie kwalifikujące",
    host: { id: 2, name: "Prowadzący Testowy" },
    booked_by: { id: 3, name: "Dzwoniący Testowy" },
    booked_at: "2026-11-06T10:00:00Z",
    meeting_at: "2026-11-12T12:00:00Z",
    duration_minutes: 30,
    from_calendar: false,
    service: "Automatyzacje",
    problem: "Raporty składane ręcznie",
    decision_maker: null,
    timing: null,
    contact: { id: 5, name: "Anna Przykładowa", title: "Kierownik IT", phone: null, email: null, do_not_contact: false },
    confirmed_at: null,
    verdict: null,
    verdict_at: null,
    verdict_reason: null,
    return_on: null,
    phase: "upcoming",
    clash: false,
    ...overrides,
  };
}

beforeEach(() => {
  reminders.mockReturnValue({ data: [], isSuccess: true, isError: false, refetch: vi.fn() });
  vi.clearAllMocks();
  canEdit = true;
  handoffs.mockReturnValue(handoffsOk(noHandoffs));
  companyPeople.mockReturnValue({ isLoading: true, error: null, isSuccess: false });
});

describe("podpisy i przekierowanie", () => {
  it("odmienia liczebniki", () => {
    expect(plural(1, "spotkanie", "spotkania", "spotkań")).toBe("1 spotkanie");
    expect(plural(3, "spotkanie", "spotkania", "spotkań")).toBe("3 spotkania");
    expect(plural(12, "spotkanie", "spotkania", "spotkań")).toBe("12 spotkań");
    expect(plural(22, "spotkanie", "spotkania", "spotkań")).toBe("22 spotkania");
  });

  it("linia dnia ma cztery sekcje i dzień tygodnia z kalendarza firmy", () => {
    expect(dayHeading("2026-11-09")).toBe("Poniedziałek 9.11");
    expect(dayLine(day({ counts: { meetings: 1, reply: 2, overdue: 4, offers: 16, older_tasks: 16 } }))).toBe(
      "1 spotkanie · 2 do odpisania · 4 zaległe · 16 ofert bez ruchu",
    );
  });

  it("numer do linku bez numeru wewnętrznego", () => {
    expect(telHref("32 210 46 65 wew. 384")).toBe("tel:322104665");
  });

  it("/sales prowadzi na Mój dzień, a stare odnośniki z parametrami do Szans", () => {
    expect(salesLandingPath({})).toBe("/sales/my-day");
    expect(salesLandingPath({ bezruchu: "1" })).toBe("/sales/opportunities?bezruchu=1");
    expect(salesLandingPath({ opiekun: "153", mine: ["1"] })).toBe("/sales/opportunities?opiekun=153&mine=1");
    expect(activeSection("/sales/my-day")).toBe("my-day");
    expect(activeSection("/sales/opportunities")).toBe("opportunities");
  });

  it("powód wiersza mówi, co się stało", () => {
    expect(rowReason(row({ section: "reply", days: 14 }))).toBe("Napisali 14 dni temu · Zespół analityków");
    expect(rowReason(row({ section: "offers", days: 39 }))).toBe("Bez ruchu 39 dni · Zespół analityków");
    expect(rowReason(row({ section: "overdue", kind: "call", subject: "Ustalić termin" }))).toBe(
      "Telefon: Ustalić termin",
    );
    expect(rowReason(row({ section: "meetings", duration_minutes: 30, open_opportunities: 0 }))).toBe(
      "30 min · brak otwartej szansy",
    );
  });

  it("Odpisz bierze link z maila, potem adres osoby, a bez nich nic", () => {
    expect(replyHref(row(), "https://outlook.example/1")).toBe("https://outlook.example/1");
    expect(replyHref(row({ subject: "RE: oferta" }), undefined)).toBe("mailto:jan@example.com?subject=RE%3A%20oferta");
    expect(replyHref(row({ person: null }), undefined)).toBeUndefined();
  });
});

describe("kolejka dnia", () => {
  it("przypomnienia z Dzwonienia na dziś stoją nad kolejką (13.11.2026)", () => {
    myDay.mockReturnValue(ok(day()));
    reminders.mockReturnValue({
      isSuccess: true,
      refetch: vi.fn(),
      data: [
        {
          key: "r:7",
          section: "callbacks",
          record_id: 7,
          opportunity_id: null,
          opportunity_title: null,
          company: { id: 15, name: "Oddzwoń S.A." },
          campaign: null,
          person_name: "Jan Testowy",
          person_title: null,
          phone: null,
          state: "call_back",
          due_on: day().today,
          attempts: 1,
          last_outcome_at: null,
          since: "2026-11-06T10:00:00Z",
        },
      ],
      isError: false,
    });
    render(<MyDayView />);
    expect(reminders).toHaveBeenLastCalledWith("mine", null, day().today);
    const section = screen.getByRole("region", { name: "Przypomnienia na dziś" });
    expect(section.textContent).toContain("Oddzwoń S.A.");
    expect(screen.getByRole("link", { name: "Wszystkie przypomnienia (1)" }).getAttribute("href")).toBe(
      "/sales/calling?view=reminders",
    );
  });

  it("pusty stan dopiero po sukcesie", () => {
    myDay.mockReturnValue(ok(day()));
    render(<MyDayView />);
    expect(screen.getByText("Czysto. Nic pilnego.")).toBeTruthy();
    expect(isDayEmpty(day())).toBe(true);
  });

  it("awaria nie wygląda jak pusta lista", () => {
    myDay.mockReturnValue({ data: undefined, isLoading: false, error: new Error("boom"), isSuccess: false, refetch: vi.fn() });
    render(<MyDayView />);
    expect(screen.queryByText("Czysto. Nic pilnego.")).toBeNull();
    expect(screen.getByRole("button", { name: /Spróbuj|Odśwież/ })).toBeTruthy();
  });

  it("pokazuje 10 ofert i odsłania resztę", () => {
    const offers = Array.from({ length: 13 }, (_, i) => row({ key: `offer-${i}`, company: { id: i + 1, name: `Firma ${i}` } }));
    myDay.mockReturnValue(ok(day({ offers, counts: { meetings: 0, reply: 0, overdue: 0, offers: 13, older_tasks: 3 } })));
    render(<MyDayView />);
    expect(screen.queryByText("Firma 12")).toBeNull();
    expect(screen.getByText("3 starsze zadania")).toBeTruthy();
    fireEvent.click(screen.getByText("Pokaż pozostałe 3"));
    expect(screen.getByText("Firma 12")).toBeTruthy();
  });

  it("nie ma paska postępu ani przełącznika osoby", () => {
    myDay.mockReturnValue(ok(day({ offers: [row()], counts: { meetings: 0, reply: 0, overdue: 0, offers: 1, older_tasks: 0 } })));
    render(<MyDayView />);
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("przekazane spotkania stoją nad kolejką i nie dublują wiersza z kalendarza", () => {
    const sameOpportunity = row({ key: "meeting-1", section: "meetings", activity_id: 1 });
    const other = row({
      key: "meeting-2",
      section: "meetings",
      activity_id: 2,
      company: { id: 8, name: "Inna Firma" },
      opportunity: null,
    });
    myDay.mockReturnValue(
      ok(day({ meetings: [sameOpportunity, other], counts: { meetings: 2, reply: 0, overdue: 0, offers: 0, older_tasks: 0 } })),
    );
    handoffs.mockReturnValue(handoffsOk({ to_me: [handoff({ phase: "verdict" })], booked_by_me: [], weeks: [] }));
    render(<MyDayView />);
    expect(screen.getByText("Przekazane do Ciebie")).toBeTruthy();
    expect(screen.getByText(/1 przekazane spotkanie · 1 spotkanie ·/)).toBeTruthy();
    // Wiersz listy i karta po prawej; spotkania tej samej szansy nie ma drugi raz w „Spotkania dziś”.
    expect(screen.getAllByText("Firma Testowa")).toHaveLength(2);
    expect(screen.getByText("Inna Firma")).toBeTruthy();
    // Po terminie karta od razu pyta o werdykt.
    expect(screen.getByText("Jak poszło?")).toBeTruthy();
    expect(screen.getByText("Raporty składane ręcznie")).toBeTruthy();
  });

  it("same przekazania to nie jest pusty dzień", () => {
    myDay.mockReturnValue(ok(day()));
    handoffs.mockReturnValue(handoffsOk({ to_me: [handoff()], booked_by_me: [], weeks: [] }));
    render(<MyDayView />);
    expect(screen.queryByText("Czysto. Nic pilnego.")).toBeNull();
    expect(screen.getByText("Przekazane do Ciebie")).toBeTruthy();
  });

  it("awaria przekazań nie wygląda jak ich brak", () => {
    myDay.mockReturnValue(ok(day({ offers: [row()] })));
    handoffs.mockReturnValue({ data: undefined, isError: true, isSuccess: false, refetch: vi.fn() });
    render(<MyDayView />);
    expect(screen.getByText("Nie udało się wczytać przekazanych spotkań.")).toBeTruthy();
  });

  it("„Umów spotkanie” jest tylko dla osób z edycją", () => {
    myDay.mockReturnValue(ok(day()));
    const { unmount } = render(<MyDayView />);
    expect(screen.getByRole("button", { name: "Umów spotkanie" })).toBeTruthy();
    unmount();
    canEdit = false;
    render(<MyDayView />);
    expect(screen.queryByRole("button", { name: "Umów spotkanie" })).toBeNull();
  });
});

describe("przyciski wiersza", () => {
  it("spotkanie przypięte przez automat mówi o tym w wierszu", () => {
    expect(rowReason(row({ section: "meetings", duration_minutes: 60, auto_pinned: true }))).toBe(
      "60 min · przypięte samo, jedyna otwarta szansa",
    );
  });

  it("po spotkaniu bez szansy wiersz proponuje „Załóż szansę”", () => {
    const meeting = row({
      section: "meetings",
      activity_id: 9,
      opportunity: null,
      open_opportunities: 0,
      can_create_opportunity: true,
    });
    render(<MyDayRowItem row={meeting} canEdit />);
    expect(screen.queryByRole("button", { name: "Załóż szansę" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Po spotkaniu" }));
    expect(screen.getByRole("button", { name: "Załóż szansę" })).toBeTruthy();
    expect(screen.getByText("Co dalej i kiedy")).toBeTruthy();
  });

  it("po spotkaniu krok dostaje własną datę zamiast przycisku terminu", async () => {
    createActivity.mockImplementation((_input, { onSuccess }) => onSuccess());
    render(<MyDayRowItem row={row({ section: "meetings", activity_id: 9 })} canEdit />);
    fireEvent.click(screen.getByRole("button", { name: "Po spotkaniu" }));
    const custom = new Date();
    custom.setDate(custom.getDate() + 10);
    const pad = (value: number) => String(value).padStart(2, "0");
    const isoDay = `${custom.getFullYear()}-${pad(custom.getMonth() + 1)}-${pad(custom.getDate())}`;
    fireEvent.change(screen.getByLabelText("Własna data"), { target: { value: isoDay } });
    expect(screen.getByRole("radio", { name: "Za 3 dni" }).getAttribute("aria-checked")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(createActivity).toHaveBeenCalled());
    expect(new Date(createActivity.mock.calls[0][0].due_at).toDateString()).toBe(custom.toDateString());
  });

  it("data z przeszłości nie da się zapisać", () => {
    render(<MyDayRowItem row={row({ section: "meetings", activity_id: 9 })} canEdit />);
    fireEvent.click(screen.getByRole("button", { name: "Po spotkaniu" }));
    fireEvent.change(screen.getByLabelText("Własna data"), { target: { value: "2020-01-02" } });
    expect((screen.getByRole("button", { name: "Zapisz" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: "Za tydzień" }));
    expect((screen.getByRole("button", { name: "Zapisz" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("spotkanie przy szansie nie proponuje drugiej", () => {
    render(<MyDayRowItem row={row({ section: "meetings", activity_id: 9 })} canEdit />);
    fireEvent.click(screen.getByRole("button", { name: "Po spotkaniu" }));
    expect(screen.queryByRole("button", { name: "Załóż szansę" })).toBeNull();
  });

  it("klik w wynik zapisuje rozmowę i krok z podpowiedzi, bez drugiego „Zapisz”", async () => {
    logCall.mockImplementation((_input, { onSuccess }) => onSuccess());
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    expect(screen.queryByRole("button", { name: "Zapisz" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Dodzwoniłem" }));
    await waitFor(() => expect(createActivity).toHaveBeenCalled());
    expect(logCall.mock.calls[0][0]).toEqual({ opportunity_id: 21, outcome: "connected", contact_id: 3 });
    expect(createActivity.mock.calls[0][0]).toMatchObject({
      kind: "task",
      subject: "Wysłać podsumowanie rozmowy",
      opportunity_id: 21,
      company_id: null,
    });
  });

  it("termin kroku idzie z wyniku: „Nie odebrał” to jutro, nie trzy dni", async () => {
    logCall.mockImplementation((_input, { onSuccess }) => onSuccess());
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    fireEvent.click(screen.getByRole("button", { name: "Nie odebrał" }));
    await waitFor(() => expect(createActivity).toHaveBeenCalled());
    const due = new Date(createActivity.mock.calls[0][0].due_at);
    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    expect(due.toDateString()).toBe(tomorrow.toDateString());
    expect(createActivity.mock.calls[0][0].subject).toBe("Zadzwonić ponownie");
  });

  it("notatka z rozmowy idzie razem z wynikiem", async () => {
    logCall.mockImplementation((_input, { onSuccess }) => onSuccess());
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    fireEvent.change(screen.getByLabelText("Notatka z rozmowy"), { target: { value: "Decyzja w piątek" } });
    fireEvent.click(screen.getByRole("button", { name: "Oddzwonić" }));
    await waitFor(() => expect(logCall).toHaveBeenCalled());
    expect(logCall.mock.calls[0][0].note).toBe("Decyzja w piątek");
  });

  it("klawisz 2 zapisuje „Nie odebrał”, a cyfra wpisana w notatkę nic nie zapisuje", async () => {
    logCall.mockImplementation((_input, { onSuccess }) => onSuccess());
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    fireEvent.keyDown(screen.getByLabelText("Notatka z rozmowy"), { key: "2" });
    expect(logCall).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("group", { name: "Wynik rozmowy" }), { key: "2" });
    await waitFor(() => expect(logCall).toHaveBeenCalled());
    expect(logCall.mock.calls[0][0].outcome).toBe("no_answer");
  });

  it("„Inny krok” zostawia wybór kroku i dopiero „Zapisz” zapisuje", async () => {
    logCall.mockImplementation((_input, { onSuccess }) => onSuccess());
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    fireEvent.click(screen.getByRole("button", { name: "Inny krok" }));
    const save = screen.getByRole("button", { name: "Zapisz" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Prosi o ofertę" }));
    expect(logCall).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Co dalej"), { target: { value: "Wysłać ofertę na 2 osoby" } });
    fireEvent.click(save);
    await waitFor(() => expect(createActivity).toHaveBeenCalled());
    expect(logCall.mock.calls[0][0].outcome).toBe("wants_offer");
    expect(createActivity.mock.calls[0][0].subject).toBe("Wysłać ofertę na 2 osoby");
  });

  it("klik w numer otwiera zapis wyniku bez „Zadzwoniłem”", () => {
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByRole("link", { name: "+48 600 100 200" }));
    expect(screen.getByRole("group", { name: "Wynik rozmowy" })).toBeTruthy();
  });

  it("„Umówione spotkanie” otwiera formularz z firmą, szansą i osobą z wiersza", () => {
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    fireEvent.click(screen.getByRole("button", { name: "Umówione spotkanie" }));
    expect(screen.getByText("okno „Umów spotkanie”")).toBeTruthy();
    expect(bookProps.mock.calls[0][0]).toMatchObject({
      company: { id: 7, name: "Firma Testowa" },
      contactId: 3,
      opportunity: { id: 21, name: "Zespół analityków", company: { id: 7, name: "Firma Testowa" } },
    });
    expect(logCall).not.toHaveBeenCalled();
  });

  it("telefon przy zadaniu firmy idzie trasą firmy i zamyka zadanie", async () => {
    logCompanyCall.mockImplementation((_input, { onSuccess }) => onSuccess());
    const overdue = row({ key: "overdue-5", section: "overdue", opportunity: null, activity_id: 5, kind: "task", amount: null });
    render(<MyDayRowItem row={overdue} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    fireEvent.click(screen.getByRole("button", { name: "Nie odebrał" }));
    await waitFor(() => expect(completeActivity).toHaveBeenCalled());
    expect(completeActivity.mock.calls[0][0]).toEqual({ id: 5 });
    expect(logCompanyCall.mock.calls[0][0]).toEqual({ company_id: 7, outcome: "no_answer", contact_id: 3 });
    expect(logCall).not.toHaveBeenCalled();
    expect(createActivity.mock.calls[0][0]).toMatchObject({ company_id: 7, opportunity_id: null });
  });

  it("Nie kontaktować pyta, zapisuje sprzeciw i nie zakłada kroku", async () => {
    askConfirm.mockResolvedValue(true);
    logCall.mockImplementation((_input, { onSuccess }) => onSuccess());
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    fireEvent.click(screen.getByRole("button", { name: "Nie kontaktować" }));
    await waitFor(() => expect(logCall).toHaveBeenCalled());
    expect(logCall.mock.calls[0][0].outcome).toBe("do_not_contact");
    expect(createActivity).not.toHaveBeenCalled();
  });

  it("odmowa w oknie potwierdzenia nic nie zapisuje", async () => {
    askConfirm.mockResolvedValue(false);
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    fireEvent.click(screen.getByRole("button", { name: "Nie kontaktować" }));
    await waitFor(() => expect(askConfirm).toHaveBeenCalled());
    expect(logCall).not.toHaveBeenCalled();
  });

  it("błąd serwera wraca jako komunikat i wyniki zostają do ponownej próby", async () => {
    logCall.mockImplementation((_input, { onError }) => onError(new Error("boom")));
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    fireEvent.click(screen.getByRole("button", { name: "Dodzwoniłem" }));
    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(createActivity).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Dodzwoniłem" })).toBeTruthy();
  });

  it("nieudany krok po zapisanej rozmowie zamyka panel, żeby rozmowa się nie zdublowała", async () => {
    logCall.mockImplementation((_input, { onSuccess }) => onSuccess());
    createActivity.mockImplementation((_input, { onError }) => onError(new Error("boom")));
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    fireEvent.click(screen.getByRole("button", { name: "Dodzwoniłem" }));
    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(screen.queryByRole("group", { name: "Wynik rozmowy" })).toBeNull();
  });

  it("Zaplanuj ma już wpisane „Zadzwonić”, więc wystarczy termin i „Zapisz”", () => {
    createActivity.mockImplementation((_input, { onSuccess }) => onSuccess());
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zaplanuj"));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(createActivity.mock.calls[0][0]).toMatchObject({ kind: "task", subject: "Zadzwonić", opportunity_id: 21 });
  });

  it("Zaplanuj zapisuje krok przy szansie", () => {
    createActivity.mockImplementation((_input, { onSuccess }) => onSuccess());
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zaplanuj"));
    fireEvent.change(screen.getByLabelText("Co dalej"), { target: { value: "Dopytać o decyzję" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(createActivity.mock.calls[0][0]).toMatchObject({
      kind: "task",
      subject: "Dopytać o decyzję",
      opportunity_id: 21,
      company_id: null,
    });
    expect(showSuccess).toHaveBeenCalled();
  });

  it("Zaplanuj przy zaległym przekłada to samo zadanie", () => {
    updateActivity.mockImplementation((_input, { onSuccess }) => onSuccess());
    const overdue = row({ key: "overdue-9", section: "overdue", activity_id: 9, kind: "task", subject: "Oddzwonić" });
    render(<MyDayRowItem row={overdue} canEdit />);
    fireEvent.click(screen.getByText("Zaplanuj"));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(updateActivity.mock.calls[0][0].subject).toBe("Oddzwonić");
    expect(createActivity).not.toHaveBeenCalled();
  });

  it("Zrobione zamyka zadanie", () => {
    const overdue = row({ key: "overdue-9", section: "overdue", activity_id: 9, kind: "task" });
    render(<MyDayRowItem row={overdue} canEdit />);
    fireEvent.click(screen.getByText("Zrobione"));
    expect(completeActivity.mock.calls[0][0]).toEqual({ id: 9 });
  });

  it("Odpisz otwiera link do maila", () => {
    render(<MyDayRowItem row={row({ section: "reply", web_link: "https://outlook.example/x" })} canEdit />);
    expect(screen.getByRole("link", { name: "Odpisz" }).getAttribute("href")).toBe("https://outlook.example/x");
  });

  it("Odpisz bez linku i adresu nie udaje, że działa", () => {
    render(<MyDayRowItem row={row({ section: "reply", person: null })} canEdit />);
    expect((screen.getByRole("button", { name: "Odpisz" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("Uzupełnij numer zapisuje numer znanej osoby", () => {
    updateContact.mockImplementation((_input, { onSuccess }) => onSuccess());
    const known = { id: 11, name: "Bez Numeru", title: null, phone: null, email: null };
    render(<MyDayRowItem row={row({ person: null, people_without_phone: [known] })} canEdit />);
    fireEvent.click(screen.getByText("Uzupełnij numer"));
    fireEvent.change(screen.getByLabelText("Numer telefonu"), { target: { value: "600 100 200" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz numer" }));
    expect(updateContact.mock.calls[0][0]).toEqual({ mobile_phone: "600 100 200" });
  });

  it("Uzupełnij numer zakłada nową osobę, gdy nie ma kogo wybrać", () => {
    createContact.mockImplementation((_input, { onSuccess }) => onSuccess());
    render(<MyDayRowItem row={row({ person: null })} canEdit />);
    fireEvent.click(screen.getByText("Uzupełnij numer"));
    const save = screen.getByRole("button", { name: "Zapisz numer" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Imię i nazwisko"), { target: { value: "Nowa Osoba" } });
    fireEvent.change(screen.getByLabelText("Numer telefonu"), { target: { value: "600 100 200" } });
    fireEvent.click(save);
    expect(createContact.mock.calls[0][0]).toEqual({
      company_id: 7,
      full_name: "Nowa Osoba",
      mobile_phone: "600 100 200",
    });
  });

  it("za krótki numer nie przechodzi", () => {
    render(<MyDayRowItem row={row({ person: null })} canEdit />);
    fireEvent.click(screen.getByText("Uzupełnij numer"));
    fireEvent.change(screen.getByLabelText("Imię i nazwisko"), { target: { value: "Nowa Osoba" } });
    fireEvent.change(screen.getByLabelText("Numer telefonu"), { target: { value: "12" } });
    expect((screen.getByRole("button", { name: "Zapisz numer" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("firma z zakazem kontaktu nie ma telefonu ani numeru do uzupełnienia", () => {
    render(<MyDayRowItem row={row({ do_not_contact: true, person: null })} canEdit />);
    expect(screen.getByText("Nie kontaktować")).toBeTruthy();
    expect(screen.queryByText("Zadzwoniłem")).toBeNull();
    expect(screen.queryByText("Uzupełnij numer")).toBeNull();
  });

  it("sam podgląd nie ma przycisków zapisu", () => {
    const overdue = row({ key: "overdue-9", section: "overdue", activity_id: 9, kind: "task" });
    render(<MyDayRowItem row={overdue} canEdit={false} />);
    expect(screen.queryByText("Zaplanuj")).toBeNull();
    expect(screen.queryByText("Zrobione")).toBeNull();
    expect(screen.queryByText("Zadzwoniłem")).toBeNull();
  });
});
