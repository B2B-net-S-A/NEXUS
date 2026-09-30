/**
 * Blok „Po ludzku”: awaria nigdy nie udaje pustki, zamknięta rekrutacja
 * dostaje przycisk zamiast samoodświeżania, nieaktualna otwarta odświeża się raz.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClientAbout, PlainBriefBlock, ResearchProgress, RoleHistoryStrip } from "@/components/champion/plain/PlainBriefBlock";
import { SourceLinks } from "@/components/champion/plain/PlainBits";
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

  it("długi opis klienta jest zwinięty z „Pokaż więcej”", () => {
    render(<ClientAbout text={"Nordea ".repeat(100)} />);
    expect(screen.getByTestId("plain-client-about").className).toContain("line-clamp-4");
    fireEvent.click(screen.getByRole("button", { name: "Pokaż więcej" }));
    expect(screen.getByTestId("plain-client-about").className).not.toContain("line-clamp-4");
  });

  it("krótki opis klienta bez przycisku", () => {
    render(<ClientAbout text="Duży bank." />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("źródła: najwyżej 3 linki", () => {
    const sources = Array.from({ length: 8 }, (_, i) => ({ url: `https://e.com/${i}`, title: `Źródło ${i}` }));
    render(<SourceLinks sources={sources} />);
    expect(screen.getAllByRole("link")).toHaveLength(3);
  });

  it("pierwsza rekrutacja na rolę mówi, czemu nie ma statystyk", () => {
    const role = {
      id: 1, slug: "r", name: "Konsultant SAP FI-CO", summary: null, example: null,
      day_to_day: [], candidate_questions: [], typical_skills: [], sources: [],
      origin: "ai", status: "ready", updated_at: null, assignment: "auto",
      stats: { jobs: 1, clients: 1, hires: 0, hired_titles: [] },
    } as unknown as Parameters<typeof RoleHistoryStrip>[0]["role"];
    render(<RoleHistoryStrip role={role} />);
    expect(screen.getByTestId("role-history-first")).toHaveTextContent("Pierwsza taka rekrutacja");
  });

  it("postęp researchu: rola, hasła słowniczka i teksty", () => {
    const brief = {
      ...EMPTY,
      glossary: [
        { term_key: "sap fi-co", display_name: "SAP FI-CO", level: "must", level_label: "wymagane", status: "researching" },
      ],
    } as unknown as PlainBrief;
    render(<ResearchProgress brief={brief} refreshing />);
    const box = screen.getByTestId("plain-research-progress");
    expect(box).toHaveTextContent("Rola: szukam opisu w internecie");
    expect(box).toHaveTextContent("SAP FI-CO");
    expect(box).toHaveTextContent("Teksty dla tej rekrutacji: w toku");
  });
});
