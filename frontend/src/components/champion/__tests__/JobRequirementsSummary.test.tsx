/**
 * Zakładka „Wymagania” podglądu w panelu osoby (D5, 09.10.2026): lista
 * wymagań ze zdaniem ze słowniczka „po ludzku” i „Szukaj w CV”.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobRequirementsSummary } from "@/components/champion/JobRequirementsSummary";

const getMock = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    championApi: { ...actual.championApi, get: (...args: unknown[]) => getMock(...args) },
  };
});
const plainBriefMock = vi.fn();
vi.mock("@/lib/api/plainKnowledge", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/plainKnowledge")>();
  return { ...actual, usePlainBrief: () => plainBriefMock() };
});

const PROFILE = {
  basics: { rate_value: 150, work_mode: "hybrid", onsite_days_per_week: 2, language: "EN B2" },
  stack: { must: [{ name: "Java 17" }, { name: "Kafka" }], nice: [{ name: "Kubernetes" }], notes: "" },
};

function term(name: string, summary: string, status = "ready") {
  return {
    term_key: name.toLowerCase(),
    display_name: name,
    level: "must",
    level_label: "wymagane",
    status,
    summary,
    does: null,
    cv_hints: [],
    confused_with: null,
    in_this_project: null,
    sources: [],
    origin: null,
  };
}

function renderSummary(onPickRequirement?: (name: string) => void) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <JobRequirementsSummary jobId={5} budgetHourly={150} onPickRequirement={onPickRequirement} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  plainBriefMock.mockReset();
  plainBriefMock.mockReturnValue({ data: undefined });
  getMock.mockReset();
  getMock.mockResolvedValue({
    data: {
      job_id: 5,
      champion_profile: PROFILE,
      critical_resolution: {
        decided: true,
        stored: ["Java 17"],
        suggested: [],
        effective: ["Java 17"],
        search_rows: [],
      },
    },
  });
});

describe("JobRequirementsSummary", () => {
  it("pod wymaganiem stoi zdanie ze słowniczka; hasło bez opisu pokazuje samą nazwę", async () => {
    plainBriefMock.mockReturnValue({
      data: {
        glossary: [
          term("Kafka", "Kolejka zdarzeń: systemy wysyłają sobie komunikaty i nie czekają na odpowiedź."),
          term("Kubernetes", "Szukam opisu…", "researching"),
        ],
      },
    });
    renderSummary();
    const kafka = (await screen.findByText("Kafka")).closest("li") as HTMLElement;
    expect(within(kafka).getByText(/Kolejka zdarzeń/)).toBeInTheDocument();
    expect(kafka).toHaveAttribute("data-glossary", "kafka");

    const kubernetes = screen.getByText("Kubernetes").closest("li") as HTMLElement;
    // Hasło w trakcie researchu nie ma jeszcze zdania — nie pokazujemy zaślepki.
    expect(within(kubernetes).queryByText(/Szukam opisu/)).toBeNull();
    expect(kubernetes).not.toHaveAttribute("data-glossary");
  });

  it("krytyczne stoją w osobnej grupie, reszta w „Musi mieć” i „Mile widziane”", async () => {
    renderSummary();
    const critical = (await screen.findByText("Krytyczne")).parentElement as HTMLElement;
    expect(within(critical).getByText("Java 17")).toBeInTheDocument();
    expect(within(critical).queryByText("Kafka")).toBeNull();
    expect(screen.getByText("Java 17").closest("li")).toHaveAttribute("data-critical", "true");

    const must = screen.getByText("Musi mieć").parentElement as HTMLElement;
    expect(within(must).getByText("Kafka")).toBeInTheDocument();
    const nice = screen.getByText("Mile widziane").parentElement as HTMLElement;
    expect(within(nice).getByText("Kubernetes")).toBeInTheDocument();
  });

  it("„Szukaj w CV” przekazuje nazwę wymagania", async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    renderSummary(onPick);
    await user.click(await screen.findByRole("button", { name: "Szukaj „Kafka” w CV" }));
    expect(onPick).toHaveBeenCalledWith("Kafka");
  });

  it("bez obsługi kliknięcia nie ma przycisków, warunki rekrutacji zostają", async () => {
    renderSummary();
    await screen.findByText("Kafka");
    expect(screen.queryByRole("button", { name: /Szukaj/ })).toBeNull();
    const conditions = screen.getByRole("region", { name: "Warunki rekrutacji" });
    expect(within(conditions).getByText(/^do 150(,00)? PLN\/h$/)).toBeInTheDocument();
    expect(within(conditions).getByText("2 dni w biurze")).toBeInTheDocument();
  });
});
