import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { EditJobModal } from "@/components/AppShell";
import api, { phase5Api } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  aiWriterApi: {},
  phase5Api: { clientsLookup: vi.fn() },
  pipelineTemplatesApi: {},
  requestHistoryApi: {},
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.patch).mockResolvedValue({ data: {} } as never);
});

const job = {
  id: 7,
  title: "Senior Java Developer",
  client_id: 3,
  description: "Stary opis",
  requirements: "Java",
  rate_budget_hourly: 150,
  recruiter_id: 11,
  delivery_lead_id: 12,
  status: "published",
};

function renderModal(scope?: "full" | "content") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EditJobModal job={job} onClose={() => {}} onSuccess={() => {}} scope={scope} />
    </QueryClientProvider>,
  );
}

describe("EditJobModal — edycja treści przez rekrutera (22.09.2026)", () => {
  it("scope=content pokazuje tylko opis i wymagania, bez list klientów i osób", () => {
    renderModal("content");
    expect(screen.getByDisplayValue("Stary opis")).toBeInTheDocument();
    expect(screen.queryByText("Klient")).not.toBeInTheDocument();
    expect(screen.queryByText(/Budżet PLN\/h/)).not.toBeInTheDocument();
    expect(screen.queryByText("Rekruter prowadzący")).not.toBeInTheDocument();
    expect(screen.queryByText("Delivery Lead")).not.toBeInTheDocument();
    expect(screen.getByText(/zmienia Delivery Lead/)).toBeInTheDocument();
    // Listy klientów i użytkowników nie są potrzebne — nie pytamy o nie.
    expect(phase5Api.clientsLookup).not.toHaveBeenCalled();
    expect(api.get).not.toHaveBeenCalled();
  });

  it("scope=content wysyła w PATCH wyłącznie opis i wymagania", async () => {
    const user = userEvent.setup();
    renderModal("content");
    const description = screen.getByDisplayValue("Stary opis");
    await user.clear(description);
    await user.type(description, "Nowy opis");
    await user.click(screen.getByRole("button", { name: "Zapisz zmiany" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledTimes(1));
    expect(api.patch).toHaveBeenCalledWith("/api/jobs/7", {
      description: "Nowy opis",
      requirements: "Java",
    });
  });

  it("domyślnie pełny formularz (klient, budżet, zespół)", () => {
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({ data: [] } as never);
    vi.mocked(api.get).mockResolvedValue({ data: [] } as never);
    renderModal();
    expect(screen.getByText("Klient")).toBeInTheDocument();
    expect(screen.getByText(/Budżet PLN\/h/)).toBeInTheDocument();
  });
});
