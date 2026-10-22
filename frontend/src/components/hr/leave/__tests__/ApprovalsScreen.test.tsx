/**
 * „Ludzie → Akceptacje” jako jedna lista (makieta zatwierdzona 22.10.2026):
 * chipy rodzaju zamiast przełącznika „Co akceptujesz”, „Czeka | Zdecydowane”,
 * linki z powiadomień (`?tab=consents&request=…`, `?kind=timesheet…`) i awaria
 * zapytania, która nie wygląda jak pusta skrzynka. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { hrConfig } from "@/app/preview/hr-fixtures";
import type { HrConfig } from "@/lib/api/hr";
import { approvalKeys, type ApprovalRequestRow } from "@/lib/api/hr-approvals";
import { leaveKeys, type LeaveRequestRow, type PendingLeaveRow } from "@/lib/api/hr-leave";
import { timeKeys } from "@/lib/api/hr-time";
import { warsawToday } from "@/lib/warsaw-date";

import { ApprovalsScreen } from "../ApprovalsScreen";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/people/approvals",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));

vi.setConfig({ testTimeout: 20_000 });

// Żadne zapytanie nie wychodzi: wszystko jest zasiane, a niezasiane pada od razu.
const request = vi
  .spyOn(Axios.prototype, "request")
  .mockImplementation(() => Promise.reject(new Error("offline")));

const MANAGER: HrConfig = (() => {
  const config = hrConfig({ is_manager: true, direct_reports: 4, is_admin: true });
  const open = { ...config.open_modules, approvals: true };
  return { ...config, modules: open, open_modules: open };
})();

function leave(id: string, name: string, created: string, extra: Partial<PendingLeaveRow> = {}): PendingLeaveRow {
  return {
    id,
    user_id: 900 + Number(id.replace(/\D/g, "")),
    user_name: name,
    leave_type: "vacation",
    leave_type_label: "Urlop wypoczynkowy",
    status: "pending",
    start_date: "2026-11-16",
    end_date: "2026-11-18",
    half_day: null,
    days_total: "3",
    paid_days: "3",
    unpaid_days: "0",
    note: null,
    substitute_user_id: null,
    substitute_name: null,
    forward_mail_consent: false,
    oof_internal_message: null,
    oof_external_message: null,
    decided_by_name: null,
    decided_at: null,
    decision_note: null,
    source: "self",
    created_at: created,
    can_cancel: false,
    department: "Rekrutacja",
    manager_name: "Marta Fikcyjna",
    work_total: 0,
    work_by_kind: [],
    department_absent: [],
    type_visible: true,
    can_decide: true,
    ...extra,
  };
}

function consent(id: number, title: string, submitted: string, extra: Partial<ApprovalRequestRow> = {}): ApprovalRequestRow {
  return {
    id,
    kind: "trip",
    kind_label: "Delegacja",
    status: "pending_final",
    status_label: "Czeka na zatwierdzającego",
    title,
    purpose: "Warsztat z hiring managerem.",
    amount: "800.00",
    decided_amount: null,
    currency: "PLN",
    amount_basis: "gross",
    recurrence: "once",
    amount_text: "800 zł brutto",
    payer: "reimbursement",
    link_url: null,
    needed_by: null,
    starts_on: null,
    ends_on: null,
    beneficiary_user_id: null,
    beneficiary_name: null,
    payout_year: null,
    payout_month: null,
    requester_user_id: 3,
    requester_name: "Tomasz Podglądowy",
    supervisor_user_id: null,
    supervisor_name: null,
    needs_final: true,
    final_approver_names: [],
    endorsed_by_name: null,
    endorsed_at: null,
    endorse_note: null,
    decided_by_name: null,
    decided_at: null,
    decision_note: null,
    decision_channel: null,
    bonus_id: null,
    submitted_at: submitted,
    can_decide: true,
    decides_as: "final",
    can_edit: false,
    can_withdraw: false,
    context: null,
    ...extra,
  };
}

const PENDING = [
  leave("lv-1", "Kamil Testowy", "2026-10-18T09:00:00+02:00"),
  leave("lv-2", "Julia Próbna", "2026-10-20T09:00:00+02:00"),
];
const REPORTED = [
  leave("lv-3", "Ola Przykładowa", "2026-10-19T09:00:00+02:00", {
    status: "approved",
    is_report: true,
    leave_type_label: "Przerwa w świadczeniu usług",
    can_report_conflict: true,
  }),
];
const CONSENTS = [
  consent(1, "Gdańsk — warsztat", "2026-10-19T07:00:00Z"),
  consent(2, "Licencja edytora", "2026-10-21T07:00:00Z"),
  consent(3, "Prezent dla klienta", "2026-10-21T08:00:00Z", { needed_by: warsawToday(), kind: "gift", kind_label: "Prezent" }),
];

function seed({ pending = true }: { pending?: boolean } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  if (pending) {
    client.setQueryData(leaveKeys.pending, { items: PENDING, total: PENDING.length, covering: [], reported: REPORTED });
  }
  client.setQueryData(approvalKeys.list("inbox"), CONSENTS);
  for (const row of CONSENTS) client.setQueryData(approvalKeys.detail(row.id), row);
  client.setQueryData(approvalKeys.topups, []);
  return client;
}

function open(search: string, client = seed()) {
  window.history.replaceState({}, "", `/people/approvals${search}`);
  return render(
    <QueryClientProvider client={client}>
      <ApprovalsScreen config={MANAGER} />
    </QueryClientProvider>,
  );
}

const chip = (name: RegExp) =>
  within(screen.getByRole("group", { name: "Rodzaj spraw" })).getByRole("button", { name });

beforeEach(() => {
  request.mockClear();
});
afterEach(() => window.history.replaceState({}, "", "/"));

describe("Akceptacje — jedna lista", () => {
  it("„Wszystko”: pilna zgoda, potem nieobecności i zgody od najstarszych, do wiadomości; bez „Co akceptujesz”", async () => {
    open("");
    expect(screen.queryByRole("radiogroup", { name: "Co akceptujesz" })).toBeNull();
    expect(chip(/^Wszystko/)).toHaveAttribute("aria-pressed", "true");
    expect(chip(/^Wszystko/)).toHaveTextContent("6");
    expect(chip(/^Nieobecności/)).toHaveTextContent("2");
    expect(chip(/^Zgody/)).toHaveTextContent("3");
    expect(chip(/^Do wiadomości/)).toHaveTextContent("1");
    expect(chip(/^Raporty godzin/)).toBeInTheDocument();

    const urgent = screen.getByRole("list", { name: "Potrzebne do jutra" });
    expect(within(urgent).getByText("Prezent dla klienta")).toBeInTheDocument();
    const decide = screen.getByRole("list", { name: "Do decyzji" });
    const order = within(decide)
      .getAllByRole("button")
      .map((button) => button.textContent ?? "");
    expect(order.map((text) => text.match(/Kamil|Julia|Gdańsk|Licencja/)?.[0])).toEqual([
      "Kamil",
      "Gdańsk",
      "Julia",
      "Licencja",
    ]);
    const info = screen.getByRole("list", {
      name: "Zgłoszone przerwy i nieobecności (B2B, zlecenie) — do wiadomości",
    });
    expect(within(info).getByRole("button", { name: /^Ola Przykładowa/ })).toBeInTheDocument();
    // Pierwsza sprawa listy otwarta od razu, raporty godzin pod skrzynką.
    expect(screen.getByRole("region", { name: "Zgoda: Prezent dla klienta" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Raporty godzin" })).toBeInTheDocument();
  });

  it("chipy zawężają listę i zapisują się w adresie", async () => {
    const user = userEvent.setup();
    open("");

    await user.click(chip(/^Nieobecności/));
    expect(window.location.search).toBe("?tab=leave");
    const leaveList = screen.getByRole("list", { name: "Wnioski do decyzji (umowa o pracę)" });
    expect(within(leaveList).getAllByRole("button")).toHaveLength(2);
    expect(screen.queryByText("Gdańsk — warsztat")).toBeNull();
    expect(screen.queryByRole("list", { name: /do wiadomości/ })).toBeNull();
    expect(screen.queryByRole("region", { name: "Raporty godzin" })).toBeNull();

    await user.click(chip(/^Zgody/));
    expect(window.location.search).toBe("?tab=consents");
    expect(screen.getByRole("list", { name: "Do decyzji" })).toHaveTextContent("Gdańsk — warsztat");
    expect(screen.queryByText("Kamil Testowy")).toBeNull();

    await user.click(chip(/^Do wiadomości/));
    expect(screen.getByRole("region", { name: "Szczegóły: Ola Przykładowa" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: /decyzji/ })).toBeNull();

    await user.click(chip(/^Wszystko/));
    expect(window.location.search).toBe("");
  });

  it("link z powiadomienia o zgodzie: chip „Zgody” i ta zgoda otwarta", () => {
    open("?tab=consents&request=2");
    expect(chip(/^Zgody/)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: "Zgoda: Licencja edytora" })).toBeInTheDocument();
    expect(screen.queryByText("Kamil Testowy")).toBeNull();
  });

  it("link z powiadomienia o raporcie godzin: chip „Raporty godzin”, bez skrzynki", () => {
    const client = seed();
    client.setQueryData(timeKeys.team(2026, 9), { year: 2026, month: 9, norm_hours: 168, items: [] });
    open("?kind=timesheet&year=2026&month=9", client);
    expect(chip(/^Raporty godzin/)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: "Raporty godzin" })).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Do decyzji" })).toBeNull();
    expect(screen.queryByRole("radiogroup", { name: /zdecydowane/ })).toBeNull();
  });

  it("„Zdecydowane”: historia nieobecności i zgody rozstrzygnięte zamiast „Historii wniosków”", async () => {
    const user = userEvent.setup();
    const client = seed();
    const history: LeaveRequestRow[] = [{ ...PENDING[0], status: "approved", decided_by_name: "Marta Fikcyjna" }];
    client.setQueryData(leaveKeys.history({ status: null, user_id: null }), {
      items: history,
      counts: { all: 1, pending: 0, approved: 1, rejected: 0, cancelled: 0 },
    });
    client.setQueryData(leaveKeys.people, []);
    client.setQueryData(approvalKeys.list("decided"), [
      consent(9, "Konferencja HR", "2026-10-01T07:00:00Z", {
        status: "approved",
        status_label: "Zatwierdzona",
        decided_by_name: "Aniela Administrująca",
        decided_at: "2026-10-02T10:00:00Z",
      }),
    ]);
    open("", client);
    expect(screen.queryByRole("button", { name: "Historia wniosków" })).toBeNull();

    await user.click(screen.getByRole("radio", { name: "Zdecydowane" }));
    expect(window.location.search).toBe("?view=decided");
    expect(screen.getByRole("heading", { name: "Nieobecności" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Kamil Testowy/ })).toBeInTheDocument();
    const decided = screen.getByRole("table", { name: "Zgody — zdecydowane" });
    expect(within(decided).getByText("Konferencja HR")).toBeInTheDocument();
    expect(within(decided).getByText("Zatwierdzona")).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Do decyzji" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Raporty godzin" })).toBeNull();
  });

  it("awaria wczytania nieobecności to notka z ponowieniem, nie pusta skrzynka", async () => {
    const client = seed({ pending: false });
    client.setQueryData(approvalKeys.list("inbox"), []);
    open("?tab=leave", client);
    expect(await screen.findByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/nieobecności do decyzji — mogą czekać/);
    expect(screen.queryByTestId("approvals-empty")).toBeNull();
    expect(screen.queryByText("Nic nie czeka na Twoją decyzję.")).toBeNull();
  });

  it("pusta skrzynka mówi to jednym zdaniem dopiero po udanym wczytaniu", () => {
    const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } });
    client.setQueryData(leaveKeys.pending, { items: [], total: 0, covering: [], reported: [] });
    client.setQueryData(approvalKeys.list("inbox"), []);
    client.setQueryData(approvalKeys.topups, []);
    open("?tab=consents", client);
    expect(screen.getByTestId("approvals-empty")).toHaveTextContent("Nic nie czeka na Twoją decyzję.");
    expect(chip(/^Zgody/)).toHaveTextContent("0");
  });
});
