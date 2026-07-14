import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/lib/api";
import { CandidateQuickView } from "@/components/v2/pages/CandidateQuickView";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn(), post: vi.fn() },
  extractErrorMsg: () => "",
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }),
}));

vi.mock("@/components/ui/sheet", () => ({
  SheetTitle: ({ children }: { children: React.ReactNode }) => (
    <h2 className="sr-only">{children}</h2>
  ),
  SheetDescription: ({ children }: { children: React.ReactNode }) => (
    <p className="sr-only">{children}</p>
  ),
}));

vi.mock("@/hooks/useCandidateNavigation", () => ({
  useCandidateNavigation: () => ({
    position: 1,
    total: 1,
    hasPrev: false,
    hasNext: false,
    isLoading: false,
    error: null,
    goPrev: vi.fn(),
    goNext: vi.fn(),
    retry: vi.fn(),
  }),
}));

vi.mock("@/components/v2/DeferUntilVisible", () => ({
  DeferUntilVisible: ({ children }: { children: React.ReactNode }) => children,
}));

vi.mock("@/components/SuggestedJobsWidget", () => ({
  SuggestedJobsWidget: () => <div>Sugerowane rekrutacje test</div>,
}));

vi.mock("@/components/calls/CallButton", () => ({
  default: ({ phone }: { phone: string }) => <button>{phone}</button>,
}));

vi.mock("@/components/v2/modals/QuickAssignV2", () => ({
  QuickAssignV2: () => null,
}));

vi.mock("@/components/v2/CandidateHighlights", () => ({
  AtOurClientBanner: () => null,
}));

vi.mock("@/components/v2/RiskBadge", () => ({
  RiskBadge: () => <span>Niskie ryzyko</span>,
}));

const apiGet = vi.mocked(api.get);

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("CandidateQuickView", () => {
  beforeEach(() => {
    push.mockReset();
    apiGet.mockReset();
    apiGet.mockImplementation((url: string) => {
      if (url === "/api/candidates/7") {
        return Promise.resolve({
          data: {
            id: 7,
            name: "Jan Adam",
            lastname: "Kowalski",
            email: "jan@example.com",
            phone: "+48 500 100 200",
            status: "active",
            position: "Cloud Architect",
            location: "Warszawa",
            cv_filename: "JanKowalski.pdf",
            skills: ["AWS", "Azure", "Kubernetes", "Terraform", "Docker", "CI/CD", "Go"],
          },
        } as never);
      }
      if (url === "/api/candidates/7/risk") {
        return Promise.resolve({ data: { level: "low" } } as never);
      }
      if (url === "/api/candidates/7/history") {
        return Promise.resolve({
          data: {
            jobs: [
              {
                job_id: 11,
                job_title: "Platform Engineer",
                latest_stage: "screening",
                last_moved_at: "2026-07-13T08:00:00Z",
              },
            ],
          },
        } as never);
      }
      if (url === "/api/candidates/7/ai-profile") {
        return Promise.resolve({ data: { summary: "Mocny profil chmurowy." } } as never);
      }
      if (url === "/api/candidates/7/timeline?limit=3") {
        return Promise.resolve({
          data: { timeline: [{ id: 1, type: "note", content: "Rozmowa techniczna" }] },
        } as never);
      }
      if (url === "/api/candidates/7/documents") {
        return Promise.resolve({
          data: [{ id: 3, filename: "JanKowalski.pdf", is_primary: true }],
        } as never);
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });
  });

  it("renders the compact hierarchy, correct initials and a single close", async () => {
    const onClose = vi.fn();
    render(
      <CandidateQuickView candidateId={7} onClose={onClose} />,
      { wrapper },
    );

    expect(
      await screen.findAllByRole("heading", { name: "Jan Adam Kowalski" }),
    ).toHaveLength(2);
    expect(screen.getByText("JK")).toBeInTheDocument();
    expect(screen.getAllByText("Cloud Architect").length).toBeGreaterThan(0);
    expect(await screen.findByText("Platform Engineer")).toBeInTheDocument();
    expect(await screen.findByText("JanKowalski.pdf")).toBeInTheDocument();
    expect(await screen.findByText("Sugerowane rekrutacje test")).toBeInTheDocument();
    expect(screen.queryByText("Go")).not.toBeInTheDocument();

    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: "Zamknij szybki podgląd" }),
      ).toHaveLength(1),
    );
  });

  it("finishes loading with a dedicated 404 state", async () => {
    apiGet.mockImplementation((url: string) => {
      if (url === "/api/candidates/7") {
        return Promise.reject({ response: { status: 404 } });
      }
      return Promise.resolve({ data: {} } as never);
    });

    render(<CandidateQuickView candidateId={7} onClose={vi.fn()} />, {
      wrapper,
    });

    expect(await screen.findByText("Nie znaleziono kandydata")).toBeInTheDocument();
    expect(screen.getByText("Kandydat mógł zostać usunięty.")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Spróbuj ponownie" }),
    ).not.toBeInTheDocument();
  });
});
