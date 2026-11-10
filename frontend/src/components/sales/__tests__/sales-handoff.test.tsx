/**
 * Przekazanie spotkania i werdykt: formularz „Umów spotkanie”, listy w „Mój dzień”,
 * karta przekazania i podpowiedź tożsamości firmy. Dane fikcyjne.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Meeting } from "@/lib/api/sales";
import type { CompanyIdentity, Handoff, HandoffWeek, HostBusy } from "@/lib/api/sales-handoffs";

const bookMeeting = vi.fn();
const giveVerdict = vi.fn();
const setTerm = vi.fn();
const confirmTerm = vi.fn();
const createCompany = vi.fn();
const updateCompany = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();
const identity = vi.fn();
const hostBusy = vi.fn();
const contacts = vi.fn();
const opportunities = vi.fn();
const companyCard = vi.fn();

const mutation = (mutate: ReturnType<typeof vi.fn>) => ({ mutate, isPending: false });

vi.mock("@/lib/api/sales-handoffs", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-handoffs")>()),
  useHandoffForm: () => ({
    data: {
      hosts: [
        { id: 2, name: "Prowadzący Testowy" },
        { id: 4, name: "Druga Prowadząca" },
      ],
      default_host_id: 2,
    },
  }),
  useBookMeeting: () => mutation(bookMeeting),
  useGiveVerdict: () => mutation(giveVerdict),
  useSetHandoffTerm: () => mutation(setTerm),
  useConfirmHandoff: () => mutation(confirmTerm),
  useCompanyIdentity: (input: { name?: string; email?: string; website?: string }) => identity(input),
  useHostBusy: (hostId: number | null, day: string | null) => hostBusy(hostId, day),
}));
vi.mock("@/lib/api/sales", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales")>()),
  useSalesCompany: (id: number) => companyCard(id),
  useSalesContacts: (companyId: number | null) => contacts(companyId),
  useOpportunities: (filters: { company_id?: number | null }) => opportunities(filters),
  useCompanyBriefing: () => ({ isSuccess: false }),
  useCompanyPeople: () => ({ isLoading: true, error: null, isSuccess: false }),
  useCreateSalesCompany: () => mutation(createCompany),
  useUpdateSalesCompany: () => mutation(updateCompany),
  useRegistryLookup: () => mutation(vi.fn()),
}));
vi.mock("@/lib/use-debounced-value", () => ({ useDebouncedValue: <T,>(value: T) => value }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess }) }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: { id: number } }) => unknown) => selector({ user: { id: 3 } }),
  hasRole: () => false,
}));
vi.mock("../useOwnerFilterOptions", () => ({ useOwnerFilterOptions: () => [] }));
vi.mock("../CompanyPicker", () => ({ CompanyPicker: () => null }));
vi.mock("@/components/ds/AppModal", () => ({
  AppModal: ({ title, children, footer }: { title: string; children: ReactNode; footer?: ReactNode }) => (
    <div role="dialog" aria-label={title}>
      {children}
      {footer}
    </div>
  ),
}));
vi.mock("../SalesSelect", () => ({
  SalesSelect: ({
    value,
    onValueChange,
    options,
    ariaLabel,
    anyLabel,
  }: {
    value: string;
    onValueChange: (value: string) => void;
    options: readonly { value: string; label: string }[];
    ariaLabel?: string;
    anyLabel?: string;
  }) => (
    <select aria-label={ariaLabel} value={value} onChange={(event) => onValueChange(event.target.value)}>
      {anyLabel !== undefined && <option value="">{anyLabel}</option>}
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

import { CompanyFormDialog } from "../CompanyFormDialog";
import { BookMeetingForm } from "../handoff/BookMeetingForm";
import { HandoffCard } from "../handoff/HandoffCard";
import { BookedByMeSection, HandedToMeSection } from "../handoff/HandoffSections";
import {
  bookerStatus,
  briefLine,
  freeStarts,
  handoffWhen,
  mailAddress,
  termFromFields,
  visibleWeeks,
  weekFunnel,
  weekLabel,
} from "../handoff/helpers";
import { HostCalendar } from "../handoff/HostCalendar";
import { VerdictPanel } from "../handoff/VerdictPanel";
import { MeetingDecisionCell } from "../MeetingDecisionCell";

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
    decision_maker: "Kierownik IT",
    timing: null,
    contact: {
      id: 5,
      name: "Anna Przykładowa",
      title: "Kierownik IT",
      phone: "600 100 200",
      email: "anna@firma-testowa.example",
      do_not_contact: false,
    },
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

const noIdentity: CompanyIdentity = { domain: null, domain_source: null, matches: [] };
const busy = (data: HostBusy) => ({ isPending: false, isSuccess: true, data });

beforeEach(() => {
  vi.clearAllMocks();
  identity.mockReturnValue({ data: noIdentity });
  hostBusy.mockReturnValue(busy({ calendar: "ok", busy: [] }));
  contacts.mockReturnValue({ data: { items: [], total: 0 } });
  opportunities.mockReturnValue({ data: { items: [], total: 0 } });
  companyCard.mockReturnValue({ isSuccess: false, data: undefined });
});

describe("podpisy przekazania", () => {
  const now = new Date("2026-11-10T08:00:00Z");

  it("termin czyta się jak w rozmowie", () => {
    expect(handoffWhen(null, now)).toBe("bez terminu");
    expect(handoffWhen("2026-11-10T08:30:00Z", now)).toBe("dziś 09:30");
    expect(handoffWhen("2026-11-11T12:00:00Z", now)).toBe("jutro 13:00");
    expect(handoffWhen("2026-11-12T12:00:00Z", now)).toBe("czw 12.11 13:00");
  });

  it("wiersz mówi, z kim jest spotkanie i od kogo przyszło", () => {
    expect(briefLine(handoff(), "host")).toBe("Kierownik IT · Automatyzacje · od: Dzwoniący Testowy");
    expect(briefLine(handoff({ contact: null, service: null }), "booker")).toBe(
      "bez osoby · prowadzi: Prowadzący Testowy",
    );
  });

  it("osoba, która umówiła, widzi werdykt słowami", () => {
    expect(bookerStatus(handoff())).toBe("Czeka na spotkanie");
    expect(bookerStatus(handoff({ phase: "no_term", meeting_at: null }))).toBe("Bez terminu");
    expect(bookerStatus(handoff({ verdict: "qualified", phase: "done" }))).toBe("Kwalifikuje się");
    expect(bookerStatus(handoff({ verdict: "not_now", return_on: "2026-12-15", phase: "done" }))).toBe(
      "Nie teraz, wraca 15.12",
    );
    expect(bookerStatus(handoff({ verdict: "not_a_fit", verdict_reason: "Za mała firma", phase: "done" }))).toBe(
      "Nie nasz klient: Za mała firma",
    );
    expect(bookerStatus(handoff({ verdict: "no_show", phase: "done" }))).toBe("Nie odbyło się, umów ponownie");
  });

  it("tygodnie: bieżący i poprzedni zawsze, starsze tylko z liczbami", () => {
    const weeks: HandoffWeek[] = [
      { week_start: "2026-11-09", booked: 6, held: 2, qualified: 1 },
      { week_start: "2026-11-02", booked: 0, held: 0, qualified: 0 },
      { week_start: "2026-10-26", booked: 0, held: 0, qualified: 0 },
      { week_start: "2026-10-19", booked: 3, held: 3, qualified: 0 },
    ];
    const shown = visibleWeeks(weeks);
    expect(shown.map((week) => week.week_start)).toEqual(["2026-11-09", "2026-11-02", "2026-10-19"]);
    expect(weekFunnel(weeks[0])).toBe("6 → 2 → 1");
    expect([weekLabel(shown[0], 0), weekLabel(shown[1], 1), weekLabel(shown[2], 2)]).toEqual([
      "ten tydzień",
      "poprzedni",
      "od 19.10",
    ]);
  });

  it("adres z dopiskiem nie staje się odnośnikiem do poczty", () => {
    expect(mailAddress(" anna@firma.example ")).toBe("anna@firma.example");
    expect(mailAddress("anna@firma.example?bcc=ktos@inny.example")).toBeUndefined();
    expect(mailAddress(null)).toBeUndefined();
  });

  it("wolne godziny omijają zajęte i przeszłe", () => {
    const morning = termFromFields("2026-11-12", "08:00") as string;
    const blockStart = termFromFields("2026-11-12", "09:00") as string;
    const blockEnd = termFromFields("2026-11-12", "10:00") as string;
    const free = freeStarts("2026-11-12", 30, [{ start: blockStart, end: blockEnd }], new Date(morning), 4);
    expect(free).toEqual(["08:30", "10:00", "10:30", "11:00"]);
    expect(termFromFields("2026-11-12", "")).toBeNull();
  });
});

describe("formularz „Umów spotkanie”", () => {
  const fill = (label: string, value: string) =>
    fireEvent.change(screen.getByLabelText(label), { target: { value } });

  it("zapisuje nową firmę, osobę, termin i odpowiedzi", () => {
    identity.mockReturnValue({ data: { ...noIdentity, domain: "firma-nowa.example", domain_source: "email" } });
    render(<BookMeetingForm onSaved={vi.fn()} onCancel={vi.fn()} />);
    fill("Nazwa firmy", "Firma Nowa");
    fill("Imię i nazwisko", "Anna Przykładowa");
    fill("E-mail", "anna@firma-nowa.example");
    fill("Dzień spotkania", "2026-11-12");
    fill("Godzina spotkania", "13:00");
    fill("Usługa", "Automatyzacje");
    fill("Problem", "Raporty składane ręcznie");
    fireEvent.click(screen.getByRole("button", { name: /^Umów / }));

    const payload = bookMeeting.mock.calls[0][0];
    expect(payload.new_company).toEqual({
      name: "Firma Nowa",
      website_url: null,
      // Domena z adresu e-mail osoby: podpowiedź widać w polu, zanim pójdzie do zapisu.
      domain: "firma-nowa.example",
      allow_duplicate: false,
    });
    expect(payload.new_contact).toEqual({
      full_name: "Anna Przykładowa",
      title: null,
      email: "anna@firma-nowa.example",
      phone: null,
    });
    // Prowadzący z ostatniego przekazania jest wybrany od razu.
    expect(payload.host_user_id).toBe(2);
    expect(payload.meeting_at).toBe(termFromFields("2026-11-12", "13:00"));
    expect(payload).toMatchObject({ service: "Automatyzacje", problem: "Raporty składane ręcznie", timing: null });
    expect(payload.company_id).toBeUndefined();
  });

  it("brak terminu, osoby i odpowiedzi nie zatrzymuje zapisu", () => {
    render(<BookMeetingForm onSaved={vi.fn()} onCancel={vi.fn()} />);
    const save = screen.getByRole("button", { name: "Zapisz bez terminu" });
    expect(save).toHaveProperty("disabled", true);
    fill("Nazwa firmy", "Firma Nowa");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz bez terminu" }));
    const payload = bookMeeting.mock.calls[0][0];
    expect(payload.meeting_at).toBeNull();
    expect(payload.new_contact).toBeUndefined();
    expect(payload.contact_id).toBeUndefined();
  });

  it("podpowiada istniejącą kartę i pozwala jej użyć", () => {
    identity.mockReturnValue({
      data: {
        ...noIdentity,
        matches: [{ id: 7, name: "Firma Testowa", hq_city: "Poznań", domain: null, open_opportunities: 1, reason: "name" }],
      },
    });
    contacts.mockReturnValue({
      data: { items: [{ id: 5, full_name: "Anna Przykładowa", title: "Kierownik IT" }], total: 1 },
    });
    render(<BookMeetingForm onSaved={vi.fn()} onCancel={vi.fn()} />);
    fill("Nazwa firmy", "Firma Test");
    expect(screen.getByText(/ta sama nazwa · Poznań · 1 otwarta szansa/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Firma Testowa" }));
    expect(screen.queryByLabelText("Nazwa firmy")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz bez terminu" }));
    const payload = bookMeeting.mock.calls[0][0];
    expect(payload).toMatchObject({ company_id: 7, contact_id: 5 });
    expect(payload.new_company).toBeUndefined();
  });

  it("własną szansę w tej firmie przekazuje zamiast zakładać drugą", () => {
    opportunities.mockReturnValue({
      data: {
        items: [
          { id: 90, title: "Cudza", owner: { id: 8, name: "Ktoś" }, stage: { key: "lead", name: "Lead" } },
          { id: 91, title: "Spotkanie wstępne", owner: { id: 3, name: "Ja" }, stage: { key: "lead", name: "Lead" } },
        ],
        total: 2,
      },
    });
    render(<BookMeetingForm company={{ id: 7, name: "Firma Testowa" }} onSaved={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByText(/Masz już w tej firmie szansę „Spotkanie wstępne”/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz bez terminu" }));
    expect(bookMeeting.mock.calls[0][0].opportunity_id).toBe(91);
    expect(bookMeeting.mock.calls[0][0].company_id).toBeUndefined();

    fireEvent.click(screen.getByLabelText("Przekaż moją szansę zamiast zakładać nową"));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz bez terminu" }));
    expect(bookMeeting.mock.calls[1][0]).toMatchObject({ company_id: 7 });
    expect(bookMeeting.mock.calls[1][0].opportunity_id).toBeUndefined();
  });

  it("karta bez domeny dostaje ją z maila osoby, a karta z domeną zostaje nietknięta", () => {
    identity.mockReturnValue({ data: { ...noIdentity, domain: "firma-testowa.example", domain_source: "email" } });
    companyCard.mockReturnValue({ isSuccess: true, data: { id: 7, domain: null } });
    const { unmount } = render(
      <BookMeetingForm company={{ id: 7, name: "Firma Testowa" }} onSaved={vi.fn()} onCancel={vi.fn()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Zapisz bez terminu" }));
    expect(bookMeeting.mock.calls[0][0].company_domain).toBe("firma-testowa.example");
    unmount();

    companyCard.mockReturnValue({ isSuccess: true, data: { id: 7, domain: "stara.example" } });
    render(<BookMeetingForm company={{ id: 7, name: "Firma Testowa" }} onSaved={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.queryByLabelText("Domena poczty")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz bez terminu" }));
    expect(bookMeeting.mock.calls[1][0].company_domain).toBeUndefined();
  });

  it("karta o tej samej nazwie ostrzega: użyj jej albo załóż nową mimo to", () => {
    bookMeeting.mockImplementationOnce((_payload, { onError }) =>
      onError({
        response: {
          data: {
            detail: { code: "sales_company_duplicate", duplicates: [{ id: 7, name: "Firma Testowa", nip: null }] },
          },
        },
      }),
    );
    render(<BookMeetingForm onSaved={vi.fn()} onCancel={vi.fn()} />);
    fill("Nazwa firmy", "Firma Testowa");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz bez terminu" }));
    expect(screen.getByRole("alert").textContent).toContain("Karta o tej nazwie już jest");
    fireEvent.click(screen.getByRole("button", { name: "Załóż nową kartę mimo to" }));
    expect(bookMeeting.mock.calls[1][0].new_company.allow_duplicate).toBe(true);
  });

  it("odmowa dla klienta NEXUSA zostaje w formularzu ze wskazaniem Delivery Leada", () => {
    const refusal = "Klient Testowy to klient NEXUSA, szansy nie zakładamy. Przekaż do: Delivery Lead Testowy.";
    bookMeeting.mockImplementationOnce((_payload, { onError }) =>
      onError({ response: { status: 409, data: { detail: refusal } } }),
    );
    const onSaved = vi.fn();
    render(<BookMeetingForm onSaved={onSaved} onCancel={vi.fn()} />);
    fill("Nazwa firmy", "Klient Testowy");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz bez terminu" }));
    expect(screen.getByRole("alert").textContent).toContain("Przekaż do: Delivery Lead Testowy");
    expect(onSaved).not.toHaveBeenCalled();
  });

  it("ponowne umówienie wraca z odpowiedziami i szansą", () => {
    const previous = handoff({ verdict: "no_show", phase: "done" });
    render(
      <BookMeetingForm
        opportunity={{ id: 21, name: previous.opportunity.name, company: previous.company }}
        handoff={previous}
        onSaved={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect((screen.getByLabelText("Problem") as HTMLInputElement).value).toBe("Raporty składane ręcznie");
    fireEvent.click(screen.getByRole("button", { name: "Zapisz bez terminu" }));
    expect(bookMeeting.mock.calls[0][0]).toMatchObject({ opportunity_id: 21, host_user_id: 2 });
  });
});

describe("kalendarz prowadzącego", () => {
  const props = { hostId: 2, hostName: "Prowadzący Testowy", day: "2026-11-12", minutes: 30 };

  it("ostrzega o kolizji, ale niczego nie blokuje", () => {
    hostBusy.mockReturnValue(
      busy({
        calendar: "ok",
        busy: [
          {
            start: termFromFields("2026-11-12", "13:00") as string,
            end: termFromFields("2026-11-12", "14:00") as string,
          },
        ],
      }),
    );
    render(<HostCalendar {...props} time="13:30" onPickTime={vi.fn()} />);
    expect(screen.getByRole("status").textContent).toContain("ma wtedy zajęte");
    expect(screen.getByText("to spotkanie")).toBeTruthy();
  });

  it("bez połączonej skrzynki mówi, że termin trzeba ustalić z prowadzącym", () => {
    hostBusy.mockReturnValue(busy({ calendar: "unavailable", busy: [] }));
    render(<HostCalendar {...props} time="" onPickTime={vi.fn()} />);
    expect(screen.getByText(/nie jest połączony z NEXUSEM/)).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Wolne godziny" })).toBeNull();
  });

  it("bez dnia nie pyta o kalendarz", () => {
    const { container } = render(<HostCalendar {...props} day="" time="" onPickTime={vi.fn()} />);
    expect(container.textContent).toBe("");
  });
});

describe("listy w „Mój dzień”", () => {
  it("przekazane: najpierw terminy, osobno bez terminu, przycisk mówi co zrobić", () => {
    const rows = [
      handoff({ opportunity: { id: 1, name: "A" }, company: { id: 1, name: "Po Terminie" }, phase: "verdict" }),
      handoff({ opportunity: { id: 2, name: "B" }, company: { id: 2, name: "Na Jutro" }, phase: "confirm", clash: true }),
      handoff({ opportunity: { id: 3, name: "C" }, company: { id: 3, name: "Za Tydzień" }, phase: "upcoming" }),
      ...[4, 5, 6, 7].map((id) =>
        handoff({
          opportunity: { id, name: `D${id}` },
          company: { id, name: `Bez Terminu ${id}` },
          meeting_at: null,
          phase: "no_term",
        }),
      ),
    ];
    const onOpen = vi.fn();
    render(<HandedToMeSection rows={rows} selectedId={null} canEdit onOpen={onOpen} />);
    expect(screen.getByText("3 z terminem · 4 bez terminu")).toBeTruthy();
    expect(screen.getByText("Kolizja")).toBeTruthy();
    expect(screen.queryByText("Bez Terminu 7")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż wszystkie" }));
    expect(screen.getByText("Bez Terminu 7")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Werdykt" }));
    expect(onOpen).toHaveBeenLastCalledWith(rows[0], "verdict");
    fireEvent.click(screen.getByRole("button", { name: "Potwierdź" }));
    expect(onOpen).toHaveBeenLastCalledWith(rows[1], null);
    fireEvent.click(screen.getAllByRole("button", { name: "Ustaw termin" })[0]);
    expect(onOpen).toHaveBeenLastCalledWith(rows[3], "term");
  });

  it("sam podgląd nie daje przycisków werdyktu", () => {
    render(
      <HandedToMeSection rows={[handoff({ phase: "verdict" })]} selectedId={null} canEdit={false} onOpen={vi.fn()} />,
    );
    expect(screen.queryByRole("button", { name: "Werdykt" })).toBeNull();
  });

  it("umówione przez Ciebie: werdykt przy wierszu i własne liczby tygodnia", () => {
    const noShow = handoff({ opportunity: { id: 2, name: "B" }, verdict: "no_show", phase: "done" });
    const onRebook = vi.fn();
    render(
      <BookedByMeSection
        rows={[handoff({ verdict: "qualified", phase: "done" }), noShow]}
        weeks={[
          { week_start: "2026-11-09", booked: 6, held: 2, qualified: 1 },
          { week_start: "2026-11-02", booked: 12, held: 9, qualified: 4 },
        ]}
        selectedId={null}
        canEdit
        onOpen={vi.fn()}
        onRebook={onRebook}
      />,
    );
    const weeks = screen.getByTestId("handoff-weeks").textContent;
    expect(weeks).toContain("ten tydzień 6 → 2 → 1");
    expect(weeks).toContain("poprzedni 12 → 9 → 4");
    expect(screen.getByText("Kwalifikuje się")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Umów ponownie" }));
    expect(onRebook).toHaveBeenCalledWith(noShow);
    // Liczby tylko własne: bez celu, paska postępu i przełącznika osoby.
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("bez spotkań i bez liczb sekcji nie ma", () => {
    const { container } = render(
      <BookedByMeSection rows={[]} weeks={[]} selectedId={null} canEdit onOpen={vi.fn()} onRebook={vi.fn()} />,
    );
    expect(container.textContent).toBe("");
  });
});

describe("werdykt", () => {
  it("„Kwalifikuje się” i „Nie odbyło się” to jedno kliknięcie", () => {
    const onSaved = vi.fn();
    giveVerdict.mockImplementation((_input, { onSuccess }) => onSuccess());
    render(<VerdictPanel handoff={handoff({ phase: "verdict" })} onSaved={onSaved} />);
    fireEvent.click(screen.getByRole("button", { name: /Kwalifikuje się/ }));
    expect(giveVerdict.mock.calls[0][0]).toEqual({ opportunity_id: 21, kind: "qualified" });
    expect(onSaved).toHaveBeenCalledWith("qualified");
    fireEvent.click(screen.getByRole("button", { name: /Nie odbyło się/ }));
    expect(giveVerdict.mock.calls[1][0]).toEqual({ opportunity_id: 21, kind: "no_show" });
    expect(screen.getByText(/Werdykt zobaczy Dzwoniący Testowy/)).toBeTruthy();
  });

  it("„Nie teraz” pyta o datę powrotu", () => {
    render(<VerdictPanel handoff={handoff({ phase: "verdict" })} onSaved={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Nie teraz/ }));
    expect(giveVerdict).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("Data powrotu"), { target: { value: "2027-01-15" } });
    fireEvent.change(screen.getByLabelText("Dopisek"), { target: { value: "budżet od stycznia" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz „Nie teraz”" }));
    expect(giveVerdict.mock.calls[0][0]).toEqual({
      opportunity_id: 21,
      kind: "not_now",
      return_on: "2027-01-15",
      reason: "budżet od stycznia",
    });
  });

  it("„Nie nasz klient” zamyka z powodem, a powód nie jest wymagany", () => {
    render(<VerdictPanel handoff={handoff({ phase: "verdict" })} onSaved={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Nie nasz klient/ }));
    fireEvent.click(screen.getByRole("button", { name: "Za mała firma" }));
    fireEvent.click(screen.getByRole("button", { name: "Zamknij szansę" }));
    expect(giveVerdict.mock.calls[0][0]).toEqual({ opportunity_id: 21, kind: "not_a_fit", reason: "Za mała firma" });
    fireEvent.change(screen.getByLabelText("Powód"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Zamknij szansę" }));
    expect(giveVerdict.mock.calls[1][0].reason).toBeNull();
  });
});

describe("karta przekazania", () => {
  const card = (data: Handoff, viewer: "host" | "booker" = "host", canEdit = true) =>
    render(
      <HandoffCard handoff={data} viewer={viewer} canEdit={canEdit} panel={null} onPanel={vi.fn()} onRebook={vi.fn()} />,
    );

  it("pokazuje odpowiedzi z rozmowy i osobę", () => {
    card(handoff());
    expect(screen.getByText("Raporty składane ręcznie")).toBeTruthy();
    expect(screen.getByText("Anna Przykładowa")).toBeTruthy();
    expect(screen.getByText("Umówione przez: Dzwoniący Testowy, 06.11")).toBeTruthy();
    expect(screen.queryByTestId("verdict-panel")).toBeNull();
  });

  it("dzień przed spotkaniem prosi o potwierdzenie u klienta i sama niczego nie wysyła", () => {
    card(handoff({ phase: "confirm" }));
    const block = within(screen.getByTestId("confirm-block"));
    expect(block.getByRole("link", { name: "Zadzwoń" }).getAttribute("href")).toBe("tel:600100200");
    expect(block.getByRole("link", { name: "Napisz" }).getAttribute("href")).toContain(
      "mailto:anna@firma-testowa.example",
    );
    expect(confirmTerm).not.toHaveBeenCalled();
    fireEvent.click(block.getByRole("button", { name: "Klient potwierdził" }));
    expect(confirmTerm.mock.calls[0][0]).toBe(21);
  });

  it("po terminie od razu pyta o werdykt, bez terminu o termin", () => {
    const { unmount } = card(handoff({ phase: "verdict" }));
    expect(screen.getByTestId("verdict-panel")).toBeTruthy();
    unmount();
    card(handoff({ phase: "no_term", meeting_at: null }));
    expect(screen.getByTestId("term-panel")).toBeTruthy();
  });

  it("termin z kalendarza zmienia się w Outlooku", () => {
    card(handoff({ from_calendar: true }));
    expect(screen.getByText("Termin z kalendarza")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Zmień termin" })).toBeNull();
  });

  it("osoba, która umówiła, nie daje werdyktu, ale umawia ponownie", () => {
    card(handoff({ verdict: "no_show", phase: "done" }), "booker");
    expect(screen.queryByRole("button", { name: "Daj werdykt" })).toBeNull();
    expect(screen.getByRole("button", { name: "Umów ponownie" })).toBeTruthy();
    expect(screen.getByText("Nie odbyło się, umów ponownie")).toBeTruthy();
  });

  it("osoba ze sprzeciwem nie ma klikalnego numeru", () => {
    const objecting = handoff();
    card({ ...objecting, contact: { ...objecting.contact!, do_not_contact: true }, phase: "confirm" });
    expect(screen.getByText("Nie kontaktować")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Zadzwoń" })).toBeNull();
  });
});

describe("spotkanie przypięte samo", () => {
  const meeting = (overrides: Partial<Meeting>) =>
    ({
      id: 1,
      decision: "linked",
      can_unpin: true,
      opportunity: { id: 11, name: "Migracja" },
      open_opportunities: [],
      ...overrides,
    }) as Meeting;

  it("mówi o tym i daje „Odepnij”", () => {
    const onUnpin = vi.fn();
    render(
      <MeetingDecisionCell
        meeting={meeting({ auto_pinned: true })}
        canEdit
        busy={false}
        onPin={vi.fn()}
        onCreate={vi.fn()}
        onUnpin={onUnpin}
      />,
    );
    expect(screen.getByText("samo").getAttribute("title")).toContain("Przypięte samo");
    fireEvent.click(screen.getByRole("button", { name: "Odepnij" }));
    expect(onUnpin).toHaveBeenCalled();
  });

  it("przypięte ręcznie zostaje przy „Cofnij”", () => {
    render(
      <MeetingDecisionCell
        meeting={meeting({ auto_pinned: false })}
        canEdit
        busy={false}
        onPin={vi.fn()}
        onCreate={vi.fn()}
        onUnpin={vi.fn()}
      />,
    );
    expect(screen.queryByText("samo")).toBeNull();
    expect(screen.getByRole("button", { name: "Cofnij" })).toBeTruthy();
  });
});

describe("tożsamość firmy w oknie „Nowa firma”", () => {
  it("podpowiada istniejące karty i bierze domenę z adresu strony", () => {
    identity.mockReturnValue({
      data: {
        domain: "firma-testowa.example",
        domain_source: "website",
        matches: [
          { id: 7, name: "Firma Testowa", hq_city: null, domain: null, open_opportunities: 0, reason: "similar" },
        ],
      },
    });
    render(<CompanyFormDialog open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Nazwa"), { target: { value: "Firma Test" } });
    fireEvent.change(screen.getByLabelText("Strona www"), { target: { value: "www.firma-testowa.example" } });
    const hints = within(screen.getByTestId("company-identity-hints"));
    expect(hints.getByRole("link", { name: "Firma Testowa" }).getAttribute("href")).toBe("/sales/companies/7");
    expect(screen.getByText(/Zapiszemy firma-testowa.example z adresu strony/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Dodaj firmę" }));
    // Podpowiedź nie blokuje: zapis idzie od razu, a domenę ze strony wylicza serwer.
    expect(createCompany.mock.calls[0][0]).toMatchObject({
      name: "Firma Test",
      domain: null,
      website_url: "www.firma-testowa.example",
    });
  });

  it("przy edycji skasowana domena idzie do zapisu pusta", () => {
    identity.mockReturnValue({ data: { ...noIdentity, domain: "ze-strony.example", domain_source: "website" } });
    const company = {
      id: 7,
      name: "Firma Testowa",
      domain: "stara.example",
      website_url: "https://ze-strony.example",
      tags: [],
      lifecycle_stage: "lead",
      owner: null,
      parent: null,
    } as unknown as import("@/lib/api/sales").SalesCompany;
    const update = vi.fn();
    updateCompany.mockImplementation(update);
    render(<CompanyFormDialog open onOpenChange={vi.fn()} company={company} />);
    expect(screen.queryByTestId("company-identity-hints")).toBeNull();
    fireEvent.change(screen.getByLabelText("Domena poczty"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(update.mock.calls[0][0].domain).toBeNull();
  });

  it("wpisana domena ma pierwszeństwo przed podpowiedzią", () => {
    identity.mockReturnValue({ data: { ...noIdentity, domain: "ze-strony.example", domain_source: "website" } });
    render(<CompanyFormDialog open onOpenChange={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Nazwa"), { target: { value: "Firma" } });
    fireEvent.change(screen.getByLabelText("Domena poczty"), { target: { value: "wpisana.example" } });
    fireEvent.click(screen.getByRole("button", { name: "Dodaj firmę" }));
    expect(createCompany.mock.calls[0][0].domain).toBe("wpisana.example");
  });
});
