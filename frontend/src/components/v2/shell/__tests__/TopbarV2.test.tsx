import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAuthStore, type User } from "@/store/auth";

// Pasek liczy tylko podpowiedź w polu wyszukiwania — widżety z zapytaniami
// (liga, cele, dzwonki, nieobecni) nie są tu potrzebne.
vi.mock("../BreadcrumbV2", () => ({ BreadcrumbV2: () => null }));
vi.mock("../QuickActionsV2", () => ({ QuickActionsV2: () => null }));
vi.mock("../CommandPaletteV2", () => ({ CommandPaletteV2: () => null }));
vi.mock("../AppearanceMenu", () => ({ AppearanceMenu: () => null }));
vi.mock("../ChatNotificationsDropdown", () => ({ ChatNotificationsDropdown: () => null }));
vi.mock("../CvNotificationsDropdown", () => ({ CvNotificationsDropdown: () => null }));
vi.mock("../JobsNotificationsDropdown", () => ({ JobsNotificationsDropdown: () => null }));
vi.mock("../ContractsNotificationsDropdown", () => ({
  ContractsNotificationsDropdown: () => null,
}));
vi.mock("../InterviewNotificationsDropdown", () => ({
  InterviewNotificationsDropdown: () => null,
}));
vi.mock("@/components/v2/kpi/MyKpiWidget", () => ({ MyKpiWidget: () => null }));
vi.mock("@/components/v2/league/MyLeagueWidget", () => ({ MyLeagueWidget: () => null }));
vi.mock("@/components/v2/my-people/MyPeopleLauncher", () => ({
  MyPeopleTopbarButton: () => null,
}));
vi.mock("@/components/hr/leave/AbsentTodayButton", () => ({ AbsentTodayButton: () => null }));
vi.mock("@/components/hr/approvals/ConsentsTopbarButton", () => ({
  ConsentsTopbarButton: () => null,
}));
vi.mock("@/components/v2/jobs/p0/P0TopbarButton", () => ({ P0TopbarButton: () => null }));
vi.mock("@/components/novelties/NoveltiesTopbarButton", () => ({ NoveltiesTopbarButton: () => null }));

import { TopbarV2 } from "../TopbarV2";

const WORK_HINT = "Szukaj kandydatów, rekrutacji, klientów…";
const SCREEN_HINT = "Przejdź do ekranu…";

function account(role: "recruiter" | "employee"): User {
  return {
    id: 7,
    email: "anna.przykladowa@example.com",
    full_name: "Anna Przykładowa",
    role,
    roles: [role],
  } as unknown as User;
}

function renderTopbar() {
  return render(
    <TopbarV2
      onOpenMobileSidebar={vi.fn()}
      pendingModal={null}
      onClearPendingModal={vi.fn()}
      onOpenCommandPalette={vi.fn()}
    />,
  );
}

afterEach(() => {
  act(() => useAuthStore.setState({ user: null, hydrated: false }));
});

describe("TopbarV2 — podpowiedź w polu wyszukiwania", () => {
  it("przed odczytem konta pokazuje szukanie kandydatów i nie przeskakuje po hydrate", () => {
    act(() => useAuthStore.setState({ user: null, hydrated: false }));
    renderTopbar();

    expect(screen.getByText(WORK_HINT)).toBeInTheDocument();
    expect(screen.queryByText(SCREEN_HINT)).not.toBeInTheDocument();

    act(() => useAuthStore.setState({ user: account("recruiter"), hydrated: true }));
    expect(screen.getByText(WORK_HINT)).toBeInTheDocument();
  });

  it("konto bez sekcji pracy („Pracownik”) dostaje przejście do ekranu", () => {
    act(() => useAuthStore.setState({ user: account("employee"), hydrated: true }));
    renderTopbar();

    expect(screen.getByText(SCREEN_HINT)).toBeInTheDocument();
    expect(screen.queryByText(WORK_HINT)).not.toBeInTheDocument();
  });
});
