import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const listCandidateThreads = vi.fn();
const searchEmails = vi.fn();
vi.mock("@/lib/api", () => ({
  microsoft365Api: {
    listCandidateThreads: (...a: unknown[]) => listCandidateThreads(...a),
    searchEmails: (...a: unknown[]) => searchEmails(...a),
  },
}));
vi.mock("../EmailCompose", () => ({ default: () => null }));
vi.mock("../EmailThreadView", () => ({ default: () => null }));
vi.mock("../EmailBulkActionBar", () => ({ EmailBulkActionBar: () => null }));
vi.mock("@/lib/use-debounced-value", () => ({ useDebouncedValue: <T,>(v: T) => v }));

import EmailThreadList, { nextEmailPageOffset } from "../EmailThreadList";

function thread(i: number) {
  return {
    conversation_id: `conv-${i}`,
    subject: `Wątek ${i}`,
    message_count: 1,
    unread_count: 0,
    latest: {
      id: i,
      from_address: "a@example.com",
      from_name: "Anna",
      body_preview: "",
      received_at: "2026-09-01T10:00:00Z",
      has_attachments: false,
      match_method: "strict",
    },
  };
}

function renderList() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EmailThreadList candidateId={42} candidateName="Jan" candidateEmail="jan@example.com" />
    </QueryClientProvider>,
  );
}

describe("nextEmailPageOffset", () => {
  it("zwraca następny offset tylko, gdy coś zostało", () => {
    expect(nextEmailPageOffset({ total: 120, offset: 0, limit: 50, items: new Array(50) })).toBe(50);
    expect(nextEmailPageOffset({ total: 120, offset: 100, limit: 50, items: new Array(20) })).toBe(
      undefined,
    );
    expect(nextEmailPageOffset({ total: 5, offset: 0, limit: 50, items: [] })).toBe(undefined);
  });
});

describe("EmailThreadList — stronicowanie i wyszukiwanie w mailach kandydata (FE-08/09)", () => {
  beforeEach(() => {
    listCandidateThreads.mockReset();
    searchEmails.mockReset();
  });

  it("pokazuje „Pokazano X z Y” i dociąga kolejną stronę", async () => {
    listCandidateThreads.mockImplementation((_id: number, limit: number, offset: number) =>
      Promise.resolve({
        data: {
          items: offset === 0 ? [thread(1), thread(2)] : [thread(3)],
          total: 3,
          limit,
          offset,
        },
      }),
    );
    renderList();
    expect(await screen.findByText("Pokazano 2 z 3 wątków")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pokaż więcej" }));
    expect(await screen.findByText("Pokazano 3 z 3 wątków")).toBeInTheDocument();
    expect(listCandidateThreads).toHaveBeenLastCalledWith(42, 50, 2);
    expect(screen.queryByRole("button", { name: "Pokaż więcej" })).toBeNull();
  });

  it("wyszukiwarka przekazuje candidate_id tego kandydata", async () => {
    listCandidateThreads.mockResolvedValue({ data: { items: [], total: 0, limit: 50, offset: 0 } });
    searchEmails.mockResolvedValue({ data: { items: [], total: 0, limit: 50, offset: 0 } });
    renderList();
    fireEvent.change(screen.getByLabelText("Wyszukaj w mailach"), {
      target: { value: "oferta" },
    });
    await waitFor(() => expect(searchEmails).toHaveBeenCalledWith("oferta", 50, 0, 42));
    expect(await screen.findByText(/w mailach tego kandydata/)).toBeInTheDocument();
  });
});
