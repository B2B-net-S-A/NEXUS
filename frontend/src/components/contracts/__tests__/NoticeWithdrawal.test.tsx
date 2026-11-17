/**
 * „Wycofaj wypowiedzenie” (zgłoszenie Finansów 17.11.2026): umowa B2B
 * skrócona aneksem „Wcześniejsze zakończenie” skończyła się w nocy, a konsultant
 * wycofał wypowiedzenie. „Przedłuż” odsyłał do „Cofnij zakończenie”, a to
 * blokowało się radą „przedłuż aneksem”. Teraz wyjście jest przy samym aneksie.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  preview: vi.fn(),
  withdraw: vi.fn(),
  documents: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: {
    get: (...a: unknown[]) => mocks.get(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  },
  contractsApi: {
    noticeWithdrawalPreview: (...a: unknown[]) => mocks.preview(...a),
    withdrawNotice: (...a: unknown[]) => mocks.withdraw(...a),
    documents: (...a: unknown[]) => mocks.documents(...a),
  },
  CONTRACT_FIELD_LABELS: { end_date: "Data zakończenia projektu", status: "Status" },
  CONTRACT_TERMINATION_REASONS: [],
}));

vi.mock("@/lib/contract-documents", () => ({ openContractDocument: vi.fn() }));

vi.mock("@/store/auth", async () => {
  const actual =
    await vi.importActual<typeof import("@/store/auth")>("@/store/auth");
  const state = { user: { id: 1, role: "finance", roles: ["finance"] } };
  return {
    ...actual,
    useAuthStore: (selector: (s: typeof state) => unknown) => selector(state),
    canManageCandidateFinance: () => true,
    canViewClientFinance: () => true,
  };
});

import { ContractAmendmentsTab } from "@/components/ContractAmendmentsTab";
import {
  noticeEndDate,
  noticeEndOptions,
} from "@/components/contracts/NoticeWithdrawalDialog";

const NOTICE = {
  id: 63,
  contract_id: 216,
  amendment_type: "early_termination",
  old_values: { end_date: "2026-12-15", status: "active" },
  new_values: { end_date: "2026-10-31", status: "ended" },
  effective_date: "2026-07-13",
  reason: "przysłał wypowiedzenie, 3 msc",
  document_id: null,
  created_by: 2,
  created_by_email: null,
  created_by_name: "Marta K.",
  created_at: "2026-07-13T12:21:44Z",
  source: "manual",
  b2b_document_id: null,
  state: "in_force",
  document: null,
  withdrawn: false,
  withdrawable: true,
};

const WITHDRAWAL = {
  ...NOTICE,
  id: 90,
  amendment_type: "custom_change",
  old_values: { end_date: "2026-10-31", status: "ended" },
  new_values: {
    annex_title: "Wycofanie wypowiedzenia",
    end_date: null,
    status: "active",
    withdrawn_amendment_id: 63,
  },
  effective_date: "2026-11-17",
  reason: null,
  withdrawable: false,
};

const PREVIEW = {
  contract_id: 216,
  contract_type: "b2b",
  status: "ended",
  end_date: "2026-10-31",
  notice: {
    amendment_id: 63,
    effective_date: "2026-07-13",
    notice_end: "2026-10-31",
    end_before_notice: "2026-12-15",
    reason: null,
  },
  earliest_end_date: "2026-11-17",
  indefinite_allowed: true,
  reversal: {
    contract_id: 216,
    source: "snapshot",
    terminated_on: "2026-10-31",
    contract: {
      status_now: "ended",
      status_target: "active",
      end_date_now: "2026-10-31",
      end_date_target: null,
      clears_termination: false,
    },
    orders: [
      {
        order_id: 185,
        order_group_id: null,
        order_label: "284887",
        kind: "periodic",
        consultant: "A. G.",
        status_now: "completed",
        status_target: "active",
        end_date_now: "2026-10-31",
        end_date_target: "2026-12-15",
        end_date_source: "snapshot",
        removes_decision_case: false,
      },
    ],
    skipped: [],
    blockers: [],
    md_imports: [],
    decision_cases_removed: 0,
    executed: false,
  },
};

function serve(amendments: unknown[]) {
  mocks.get.mockImplementation((url: string) =>
    Promise.resolve({ data: url.endsWith("/annex-documents") ? [] : amendments }),
  );
}

function renderTab(props: Partial<React.ComponentProps<typeof ContractAmendmentsTab>> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  render(
    <QueryClientProvider client={client}>
      <ContractAmendmentsTab contractId={216} clientId={11} {...props} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  Object.values(mocks).forEach((m) => m.mockReset());
  mocks.preview.mockResolvedValue({ data: PREVIEW });
  mocks.documents.mockResolvedValue({ data: [] });
  mocks.withdraw.mockResolvedValue({ data: {} });
});

describe("opcje daty końca po wycofaniu", () => {
  it("B2B: najpierw umowa bezterminowa, potem data sprzed wypowiedzenia", () => {
    expect(noticeEndOptions(PREVIEW).map((o) => o.value)).toEqual([
      "indefinite",
      "before_notice",
      "custom",
    ]);
  });

  it("data sprzed wypowiedzenia, która minęła, nie jest opcją", () => {
    const past = {
      ...PREVIEW,
      notice: { ...PREVIEW.notice, end_before_notice: "2026-11-01" },
    };
    expect(noticeEndOptions(past).map((o) => o.value)).toEqual(["indefinite", "custom"]);
  });

  it("umowa zlecenie nie dostaje opcji bez daty", () => {
    expect(
      noticeEndOptions({ ...PREVIEW, indefinite_allowed: false }).map((o) => o.value),
    ).toEqual(["before_notice", "custom"]);
  });

  it("wybór zamienia się na datę do wysłania", () => {
    expect(noticeEndDate("indefinite", PREVIEW, "")).toBeNull();
    expect(noticeEndDate("before_notice", PREVIEW, "")).toBe("2026-12-15");
    expect(noticeEndDate("custom", PREVIEW, "")).toBeUndefined();
    expect(noticeEndDate("custom", PREVIEW, "2027-01-31")).toBe("2027-01-31");
  });
});

describe("Aneksy: wycofanie wypowiedzenia", () => {
  it("przy wypowiedzeniu jest przycisk, a podpowiedź „Przedłuż” nie odsyła w kółko", async () => {
    serve([NOTICE]);
    renderTab({ extensionLocked: true, canWithdrawNotice: true });

    expect(
      await screen.findByRole("button", { name: "Wycofaj wypowiedzenie" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Konsultant wycofał wypowiedzenie\?/)).toBeInTheDocument();
    expect(screen.queryByText(/nie ma czego przedłużać/)).not.toBeInTheDocument();
  });

  it("bez uprawnienia do korekty zakończenia przycisku nie ma", async () => {
    serve([NOTICE]);
    renderTab({ extensionLocked: true });
    await screen.findByText("Wcześniejsze zakończenie");
    expect(
      screen.queryByRole("button", { name: "Wycofaj wypowiedzenie" }),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/nie ma czego przedłużać/)).toBeInTheDocument();
  });

  it("po wycofaniu: aneks „Wycofany”, wpis z nazwą i umową bezterminową", async () => {
    serve([WITHDRAWAL, { ...NOTICE, withdrawn: true, withdrawable: false }]);
    renderTab({ canWithdrawNotice: true });

    const entry = (await screen.findByText("Wycofanie wypowiedzenia")).closest("tr")!;
    expect(within(entry).getByText(/bezterminowo/)).toBeInTheDocument();
    expect(within(entry).queryByText(/withdrawn_amendment_id|annex_title/)).toBeNull();
    const notice = screen.getByText("Wcześniejsze zakończenie").closest("tr")!;
    expect(within(notice).getByText("Wycofany")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Wycofaj wypowiedzenie" }),
    ).not.toBeInTheDocument();
  });

  it("okno pokazuje zamówienie do przywrócenia i wysyła umowę bezterminową", async () => {
    serve([NOTICE]);
    renderTab({ canWithdrawNotice: true });

    fireEvent.click(await screen.findByRole("button", { name: "Wycofaj wypowiedzenie" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/284887/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Umowa bezterminowa/)).toBeChecked();

    const submit = within(dialog)
      .getAllByRole("button", { name: "Wycofaj wypowiedzenie" })
      .at(-1)!;
    fireEvent.click(submit);
    await waitFor(() =>
      expect(mocks.withdraw).toHaveBeenCalledWith(216, {
        end_date: null,
        note: null,
        document_id: null,
      }),
    );
  });

  it("inna data końca wymaga daty od dziś", async () => {
    serve([NOTICE]);
    renderTab({ canWithdrawNotice: true });

    fireEvent.click(await screen.findByRole("button", { name: "Wycofaj wypowiedzenie" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(await within(dialog).findByLabelText(/Inna data końca/));
    const submit = within(dialog)
      .getAllByRole("button", { name: "Wycofaj wypowiedzenie" })
      .at(-1)!;
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Nowa data końca umowy"), {
      target: { value: "2026-11-10" },
    });
    expect(within(dialog).getByRole("alert")).toHaveTextContent(/dzisiejsza albo późniejsza/);
    expect(submit).toBeDisabled();
  });
});
