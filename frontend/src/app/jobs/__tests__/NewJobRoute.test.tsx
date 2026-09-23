/**
 * B1 (test na produkcji 23.09.2026): zanim znamy tożsamość (przed `hydrate()`
 * i w HTML-u z serwera) `/jobs/new` pokazuje szkielet formularza, nie pusty
 * obszar. `null` zostaje wyłącznie dla kogoś, o kim wiemy, że nie ma
 * `job.create` — i wtedy przekierowanie na listę.
 */

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useAuthStore, type User } from "@/store/auth";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
}));
vi.mock("@/components/v2/jobs/new/NewJobPage", () => ({
  NewJobPage: () => <div data-testid="new-job-page" />,
}));

import NewJobRoute from "@/app/jobs/new/page";
import NewJobLoading from "@/app/jobs/new/loading";

function user(role: "admin" | "recruiter"): User {
  return {
    id: 1,
    email: `${role}@example.com`,
    name: role,
    role,
    roles: [role],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
  } as User;
}

afterEach(() => {
  useAuthStore.setState({ user: null, hydrated: false });
  replace.mockReset();
});

describe("/jobs/new — okno przed hydracją", () => {
  it("przed hydracją pokazuje szkielet, nie pustkę", () => {
    useAuthStore.setState({ user: null, hydrated: false });
    render(<NewJobRoute />);
    expect(screen.getByTestId("new-job-skeleton")).toBeInTheDocument();
    expect(
      screen.getByRole("status", { name: "Ładowanie formularza nowej rekrutacji" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("new-job-page")).toBeNull();
  });

  it("uprawniony użytkownik dostaje formularz", () => {
    useAuthStore.setState({ user: user("admin"), hydrated: true });
    render(<NewJobRoute />);
    expect(screen.getByTestId("new-job-page")).toBeInTheDocument();
    expect(screen.queryByTestId("new-job-skeleton")).toBeNull();
  });

  it("bez job.create — nic i przekierowanie na listę", () => {
    useAuthStore.setState({ user: user("recruiter"), hydrated: true });
    const { container } = render(<NewJobRoute />);
    expect(container).toBeEmptyDOMElement();
    expect(replace).toHaveBeenCalledWith("/jobs");
  });

  it("loading.tsx (miękka nawigacja) renderuje ten sam szkielet", () => {
    render(<NewJobLoading />);
    expect(screen.getByTestId("new-job-skeleton")).toBeInTheDocument();
  });
});
