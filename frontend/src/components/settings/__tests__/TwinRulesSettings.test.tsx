import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const toast = vi.hoisted(() => ({ showError: vi.fn(), showSuccess: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
const apiMock = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: apiMock, default: apiMock }));
// Podgląd liczb bez czekania na opóźnienie wpisywania.
vi.mock("@/lib/use-debounced-value", () => ({ useDebouncedValue: <T,>(v: T) => v }));

import type { TwinRules, TwinRulesPayload } from "@/lib/job-twins-api";

import { TwinRulesSettings } from "../TwinRulesSettings";

const DEFAULTS: TwinRules = {
  min_similarity: 80,
  critical: { mode: "required", include_title: false },
  must: { mode: "warning", min_share: 50 },
  location: { mode: "warning" },
  work_mode: { mode: "warning" },
  budget: { mode: "warning", max_diff: 10 },
  client: { mode: "off" },
  category: { mode: "off" },
  different_dl: { mode: "required" },
  max_twins: 3,
  open_similar_limit: 8,
  pair_hint: "default",
};

const LABELS = {
  similarity: "Podobieństwo opisu",
  critical: "Umiejętności krytyczne",
  must: "Wymagania",
  location: "Lokalizacja",
  work_mode: "Tryb pracy",
  budget: "Budżet",
  client: "Klient",
  category: "Kategoria kompetencji",
  different_dl: "Delivery Lead",
};

function payload(canEdit: boolean): TwinRulesPayload {
  return { rules: DEFAULTS, defaults: DEFAULTS, labels: LABELS, can_edit: canEdit };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TwinRulesSettings />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMock.post.mockResolvedValue({
    data: {
      pairs_in_scope: 53,
      pass_required: 46,
      with_warnings: 40,
      suggestions: 7,
      suggestions_saved: 9,
      per_rule: { critical: 46, location: 35, work_mode: 29, budget: 43, must: 27, different_dl: 9 },
      examples: [
        {
          status: "drop",
          similarity: 93,
          job: { id: 1, title: "IT Analyst" },
          other: { id: 2, title: "IT Analyst (Senior)" },
          reason: "Umiejętności krytyczne: „several years…” — nie ma w drugiej",
        },
      ],
    },
  });
  apiMock.put.mockImplementation(async (_url: string, body: TwinRules) => ({
    data: { ...payload(true), rules: body },
  }));
});

describe("TwinRulesSettings — zasady bliźniaków (29.10.2026)", () => {
  it("shows the counts, changes a rule mode and saves for the whole company", async () => {
    apiMock.get.mockResolvedValue({ data: payload(true) });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("twin-rules-summary")).toHaveTextContent(
        "7 możliwych bliźniaków różnych DL-i (teraz 9)",
      ),
    );
    expect(screen.getByTestId("twin-rule-location")).toHaveTextContent("spełnia 35 z 53");
    expect(screen.getByText(/IT Analyst ↔ IT Analyst \(Senior\)/)).toBeInTheDocument();
    expect(screen.getByTestId("twin-rules-save")).toBeDisabled();

    const location = screen.getByRole("radiogroup", { name: "Jak działa: Lokalizacja" });
    fireEvent.click(location.querySelectorAll("button")[0]); // Wymagane
    fireEvent.change(screen.getByLabelText("Podobieństwo opisu rekrutacji"), { target: { value: "75" } });
    await waitFor(() => expect(screen.getByTestId("twin-rules-save")).toBeEnabled());
    fireEvent.click(screen.getByTestId("twin-rules-save"));
    await waitFor(() => expect(apiMock.put).toHaveBeenCalled());
    const [url, body] = apiMock.put.mock.calls[0];
    expect(url).toBe("/api/job-twins/rules");
    expect(body.location.mode).toBe("required");
    expect(body.min_similarity).toBe(75);
    expect(toast.showSuccess).toHaveBeenCalled();
  });

  it("is read-only for a Delivery Lead and asks for no preview", async () => {
    apiMock.get.mockResolvedValue({ data: payload(false) });
    renderPanel();
    expect(await screen.findByText(/Zasady zmieniają Head of Recruitment i admin/)).toBeInTheDocument();
    expect(screen.getByLabelText("Podobieństwo opisu rekrutacji")).toBeDisabled();
    expect(screen.queryByTestId("twin-rules-save")).toBeNull();
    expect(apiMock.post).not.toHaveBeenCalled();
  });
});
