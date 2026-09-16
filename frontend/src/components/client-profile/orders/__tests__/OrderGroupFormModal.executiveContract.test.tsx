/**
 * Centrum e-Zdrowia: nowe zamówienie MD/kosztowe wisi pod KONKRETNĄ umową
 * wykonawczą. Select jest bramkowany po `client_id` — u innych klientów nie
 * renderuje się wcale i nie wysyła `executive_contract_id`.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrderGroupFormModal } from "@/components/client-profile/orders/OrderGroupFormModal";
import type { OrderGroupInput } from "@/lib/api/orderGroups";
import { EZDROWIE_CLIENT_ID } from "@/lib/ezdrowie";

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: { extractPlan: vi.fn(), consultantOptions: vi.fn() },
}));

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: { extractOrderPdf: vi.fn() },
}));

const hookState = vi.hoisted(() => ({
  isSuccess: true,
  isError: false,
  groups: [
    {
      framework_contract_id: 12,
      project_part: "cz2",
      label: "Cz. II — CeZ/145/2025",
      options: [
        { id: 71, number: "CeZ/242/2025", status: "active", framework_contract_id: 12, project_part: "cz2" },
      ],
    },
    {
      framework_contract_id: 14,
      project_part: "cz4",
      label: "Cz. IV — CeZ/188/2025",
      options: [
        { id: 72, number: "CeZ/301/2025", status: "active", framework_contract_id: 14, project_part: "cz4" },
      ],
    },
  ] as Array<{
    framework_contract_id: number;
    project_part: string;
    label: string;
    options: Array<{ id: number; number: string; status: string; framework_contract_id: number; project_part: string }>;
  }>,
}));

vi.mock("@/lib/api/executiveContracts", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/executiveContracts")>()),
  useExecutiveContractOptions: vi.fn(() => ({
    isSuccess: hookState.isSuccess,
    isError: hookState.isError,
    refetch: vi.fn(),
    groups: hookState.groups,
  })),
}));

const DEFAULT_GROUPS = [...hookState.groups];

function renderModal(clientId: number, onSubmit = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <OrderGroupFormModal
        open
        onOpenChange={vi.fn()}
        group={null}
        clientId={clientId}
        orderType="md"
        onOrderTypeChange={vi.fn()}
        allowedOrderTypes={["periodic", "cost", "md"]}
        submitting={false}
        error={null}
        onSubmit={onSubmit}
        onDeleteFile={vi.fn()}
      />
    </QueryClientProvider>,
  );
  return onSubmit;
}

const setupUser = () => userEvent.setup({ pointerEventsCheck: 0 });

async function fillRequired(user: ReturnType<typeof setupUser>) {
  await user.type(screen.getByLabelText("Numer zamówienia *"), "CeZ/242/2025/Z-9");
  await user.type(screen.getByLabelText("Obowiązuje od *"), "2026-10-01");
  // Aktywne zamówienie MD wymaga konsultantów — szkic pozwala sprawdzić sam
  // nagłówek bez odczytu PDF-a.
  await user.selectOptions(screen.getByRole("combobox", { name: "Status zamówienia" }), "draft");
}

describe("OrderGroupFormModal — umowa wykonawcza (CeZ)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hookState.isSuccess = true;
    hookState.isError = false;
    hookState.groups = DEFAULT_GROUPS;
  });

  it("u innego klienta selektu nie ma i payload nie niesie executive_contract_id", async () => {
    const user = setupUser();
    const onSubmit = renderModal(18);
    expect(screen.queryByLabelText("Umowa wykonawcza *")).toBeNull();

    await fillRequired(user);
    await user.click(screen.getByRole("button", { name: "Utwórz zamówienie" }));

    const payload = onSubmit.mock.calls[0][0] as OrderGroupInput;
    expect(payload).not.toHaveProperty("executive_contract_id");
  });

  it("u CeZ select jest wymagany: bez wyboru zapis stoi, z wyborem idzie id umowy", async () => {
    const user = setupUser();
    const onSubmit = renderModal(EZDROWIE_CLIENT_ID);
    await fillRequired(user);

    const select = screen.getByLabelText("Umowa wykonawcza *");
    // `<optgroup>` per część — DL widzi, pod którą częścią wisi umowa.
    expect(select.querySelectorAll("optgroup")).toHaveLength(2);
    expect(select.querySelector('optgroup[label="Cz. II — CeZ/145/2025"]')).not.toBeNull();
    expect(screen.getByText("Wybierz umowę wykonawczą.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Utwórz zamówienie" })).toBeDisabled();

    await user.selectOptions(select, "72");
    await user.click(screen.getByRole("button", { name: "Utwórz zamówienie" }));

    const payload = onSubmit.mock.calls[0][0] as OrderGroupInput;
    expect(payload.executive_contract_id).toBe(72);
  });

  it("bez aktywnych umów wykonawczych kieruje do sekcji Struktura umów zamiast pustego selektu", () => {
    hookState.groups = [];
    renderModal(EZDROWIE_CLIENT_ID);

    expect(screen.queryByLabelText("Umowa wykonawcza *")).toBeNull();
    expect(
      screen.getByText(/Dodaj umowę wykonawczą w sekcji Struktura umów na profilu klienta/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Utwórz zamówienie" })).toBeDisabled();
  });
});
