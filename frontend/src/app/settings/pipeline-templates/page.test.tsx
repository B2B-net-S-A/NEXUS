import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  user: null as Record<string, unknown> | null,
}));

vi.mock("@/components/settings/PipelineTemplatesTab", () => ({
  PipelineTemplatesTab: () => <div>EDYTOR PROCESÓW</div>,
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (state: unknown) => unknown) =>
    selector({ user: mocks.user, hydrated: true }),
  hasRole: (user: { roles?: string[] } | null, ...roles: string[]) =>
    !!user && roles.some((role) => (user.roles ?? []).includes(role)),
}));

import PipelineTemplatesPage from "./page";

// UAT A-B04: rola bez prawa zapisu widziała pełny edytor.
describe("/settings/pipeline-templates — bramka", () => {
  it("rekruter dostaje odmowę, nie edytor", () => {
    mocks.user = {
      role: "recruiter",
      roles: ["recruiter"],
      effective_section_access: { pipeline: "write" },
    };
    render(<PipelineTemplatesPage />);
    expect(screen.getByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByText("EDYTOR PROCESÓW")).toBeNull();
  });

  it("Delivery Lead bez zapisu sekcji Pipeline też dostaje odmowę", () => {
    mocks.user = {
      role: "delivery_lead",
      roles: ["delivery_lead"],
      effective_section_access: { pipeline: "read" },
    };
    render(<PipelineTemplatesPage />);
    expect(screen.queryByText("EDYTOR PROCESÓW")).toBeNull();
  });

  it("Delivery Lead z zapisem Pipeline widzi edytor", () => {
    mocks.user = {
      role: "delivery_lead",
      roles: ["delivery_lead"],
      effective_section_access: { pipeline: "write" },
    };
    render(<PipelineTemplatesPage />);
    expect(screen.getByText("EDYTOR PROCESÓW")).toBeInTheDocument();
  });
});
