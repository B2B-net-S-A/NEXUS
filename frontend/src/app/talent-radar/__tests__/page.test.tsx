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

  it("przed hydracją nie twierdzi, że brak uprawnień", () => {
    // „NIE WIEM JESZCZE" ≠ „NIE WOLNO" — dlatego bramką jest `RequireRole`,
    // a nie policzone wprost `useCapability` (przed `hydrate()` user === null).
    act(() => {
      useAuthStore.setState({ user: null, hydrated: false });
    });

    const { container } = render(<TalentRadarPage />);

    expect(container).toBeEmptyDOMElement();
  });

  it("po hydracji bez sesji pokazuje wyjaśnienie, nie pustkę", () => {
    act(() => {
      useAuthStore.setState({ user: null, hydrated: true });
    });

    render(<TalentRadarPage />);

    expect(screen.queryByTestId("radar-workspace")).not.toBeInTheDocument();
    expect(
      screen.getByText(/zgłoś to administratorowi/),
    ).toBeInTheDocument();
  });
});
