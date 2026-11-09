/**
 * „Mój dzień”: kolejka z API, prawdziwe przyciski w wierszach, rama i przekierowanie.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MyDay, MyDayRow } from "@/lib/api/sales";

const myDay = vi.fn();
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

beforeEach(() => {
  vi.clearAllMocks();
  canEdit = true;
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
});

describe("przyciski wiersza", () => {
  it("Zadzwoniłem zapisuje wynik przy szansie i krok", async () => {
    logCall.mockImplementation((_input, { onSuccess }) => onSuccess());
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    fireEvent.click(screen.getByRole("button", { name: "Dodzwoniłem" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(createActivity).toHaveBeenCalled());
    expect(logCall.mock.calls[0][0]).toEqual({ opportunity_id: 21, outcome: "connected", contact_id: 3 });
    const step = createActivity.mock.calls[0][0];
    expect(step.opportunity_id).toBe(21);
    expect(step.kind).toBe("task");
    expect(step.subject).toBeTruthy();
  });

  it("zapis bez wyboru wyniku jest niemożliwy", () => {
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    expect((screen.getByRole("button", { name: "Zapisz" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("telefon przy zadaniu firmy idzie trasą firmy i zamyka zadanie", async () => {
    logCompanyCall.mockImplementation((_input, { onSuccess }) => onSuccess());
    const overdue = row({ key: "overdue-5", section: "overdue", opportunity: null, activity_id: 5, kind: "task", amount: null });
    render(<MyDayRowItem row={overdue} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    fireEvent.click(screen.getByRole("button", { name: "Brak odpowiedzi" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
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

  it("błąd serwera wraca jako komunikat i wiersz zostaje", async () => {
    logCall.mockImplementation((_input, { onError }) => onError(new Error("boom")));
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    fireEvent.click(screen.getByRole("button", { name: "Dodzwoniłem" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(createActivity).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Zapisz" })).toBeTruthy();
  });

  it("nieudany krok po zapisanej rozmowie zamyka panel, żeby rozmowa się nie zdublowała", async () => {
    logCall.mockImplementation((_input, { onSuccess }) => onSuccess());
    createActivity.mockImplementation((_input, { onError }) => onError(new Error("boom")));
    render(<MyDayRowItem row={row()} canEdit />);
    fireEvent.click(screen.getByText("Zadzwoniłem"));
    fireEvent.click(screen.getByRole("button", { name: "Dodzwoniłem" }));
    fireEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(showError).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: "Zapisz" })).toBeNull();
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
