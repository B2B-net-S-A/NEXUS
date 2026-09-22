import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => get(...a),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  };
  return { default: client, api: client };
});

import { JobShareTab } from "../JobShareTab";
import { ToastProvider } from "@/components/Toast";

// Pierwsza strona opublikowanych rekrutacji NIE zawiera rekrutacji 555.
const FIRST_PAGE = { items: [{ id: 1, title: "Inna rekrutacja", status: "published" }] };

function routeGet(job555: { id: number; title: string; status: string }) {
  get.mockImplementation((url: string) => {
    if (url === "/api/jobs") return Promise.resolve({ data: FIRST_PAGE });
    if (url === "/api/jobs/555") return Promise.resolve({ data: job555 });
    if (url === "/api/invite-links") return Promise.resolve({ data: [] });
    if (url === "/api/me/career-link") return Promise.resolve({ data: {} });
    return new Promise(() => {});
  });
}

function renderTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <JobShareTab enabled defaultJobId={555} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

const CLOSED_MSG = /nie jest opublikowana/;

describe("JobShareTab — defaultJobId spoza pierwszej strony (FE-13)", () => {
  beforeEach(() => {
    get.mockReset();
  });

  it("opublikowana rekrutacja spoza listy nie jest nazywana nieopublikowaną", async () => {
    routeGet({ id: 555, title: "Rekrutacja z drugiej setki", status: "published" });
    renderTab();
    await waitFor(() => expect(get).toHaveBeenCalledWith("/api/jobs/555"));
    expect(await screen.findByText("Rekrutacja z drugiej setki")).toBeInTheDocument();
    expect(screen.queryByText(CLOSED_MSG)).toBeNull();
  });

  it("zamknięta rekrutacja dalej dostaje właściwy komunikat", async () => {
    routeGet({ id: 555, title: "Zamknięta", status: "closed" });
    renderTab();
    expect(await screen.findByText(CLOSED_MSG)).toBeInTheDocument();
  });

  it("lista szuka po stronie serwera: status=published", async () => {
    routeGet({ id: 555, title: "X", status: "published" });
    renderTab();
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith(
        "/api/jobs",
        expect.objectContaining({ params: expect.objectContaining({ status: "published" }) }),
      ),
    );
  });
});
