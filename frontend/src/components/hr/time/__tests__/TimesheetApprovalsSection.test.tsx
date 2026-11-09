import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { HrConfig } from "@/lib/api/hr";
import type { TeamQueueItem } from "@/lib/api/hr-time";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  toast: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: mocks.get, post: mocks.post, put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast: mocks.toast }),
}));

vi.mock("@/components/v2/modals/ConfirmV2", () => ({
  useConfirmV2: () => ({ askConfirm: async () => true, confirmDialog: null }),
}));

import { TimesheetApprovalsSection } from "../TimesheetApprovalsSection";

const modules = {
  people: true,
  leave: true,
  time: true,
  payroll: false,
  lifecycle: false,
  care: false,
  cases: false,
  equipment: false,
  settlements: false,
  approvals: false,
  back_office: false,
};

function config(me: Partial<HrConfig["me"]>): HrConfig {
  return {
    program: true,
    modules,
    open_modules: modules,
    me: {
      has_profile: true,
      employment_status: "active",
      is_manager: false,
      direct_reports: 0,
      is_admin: false,
      people_admin: false,
      payroll: false,
      equipment: false,
      cases: false,
      ...me,
    },
  };
}

function header(id: number, status: "draft" | "submitted" | "approved") {
  return {
    id,
    status,
    submitted_at: status === "draft" ? null : "2031-04-02T08:00:00Z",
    return_note: null,
    returned_at: null,
    approved_at: status === "approved" ? "2031-04-03T08:00:00Z" : null,
    approved_by_name: null,
    payroll_locked: false,
    pdf_hash: null,
  };
}

const items: TeamQueueItem[] = [
  {
    user_id: 21,
    name: "Ewa Przykładowa",
    job_title: "Rekruterka",
    timesheet: header(301, "submitted"),
    status: "submitted",
    hours: 168,
    overtime_hours: 2,
    absence_days: 1,
    can_decide: true,
  },
  {
    user_id: 22,
    name: "Julia Testowa",
    job_title: null,
    timesheet: null,
    status: "missing",
    hours: 0,
    overtime_hours: 0,
    absence_days: 0,
    can_decide: true,
  },
  {
    user_id: 23,
    name: "Tomasz Fikcyjny",
    job_title: null,
    timesheet: header(303, "approved"),
    status: "approved",
    hours: 160,
    overtime_hours: 0,
    absence_days: 0,
    can_decide: true,
  },
];

const draftItem: TeamQueueItem = {
  user_id: 24,
  name: "Ola Przykładowa",
  job_title: null,
  timesheet: header(304, "draft"),
  status: "draft",
  hours: 72,
  overtime_hours: 0,
  absence_days: 0,
  can_decide: true,
};

function renderSection(me: Partial<HrConfig["me"]>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TimesheetApprovalsSection config={config(me)} initialMonth={{ year: 2031, month: 3 }} />
    </QueryClientProvider>,
  );
}

describe("TimesheetApprovalsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.get.mockResolvedValue({ data: { year: 2031, month: 3, norm_hours: 176, items } });
  });

  it("link z powiadomienia na otwartym ekranie zmienia miesiąc i otwiera podgląd osoby", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const me = config({ is_manager: true, direct_reports: 3 });
    const view = render(
      <QueryClientProvider client={client}>
        <TimesheetApprovalsSection config={me} initialMonth={{ year: 2031, month: 3 }} />
      </QueryClientProvider>,
    );
    await screen.findByTestId("queue-21");
    // Miękka nawigacja App Routera: ten sam komponent, nowe parametry adresu.
    view.rerender(
      <QueryClientProvider client={client}>
        <TimesheetApprovalsSection
          config={me}
          initialMonth={{ year: 2031, month: 4 }}
          focusUserId={21}
        />
      </QueryClientProvider>,
    );
    await waitFor(() => {
      const urls = mocks.get.mock.calls.map(([url]) => url);
      expect(urls).toContain("/api/hr/time/team/2031/4");
      expect(urls).toContain("/api/hr/time/team/21/2031/4");
    });
  });

  it("osoba bez zespołu i bez Rozliczeń nie widzi sekcji", () => {
    const { container } = renderSection({});
    expect(container).toBeEmptyDOMElement();
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("koordynator widzi zespół, zaślepkę i decyzje tylko przy wysłanym", async () => {
    renderSection({ is_manager: true, direct_reports: 3 });

    const submitted = await screen.findByTestId("queue-21");
    expect(within(submitted).getByText("Do akceptacji")).toBeInTheDocument();
    expect(within(submitted).getByRole("button", { name: "Potwierdź" })).toBeInTheDocument();
    expect(within(submitted).getByText("168 / 176 h")).toBeInTheDocument();
    const missing = screen.getByTestId("queue-22");
    expect(within(missing).getByText("Nie założony")).toBeInTheDocument();
    expect(within(missing).queryByRole("button", { name: "Potwierdź" })).toBeNull();
    const approved = screen.getByTestId("queue-23");
    expect(within(approved).getByRole("button", { name: "Cofnij akceptację" })).toBeInTheDocument();
    // ZIP jest dla Płac i Kadr, nie dla przełożonego.
    expect(screen.queryByRole("button", { name: /Pobierz ZIP/ })).toBeNull();
  });

  it("akceptacja wysyła decyzję dla właściwego raportu godzin", async () => {
    mocks.post.mockResolvedValue({ data: header(301, "approved") });
    renderSection({ is_manager: true, direct_reports: 3 });

    const row = await screen.findByTestId("queue-21");
    fireEvent.click(within(row).getByRole("button", { name: "Potwierdź" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/time/timesheets/301/approve", undefined),
    );
  });

  it("szkic osoby, która odeszła: „Potwierdź za osobę” wysyła decyzję dla jej raportu", async () => {
    mocks.get.mockResolvedValue({
      data: {
        year: 2031,
        month: 3,
        norm_hours: 168,
        items: [{ ...draftItem, can_confirm_for_person: true }],
      },
    });
    mocks.post.mockResolvedValue({ data: header(304, "approved") });
    renderSection({ is_manager: true, direct_reports: 1 });
    fireEvent.click(await screen.findByRole("button", { name: "Potwierdź za osobę" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith(
        "/api/hr/time/timesheets/304/confirm-for-person",
        undefined,
      ),
    );
    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith("Raport godzin potwierdzony za osobę", "success"),
    );
  });

  it("„Potwierdź za osobę” nie ma przy pustym szkicu ani u osoby, która pracuje", async () => {
    mocks.get.mockResolvedValue({
      data: {
        year: 2031,
        month: 3,
        norm_hours: 168,
        items: [
          { ...draftItem, can_confirm_for_person: true, hours: 0 },
          { ...draftItem, user_id: 25, name: "Julia Testowa", timesheet: header(305, "draft") },
        ],
      },
    });
    renderSection({ is_manager: true, direct_reports: 1 });
    await screen.findByText("Julia Testowa");
    expect(screen.queryByRole("button", { name: "Potwierdź za osobę" })).toBeNull();
    // Przypomnienie tylko u osoby w pracy: kto odszedł, nie ma konta.
    expect(screen.getAllByRole("button", { name: "Przypomnij" })).toHaveLength(1);
  });

  it("anulowany zwrot nie zostawia notatki na następne otwarcie", async () => {
    // Audyt 19.10.2026: „Anuluj” zamykał okno, a notatka zostawała i trafiała
    // do powiadomienia następnej zwracanej osoby.
    renderSection({ people_admin: true });
    const row = await screen.findByTestId("queue-21");
    fireEvent.click(within(row).getByRole("button", { name: "Zwróć" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Co trzeba poprawić"), {
      target: { value: "Uwaga dla innej osoby" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    fireEvent.click(within(row).getByRole("button", { name: "Zwróć" }));
    const again = await screen.findByRole("dialog");
    expect(within(again).getByLabelText("Co trzeba poprawić")).toHaveValue("");
  });

  it("zwrot wymaga notatki i wysyła ją", async () => {
    mocks.post.mockResolvedValue({ data: header(301, "draft") });
    renderSection({ people_admin: true });

    const row = await screen.findByTestId("queue-21");
    fireEvent.click(within(row).getByRole("button", { name: "Zwróć" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Zwróć" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Napisz, co trzeba poprawić.",
    );
    expect(mocks.post).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText("Co trzeba poprawić"), {
      target: { value: "Brakuje opisu 5 marca" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Zwróć" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/time/timesheets/301/return", {
        note: "Brakuje opisu 5 marca",
      }),
    );
  });

  it("Rozliczenia bez zespołu dostają paczkę ZIP i CSV całego miesiąca", async () => {
    renderSection({ payroll: true });
    expect(screen.getByRole("button", { name: /Pobierz ZIP/ })).toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Eksport CSV" }));
    const dialog = await screen.findByRole("dialog");
    // Bez kolejki nie ma kogo wybrać — tylko cały zespół za miesiąc.
    expect(within(dialog).queryByRole("radio")).toBeNull();
    expect(within(dialog).getByText(/Wszystkie wpisy za marzec 2031/)).toBeInTheDocument();
  });

  it("koordynator eksportuje CSV osoby z zespołu, bez całego zespołu", async () => {
    renderSection({ is_manager: true, direct_reports: 3 });
    await screen.findByTestId("queue-21");
    fireEvent.click(screen.getByRole("button", { name: "Eksport CSV" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("radio", { name: /Cały zespół/ })).toBeNull();
    expect(within(dialog).getByLabelText("Od miesiąca")).toHaveValue("2031-03");
  });

  it("„Przypomnij” przy braku i szkicu wysyła przypomnienie za ten miesiąc", async () => {
    mocks.get.mockResolvedValue({
      data: { year: 2031, month: 3, norm_hours: 176, items: [...items, draftItem] },
    });
    mocks.post.mockResolvedValue({
      data: { target: "person", status: "missing", sent: true, already_today: false },
    });
    renderSection({ is_manager: true, direct_reports: 4 });

    const missing = await screen.findByTestId("queue-22");
    expect(within(screen.getByTestId("queue-24")).getByRole("button", { name: "Przypomnij" })).toBeInTheDocument();
    // „Do akceptacji” decyduje akceptujący — tam zostaje „Akceptuj”, bez „Przypomnij”.
    expect(within(screen.getByTestId("queue-21")).queryByRole("button", { name: "Przypomnij" })).toBeNull();
    expect(within(screen.getByTestId("queue-23")).queryByRole("button", { name: "Przypomnij" })).toBeNull();

    fireEvent.click(within(missing).getByRole("button", { name: "Przypomnij" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/time/remind/22/2031/3"),
    );
    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith("Przypomnienie poszło do: Julia Testowa.", "success"),
    );
  });

  it("odmowa „Przypomnij” (409) pokazuje komunikat serwera", async () => {
    mocks.post.mockRejectedValue({
      isAxiosError: true,
      response: { status: 409, data: { detail: "Miesiąc jest zamknięty w rozliczeniach." } },
    });
    renderSection({ is_manager: true, direct_reports: 3 });

    const missing = await screen.findByTestId("queue-22");
    fireEvent.click(within(missing).getByRole("button", { name: "Przypomnij" }));
    await waitFor(() =>
      expect(mocks.toast).toHaveBeenCalledWith("Miesiąc jest zamknięty w rozliczeniach.", "error"),
    );
  });

  it("godziny wobec normy, brak raportu bez godzin", async () => {
    renderSection({ is_manager: true, direct_reports: 3 });

    expect(await screen.findByText("160 / 176 h")).toBeInTheDocument();
    const missing = screen.getByTestId("queue-22");
    expect(within(missing).queryByText(/\/ 176 h/)).toBeNull();
  });

  it("długa lista jest zwinięta: najpierw brak raportu i do akceptacji, potem „Pokaż wszystkie”", async () => {
    const many: TeamQueueItem[] = [
      ...items,
      ...Array.from({ length: 5 }, (_, index) => ({
        ...draftItem,
        user_id: 30 + index,
        name: `Osoba Fikcyjna ${index + 1}`,
      })),
    ];
    mocks.get.mockResolvedValue({ data: { year: 2031, month: 3, norm_hours: 176, items: many } });
    renderSection({ is_manager: true, direct_reports: many.length });

    await screen.findByTestId("queue-22");
    const order = screen.getAllByTestId(/^queue-/).map((row) => row.dataset.testid);
    expect(order).toEqual(["queue-22", "queue-21", "queue-30", "queue-31", "queue-32"]);
    // Zaakceptowany jest na końcu listy — w zwiniętej go nie ma.
    expect(screen.queryByTestId("queue-23")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Pokaż wszystkie (8)" }));
    expect(screen.getAllByTestId(/^queue-/)).toHaveLength(8);
    expect(screen.getByTestId("queue-23")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Zwiń" }));
    expect(screen.getAllByTestId(/^queue-/)).toHaveLength(5);
  });

  it("chip statusu zawęża kolejkę i liczy każdy status", async () => {
    renderSection({ is_manager: true, direct_reports: 3 });
    await screen.findByTestId("queue-21");
    const statuses = screen.getByRole("group", { name: "Status raportu" });
    expect(within(statuses).getByRole("button", { name: /^Wszystkie/ })).toHaveTextContent("3");
    expect(within(statuses).getByRole("button", { name: /^Szkic/ })).toHaveTextContent("0");

    fireEvent.click(within(statuses).getByRole("button", { name: /^Do akceptacji/ }));
    expect(screen.getByTestId("queue-21")).toBeInTheDocument();
    expect(screen.queryByTestId("queue-22")).toBeNull();
    expect(screen.queryByTestId("queue-23")).toBeNull();

    fireEvent.click(within(statuses).getByRole("button", { name: /^Szkic/ }));
    expect(screen.getByText("W tym miesiącu nikt nie ma statusu „Szkic”.")).toBeInTheDocument();

    fireEvent.click(within(statuses).getByRole("button", { name: /^Wszystkie/ }));
    expect(screen.getByTestId("queue-22")).toBeInTheDocument();
  });

  it("wybrany status pokazuje wszystkich, bez zwijania do 5", async () => {
    const many = Array.from({ length: 8 }, (_, index) => ({ ...items[0], user_id: 100 + index }));
    mocks.get.mockResolvedValue({ data: { year: 2031, month: 3, norm_hours: 176, items: [...many, items[1]] } });
    renderSection({ is_manager: true, direct_reports: 9 });
    await screen.findByTestId("queue-100");
    expect(screen.getAllByTestId(/^queue-/)).toHaveLength(5);

    fireEvent.click(screen.getByRole("button", { name: /^Do akceptacji/ }));
    expect(screen.getAllByTestId(/^queue-/)).toHaveLength(8);
    expect(screen.queryByRole("button", { name: /Pokaż wszystkie/ })).toBeNull();
  });

  describe("cofnięcie nieobecności w podglądzie raportu", () => {
    const leave = { status: "approved", fraction: 1, full: true, paid_work: false, paid_hours: 0, label: "Nieobecność" };
    const monthDay = (date: string, withLeave: boolean) => ({
      date,
      weekday: 1,
      is_weekend: false,
      holiday: null,
      day_off: null,
      working_day: true,
      location: withLeave ? null : "onsite",
      location_source: null,
      attendance_status: null,
      attendance_note: null,
      leave: withLeave ? leave : null,
      entries: [],
      hours: 0,
      capacity: withLeave ? null : 8,
      overtime_hours: 0,
    });
    const month = {
      user_id: 21,
      name: "Ewa Przykładowa",
      year: 2031,
      month: 3,
      employment_type: "zlecenie",
      timesheet: header(301, "submitted"),
      days: [monthDay("2031-03-10", false), monthDay("2031-03-11", true), monthDay("2031-03-12", true)],
      totals: { work_hours: 0, leave_paid_hours: 0, overtime_hours: 0, leave_days: 2, working_days: 3, norm_hours: 24, days_missing: 1 },
    };
    const term = {
      id: "t-1",
      user_id: 21,
      user_name: "Ewa Przykładowa",
      leave_type: "vacation",
      leave_type_label: "Nieobecność",
      status: "approved",
      start_date: "2031-03-11",
      end_date: "2031-03-12",
      half_day: null,
      days_total: "2",
      employment_type: "zlecenie",
      is_report: true,
    };

    async function openPreview(me: Partial<HrConfig["me"]>) {
      mocks.get.mockImplementation(async (url: string) => {
        if (url === "/api/hr/time/team/21/2031/3") return { data: month };
        if (url === "/api/hr/leave/approvals/history") return { data: { items: [term] } };
        return { data: { year: 2031, month: 3, norm_hours: 176, items } };
      });
      renderSection(me);
      const row = await screen.findByTestId("queue-21");
      fireEvent.click(within(row).getByRole("button", { name: "Podgląd" }));
      return screen.findByTestId("day-2031-03-11");
    }
    const historyCalls = () =>
      mocks.get.mock.calls.filter(([url]) => url === "/api/hr/leave/approvals/history");

    it("admin cofa cały termin z powodem; przycisk stoi raz", async () => {
      mocks.post.mockResolvedValue({ data: { ...term, status: "cancelled" } });
      const first = await openPreview({ is_admin: true, leave_approver: true });
      const button = await within(first).findByRole("button", { name: /^Cofnij/ });
      expect(button).toHaveTextContent("Cofnij 11–12.03.2031");
      expect(within(screen.getByTestId("day-2031-03-12")).queryByRole("button")).toBeNull();

      fireEvent.click(button);
      const dialog = await screen.findByRole("dialog", { name: /Cofnąć nieobecność/ });
      expect(dialog).toHaveTextContent("Czeka na akceptację");
      fireEvent.click(within(dialog).getByRole("button", { name: "Cofnij nieobecność" }));
      expect(await within(dialog).findByText(/Podaj powód/)).toBeInTheDocument();
      expect(mocks.post).not.toHaveBeenCalled();

      fireEvent.change(within(dialog).getByLabelText(/Powód/), { target: { value: "Pomyłka, pracowała" } });
      fireEvent.click(within(dialog).getByRole("button", { name: "Cofnij nieobecność" }));
      await waitFor(() =>
        expect(mocks.post).toHaveBeenCalledWith("/api/hr/leave/approvals/t-1/cancel", {
          reason: "Pomyłka, pracowała",
        }),
      );
    });

    it("koordynator bez Administracji współpracy nie cofa zgłoszenia z B2B i zlecenia (D5)", async () => {
      const first = await openPreview({ is_manager: true, direct_reports: 3, leave_approver: true });
      await waitFor(() => expect(historyCalls()).toHaveLength(1));
      expect(within(first).queryByRole("button")).toBeNull();
    });

    it("koordynator cofa wniosek z umowy o pracę", async () => {
      term.is_report = false;
      try {
        const first = await openPreview({ is_manager: true, direct_reports: 3, leave_approver: true });
        expect(await within(first).findByRole("button", { name: /^Cofnij/ })).toBeInTheDocument();
      } finally {
        term.is_report = true;
      }
    });

    it("same „Raporty godzin” bez kolejki nieobecności nie pytają o historię", async () => {
      const first = await openPreview({ timesheets: true, leave_approver: false });
      expect(within(first).queryByRole("button")).toBeNull();
      expect(historyCalls()).toHaveLength(0);
    });

    it("osoba poza decyzją patrzącego nie ma przycisku ani zapytania", async () => {
      const blocked = items.map((item) => (item.user_id === 21 ? { ...item, can_decide: false } : item));
      mocks.get.mockImplementation(async (url: string) => {
        if (url === "/api/hr/time/team/21/2031/3") return { data: month };
        return { data: { year: 2031, month: 3, norm_hours: 176, items: blocked } };
      });
      renderSection({ is_admin: true, leave_approver: true });
      const row = await screen.findByTestId("queue-21");
      fireEvent.click(within(row).getByRole("button", { name: "Podgląd" }));
      const first = await screen.findByTestId("day-2031-03-11");
      expect(within(first).queryByRole("button")).toBeNull();
      expect(historyCalls()).toHaveLength(0);
    });
  });

  it("krótka lista nie ma „Pokaż wszystkie”", async () => {
    renderSection({ is_manager: true, direct_reports: 3 });
    await screen.findByTestId("queue-21");
    expect(screen.queryByRole("button", { name: /Pokaż wszystkie/ })).toBeNull();
  });
});
