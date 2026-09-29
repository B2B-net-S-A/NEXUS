/**
 * Blok „Po ludzku”: awaria nigdy nie udaje pustki, zamknięta rekrutacja
 * dostaje przycisk zamiast samoodświeżania, nieaktualna otwarta odświeża się raz.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PlainBriefBlock } from "@/components/champion/plain/PlainBriefBlock";
import type { PlainBrief } from "@/lib/api/plainKnowledge";

const apiGet = vi.fn();
const apiPost = vi.fn();

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: {
    get: (...a: unknown[]) => apiGet(...a),
    post: (...a: unknown[]) => apiPost(...a),
    put: vi.fn(),
  },
}));

const EMPTY: PlainBrief = {
  job_id: 5,
  status: "none",
  stale: true,
  is_open: false,
  can_refresh: true,
  can_change_role: false,
  generated_at: null,
  message: null,
  one_liner: null,
  example: null,
  day_to_day: [],
  pitch: null,
  candidate_qa: [],
  screening_plain: [],
  glossary: [],
  role: null,
  client: null,
};

function renderBlock() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <PlainBriefBlock jobId={5} />
    </QueryClientProvider>,
  );
}

describe("PlainBriefBlock", () => {
  beforeEach(() => vi.clearAllMocks());

  it("błąd odczytu = komunikat z „Ponów”, nie pusty blok", async () => {
    apiGet.mockRejectedValue(Object.assign(new Error("boom"), { response: { status: 500 } }));
    renderBlock();
    expect(await screen.findByText(/Nie udało się wczytać wyjaśnienia/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Ponów/ })).toBeInTheDocument();
  });

  it("zamknięta rekrutacja bez wyjaśnienia: przycisk, bez samoodświeżania", async () => {
    apiGet.mockResolvedValue({ data: EMPTY });
    renderBlock();
    expect(await screen.findByRole("button", { name: /Przygotuj wyjaśnienie/ })).toBeInTheDocument();
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("otwarta z nieaktualnym wyjaśnieniem: jedno odświeżenie", async () => {
    apiGet.mockResolvedValue({ data: { ...EMPTY, is_open: true } });
    apiPost.mockResolvedValue({
      data: { ...EMPTY, is_open: true, status: "ready", stale: false, one_liner: "Szukamy testera." },
    });
    renderBlock();
    expect(await screen.findByText("Szukamy testera.")).toBeInTheDocument();
    await waitFor(() => expect(apiPost).toHaveBeenCalledTimes(1));
    expect(apiPost.mock.calls[0][0]).toBe("/api/jobs/5/plain-brief/refresh");
  });
});
