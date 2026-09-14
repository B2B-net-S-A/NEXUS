import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ pathname: "/", get: vi.fn() }));

vi.mock("next/navigation", () => ({ usePathname: () => mocks.pathname }));
vi.mock("@/lib/api", () => ({ default: { get: mocks.get } }));

import { BreadcrumbV2 } from "@/components/v2/shell/BreadcrumbV2";

function renderAt(pathname: string) {
  mocks.pathname = pathname;
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <BreadcrumbV2 />
    </QueryClientProvider>,
  );
}

describe("BreadcrumbV2 — polskie nazwy segmentów (UAT M01-B09, M03-B09, M11-B08)", () => {
  it.each([
    ["/applications", "Zgłoszenia"],
    ["/sourcing/marketplace", "Targ / Dostępni"],
    ["/candidates/bulk-import", "Masowy import CV"],
    ["/candidates/search", "Wyszukiwanie"],
    ["/pending-verifications", "Weryfikacje"],
    ["/settings/entity-fields", "Konfiguracja pól"],
    ["/settings/team-structure", "Kompetencje i odpowiedzialności"],
  ])("%s → %s", (pathname, label) => {
    renderAt(pathname);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("prep-kit kończy się nazwą strony, a nie pustym okruszkiem", () => {
    mocks.get.mockResolvedValue({ data: { title: "Rekrutacja testowa" } });
    renderAt("/jobs/123/prep/456");
    const nav = screen.getByRole("navigation", { name: "Ścieżka" });
    expect(nav.lastElementChild).toHaveTextContent("Przygotowanie do rozmowy");
  });

  it("segment bez własnej strony nie jest linkiem", () => {
    renderAt("/sourcing/marketplace");
    expect(screen.getByText("Sourcing").closest("a")).toBeNull();
  });

  it("stałe nazwy sekcji w środku ścieżki się nie kurczą", () => {
    renderAt("/settings/team-structure");
    expect(screen.getByText("Ustawienia").closest("div")).toHaveClass("shrink-0");
  });
});
