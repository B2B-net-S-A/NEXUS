import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  stats: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("tab=draft"),
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/lib/api", () => ({
  contractorsApi: {
    list: (...args: unknown[]) => mocks.list(...args),
    stats: (...args: unknown[]) => mocks.stats(...args),
  },
}));

vi.mock("@/components/v2/modals/DraftCompletionModal", () => ({
  DraftCompletionModal: () => null,
}));

import {
  AtOurClientBanner,
  type EmploymentInfo,
} from "@/components/v2/CandidateHighlights";
import { ContractorsListV2 } from "@/components/v2/pages/ContractorsListV2";

function renderWithQueryClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

describe("powiązania kandydata i kontraktora", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.list.mockResolvedValue({
      data: {
        items: [
          {
            contract_id: 91,
            candidate: {
              id: 7,
              name: "Jan",
              lastname: "Kowalski",
              email: "jan@example.com",
            },
            client_name: "Nordea",
            job_title: "Cloud Engineer",
            status: "ready_for_signature",
            start_date: "2026-08-01",
            end_date: null,
            rate_candidate: null,
            rate_client: null,
            rate_unit: "hourly",
            currency: "PLN",
            margin: null,
            contract_type: "b2b",
            work_mode: null,
            missing_fields: [],
          },
        ],
        total: 1,
        page: 1,
        page_size: 50,
      },
    });
    mocks.stats.mockResolvedValue({
      data: {
        draft: 1,
        drafts_incomplete: 0,
        active: 0,
        ending: 0,
      },
    });
  });

  it("profil kandydata pokazuje klienta i prowadzi do tego samego kontraktu", () => {
    const employment: EmploymentInfo = {
      state: "employed_at_client",
      client_id: 3,
      client_name: "Nordea",
      contract_id: 91,
      job_id: 20,
      source: "pipeline",
    };

    render(<AtOurClientBanner employment={employment} />);

    expect(screen.getByText("Zatrudniony u: Nordea")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Przejdź do kontraktora/ }),
    ).toHaveAttribute("href", "/contracts/91?from=candidate");
  });

  it("lista kontraktorów pokazuje oczekujący status i osobne linki w obie strony", async () => {
    renderWithQueryClient(<ContractorsListV2 />);

    expect(
      await screen.findByRole("link", { name: "Jan Kowalski" }),
    ).toHaveAttribute("href", "/candidates/7");
    expect(screen.getByText("Do aktywacji")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Szczegóły/ })).toHaveAttribute(
      "href",
      "/contracts/91?from=contractors",
    );
    expect(mocks.list).toHaveBeenCalledWith({
      status: "draft",
      page: 1,
      page_size: 50,
    });
  });
});
