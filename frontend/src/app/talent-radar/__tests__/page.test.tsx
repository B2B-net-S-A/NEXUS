import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import TalentRadarPage from "@/app/talent-radar/page";
import { useAuthStore, type User, type UserRole } from "@/store/auth";

// Workspace ciągnie react-query, `api` i pół modułu radaru — przedmiotem tego
// testu jest BRAMKA STRONY, nie zawartość, więc podmieniamy go zaślepką.
vi.mock("@/components/talent-radar/TalentRadarWorkspace", () => ({
  TalentRadarWorkspace: () => <div data-testid="radar-workspace" />,
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

afterEach(() => {
  act(() => {
    useAuthStore.setState({ user: null, hydrated: false });
  });
});

describe("TalentRadarPage — bramka roli", () => {
  // Trzy role, które strona odcinała ręczną listą, mimo że backend
  // (`CurrentUser`), middleware (brak wpisu) i `nav.talent_radar` = ALL_ROLES
  // wszystkie je przepuszczają. HoR to ta osoba, której zrzut 403 uruchomił
  // decyzję z 19.08.
  it.each(["head_of_recruitment", "finance", "user"] as const)(
    "renderuje radar dla roli %s (nav.talent_radar = każda zalogowana)",
    (role) => {
      act(() => {
        useAuthStore.setState({ user: mkUser(role), hydrated: true });
      });

      render(<TalentRadarPage />);

      expect(screen.getByTestId("radar-workspace")).toBeInTheDocument();
      expect(
        screen.queryByText(/Brak uprawnień|zgłoś to administratorowi/),
      ).not.toBeInTheDocument();
    },
  );

  it("renderuje radar dla rekrutera (brak regresji na rolach, które go miały)", () => {
    act(() => {
      useAuthStore.setState({ user: mkUser("recruiter"), hydrated: true });
    });

    render(<TalentRadarPage />);

    expect(screen.getByTestId("radar-workspace")).toBeInTheDocument();
  });

  // Strona nie ma własnej bramki (#1215 zdjął piątą kopię listy ról): wejścia
  // pilnuje middleware, a `nav.talent_radar = ALL_ROLES` znaczy, że każdy, kto
  // się zalogował, ma tu wstęp. Dlatego stan przed hydracją NIE może renderować
  // odmowy — „nie wiem jeszcze" ≠ „nie wolno", a bramka liczona wprost
  // twierdziłaby adminowi przez kilka sekund, że nie ma uprawnień.
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
  });
});
