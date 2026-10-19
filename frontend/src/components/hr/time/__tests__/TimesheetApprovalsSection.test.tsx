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
    mocks.get.mockResolvedValue({ data: { year: 2031, month: 3, items } });
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

  it("osoba bez zespołu i bez Płac nie widzi sekcji", () => {
    const { container } = renderSection({});
    expect(container).toBeEmptyDOMElement();
    expect(mocks.get).not.toHaveBeenCalled();
  });

  it("przełożony widzi zespół, zaślepkę i decyzje tylko przy wysłanym", async () => {
    renderSection({ is_manager: true, direct_reports: 3 });

    const submitted = await screen.findByTestId("queue-21");
    expect(within(submitted).getByText("Do akceptacji")).toBeInTheDocument();
    expect(within(submitted).getByRole("button", { name: "Akceptuj" })).toBeInTheDocument();
    expect(within(submitted).getByText("168")).toBeInTheDocument();
    const missing = screen.getByTestId("queue-22");
    expect(within(missing).getByText("Nie założony")).toBeInTheDocument();
    expect(within(missing).queryByRole("button", { name: "Akceptuj" })).toBeNull();
    const approved = screen.getByTestId("queue-23");
    expect(within(approved).getByRole("button", { name: "Cofnij akceptację" })).toBeInTheDocument();
    // ZIP jest dla Płac i Kadr, nie dla przełożonego.
    expect(screen.queryByRole("button", { name: /Pobierz ZIP/ })).toBeNull();
  });

  it("akceptacja wysyła decyzję dla właściwego timesheetu", async () => {
    mocks.post.mockResolvedValue({ data: header(301, "approved") });
    renderSection({ is_manager: true, direct_reports: 3 });

    const row = await screen.findByTestId("queue-21");
    fireEvent.click(within(row).getByRole("button", { name: "Akceptuj" }));
    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/hr/time/timesheets/301/approve", undefined),
    );
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

  it("Płace bez zespołu dostają paczkę ZIP i CSV całego miesiąca", async () => {
    renderSection({ payroll: true });
    expect(screen.getByRole("button", { name: /Pobierz ZIP/ })).toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Eksport CSV" }));
    const dialog = await screen.findByRole("dialog");
    // Bez kolejki nie ma kogo wybrać — tylko cały zespół za miesiąc.
    expect(within(dialog).queryByRole("radio")).toBeNull();
    expect(within(dialog).getByText(/Wszystkie wpisy za marzec 2031/)).toBeInTheDocument();
  });

  it("przełożony eksportuje CSV osoby z zespołu, bez całego zespołu", async () => {
    renderSection({ is_manager: true, direct_reports: 3 });
    await screen.findByTestId("queue-21");
    fireEvent.click(screen.getByRole("button", { name: "Eksport CSV" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("radio", { name: /Cały zespół/ })).toBeNull();
    expect(within(dialog).getByLabelText("Od miesiąca")).toHaveValue("2031-03");
  });
});
