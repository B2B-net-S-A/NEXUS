import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { JobTwinsPayload, TwinItem } from "@/lib/job-twins-api";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => mocks.get(...args) },
  api: { get: (...args: unknown[]) => mocks.get(...args) },
}));

import { JobTwinChipView } from "../JobTwinChip";
import { ManualTwinPicker } from "../TwinSuggestionsButton";

function twin(id: number, ref: string): TwinItem {
  return {
    id,
    title: "Analityk",
    reference_number: null,
    client_reference: ref,
    client_id: 1,
    client_name: "Klient Demo",
    delivery_lead_id: 1,
    delivery_lead_name: "Anna K.",
    status: "published",
    is_open: true,
    p1: false,
    budget_min_hourly: null,
    budget_hourly: null,
    remote_policy: null,
    onsite_days_per_week: null,
    onsite_days_per_month: null,
    location: null,
    people_count: 0,
    question_pairs: [],
  };
}

function httpError(status: number) {
  return Object.assign(new Error(String(status)), { response: { status } });
}

function payload(over: Partial<JobTwinsPayload>): JobTwinsPayload {
  return { job_id: 10, can_manage: true, max_twins: 3, twins: [], ...over };
}

describe("Ręczne łączenie bliźniaka na pasku rekrutacji (10.11.2026)", () => {
  it("shows „Połącz bliźniaka” to someone who may link and opens the picker without a chosen request", () => {
    const onEdit = vi.fn();
    render(<JobTwinChipView data={payload({})} onEdit={onEdit} />);
    fireEvent.click(screen.getByRole("button", { name: /Połącz bliźniaka/ }));
    expect(onEdit).toHaveBeenCalledWith("new");
  });

  it("shows nothing to a recruiter without a twin", () => {
    const { container } = render(<JobTwinChipView data={payload({ can_manage: false })} onEdit={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("recruiter sees the twin chip but no link button", () => {
    render(<JobTwinChipView data={payload({ can_manage: false, twins: [twin(11, "43134")] })} onEdit={vi.fn()} />);
    expect(screen.getByTestId("job-twin-chip")).toHaveTextContent("43134");
    expect(screen.queryByTestId("job-twin-link")).toBeNull();
  });

  it("offers „+ Bliźniak” below the limit and nothing more at the limit", () => {
    const { rerender } = render(<JobTwinChipView data={payload({ twins: [twin(11, "43134")] })} onEdit={vi.fn()} />);
    expect(screen.getByTestId("job-twin-link")).toHaveTextContent("Bliźniak");
    rerender(
      <JobTwinChipView data={payload({ twins: [twin(11, "A"), twin(12, "B"), twin(13, "C")] })} onEdit={vi.fn()} />,
    );
    expect(screen.queryByTestId("job-twin-link")).toBeNull();
  });
});

describe("Połącz wybrane rekrutacje na liście (10.11.2026)", () => {
  beforeEach(() => {
    mocks.get.mockReset();
  });

  function renderPicker(onPick = vi.fn()) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <ManualTwinPicker onPick={onPick} />
      </QueryClientProvider>,
    );
    return onPick;
  }

  it("searches only open requests and hands over the first one with its label", async () => {
    mocks.get.mockResolvedValue({
      data: {
        items: [
          {
            id: 789208,
            title: "DORA Change Specialist",
            reference_number: "NORD/074",
            client_reference: "43157",
            client_name: "Klient Demo",
          },
        ],
      },
    });
    const onPick = renderPicker();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "DORA" } });
    fireEvent.click(await screen.findByRole("button", { name: "Wybierz" }));
    expect(mocks.get).toHaveBeenCalledWith(
      "/api/jobs",
      expect.objectContaining({ params: { q: "DORA", open_only: true, page_size: 8 } }),
    );
    expect(onPick).toHaveBeenCalledWith(789208, "43157 DORA Change Specialist");
  });

  it("does not search for a single letter and says when nothing open matches", async () => {
    mocks.get.mockResolvedValue({ data: { items: [] } });
    renderPicker();
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "D" } });
    await new Promise((r) => setTimeout(r, 400));
    expect(mocks.get).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "Zzz" } });
    expect(await screen.findByText(/Nic otwartego nie pasuje do „Zzz”/)).toBeInTheDocument();
  });

  it("shows a failed search as an error, not as an empty result", async () => {
    mocks.get.mockRejectedValue(httpError(500));
    renderPicker();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "DORA" } });
    expect(await screen.findByText("Nie udało się wyszukać rekrutacji.")).toBeInTheDocument();
    expect(screen.queryByText(/Nic otwartego/)).toBeNull();
  });
});
