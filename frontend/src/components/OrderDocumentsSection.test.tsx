import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OrderDocumentsSection } from "@/components/OrderDocumentsSection";
import { dlPortalApi } from "@/lib/api/dlPortal";

vi.mock("@/lib/api/dlPortal", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/dlPortal")>();
  return {
    ...actual,
    dlPortalApi: {
      ...actual.dlPortalApi,
      listContractOrderDocuments: vi.fn(),
      listCandidateOrderDocuments: vi.fn(),
    },
  };
});

vi.mock("@/lib/order-documents", () => ({
  openOrderDocument: vi.fn(),
  downloadOrderDocument: vi.fn(),
}));

const listContract = vi.mocked(dlPortalApi.listContractOrderDocuments);

function renderSection(props: { contractId?: number; candidateId?: number }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <OrderDocumentsSection {...props} />
    </QueryClientProvider>,
  );
}

const sampleDoc = {
  order_id: 5,
  client_id: 10,
  contract_id: 3,
  title: "PO-5",
  filename: "po.pdf",
  content_type: "application/pdf",
  size_bytes: 2048,
  created_at: "2026-06-01T10:00:00Z",
  order_status: "active" as const,
};

describe("OrderDocumentsSection", () => {
  beforeEach(() => {
    listContract.mockReset();
  });

  it("renderuje nic gdy brak plików zamówień", async () => {
    listContract.mockResolvedValue({ data: { documents: [] } } as never);
    const { container } = renderSection({ contractId: 3 });
    await waitFor(() => expect(listContract).toHaveBeenCalled());
    expect(container.querySelector("table")).toBeNull();
    expect(screen.queryByText("Dokumenty zamówień")).not.toBeInTheDocument();
  });

  it("renderuje tabelę plików gdy zamówienia mają PDF", async () => {
    listContract.mockResolvedValue({
      data: { documents: [sampleDoc] },
    } as never);
    renderSection({ contractId: 3 });
    await waitFor(() =>
      expect(screen.getByText("Dokumenty zamówień")).toBeInTheDocument(),
    );
    expect(screen.getByText("PO-5")).toBeInTheDocument();
    expect(screen.getByText("po.pdf")).toBeInTheDocument();
  });

  it("nie wywala się i nic nie renderuje przy błędzie (np. 403)", async () => {
    listContract.mockRejectedValue(new Error("HTTP 403"));
    const { container } = renderSection({ contractId: 3 });
    await waitFor(() => expect(listContract).toHaveBeenCalled());
    expect(container.querySelector("table")).toBeNull();
  });
});
