import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TalentRadarPage from "@/app/talent-radar/page";
import { useAuthStore, type User, type UserRole } from "@/store/auth";

// Workspace ciągnie react-query, `api` i pół modułu radaru — przedmiotem tego
// testu jest ROUTING STRONY, nie zawartość, więc podmieniamy go zaślepką.
vi.mock("@/components/talent-radar/TalentRadarWorkspace", () => ({
  TalentRadarWorkspace: () => <div data-testid="radar-workspace" />,
}));

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
}));

function mkUser(role: UserRole): User {
  return {
    id: 3,
    email: `${role}@example.com`,
    name: `Test ${role}`,
    role,
    roles: [role],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
  } as User;
}

beforeEach(() => replace.mockClear());

afterEach(() => {
  act(() => {
    useAuthStore.setState({ user: null, hydrated: false });
  });
});

describe("TalentRadarPage — tryb ekranu Kandydaci", () => {
  // Od 21.09.2026 radar jest trybem „Z treści requestu" ekranu Kandydaci.
  // Każda rola z dostępem do kandydatów trafia tam (także z linków
  // w powiadomieniach, które zapisały `/talent-radar`).
  it.each(["recruiter", "head_of_recruitment", "finance", "admin"] as const)(
    "rola %s jest przekierowywana do /candidates?mode=request",
    (role) => {
      act(() => {
        useAuthStore.setState({ user: mkUser(role), hydrated: true });
      });

      render(<TalentRadarPage />);

      expect(replace).toHaveBeenCalledWith("/candidates?mode=request");
      expect(screen.queryByTestId("radar-workspace")).not.toBeInTheDocument();
    },
  );

  // Decyzja z 19.08: radar dla KAŻDEJ zalogowanej roli. Rola bez dostępu do
  // `/candidates` (middleware ją odbija) dostaje radar tutaj, bez odmowy.
  it("rola bez dostępu do kandydatów dostaje radar na miejscu", () => {
    act(() => {
      useAuthStore.setState({ user: mkUser("user"), hydrated: true });
    });

    render(<TalentRadarPage />);

    expect(screen.getByTestId("radar-workspace")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
    expect(
      screen.queryByText(/Brak uprawnień|zgłoś to administratorowi/),
    ).not.toBeInTheDocument();
  });

  // „Nie wiem jeszcze" ≠ „nie wolno": przed hydracją nie ma ani odmowy, ani
  // przekierowania w ciemno.
  it.each([
    ["przed hydracją", { user: null, hydrated: false }],
    ["po hydracji bez sesji", { user: null, hydrated: true }],
  ] as const)("%s nie twierdzi, że brak uprawnień", (_label, state) => {
    act(() => {
      useAuthStore.setState(state);
    });

    render(<TalentRadarPage />);

    expect(
      screen.queryByText(/Brak uprawnień|zgłoś to administratorowi/),
    ).not.toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});
