import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { hrConfig } from "@/app/preview/hr-fixtures";
import { ApprovalsScreen } from "@/components/hr/leave/ApprovalsScreen";
import type { HrConfig } from "@/lib/api/hr";
import { approvalKeys, type ApprovalRequestRow } from "@/lib/api/hr-approvals";

// Zgody w „Akceptacjach” (od 22.10.2026 jedna lista z nieobecnościami) — tu
// sam moduł zgód: urlopy i czas wyłączone, więc lista ma tylko zgody.
const nav = vi.hoisted(() => ({ params: new URLSearchParams() }));
const decide = vi.hoisted(() => ({ mutate: vi.fn() }));

vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.params,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));
vi.mock("@/components/Toast", () => ({ useToast: () => ({ showToast: vi.fn() }) }));
vi.mock("@/lib/api/hr-approvals", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/hr-approvals")>();
  return {
    ...actual,
    useDecideApproval: () => ({ isPending: false, mutate: decide.mutate }),
    usePendingTopups: () => ({ isSuccess: true, data: [] }),
  };
});

const row = (overrides: Partial<ApprovalRequestRow>): ApprovalRequestRow =>
  ({
    id: 1,
    kind: "trip",
    kind_label: "Delegacja",
    status: "pending_final",
    status_label: "Czeka na zatwierdzającego",
    title: "Gdańsk — warsztat",
    purpose: "Warsztat z hiring managerem.",
    amount: "2180.00",
    decided_amount: null,
    currency: "PLN",
    amount_basis: "gross",
    recurrence: "once",
    amount_text: "2 180 zł brutto",
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
    final_approver_names: ["Aniela Administrująca"],
    endorsed_by_name: null,
    endorsed_at: null,
    endorse_note: null,
    decided_by_name: null,
    decided_at: null,
    decision_note: null,
    decision_channel: null,
    bonus_id: null,
    submitted_at: "2026-10-20T07:00:00Z",
    can_decide: true,
    decides_as: "final",
    can_edit: false,
    can_withdraw: false,
    context: null,
    ...overrides,
  }) as ApprovalRequestRow;

const CONSENTS_ONLY: HrConfig = (() => {
  const config = hrConfig({ is_admin: true, has_profile: false });
  const open = { ...config.open_modules, leave: false, time: false, approvals: true };
  return { ...config, modules: open, open_modules: open };
})();

function renderInbox(rows: ApprovalRequestRow[]) {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  client.setQueryData(approvalKeys.list("inbox"), rows);
  for (const item of rows) client.setQueryData(approvalKeys.detail(item.id), item);
  return render(
    <QueryClientProvider client={client}>
      <ApprovalsScreen config={CONSENTS_ONLY} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  nav.params = new URLSearchParams();
  decide.mutate.mockReset();
});

describe("Akceptacje — zgody (szczegół, okno decyzji z linku)", () => {
  it("premia: osoba na pierwszym planie, liczby „NEXUS sprawdził” i zdanie o Płacach", () => {
    renderInbox([
      row({
        id: 7,
        kind: "bonus",
        kind_label: "Wynagrodzenie dodatkowe",
        title: "Trzy przejęte rekrutacje",
        payer: null,
        beneficiary_user_id: 107,
        beneficiary_name: "Julia Próbna",
        payout_year: 2026,
        payout_month: 10,
        context: {
          kind_month: { count: 2, amount: "3500.00" },
          kind_year: { count: 11, amount: "18200.00" },
          all_month: { count: 14, amount: "21380.00" },
          beneficiary_year: {
            automatic: "9400.00",
            outside_contract: "0.00",
            manual: "0.00",
            same_month_automatic: "1200.00",
          },
        },
      }),
    ]);
    const list = screen.getByRole("list", { name: "Do decyzji" });
    expect(within(list).getByText("Julia Próbna")).toBeInTheDocument();
    expect(screen.getByText(/z umowy i reguł 9400 zł/)).toBeInTheDocument();
    expect(screen.getByText(/sprawdź, czy to nie dubel/)).toBeInTheDocument();
    expect(screen.getByText(/Wynagrodzenie dodatkowe trafi do Płac jako przyznane/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Zatwierdź inną kwotę/ })).toBeInTheDocument();
  });

  it("przełożony ponad próg widzi „Popieram” bez zmiany kwoty", () => {
    renderInbox([
      row({
        status: "pending_supervisor",
        supervisor_user_id: 2,
        supervisor_name: "Marta Fikcyjna",
        decides_as: "supervisor",
      }),
    ]);
    expect(screen.getByRole("button", { name: "Popieram" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /inną kwotę/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Po poparciu/)).toBeInTheDocument();
  });

  it("przycisk z maila otwiera zgodę z oknem decyzji; odrzucenie wymaga powodu", async () => {
    nav.params = new URLSearchParams("tab=consents&request=2&decide=reject");
    renderInbox([row({ id: 1, title: "Pierwsza" }), row({ id: 2, title: "Druga z linku" })]);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Odrzucić zgodę?")).toBeInTheDocument();
    expect(within(dialog).getByText(/Druga z linku/)).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole("button", { name: "Odrzuć" }));
    expect(decide.mutate).not.toHaveBeenCalled();
    expect(within(dialog).getByText(/Napisz jedno zdanie/)).toBeInTheDocument();

    await userEvent.type(within(dialog).getByLabelText(/Powód/), "Nie w tym kwartale");
    await userEvent.click(within(dialog).getByRole("button", { name: "Odrzuć" }));
    expect(decide.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ id: 2, action: "reject", note: "Nie w tym kwartale" }),
      expect.anything(),
    );
  });

  it("zgoda z linku już rozpatrzona — pusta skrzynka mówi to wprost", () => {
    nav.params = new URLSearchParams("request=9&decide=approve");
    renderInbox([]);
    expect(screen.getByText(/już rozpatrzona albo decyduje o niej ktoś inny/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
