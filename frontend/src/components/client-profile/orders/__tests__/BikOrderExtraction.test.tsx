/**
 * BIK: odczyt PDF w zamówieniu wieloosobowym.
 *
 * Reguła klienta (backend) zwraca numer, datę rozpoczęcia, `open_ended` i tabelę
 * pozycji z limitem MD i stawką każdej osoby. Te testy pilnują, że formularze
 * „Nowe zamówienie" / „Uzupełnij zamówienie" / „Dodaj przedłużenie" robią
 * z tym to samo: „bezterminowo" czyści datę „do" (z pytaniem, gdy coś było
 * wpisane), a przedłużenie wpisuje limit i stawkę osobom o tym samym nazwisku.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExtendOrderGroupModal } from "@/components/client-profile/orders/ExtendOrderGroupModal";
import { OrderGroupFormModal } from "@/components/client-profile/orders/OrderGroupFormModal";
import type { OrderExtractionResult } from "@/lib/api/dlPortal";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: {
    extractOrderPdf: vi.fn(),
    listActiveContractsForExtension: vi.fn(),
  },
}));

import { dlPortalApi } from "@/lib/api/dlPortal";

vi.mock("@/lib/api/orderGroups", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/orderGroups")>()),
  orderGroupsApi: {
    extractPlan: vi.fn(),
    consultantOptions: vi.fn().mockResolvedValue({ data: { options: [], total: 0 } }),
  },
}));

import { orderGroupsApi } from "@/lib/api/orderGroups";

const BIK_READ: OrderExtractionResult = {
  title: "4500012345",
  start_date: "2031-09-03",
  end_date: null,
  open_ended: true,
  rate_client: null,
  rate_unit: "day",
  total_value: null,
  currency: "PLN",
  md_total: null,
  uncertain: false,
  uncertain_reasons: [],
  fields_confidence: { title: 1, start_date: 1 },
  client_policy: "BIK",
  source: "claude",
  consultant_rows: [
    {
      consultant_name: "Krystian Sowiński",
      start_date: "2031-09-03",
      end_date: null,
      rate_client: 1080,
      rate_unit: "day",
      md_total: 35,
      uncertain: false,
      uncertain_reason: null,
    },
    {
      consultant_name: "Piotr Łęcki",
      start_date: "2031-09-03",
      end_date: null,
      rate_client: 1280,
      rate_unit: "day",
      md_total: 42,
      uncertain: false,
      uncertain_reason: null,
    },
  ],
};

function line(id: number, name: string, rateRevenue: number): OrderLineRead {
  return {
    id,
    group_id: 10,
    contract_id: 100 + id,
    candidate_id: id,
    consultant_name: name,
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2031-01-01",
    end_date: null,
    rate_cost: 900,
    rate_revenue: rateRevenue,
    input_value: 40,
    input_mode: "md",
    md_total: 40,
    md_remaining: 0,
    md_manual_adjustment: null,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
  };
}

const GROUP: OrderGroupRead = {
  id: 10,
  client_id: 18,
  order_number: "4500000001",
  start_date: "2031-01-01",
  end_date: "2031-12-31",
  notes: null,
  created_at: "2031-01-01T10:00:00Z",
  status: "active",
  status_label: "Aktywne",
  closure_date: null,
  closure_reason: null,
  is_cost_based: false,
  is_md_budget_based: false,
  budget_amount: null,
  budget_used: null,
  budget_remaining: null,
  budget_manual_adjustment: null,
  md_budget_total: null,
  md_budget_used: null,
  md_budget_remaining: null,
  md_budget_manual_adjustment: null,
  predecessor_group_id: null,
  filename: null,
  has_file: false,
  content_type: null,
  size_bytes: null,
  file_uploaded_at: null,
  can_add_consultant: true,
  lines: [line(1, "Krystian Sowiński", 1080), line(2, "Sowa Anna", 1500)],
  active_consultants: 2,
  event_count: 0,
  future_orders: [],
};

function provider(children: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>,
  );
}

const PDF = new File(["%PDF"], "bik.pdf", { type: "application/pdf" });

async function readDocument(user: ReturnType<typeof userEvent.setup>) {
  await user.upload(screen.getByLabelText(/Zamień plik PDF/), PDF);
  await user.click(screen.getByRole("button", { name: /Zczytaj dane z dokumentu/ }));
}

describe("BIK — odczyt zamówienia wieloosobowego", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue({
      data: BIK_READ,
    } as never);
    vi.mocked(dlPortalApi.listActiveContractsForExtension).mockResolvedValue({
      data: [],
    } as never);
  });

  function formModal(group: OrderGroupRead | null) {
    provider(
      <OrderGroupFormModal
        open
        onOpenChange={vi.fn()}
        group={group}
        clientId={18}
        orderType="md"
        onOrderTypeChange={vi.fn()}
        allowedOrderTypes={["md"]}
        submitting={false}
        error={null}
        onSubmit={vi.fn()}
        onDeleteFile={vi.fn()}
      />,
    );
  }

  it("nowe zamówienie: numer, data rozpoczęcia, bezterminowo i karty osób", async () => {
    vi.mocked(orderGroupsApi.extractPlan).mockResolvedValue({
      data: {
        order_number: "4500012345",
        start_date: "2031-09-03",
        end_date: null,
        open_ended: true,
        total_value: null,
        currency: "PLN",
        md_total: null,
        suggested_order_type: "md",
        client_policy: "BIK",
        consultant_ref: null,
        title_needs_review: false,
        document_incomplete: false,
        uncertain: false,
        uncertain_reasons: [],
        lines: BIK_READ.consultant_rows!.map((row, index) => ({
          ordinal: index + 1,
          document_name: row.consultant_name,
          position_label: String((index + 1) * 10),
          rate_revenue: row.rate_client,
          rate_revenue_unit: "day",
          rate_revenue_gross: null,
          md_total: row.md_total,
          start_date: row.start_date,
          end_date: null,
          match_status: "none",
          match_reason: "Brak kontraktu z tym imieniem i nazwiskiem u tego klienta",
          contract: null,
          options: [],
          nearest_names: [],
          warnings: [],
        })),
      },
    } as never);
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    formModal(null);
    const endField = screen.getByLabelText("Obowiązuje do (puste = bezterminowo)");
    fireEvent.change(endField, { target: { value: "2031-12-31" } });
    await user.upload(screen.getByLabelText(/Wgraj PDF zamówienia/), PDF);
    await user.click(
      screen.getByRole("button", { name: /Zczytaj i uzupełnij całe zamówienie/ }),
    );

    // Wpisana wcześniej data końca różni się od „bezterminowo" — zgoda.
    await user.click(await screen.findByRole("button", { name: /Tak/ }));
    expect(screen.getByLabelText("Numer zamówienia *")).toHaveValue("4500012345");
    expect(screen.getByLabelText("Obowiązuje od *")).toHaveValue("2031-09-03");
    expect(endField).toHaveValue("");
    const piotr = screen.getByRole("article", { name: "Konsultant: Piotr Łęcki" });
    expect(piotr).toHaveTextContent("z PDF, poz. 20");
    expect(screen.getAllByLabelText("Liczba MD")[1]).toHaveValue("42");
    expect(screen.getAllByLabelText("Stawka przychodowa")[1]).toHaveValue("1280");
  });

  it("uzupełnienie: „bezterminowo” zastępuje wpisaną datę dopiero po zgodzie", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    formModal({ ...GROUP, status: "draft", md_budget_mode_locked: false });
    const end = screen.getByLabelText("Obowiązuje do (puste = bezterminowo)");
    expect(end).toHaveValue("2031-12-31");

    await readDocument(user);
    expect(screen.getByText("Odczytane dane różnią się od wpisanych")).toBeInTheDocument();
    expect(screen.getByText("bezterminowo")).toBeInTheDocument();
    expect(end).toHaveValue("2031-12-31");

    await user.click(screen.getByRole("button", { name: /Tak — zapisz dane z dokumentu/ }));
    expect(end).toHaveValue("");
  });

  it("przedłużenie: limit MD i stawka trafiają do osób o tym samym nazwisku", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    provider(
      <ExtendOrderGroupModal
        open
        onOpenChange={vi.fn()}
        clientId={18}
        group={GROUP}
        submitting={false}
        error={null}
        onSubmit={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Obowiązuje do (puste = bezterminowo)"), {
      target: { value: "2032-06-30" },
    });

    await readDocument(user);
    // Jedyna rozbieżność to wpisana data „do" — stawka osoby jest ta sama.
    await user.click(screen.getByRole("button", { name: /Tak — zapisz dane z dokumentu/ }));

    expect(screen.getByLabelText("Liczba MD — Krystian Sowiński")).toHaveValue("35");
    expect(screen.getByLabelText("Stawka przychodowa — Krystian Sowiński")).toHaveValue(
      "1080",
    );
    // Osoba spoza dokumentu zostaje nietknięta — nie dostaje cudzego limitu.
    expect(screen.getByLabelText("Liczba MD — Sowa Anna")).toHaveValue("");
    expect(screen.getByLabelText("Stawka przychodowa — Sowa Anna")).toHaveValue("1500");
    expect(screen.getByLabelText("Obowiązuje do (puste = bezterminowo)")).toHaveValue("");
  });

  it("przedłużenie jednej osoby nie dostaje limitu z pozycji kogoś innego", async () => {
    vi.mocked(dlPortalApi.extractOrderPdf).mockResolvedValue({
      data: {
        ...BIK_READ,
        md_total: 42,
        rate_client: 1280,
        consultant_rows: [BIK_READ.consultant_rows![1]],
      },
    } as never);
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    provider(
      <ExtendOrderGroupModal
        open
        onOpenChange={vi.fn()}
        clientId={18}
        group={{ ...GROUP, lines: [line(1, "Krystian Sowiński", 1080)] }}
        submitting={false}
        error={null}
        onSubmit={vi.fn()}
      />,
    );
    await readDocument(user);
    expect(screen.getByLabelText("Liczba MD — Krystian Sowiński")).toHaveValue("");
    expect(screen.getByLabelText("Stawka przychodowa — Krystian Sowiński")).toHaveValue(
      "1080",
    );
  });
});
