/**
 * Pasek wymagań nad CV w panelu osoby (13.10.2026): wymagania krytyczne albo
 * pierwsze „Musi mieć”, warunki w jednej linii, „Szukaj w CV” z chipa.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { JobRequirementsStrip } from "@/components/champion/JobRequirementsStrip";

const getMock = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    championApi: { ...actual.championApi, get: (...args: unknown[]) => getMock(...args) },
  };
});

const BASICS = { rate_value: 150, work_mode: "hybrid", onsite_days_per_week: 2, language: "EN B2" };

function response(must: string[], critical: string[], basics: Record<string, unknown> = BASICS) {
  return {
    data: {
      job_id: 5,
      champion_profile: {
        basics,
        stack: { must: must.map((name) => ({ name })), nice: [{ name: "Kubernetes" }], notes: "" },
      },
      critical_resolution: {
        decided: critical.length > 0,
        stored: critical,
        suggested: [],
        effective: critical,
        search_rows: [],
      },
    },
  };
}

function renderStrip(props: { onPick?: (name: string) => void; onShowAll?: () => void } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <JobRequirementsStrip
        jobId={5}
        onPickRequirement={props.onPick ?? vi.fn()}
        onShowAll={props.onShowAll ?? vi.fn()}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  getMock.mockReset();
  getMock.mockResolvedValue(response(["Java 17", "Kafka"], ["Java 17"]));
});

describe("JobRequirementsStrip", () => {
  it("pokazuje wymagania krytyczne i warunki w jednej linii", async () => {
    renderStrip();
    const strip = await screen.findByTestId("requirements-strip");
    expect(await within(strip).findByRole("button", { name: "Szukaj „Java 17” w CV" })).toBeInTheDocument();
    expect(within(strip).getByText("Krytyczne")).toBeInTheDocument();
    // „Musi mieć” spoza krytycznych i „Mile widziane” zostają w pełnej liście.
    expect(within(strip).queryByText("Kafka")).toBeNull();
    expect(within(strip).queryByText("Kubernetes")).toBeNull();

    const line = within(strip).getByTestId("requirements-strip-conditions");
    expect(line).toHaveTextContent(/^do 150(,00)? PLN\/h · hybrydowo · biuro 2 dni\/tydz\. · EN B2$/);
    expect(line).toHaveAttribute("title", line.textContent);
  });

  it("bez krytycznych: pierwsze cztery „Musi mieć” i „+N” do pełnej listy", async () => {
    getMock.mockResolvedValue(response(["Java", "Kafka", "Spring", "SQL", "Docker", "AWS"], []));
    const onShowAll = vi.fn();
    const user = userEvent.setup();
    renderStrip({ onShowAll });

    const strip = await screen.findByTestId("requirements-strip");
    expect(await within(strip).findByText("Musi mieć")).toBeInTheDocument();
    const chips = within(strip).getAllByRole("button", { name: /^Szukaj „/ });
    expect(chips.map((chip) => chip.textContent)).toEqual(["Java", "Kafka", "Spring", "SQL"]);

    await user.click(within(strip).getByRole("button", { name: "Jeszcze 2 — wszystkie wymagania" }));
    expect(onShowAll).toHaveBeenCalledTimes(1);
  });

  it("chip szuka wymagania w CV", async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    renderStrip({ onPick });
    await user.click(await screen.findByRole("button", { name: "Szukaj „Java 17” w CV" }));
    expect(onPick).toHaveBeenCalledWith("Java 17");
  });

  it("warunki bez wartości nie trafiają do linii", async () => {
    getMock.mockResolvedValue(response(["Java 17"], ["Java 17"], { start_date: "2026-11-11", seniority_min_years: 5 }));
    renderStrip();
    const line = await screen.findByTestId("requirements-strip-conditions");
    expect(line).toHaveTextContent(/^start 2026-11-11 · 5\+ lat$/);
    expect(screen.queryByText(/nie podano/)).toBeNull();
  });

  it("„Wszystkie wymagania” otwiera pełną listę", async () => {
    const onShowAll = vi.fn();
    const user = userEvent.setup();
    renderStrip({ onShowAll });
    await screen.findByRole("button", { name: "Szukaj „Java 17” w CV" });
    await user.click(screen.getByRole("button", { name: "Wszystkie wymagania" }));
    expect(onShowAll).toHaveBeenCalledTimes(1);
  });

  it("rekrutacja bez wymagań i warunków mówi to wprost", async () => {
    getMock.mockResolvedValue(response([], [], {}));
    renderStrip();
    expect(await screen.findByText("Rekrutacja nie ma jeszcze wymagań.")).toBeInTheDocument();
    expect(screen.queryByTestId("requirements-strip-conditions")).toBeNull();
  });

  it("awaria odczytu nie wygląda jak brak wymagań i daje „Ponów”", async () => {
    getMock.mockRejectedValue(new Error("500"));
    const user = userEvent.setup();
    renderStrip();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wczytać wymagań.");
    expect(screen.queryByText("Rekrutacja nie ma jeszcze wymagań.")).toBeNull();

    getMock.mockResolvedValue(response(["Java 17"], ["Java 17"]));
    await user.click(screen.getByRole("button", { name: "Ponów" }));
    await waitFor(() => expect(getMock).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("button", { name: "Szukaj „Java 17” w CV" })).toBeInTheDocument();
  });

  it("w trakcie wczytywania pasek ma szkielet", () => {
    getMock.mockReturnValue(new Promise(() => undefined));
    renderStrip();
    expect(screen.getByTestId("requirements-strip")).toHaveAttribute("aria-busy", "true");
  });
});
