import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ClientsListV2 } from "@/components/v2/pages/ClientsListV2";

const getMock = vi.fn();
vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
  aiWriterApi: {},
  phase5Api: {},
  pipelineTemplatesApi: {},
  requestHistoryApi: {},
}));

function renderList() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ClientsListV2 />
    </QueryClientProvider>,
  );
}

/** Wywołania listy klientów (pomija zapytanie o hit ratio). */
function listCalls() {
  return getMock.mock.calls.filter((c) => c[0] === "/api/clients");
}

describe("ClientsListV2 — debounce wyszukiwarki", () => {
  beforeEach(() => {
    getMock.mockReset();
    getMock.mockImplementation((url: string) => {
      if (url === "/api/clients") {
        return Promise.resolve({
          data: { items: [], total: 0, page: 1, page_size: 50 },
        });
      }
      return Promise.resolve({ data: { clients: [] } });
    });
  });

  it("wysyła jedno zapytanie na serię znaków, nie jedno na znak", async () => {
    const user = userEvent.setup();
    renderList();
    await waitFor(() => expect(listCalls()).toHaveLength(1));

    const input = screen.getByPlaceholderText(/szukaj po nazwie firmy/i);
    await user.type(input, "acme");

    // Zdebouncowana fraza dolatuje jako JEDNO dodatkowe zapytanie…
    await waitFor(
      () => {
        expect(listCalls()).toHaveLength(2);
        expect(listCalls()[1][1]).toMatchObject({
          params: expect.objectContaining({ q: "acme" }),
        });
      },
      { timeout: 2000 },
    );

    // …i nic więcej się nie dosypuje (przed fixem: 4 zapytania, po jednym na znak).
    await new Promise((r) => setTimeout(r, 350));
    expect(listCalls()).toHaveLength(2);
  });

  it("input pozostaje responsywny — pokazuje surową wartość od razu", async () => {
    const user = userEvent.setup();
    renderList();
    await waitFor(() => expect(listCalls()).toHaveLength(1));

    const input = screen.getByPlaceholderText(/szukaj po nazwie firmy/i);
    await user.type(input, "ac");

    expect(input).toHaveValue("ac");
  });
});
