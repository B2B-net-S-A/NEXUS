import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { RequireSectionAccess } from "@/components/RequireSectionAccess";
import { useAuthStore } from "@/store/auth";

function setAuthState(partial: Record<string, unknown>) {
  useAuthStore.setState(partial as never);
}

describe("RequireSectionAccess", () => {
  beforeEach(() => {
    setAuthState({ user: null, token: null, realUser: null, hydrated: false });
  });

  it("does not render an access denial before auth hydration", () => {
    render(
      <RequireSectionAccess
        section="finance"
        fallback={<p>Brak uprawnień</p>}
      >
        <p>Finanse</p>
      </RequireSectionAccess>,
    );

    expect(screen.queryByText("Brak uprawnień")).not.toBeInTheDocument();
    expect(screen.queryByText("Finanse")).not.toBeInTheDocument();
  });

  it("accepts an individual grant even when the role default is none", () => {
    setAuthState({
      user: {
        role: "recruiter",
        roles: ["recruiter"],
        effective_section_access: { finance: "read" },
      },
      hydrated: true,
    });

    render(
      <RequireSectionAccess
        section="finance"
        fallback={<p>Brak uprawnień</p>}
      >
        <p>Finanse</p>
      </RequireSectionAccess>,
    );

    expect(screen.getByText("Finanse")).toBeInTheDocument();
    expect(screen.queryByText("Brak uprawnień")).not.toBeInTheDocument();
  });

  it("honours an individual denial even when the role default grants access", () => {
    setAuthState({
      user: {
        role: "finance",
        roles: ["finance"],
        effective_section_access: { finance: "none" },
      },
      hydrated: true,
    });

    render(
      <RequireSectionAccess
        section="finance"
        fallback={<p>Brak uprawnień</p>}
      >
        <p>Finanse</p>
      </RequireSectionAccess>,
    );

    expect(screen.getByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByText("Finanse")).not.toBeInTheDocument();
  });

  it("distinguishes read from write", () => {
    setAuthState({
      user: {
        role: "recruiter",
        roles: ["recruiter"],
        effective_section_access: { finance: "read" },
      },
      hydrated: true,
    });

    render(
      <RequireSectionAccess
        section="finance"
        required="write"
        fallback={<p>Tylko odczyt</p>}
      >
        <p>Edycja finansów</p>
      </RequireSectionAccess>,
    );

    expect(screen.getByText("Tylko odczyt")).toBeInTheDocument();
    expect(screen.queryByText("Edycja finansów")).not.toBeInTheDocument();
  });
});
