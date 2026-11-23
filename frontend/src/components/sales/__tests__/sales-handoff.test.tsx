/**
 * Przekazanie spotkania i werdykt: formularz „Umów spotkanie”, listy w „Mój dzień”,
 * karta przekazania i podpowiedź tożsamości firmy. Dane fikcyjne.
 */
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Meeting, SalesCompany } from "@/lib/api/sales";
import type { CompanyIdentity, Handoff, HandoffWeek, HostBusy, InviteDraft } from "@/lib/api/sales-handoffs";

const bookMeeting = vi.fn();
const giveVerdict = vi.fn();
const setTerm = vi.fn();
const confirmTerm = vi.fn();
const createCompany = vi.fn();
const updateCompany = vi.fn();
const ownerCandidates = vi.fn();
const ownerFilterOptions = vi.fn();
const showError = vi.fn();
const showSuccess = vi.fn();
const identity = vi.fn();
const hostBusy = vi.fn();
const contacts = vi.fn();
const opportunities = vi.fn();
const companyCard = vi.fn();
const inviteDraft = vi.fn();
const sendInvite = vi.fn();
const sendBookingMail = vi.fn();
const sendBookingInvite = vi.fn();
const handoffForm = vi.fn();
const defaultForm = {
  hosts: [
    { id: 2, name: "Prowadzący Testowy" },
    { id: 4, name: "Druga Prowadząca" },
  ],
  default_host_id: 2,
};

const mutation = (mutate: ReturnType<typeof vi.fn>) => ({ mutate, isPending: false });

vi.mock("@/lib/api/sales-handoffs", async (original) => ({
  ...(await original<typeof import("@/lib/api/sales-handoffs")>()),
  useHandoffForm: () => ({ data: handoffForm() }),
  useBookMeeting: () => mutation(bookMeeting),
  useGiveVerdict: () => ({ mutateAsync: giveVerdict, isPending: false }),
  useSetHandoffTerm: () => ({ mutateAsync: setTerm, isPending: false }),
  useConfirmHandoff: () => ({ mutateAsync: confirmTerm, isPending: false }),
  useCompanyIdentity: (input: { name?: string; email?: string; website?: string }) => identity(input),
  useHostBusy: (hostId: number | null, day: string | null) => hostBusy(hostId, day),
  useInviteDraft: (opportunityId: number) => inviteDraft(opportunityId),
  useSendInvite: () => ({ mutateAsync: sendInvite, isPending: false }),
  useSendBookingMail: () => ({ mutateAsync: sendBookingMail, isPending: false }),
  useSendBookingInvite: () => ({ mutateAsync: sendBookingInvite, isPending: false }),
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
  usePatchSalesCompany: () => mutation(vi.fn()),
  useSalesCompanies: () => ({ data: { items: [], total: 0 }, isSuccess: true }),
  useOwnerCandidates: (enabled?: boolean) => ownerCandidates(enabled),
  useRegistryLookup: () => mutation(vi.fn()),
}));
vi.mock("@/lib/use-debounced-value", () => ({ useDebouncedValue: <T,>(value: T) => value }));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showError, showSuccess }) }));
vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: { user: { id: number } }) => unknown) => selector({ user: { id: 3 } }),
  hasRole: () => false,
}));
vi.mock("../useOwnerFilterOptions", () => ({ useOwnerFilterOptions: () => ownerFilterOptions() }));
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
    id,
    value,
    onValueChange,
    options,
    ariaLabel,
    anyLabel,
  }: {
    id?: string;
    value: string;
    onValueChange: (value: string) => void;
    options: readonly { value: string; label: string }[];
    ariaLabel?: string;
    anyLabel?: string;
  }) => (
    <select id={id} aria-label={ariaLabel} value={value} onChange={(event) => onValueChange(event.target.value)}>
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
  bookingMailBody,
  bookingMailSubject,
  briefLine,
  freeStarts,
  handoffWhen,
  mailAddress,
  teamsInviteBody,
  teamsInviteSubject,
  termFromFields,
  visibleWeeks,
  weekFunnel,
  weekLabel,
} from "../handoff/helpers";
import { HostCalendar } from "../handoff/HostCalendar";
import { InviteDialog } from "../handoff/InviteDialog";
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
  ownerCandidates.mockReturnValue({ data: [] });
  ownerFilterOptions.mockReturnValue([]);
  hostBusy.mockReturnValue(busy({ calendar: "ok", busy: [] }));
  contacts.mockReturnValue({ data: { items: [], total: 0 } });
  opportunities.mockReturnValue({ data: { items: [], total: 0 } });
  companyCard.mockReturnValue({ isSuccess: false, data: undefined });
  giveVerdict.mockResolvedValue({});
  setTerm.mockResolvedValue({});
  confirmTerm.mockResolvedValue({});
  sendInvite.mockResolvedValue({});
  sendBookingMail.mockResolvedValue({});
  sendBookingInvite.mockResolvedValue({});
  handoffForm.mockReturnValue(defaultForm);
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
  it("„Kwalifikuje się” i „Nie odbyło się” to jedno kliknięcie", async () => {
    const onSaved = vi.fn();
    render(<VerdictPanel handoff={handoff({ phase: "verdict" })} onSaved={onSaved} />);
    fireEvent.click(screen.getByRole("button", { name: /Kwalifikuje się/ }));
    expect(giveVerdict.mock.calls[0][0]).toEqual({ opportunity_id: 21, kind: "qualified" });
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("qualified"));
    expect(showSuccess).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Nie odbyło się/ }));
    expect(giveVerdict.mock.calls[1][0]).toEqual({ opportunity_id: 21, kind: "no_show" });
    expect(screen.getByText(/Werdykt zobaczy Dzwoniący Testowy/)).toBeTruthy();
  });

  it("werdykt dochodzi do rodzica także wtedy, gdy panel zdążył zniknąć", async () => {
    // Po zapisie lista się odświeża i spotkanie z niej znika, zanim przyjdzie odpowiedź do panelu.
    let finish: () => void = () => undefined;
    giveVerdict.mockImplementationOnce(() => new Promise<void>((resolve) => (finish = resolve)));
    const onSaved = vi.fn();
    const { unmount } = render(<VerdictPanel handoff={handoff({ phase: "verdict" })} onSaved={onSaved} />);
    fireEvent.click(screen.getByRole("button", { name: /Kwalifikuje się/ }));
    unmount();
    finish();
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("qualified"));
  });

  it("nieudany zapis werdyktu mówi o tym i niczego nie zamyka", async () => {
    giveVerdict.mockRejectedValueOnce(new Error("boom"));
    const onSaved = vi.fn();
    render(<VerdictPanel handoff={handoff({ phase: "verdict" })} onSaved={onSaved} />);
    fireEvent.click(screen.getByRole("button", { name: /Nie odbyło się/ }));
    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(onSaved).not.toHaveBeenCalled();
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

describe("zaproszenie od prowadzącego", () => {
  const draft = (overrides: Partial<InviteDraft> = {}): InviteDraft => ({
    mailbox: "ok",
    subject: "Spotkanie: Automatyzacje",
    recipients: [{ address: "anna@firma-testowa.example", name: "Anna Przykładowa", blocked: null }],
    meeting_at: "2026-11-12T12:00:00Z",
    duration_minutes: 30,
    sent_at: null,
    ...overrides,
  });
  const ok = (data: InviteDraft) => ({ data, isLoading: false, error: null, isSuccess: true, refetch: vi.fn() });
  const card = (data: Handoff, viewer: "host" | "booker" = "host") =>
    render(<HandoffCard handoff={data} viewer={viewer} canEdit panel={null} onPanel={vi.fn()} />);

  it("przycisk ma tylko prowadzący przy spotkaniu z terminem, którego nie ma jeszcze w kalendarzu", () => {
    const { unmount } = card(handoff());
    expect(screen.getByRole("button", { name: "Wyślij zaproszenie" })).toBeTruthy();
    unmount();
    for (const data of [
      handoff({ from_calendar: true }),
      handoff({ invite_sent_at: "2026-11-10T10:00:00Z", from_calendar: true }),
      handoff({ meeting_at: null, phase: "no_term" }),
      handoff({ phase: "verdict" }),
    ]) {
      const view = card(data);
      expect(screen.queryByRole("button", { name: "Wyślij zaproszenie" })).toBeNull();
      view.unmount();
    }
    card(handoff(), "booker");
    expect(screen.queryByRole("button", { name: "Wyślij zaproszenie" })).toBeNull();
  });

  it("po wysłaniu karta mówi, że zaproszenie wyszło", () => {
    card(handoff({ invite_sent_at: "2026-11-10T10:00:00Z", from_calendar: true }));
    expect(screen.getByText("Zaproszenie wysłane")).toBeTruthy();
    expect(screen.queryByText("Termin z kalendarza")).toBeNull();
  });

  it("wysyła temat, adres i dopisek z kluczem jednej wysyłki", async () => {
    inviteDraft.mockReturnValue(ok(draft()));
    const onClose = vi.fn();
    render(<InviteDialog handoff={handoff()} onClose={onClose} />);
    expect((screen.getByLabelText("Do") as HTMLInputElement).value).toBe("anna@firma-testowa.example");
    fireEvent.change(screen.getByLabelText("Do"), {
      target: { value: "anna@firma-testowa.example, Jan@Firma-Testowa.example" },
    });
    fireEvent.change(screen.getByLabelText("Dopisek do zaproszenia (opcjonalnie)"), {
      target: { value: "Do zobaczenia" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Wyślij zaproszenie" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const payload = sendInvite.mock.calls[0][0];
    expect(payload).toMatchObject({
      opportunity_id: 21,
      subject: "Spotkanie: Automatyzacje",
      to: ["anna@firma-testowa.example", "jan@firma-testowa.example"],
      message: "Do zobaczenia",
    });
    expect(payload.request_id).toMatch(/^[0-9a-f-]{36}$/);
    // Drugi klik w tym samym oknie niesie ten sam klucz.
    fireEvent.click(screen.getByRole("button", { name: "Wyślij zaproszenie" }));
    await waitFor(() => expect(sendInvite).toHaveBeenCalledTimes(2));
    expect(sendInvite.mock.calls[1][0].request_id).toBe(payload.request_id);
  });

  it("adres z bazy kandydatów nie jest podpowiadany, a bez adresu nie da się wysłać", () => {
    inviteDraft.mockReturnValue(
      ok(draft({ recipients: [{ address: "ktos@poczta.example", name: "Ktoś", blocked: "candidate" }] })),
    );
    render(<InviteDialog handoff={handoff()} onClose={vi.fn()} />);
    expect((screen.getByLabelText("Do") as HTMLInputElement).value).toBe("");
    expect(screen.getByText(/jest w bazie kandydatów/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Wyślij zaproszenie" })).toHaveProperty("disabled", true);
    fireEvent.change(screen.getByLabelText("Do"), { target: { value: "to nie adres" } });
    expect(screen.getByText(/To nie jest adres/)).toBeTruthy();
  });

  it("bez połączonej skrzynki mówi, co zrobić, i nie wysyła", () => {
    inviteDraft.mockReturnValue(ok(draft({ mailbox: "missing" })));
    render(<InviteDialog handoff={handoff()} onClose={vi.fn()} />);
    expect(screen.getByRole("alert").textContent).toContain("Podłącz skrzynkę Outlook");
    expect(screen.getByRole("button", { name: "Wyślij zaproszenie" })).toHaveProperty("disabled", true);
  });

  it("odmowa serwera zostaje w oknie", async () => {
    inviteDraft.mockReturnValue(ok(draft()));
    sendInvite.mockRejectedValueOnce({
      response: { status: 502, data: { detail: "Outlook nie przyjął zaproszenia. Nic nie wyszło, spróbuj ponownie." } },
    });
    const onClose = vi.fn();
    render(<InviteDialog handoff={handoff()} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Wyślij zaproszenie" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Nic nie wyszło"));
    expect(onClose).not.toHaveBeenCalled();
  });

  it("awaria wczytania okna nie wygląda jak gotowy formularz", () => {
    inviteDraft.mockReturnValue({ data: undefined, isLoading: false, error: new Error("boom"), isSuccess: false, refetch: vi.fn() });
    render(<InviteDialog handoff={handoff()} onClose={vi.fn()} />);
    expect(screen.queryByLabelText("Temat")).toBeNull();
    expect(screen.queryByRole("button", { name: "Wyślij zaproszenie" })).toBeNull();
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

describe("opiekun w oknie „Edytuj firmę”", () => {
  it("zapisuje opiekuna bez szans w lejku i zachowuje istniejące tagi", () => {
    const company: SalesCompany = {
      id: 7,
      name: "Firma Testowa",
      legal_name: null,
      nip: null,
      krs: null,
      regon: null,
      domain: null,
      website_url: null,
      linkedin_url: null,
      industry: null,
      size_range: null,
      hq_city: null,
      hq_country: null,
      description: null,
      lifecycle_stage: "lead",
      tier: null,
      status: "active",
      tags: ["ważne", "kontakt"],
      source: null,
      parent: null,
      client: null,
      owner: { id: 11, name: "Obecny Opiekun" },
      owner_label: null,
      needs_review: false,
      open_opportunities: 0,
      open_value: "0",
      archived_at: null,
      created_at: "2026-11-01T10:00:00Z",
      updated_at: "2026-11-01T10:00:00Z",
    };
    ownerFilterOptions.mockReturnValue([
      { value: "acct:12", label: "Opiekun z lejka" },
      { value: "acct:13", label: "Opiekun z obu list" },
    ]);
    ownerCandidates.mockReturnValue({
      data: [
        { id: 13, name: "Powtórzony opiekun" },
        { id: 14, name: "Nowy Opiekun" },
      ],
    });

    render(<CompanyFormDialog open onOpenChange={vi.fn()} company={company} />);

    const owner = screen.getByLabelText("Opiekun");
    const choices = within(owner).getAllByRole("option");
    expect(owner).toHaveValue("11");
    expect(choices.map((choice) => choice.textContent)).toEqual([
      "Bez opiekuna",
      "Obecny Opiekun",
      "Opiekun z lejka",
      "Opiekun z obu list",
      "Nowy Opiekun",
    ]);
    fireEvent.change(owner, { target: { value: "14" } });
    fireEvent.change(screen.getByLabelText("Tagi (po przecinku)"), { target: { value: "ważne, kontakt, nowy" } });
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(updateCompany).toHaveBeenCalledTimes(1);
    expect(updateCompany.mock.calls[0][0]).toMatchObject({
      owner_user_id: 14,
      tags: ["ważne", "kontakt", "nowy"],
    });
  });
});

describe("mail do klienta po umówieniu (kolejka dzwonienia)", () => {
  const fill = (label: string, value: string) =>
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  const mailbox = {
    ...defaultForm,
    hosts: [
      { id: 2, name: "Prowadzący Testowy", email: "prowadzacy@nasza-firma.example" },
      { id: 4, name: "Druga Prowadząca", email: "druga@nasza-firma.example" },
    ],
    mailbox: "ok" as const,
    mailbox_address: "dzwoniacy@nasza-firma.example",
  };
  const booked = () =>
    bookMeeting.mockImplementation((_payload: unknown, options: { onSuccess: (saved: Handoff) => void }) =>
      options.onSuccess(handoff({ meeting_at: termFromFields("2026-11-12", "13:00") })),
    );
  const form = (onSaved = vi.fn()) =>
    render(
      <BookMeetingForm
        company={{ id: 7, name: "Firma Testowa" }}
        contactId={5}
        service="Automatyzacje"
        invite={{ email: "anna@firma-testowa.example" }}
        onSaved={onSaved}
        onCancel={vi.fn()}
      />,
    );

  it("szablon idzie za terminem i prowadzącym, a zapis wysyła mail z kopią do prowadzącego", async () => {
    handoffForm.mockReturnValue(mailbox);
    booked();
    const onSaved = vi.fn();
    form(onSaved);
    fill("Dzień spotkania", "2026-11-12");
    fill("Godzina spotkania", "13:00");

    // Pola formularza są w strefie przeglądarki, szablon w kalendarzu firmy: oczekiwane
    // wartości z tej samej chwili, żeby test nie zależał od strefy maszyny (CI to UTC).
    const start = termFromFields("2026-11-12", "13:00");
    const subject = bookingMailSubject(start);
    expect(screen.getByLabelText("Tytuł maila")).toHaveProperty("value", subject);
    const body = (screen.getByLabelText("Treść maila") as HTMLTextAreaElement).value;
    expect(body).toBe(bookingMailBody({ start, minutes: 30, service: "Automatyzacje", hostName: "Prowadzący Testowy" }));
    expect(body).toContain("Spotkanie poprowadzi Prowadzący Testowy (w kopii tej wiadomości).");
    expect(screen.getByText(/DW: Prowadzący Testowy <prowadzacy@nasza-firma.example>/)).toBeTruthy();
    expect(screen.getByText(/Od: dzwoniacy@nasza-firma.example/)).toBeTruthy();

    // Inny prowadzący zmienia treść, dopóki dzwoniący jej nie poprawił.
    fill("Prowadzący", "4");
    expect((screen.getByLabelText("Treść maila") as HTMLTextAreaElement).value).toContain("poprowadzi Druga Prowadząca");
    fill("Prowadzący", "2");

    fireEvent.click(screen.getByRole("button", { name: `Umów ${handoffWhen(start)} i wyślij mail` }));
    const payload = bookMeeting.mock.calls[0][0];
    expect(payload.invite_to).toBe("anna@firma-testowa.example");
    // Zaproszenie Teams prowadzącego ma własną podpowiedź, nie treść maila.
    expect(payload.invite_message).toContain("przesyłam zaproszenie na spotkanie w sprawie: Automatyzacje.");
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    const mail = sendBookingMail.mock.calls[0][0];
    expect(mail).toMatchObject({
      opportunity_id: 21,
      to: ["anna@firma-testowa.example"],
      subject,
      message: body.trim(),
      cc_host: true,
    });
    expect(typeof mail.request_id).toBe("string");
    expect(showSuccess.mock.calls[0][0]).toContain("Mail wyszedł do klienta, kopia do prowadzącego.");
  });

  it("poprawiony tytuł i treść zostają po zmianie terminu", () => {
    handoffForm.mockReturnValue(mailbox);
    form();
    fill("Tytuł maila", "Nasze spotkanie");
    fill("Treść maila", "Własna treść");
    fill("Dzień spotkania", "2026-11-13");
    fill("Godzina spotkania", "09:00");
    expect(screen.getByLabelText("Tytuł maila")).toHaveProperty("value", "Nasze spotkanie");
    expect(screen.getByLabelText("Treść maila")).toHaveProperty("value", "Własna treść");
  });

  it("mail, który nie wyszedł, zostawia zapisane spotkanie z ponowieniem albo zamknięciem bez maila", async () => {
    handoffForm.mockReturnValue(mailbox);
    booked();
    sendBookingMail.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 502, data: { detail: "Outlook nie przyjął maila. Nic nie wyszło, spróbuj ponownie." } },
    });
    const onSaved = vi.fn();
    const onBooked = vi.fn();
    render(
      <BookMeetingForm
        company={{ id: 7, name: "Firma Testowa" }}
        invite={{ email: "anna@firma-testowa.example" }}
        onBooked={onBooked}
        onSaved={onSaved}
        onCancel={vi.fn()}
      />,
    );
    fill("Dzień spotkania", "2026-11-12");
    fill("Godzina spotkania", "13:00");
    fireEvent.click(screen.getByRole("button", { name: /i wyślij mail/ }));
    // Okno wie o zapisie od razu: zamknięcie w trakcie wysyłki nie zgubi wyniku rozmowy.
    expect(onBooked).toHaveBeenCalledTimes(1);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Spotkanie zapisane: Firma Testowa");
    expect(alert.textContent).toContain("Mail do klienta nie wyszedł.");
    expect(onSaved).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Wyślij ponownie" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(bookMeeting).toHaveBeenCalledTimes(1);
    const [first, second] = sendBookingMail.mock.calls.map(([input]) => input.request_id);
    // Nowy klucz: pierwsza próba na pewno nic nie wysłała.
    expect(second).not.toBe(first);
  });

  it("„Zamknij bez maila” kończy umawianie bez drugiej próby", async () => {
    handoffForm.mockReturnValue(mailbox);
    booked();
    sendBookingMail.mockRejectedValueOnce(new Error("boom"));
    const onSaved = vi.fn();
    form(onSaved);
    fireEvent.click(screen.getByRole("button", { name: /i wyślij mail/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Zamknij bez maila" }));
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(sendBookingMail).toHaveBeenCalledTimes(1);
  });

  it("bez podłączonej skrzynki spotkanie zapisuje się bez maila", () => {
    handoffForm.mockReturnValue({ ...mailbox, mailbox: "missing", mailbox_address: null });
    booked();
    const onSaved = vi.fn();
    form(onSaved);
    expect(screen.getByText(/nie jest podłączona w Sprzedaży: spotkanie się zapisze, mail nie wyjdzie/)).toBeTruthy();
    expect(screen.getByLabelText("Wyślij mail po zapisie")).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "Zapisz bez terminu" }));
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(sendBookingMail).not.toHaveBeenCalled();
  });

  it("bez adresu klienta albo po odznaczeniu mail nie wychodzi", () => {
    handoffForm.mockReturnValue(mailbox);
    booked();
    form();
    fill("Adres e-mail klienta", "");
    expect(screen.getByText("Wpisz adres klienta: bez niego mail nie wyjdzie.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /i wyślij mail/ })).toBeNull();
    fill("Adres e-mail klienta", "anna@firma-testowa.example");
    fireEvent.click(screen.getByLabelText("Wyślij mail po zapisie"));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz bez terminu" }));
    expect(sendBookingMail).not.toHaveBeenCalled();
  });

  it("szablon czyta termin w kalendarzu firmy", () => {
    const start = "2026-11-12T12:00:00Z"; // 13:00 w Warszawie
    expect(bookingMailSubject(start)).toBe("Potwierdzenie spotkania: 12.11, godz. 13:00");
    expect(bookingMailBody({ start, minutes: 45, service: "Automatyzacje", hostName: "Prowadzący Testowy" })).toContain(
      "Potwierdzam nasze spotkanie w czwartek 12.11.2026 o 13:00 (45 min) w sprawie: Automatyzacje.",
    );
  });

  it("treść bez terminu i bez prowadzącego mówi, co przyjdzie osobno", () => {
    const body = bookingMailBody({ start: null, minutes: 30, service: "", hostName: "" });
    expect(body).toContain("Potwierdzam, że umówiliśmy spotkanie. Termin prześlemy w osobnej wiadomości.");
    expect(body).toContain("Zaproszenie w Teams przyjdzie osobno.");
    expect(body).not.toContain("poprowadzi");
  });
});

describe("zaproszenie Teams od umawiającego (decyzja 23.11.2026)", () => {
  const fill = (label: string, value: string) =>
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
  const teamsForm = {
    ...defaultForm,
    mailbox: "missing" as const,
    mailbox_address: null,
    teams_invite: true,
  };
  const booked = () =>
    bookMeeting.mockImplementation((_payload: unknown, options: { onSuccess: (saved: Handoff) => void }) =>
      options.onSuccess(handoff({ meeting_at: termFromFields("2026-11-26", "11:00") })),
    );
  const form = (onSaved = vi.fn()) =>
    render(
      <BookMeetingForm
        company={{ id: 7, name: "Firma Testowa" }}
        contactId={5}
        service="Automatyzacje"
        invite={{ email: "anna@firma-testowa.example" }}
        onSaved={onSaved}
        onCancel={vi.fn()}
      />,
    );

  it("zamiast maila: klient, prowadzący jako organizator i Ty; zapis wysyła zaproszenie", async () => {
    handoffForm.mockReturnValue(teamsForm);
    booked();
    const onSaved = vi.fn();
    form(onSaved);
    fill("Dzień spotkania", "2026-11-26");
    fill("Godzina spotkania", "11:00");

    const section = screen.getByTestId("booking-invite");
    expect(screen.queryByTestId("booking-mail")).toBeNull();
    // Własna skrzynka nie jest potrzebna: spotkanie zakłada aplikacja w kalendarzu prowadzącego.
    expect(screen.queryByText(/mail nie wyjdzie/)).toBeNull();
    expect(within(section).getByText("Prowadzący Testowy")).toBeTruthy();
    expect(within(section).getByText(/organizator: spotkanie w jego kalendarzu/)).toBeTruthy();
    expect(screen.getByLabelText("Tytuł zaproszenia")).toHaveProperty(
      "value",
      "B2Bnetwork × Firma Testowa: Automatyzacje",
    );
    const body = (screen.getByLabelText("Treść zaproszenia") as HTMLTextAreaElement).value;
    expect(body).toBe(teamsInviteBody({ service: "Automatyzacje", hostName: "Prowadzący Testowy" }));

    fill("Prowadzący", "4");
    expect((screen.getByLabelText("Treść zaproszenia") as HTMLTextAreaElement).value).toContain(
      "Poprowadzi je Druga Prowadząca.",
    );
    fill("Prowadzący", "2");
    expect(screen.getByText(/NEXUS założy spotkanie Teams w kalendarzu: Prowadzący Testowy \(organizator\), klient i Ty/)).toBeTruthy();

    const start = termFromFields("2026-11-26", "11:00");
    fireEvent.click(screen.getByRole("button", { name: `Umów ${handoffWhen(start)} i wyślij zaproszenie Teams` }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(sendBookingMail).not.toHaveBeenCalled();
    const sent = sendBookingInvite.mock.calls[0][0];
    expect(sent).toMatchObject({
      opportunity_id: 21,
      to: ["anna@firma-testowa.example"],
      subject: "B2Bnetwork × Firma Testowa: Automatyzacje",
      message: body.trim(),
      include_me: true,
    });
    expect(typeof sent.request_id).toBe("string");
    expect(showSuccess.mock.calls[0][0]).toContain("Zaproszenie Teams wyszło z kalendarza: Prowadzący Testowy.");
  });

  it("odznaczone „Ty” nie dodaje umawiającego do spotkania", async () => {
    handoffForm.mockReturnValue(teamsForm);
    booked();
    form();
    fill("Dzień spotkania", "2026-11-26");
    fill("Godzina spotkania", "11:00");
    fireEvent.click(screen.getByLabelText("Dodaj mnie do spotkania"));
    expect(screen.getByText(/\(organizator\), klient\./)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /i wyślij zaproszenie Teams/ }));
    await waitFor(() => expect(sendBookingInvite).toHaveBeenCalledTimes(1));
    expect(sendBookingInvite.mock.calls[0][0].include_me).toBe(false);
  });

  it("bez terminu zaproszenie nie wychodzi, spotkanie się zapisuje", () => {
    handoffForm.mockReturnValue(teamsForm);
    booked();
    const onSaved = vi.fn();
    form(onSaved);
    expect(screen.getByText("Wpisz dzień i godzinę: bez terminu zaproszenie nie wyjdzie.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Zapisz bez terminu" }));
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(sendBookingInvite).not.toHaveBeenCalled();
  });

  it("zaproszenie, które nie wyszło, zostawia spotkanie z ponowieniem albo zamknięciem bez zaproszenia", async () => {
    handoffForm.mockReturnValue(teamsForm);
    booked();
    sendBookingInvite.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 409,
        data: { detail: "NEXUS nie ma dostępu do kalendarza tego prowadzącego. Nic nie wyszło." },
      },
    });
    const onSaved = vi.fn();
    form(onSaved);
    fill("Dzień spotkania", "2026-11-26");
    fill("Godzina spotkania", "11:00");
    fireEvent.click(screen.getByRole("button", { name: /i wyślij zaproszenie Teams/ }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Spotkanie zapisane: Firma Testowa");
    expect(alert.textContent).toContain("Zaproszenie Teams nie wyszło.");
    expect(alert.textContent).toContain("nie ma dostępu do kalendarza");
    expect(onSaved).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Wyślij ponownie" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    const [first, second] = sendBookingInvite.mock.calls.map(([input]) => input.request_id);
    expect(second).not.toBe(first);
  });

  it("„Zamknij bez zaproszenia” kończy umawianie", async () => {
    handoffForm.mockReturnValue(teamsForm);
    booked();
    sendBookingInvite.mockRejectedValueOnce(new Error("boom"));
    const onSaved = vi.fn();
    form(onSaved);
    fill("Dzień spotkania", "2026-11-26");
    fill("Godzina spotkania", "11:00");
    fireEvent.click(screen.getByRole("button", { name: /i wyślij zaproszenie Teams/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Zamknij bez zaproszenia" }));
    expect(onSaved).toHaveBeenCalledTimes(1);
    expect(sendBookingInvite).toHaveBeenCalledTimes(1);
  });

  it("bez aplikacji w Microsoft 365 formularz zostaje przy mailu", () => {
    handoffForm.mockReturnValue({ ...teamsForm, teams_invite: false, mailbox: "ok" });
    form();
    expect(screen.getByTestId("booking-mail")).toBeTruthy();
    expect(screen.queryByTestId("booking-invite")).toBeNull();
  });

  it("tytuł bez firmy i usługi ma zapas", () => {
    expect(teamsInviteSubject("", "")).toBe("Spotkanie z B2Bnetwork");
    expect(teamsInviteSubject("Firma", "")).toBe("B2Bnetwork × Firma");
    expect(teamsInviteBody({ service: "", hostName: "" })).toBe(
      "Dzień dobry,\n\ndziękuję za rozmowę. Zapraszam na spotkanie w Teams.\n\nPozdrawiam",
    );
  });
});
