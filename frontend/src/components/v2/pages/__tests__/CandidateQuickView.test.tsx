import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import api from "@/lib/api";
import { CandidateQuickView } from "@/components/v2/pages/CandidateQuickView";
import { useAuthStore } from "@/store/auth";

const push = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn(), post: vi.fn() },
  extractErrorMsg: () => "",
  phase5Api: {
    clientsLookup: () => Promise.resolve({ data: [{ id: 5, name: "Bank SA" }] }),
    conflicts: { create: vi.fn() },
  },
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

function setSourcingAccess(
  access: "read" | "write",
  impersonating = false,
  role: "recruiter" | "user" = "recruiter",
) {
  const user = {
    id: 12,
    email: "rekruter@example.com",
    name: "Rekruter",
    role,
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    effective_section_access: { sourcing: access },
  } as const;
  useAuthStore.setState({
    user: user as never,
    realUser: impersonating ? ({ ...user, id: 1, role: "admin" } as never) : null,
    hydrated: true,
  });
}

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
      years_experience: 8,
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

describe("CandidateQuickView", () => {
  beforeEach(() => {
    setSourcingAccess("write");
    push.mockReset();
    apiGet.mockReset();
    apiGet.mockImplementation((url: string) => {
      if (url === "/api/candidates/7/quick-view") {
        return Promise.resolve({ data: quickViewData() } as never);
      }
      if (url === "/api/candidates/7/risk") {
        return Promise.resolve({ data: { level: "low" } } as never);
      }
      return Promise.reject(new Error(`Unexpected GET ${url}`));
    });
  });

  it("shows identity, facts, contact, processes and the latest note — nothing more", async () => {
    render(
      <CandidateQuickView candidateId={7} onClose={vi.fn()} rateLookup={() => "160 zł/h"} />,
      { wrapper },
    );

    const fullName = "Jan Adam Maksymilian Kowalski-Wiśniewski";
    const headings = await screen.findAllByRole("heading", { name: fullName });
    expect(headings).toHaveLength(2);
    expect(headings[1]).toHaveClass("whitespace-nowrap");
    expect(screen.getByText("JK")).toBeInTheDocument();
    expect(screen.getByText("Cloud Architect · 8 lat")).toBeInTheDocument();
    expect(screen.getByText("Aktywny")).toBeInTheDocument();

    const facts = screen.getByLabelText("Najważniejsze fakty");
    expect(within(facts).getByText("Otwarty na oferty · wypowiedzenie 2 mies.")).toBeInTheDocument();
    expect(within(facts).getByText("160 zł/h")).toBeInTheDocument();
    expect(within(facts).getByText("Warszawa, Polska")).toBeInTheDocument();

    expect(
      screen.getByText("jan.adam.maksymilian.kowalski-wisniewski@example.com"),
    ).toBeInTheDocument();
    expect(screen.getByText("+48 500 100 200")).toBeInTheDocument();

    expect(screen.getByText("Platform Engineer")).toBeInTheDocument();
    expect(screen.getByText("Rozmowa techniczna")).toBeInTheDocument();
    // Tylko NAJNOWSZA notatka.
    expect(screen.getByText("Rozmowa techniczna poszła bardzo dobrze.")).toBeInTheDocument();
    expect(screen.getByText(/Piotr Zieliński/)).toBeInTheDocument();
    expect(screen.queryByText("Notatka z importu.")).toBeNull();

    // Wycięte z podglądu: podsumowanie AI, umiejętności, źródło, CV, notatnik.
    expect(screen.queryByText("Podsumowanie AI")).toBeNull();
    expect(screen.queryByText("Kubernetes")).toBeNull();
    expect(screen.queryByText("Anna Kowalska")).toBeNull();
    expect(screen.queryByRole("button", { name: "Otwórz CV" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Dodaj notatkę" })).toBeNull();
    expect(apiGet).not.toHaveBeenCalledWith(
      "/api/candidates/7/documents?kind=cv",
      expect.anything(),
    );
  });

  it("missing rate reads as „brak”, an unknown one as a dash", async () => {
    const { unmount } = render(
      <CandidateQuickView candidateId={7} onClose={vi.fn()} rateLookup={() => null} />,
      { wrapper },
    );
    const facts = await screen.findByLabelText("Najważniejsze fakty");
    expect(within(facts).getByText("brak")).toBeInTheDocument();
    unmount();

    render(<CandidateQuickView candidateId={7} onClose={vi.fn()} />, { wrapper });
    const facts2 = await screen.findByLabelText("Najważniejsze fakty");
    expect(within(facts2).getByText("—")).toBeInTheDocument();
  });

  it("footer: assign, open profile, then the small more menu", async () => {
    render(<CandidateQuickView candidateId={7} onClose={vi.fn()} />, {
      wrapper,
    });

    await screen.findByRole("button", { name: "Otwórz profil" });
    const footer = screen.getByLabelText("Akcje kandydata");
    const names = within(footer)
      .getAllByRole("button")
      .map((button) => button.getAttribute("aria-label") ?? button.textContent?.trim());
    expect(names).toEqual([
      "Przypisz do rekrutacji",
      "Otwórz profil",
      "Więcej akcji kandydata",
    ]);
  });

  it("„Wszystkie” opens the profile on the recruitments tab", async () => {
    const onClose = vi.fn();
    render(<CandidateQuickView candidateId={7} onClose={onClose} />, { wrapper });
    await userEvent.click(await screen.findByRole("button", { name: "Wszystkie" }));
    expect(onClose).toHaveBeenCalled();
    expect(push.mock.calls[0][0]).toMatch(/^\/candidates\/7\?/);
    expect(push.mock.calls[0][0]).toContain("recruitments");
  });

  it.each([
    ["read access", "read", false],
    ["impersonation", "write", true],
  ] as const)(
    "hides sourcing mutations for %s while keeping read actions",
    async (_label, access, impersonating) => {
      setSourcingAccess(access, impersonating);

      render(<CandidateQuickView candidateId={7} onClose={vi.fn()} />, {
        wrapper,
      });

      expect(
        await screen.findByRole("button", { name: "Otwórz profil" }),
      ).toBeEnabled();
      expect(
        screen.queryByRole("button", { name: "Przypisz do rekrutacji" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Więcej akcji kandydata" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "+48 500 100 200" }),
      ).not.toBeInTheDocument();
    },
  );

  it("honours an individual write grant above the role default", async () => {
    setSourcingAccess("write", false, "user");

    render(<CandidateQuickView candidateId={7} onClose={vi.fn()} />, {
      wrapper,
    });

    expect(
      await screen.findByRole("button", { name: "Przypisz do rekrutacji" }),
    ).toBeEnabled();
  });

  it("marks as employed from the more menu through the anchored popover", async () => {
    render(<CandidateQuickView candidateId={7} onClose={vi.fn()} />, {
      wrapper,
    });

    await userEvent.click(
      await screen.findByRole("button", { name: "Więcej akcji kandydata" }),
    );
    await userEvent.click(
      await screen.findByRole("menuitem", {
        name: "Oznacz jako zatrudnionego",
      }),
    );

    expect(
      await screen.findByRole("heading", { name: "Oznacz jako zatrudnionego" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Klient")).toBeInTheDocument();
    expect(screen.queryByRole("menuitem")).toBeNull();
  });

  it("shows the employed state as a disabled menu item", async () => {
    apiGet.mockImplementation((url: string) => {
      if (url === "/api/candidates/7/quick-view") {
        const data = quickViewData();
        return Promise.resolve({
          data: {
            ...data,
            candidate: {
              ...data.candidate,
              employment: { state: "employed_at_client" },
            },
          },
        } as never);
      }
      return Promise.resolve({ data: {} } as never);
    });

    render(<CandidateQuickView candidateId={7} onClose={vi.fn()} />, {
      wrapper,
    });

    await userEvent.click(
      await screen.findByRole("button", { name: "Więcej akcji kandydata" }),
    );
    const item = await screen.findByRole("menuitem", {
      name: "Oznaczono jako zatrudnionego",
    });
    expect(item).toHaveAttribute("aria-disabled", "true");
  });

  it("offers click-to-call only when CloudTalk is enabled", async () => {
    const { unmount } = render(
      <CandidateQuickView candidateId={7} onClose={vi.fn()} />,
      { wrapper },
    );
    expect(await screen.findByText("+48 500 100 200")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "+48 500 100 200" }),
    ).not.toBeInTheDocument();
    unmount();

    const base = apiGet.getMockImplementation()!;
    apiGet.mockImplementation((url: string, config?: unknown) => {
      if (url === "/api/calls/cloudtalk-status") {
        return Promise.resolve({ data: { enabled: true } } as never);
      }
      return base(url, config as never);
    });
    render(<CandidateQuickView candidateId={7} onClose={vi.fn()} />, {
      wrapper,
    });
    expect(
      await screen.findByRole("button", { name: "+48 500 100 200" }),
    ).toBeInTheDocument();
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
