import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ContactOversightPanel } from "@/components/candidate-contact/ContactOversightPanel";
import {
  candidateContactApi,
  type CandidateContactCase,
} from "@/lib/candidate-contact";

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showError: vi.fn(),
    showSuccess: vi.fn(),
  }),
}));

vi.mock("@/lib/candidate-contact", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/candidate-contact")>();
  return {
    ...actual,
    candidateContactApi: {
      ...actual.candidateContactApi,
      oversight: vi.fn(),
      reassign: vi.fn(),
    },
  };
});

const exceptionCase: CandidateContactCase = {
  id: 88,
  status: "unassigned",
  due_at: "2026-07-28T16:00:00Z",
  callback_at: null,
  attempts_in_cycle: 0,
  version: 6,
  owner: null,
  candidate: {
    id: 9,
    name: "Ewa",
    lastname: "Kowalska",
    phone: "+48 600 100 200",
  },
  opportunities: [
    {
      job_id: 17,
      job_title: "Data Engineer",
      owner: { id: 4, name: "Piotr Nowak" },
    },
  ],
};

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("ContactOversightPanel", () => {
  beforeEach(() => {
    vi.mocked(candidateContactApi.oversight).mockResolvedValue({
      counters: {
        overdue: 1,
        unassigned: 1,
        awaiting_capacity: 0,
        blocked_no_phone: 0,
        ownerless_handoff: 2,
        reassigned_today: 4,
        traffit_lag_seconds: 120,
        traffit_status: "error",
        traffit_last_error: "Odrzucony filtr recruitment_history",
        traffit_exception_count: 3,
      },
      items: [exceptionCase],
      next_cursor: null,
    });
    vi.mocked(candidateContactApi.reassign).mockResolvedValue({
      ...exceptionCase,
      status: "queued",
      version: 7,
      owner: { id: 5, name: "Anna Lis" },
    });
  });

  it("sends an audited automatic reassign with the current version", async () => {
    render(<ContactOversightPanel featureEnabledOverride />, { wrapper });

    fireEvent.click(
      await screen.findByRole("button", { name: "Przepisz automatycznie" }),
    );

    await waitFor(() =>
      expect(candidateContactApi.reassign).toHaveBeenCalledWith(88, {
        expected_version: 6,
        target_user_id: null,
        reason:
          "Automatyczne przepisanie z panelu nadzoru Head of Recruitment",
      }),
    );
  });

  it("shows Traffit lag, status, exception count, and last error", async () => {
    render(<ContactOversightPanel featureEnabledOverride />, { wrapper });

    expect(await screen.findByText(/Lag Traffit: 2 min/)).toHaveTextContent(
      "Status: error; wyjątki: 3",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Ostatni błąd intake Traffit: Odrzucony filtr recruitment_history",
    );
    expect(screen.getByText("Przepisane dziś").previousElementSibling).toHaveTextContent(
      "4",
    );
    expect(
      screen.getByText("Handoff bez opiekuna").previousElementSibling,
    ).toHaveTextContent("2");
  });
});
