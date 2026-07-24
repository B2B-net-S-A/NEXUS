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

function quickViewData() {
  return {
    candidate: {
      id: 7,
      name: "Jan Adam Maksymilian",
      lastname: "Kowalski-Wiśniewski",
      email: "jan.adam.maksymilian.kowalski-wisniewski@example.com",
      phone: "+48 500 100 200",
      status: "active",
      location: "Warszawa, Polska",
      skills: [
        "AWS",
        "Azure",
        "Kubernetes",
        "Terraform",
        "Docker",
        "CI/CD",
        "Go",
        "Python",
        "Rust",
      ],
    },
    current_position: {
      title: "Cloud Architect",
      started_at: "2022",
      precision: "year",
    },
    availability: {
      status: "open_to_offers",
      available_from: null,
      notice_period: 2,
      notice_period_unit: "months",
    },
    source: {
      added_by_name: "Anna Kowalska",
      acquisition_source: "LinkedIn",
      imported_via: "TRAFFIT",
    },
    current_recruitments: [
      {
        job_id: 11,
        job_title: "Platform Engineer",
        client_name: "Bank SA",
        stage_id: 31,
        stage_name: "Rozmowa techniczna",
        moved_at: "2026-07-13T08:00:00Z",
        moved_by_name: "Ewa Nowak",
      },
    ],
    recent_notes: [
      {
        id: 1,
        content: "Rozmowa techniczna poszła bardzo dobrze.",
        created_at: "2026-07-13T08:00:00Z",
        author_name: "Piotr Zieliński",
      },
      {
        id: 2,
        content: "Notatka z importu.",
        created_at: "2026-07-12T08:00:00Z",
        author_name: null,
      },
    ],
    cv_highlights: {
      bullets: [
        "Senior Cloud Architect z 10-letnim doświadczeniem.",
        "Technologie: AWS, Kubernetes, Terraform.",
      ],
    },
    capabilities: {
      can_assign: true,
      can_mark_employed: true,
      can_view_documents: true,
      can_open_full_profile: true,
    },
  };
}

function documentData() {
  return {
    id: 3,
    filename: "JanKowalski.pdf",
    content_type: "application/pdf",
    size_bytes: 1024,
    document_kind: "cv",
    is_primary: true,
    uploaded_at: "2026-07-10T08:00:00Z",
    external_source: "traffit",
    created_at: "2026-07-10T08:00:00Z",
  };
}

describe("CandidateQuickView", () => {
  beforeEach(() => {
    push.mockReset();
    apiGet.mockReset();
    apiGet.mockImplementation((url: string) => {
      if (url === "/api/candidates/7/quick-view") {
        return Promise.resolve({ data: quickViewData() } as never);
      }
      if (url === "/api/candidates/7/risk") {
        return Promise.resolve({ data: { level: "low" } } as never);
      }
      if (url === "/api/candidates/7/documents?kind=cv") {
        return Promise.resolve({ data: [documentData()] } as never);
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });
  });

  it("shows complete identity, contact, source, pipeline, AI and note authors", async () => {
    const onClose = vi.fn();
    render(<CandidateQuickView candidateId={7} onClose={onClose} />, {
      wrapper,
    });

    const fullName = "Jan Adam Maksymilian Kowalski-Wiśniewski";
    const headings = await screen.findAllByRole("heading", { name: fullName });
    expect(headings).toHaveLength(2);
    expect(headings[1]).toHaveClass("whitespace-nowrap");
    expect(headings[1]).not.toHaveClass("truncate");
    expect(screen.getByText("JK")).toBeInTheDocument();
    expect(screen.getByText("Cloud Architect")).toBeInTheDocument();
    expect(
      screen.getByText(
        "jan.adam.maksymilian.kowalski-wisniewski@example.com",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("+48 500 100 200")).toBeInTheDocument();
    expect(screen.getByText("Warszawa, Polska")).toBeInTheDocument();
    expect(screen.getByText("Otwarty na oferty · 2 mies.")).toBeInTheDocument();

    expect(screen.getByText("Anna Kowalska")).toBeInTheDocument();
    expect(screen.getByText("LinkedIn")).toBeInTheDocument();
    expect(screen.getByText("TRAFFIT")).toBeInTheDocument();
    expect(screen.getByText("Rozmowa techniczna")).toBeInTheDocument();
    expect(screen.getByText(/Ewa Nowak/)).toBeInTheDocument();
    expect(
      screen.getByText("Senior Cloud Architect z 10-letnim doświadczeniem."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Piotr Zieliński/)).toBeInTheDocument();
    expect(screen.getByText(/System \/ import/)).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: "Przypisz do rekrutacji" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Oznacz jako zatrudnionego" }),
    ).toBeEnabled();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Otwórz CV" })).toBeEnabled(),
    );
    expect(screen.getByRole("button", { name: "Pełny profil" })).toBeEnabled();
    expect(screen.queryByText("Rust")).not.toBeInTheDocument();
    expect(
      await screen.findByText("Sugerowane rekrutacje test"),
    ).toBeInTheDocument();

    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: "Zamknij szybki podgląd" }),
      ).toHaveLength(1),
    );
    expect(apiGet).not.toHaveBeenCalledWith(
      "/api/candidates/7/ai-profile",
      expect.anything(),
    );
    expect(apiGet).not.toHaveBeenCalledWith(
      "/api/candidates/7/history",
      expect.anything(),
    );
  });

  it("disables the CV action with an explanation when no CV is classified", async () => {
    apiGet.mockImplementation((url: string) => {
      if (url === "/api/candidates/7/quick-view") {
        return Promise.resolve({ data: quickViewData() } as never);
      }
      if (url === "/api/candidates/7/risk") {
        return Promise.resolve({ data: { level: "low" } } as never);
      }
      if (url === "/api/candidates/7/documents?kind=cv") {
        return Promise.resolve({ data: [] } as never);
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });

    render(<CandidateQuickView candidateId={7} onClose={vi.fn()} />, {
      wrapper,
    });

    const button = await screen.findByRole("button", { name: "Otwórz CV" });
    await waitFor(() => expect(button).toBeDisabled());
    expect(button).toHaveAttribute("title", "Brak sklasyfikowanego CV");
  });

  it.each([
    [404, "Nie znaleziono kandydata", "Kandydat mógł zostać usunięty."],
    [403, "Nie masz dostępu do tego profilu", null],
  ])("finishes loading with a dedicated %s state", async (status, title, copy) => {
    apiGet.mockImplementation((url: string) => {
      if (url === "/api/candidates/7/quick-view") {
        return Promise.reject({ response: { status } });
      }
      return Promise.resolve({ data: {} } as never);
    });

    render(<CandidateQuickView candidateId={7} onClose={vi.fn()} />, {
      wrapper,
    });

    expect(await screen.findByText(title)).toBeInTheDocument();
    if (copy) expect(screen.getByText(copy)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Spróbuj ponownie" }),
    ).not.toBeInTheDocument();
  });

  it.each([
    ["network", new Error("offline")],
    ["5xx", { response: { status: 500 } }],
  ])("recovers from a %s error after retry", async (_label, initialError) => {
    let detailAttempts = 0;
    apiGet.mockImplementation((url: string) => {
      if (url === "/api/candidates/7/quick-view") {
        detailAttempts += 1;
        if (detailAttempts === 1) return Promise.reject(initialError);
        return Promise.resolve({ data: quickViewData() } as never);
      }
      if (url === "/api/candidates/7/risk") {
        return Promise.resolve({ data: { level: "low" } } as never);
      }
      if (url === "/api/candidates/7/documents?kind=cv") {
        return Promise.resolve({ data: [documentData()] } as never);
      }
      return Promise.resolve({ data: {} } as never);
    });

    render(<CandidateQuickView candidateId={7} onClose={vi.fn()} />, {
      wrapper,
    });

    const retry = await screen.findByRole("button", {
      name: "Spróbuj ponownie",
    });
    retry.click();

    expect(
      await screen.findAllByRole("heading", {
        name: "Jan Adam Maksymilian Kowalski-Wiśniewski",
      }),
    ).toHaveLength(2);
  });
});
