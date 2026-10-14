/**
 * Fakt „Rekruter” w nagłówku rekrutacji (14.10.2026, makiety A3/A4/K1): kto
 * pracuje (zalogowana osoba jako „Ty”), bursztynowe „Bez rekrutera”,
 * przerywana propozycja automatu i okienko z panelem zespołu oraz Delivery
 * Leadem — bez wychodzenia z Tablicy.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  JobRecruiterFact,
  recruiterFactView,
  type JobRecruiterFactJob,
} from "@/components/v2/jobs/JobRecruiterFact";
import type { JobRecruiter } from "@/lib/job-team";
import { useAuthStore, type User } from "@/store/auth";

const apiMock = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
  patch: vi.fn(),
}));
const toast = vi.hoisted(() => ({
  showSuccess: vi.fn(),
  showError: vi.fn(),
  showInfo: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ default: apiMock, api: apiMock }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@/hooks/useCapability", () => ({ useCapability: () => true }));

const ewa: JobRecruiter = {
  user_id: 12,
  name: "Ewa Testowa",
  via: "owner",
  proposed: false,
  assigned_by_name: "Olga Wzorcowa",
};
const piotr: JobRecruiter = {
  user_id: 13,
  name: "Piotr Makietowy",
  via: "collaborator",
  proposed: false,
  assigned_by_name: null,
};
const proposal: JobRecruiter = {
  user_id: 14,
  name: "Jan Próbny",
  via: "assignment",
  proposed: true,
  assigned_by_name: null,
};

const deliveryLead: User = {
  id: 7,
  name: "Olga Wzorcowa",
  email: "dl@example.com",
  role: "delivery_lead",
  roles: ["delivery_lead"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
  effective_section_access: { pipeline: "write" },
};

function job(recruiters: JobRecruiter[]): JobRecruiterFactJob {
  return {
    status: "published",
    primary_owner: recruiters.some((r) => r.via === "owner")
      ? { id: 12, name: "Ewa Testowa", email: "ewa@example.com", role: "recruiter" }
      : null,
    recruiters,
    can_staff: true,
    delivery_lead_user: { name: "Olga Wzorcowa" },
  };
}

function renderFact(recruiters: JobRecruiter[], onOpenTeam = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <JobRecruiterFact
        jobId={42}
        jobTitle="Analityk KYC"
        job={job(recruiters)}
        canEdit
        onOpenTeam={onOpenTeam}
      />
    </QueryClientProvider>,
  );
  return { onOpenTeam };
}

const fact = () => screen.getByTestId("job-header-recruiter");

describe("recruiterFactView", () => {
  it("pracujący: pierwsza osoba skrótem i „+N”", () => {
    expect(recruiterFactView([ewa, piotr], 99)).toMatchObject({
      kind: "working",
      text: "Ewa T.",
      more: 1,
    });
  });

  it("zalogowana osoba w zespole stoi pierwsza jako „Ty”", () => {
    const view = recruiterFactView([ewa, piotr], 13);
    expect(view).toMatchObject({ kind: "working", text: "Ty", more: 1 });
    expect(view.avatars.map((p) => p.user_id)).toEqual([13, 12]);
  });

  it("sama propozycja automatu to jeszcze nie praca", () => {
    expect(recruiterFactView([proposal], 7)).toMatchObject({
      kind: "proposal",
      text: "propozycja: Jan P.",
    });
  });

  it("nikt — „Bez rekrutera”", () => {
    expect(recruiterFactView([], 7)).toMatchObject({ kind: "none", text: "Bez rekrutera" });
  });
});

describe("JobRecruiterFact", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMock.get.mockResolvedValue({ data: [] });
    useAuthStore.setState({ user: deliveryLead, realUser: null });
  });

  it("fakt mówi, kto pracuje; czytnik ekranu dostaje pełne nazwiska", () => {
    renderFact([ewa, piotr]);
    expect(fact()).toHaveTextContent("Rekruter");
    expect(fact()).toHaveTextContent("Ewa T.");
    expect(fact()).toHaveTextContent("+1");
    expect(fact()).toHaveAccessibleName(
      "Rekruter: Rekruterzy: Ewa Testowa, Piotr Makietowy — zespół rekrutacji",
    );
  });

  it("bez rekrutera — bursztynowe ostrzeżenie; propozycja — przerywana ramka", () => {
    renderFact([]);
    expect(fact()).toHaveTextContent("Bez rekrutera");
    expect(fact()).toHaveAttribute("data-state-kind", "none");
    expect(fact().className).toMatch(/bg-warning-muted/);
  });

  it("klik otwiera okienko z panelem zespołu i Delivery Leadem", async () => {
    const { onOpenTeam } = renderFact([ewa, piotr]);
    await userEvent.click(fact());
    const popover = await screen.findByTestId("job-recruiter-popover");
    expect(within(popover).getByTestId("job-recruiters")).toBeTruthy();
    expect(within(popover).getByText("Ewa Testowa")).toBeTruthy();
    expect(within(popover).getByTestId("job-recruiter-popover-dl")).toHaveTextContent(
      "Olga Wzorcowa",
    );
    await userEvent.click(
      within(popover).getByRole("button", { name: /Kategoria i termin — Profil Championa/ }),
    );
    expect(onOpenTeam).toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByTestId("job-recruiter-popover")).toBeNull());
  });

  it("potwierdzenie „Zdejmij” nie zamyka okienka — chowa je tylko na czas okna", async () => {
    renderFact([ewa, piotr]);
    await userEvent.click(fact());
    const popover = await screen.findByTestId("job-recruiter-popover");
    await userEvent.click(within(popover).getByRole("button", { name: "Zdejmij Piotr Makietowy" }));
    const dialog = await screen.findByRole("dialog", { name: /Zdjąć Piotr Makietowy/ });
    expect(screen.getByTestId("job-recruiter-popover").className).toMatch(/invisible/);
    await userEvent.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    await waitFor(() =>
      expect(screen.getByTestId("job-recruiter-popover").className).not.toMatch(/invisible/),
    );
    expect(apiMock.delete).not.toHaveBeenCalled();
  });
});
