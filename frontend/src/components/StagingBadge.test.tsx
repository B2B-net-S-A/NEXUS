import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

async function loadBadge(env: string | undefined) {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_NEXUS_ENV", env ?? "");
  return (await import("./StagingBadge")).StagingBadge;
}

describe("StagingBadge", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("pokazuje znacznik na stagingu", async () => {
    const StagingBadge = await loadBadge("staging");
    render(<StagingBadge />);
    expect(screen.getByRole("status")).toHaveTextContent("STAGING");
  });

  it("na produkcji nic nie renderuje", async () => {
    const StagingBadge = await loadBadge(undefined);
    const { container } = render(<StagingBadge />);
    expect(container).toBeEmptyDOMElement();
  });
});
