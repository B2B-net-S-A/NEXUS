/**
 * Reguły CV zarządzane centralnie (produkcja, `CV_CENTRAL_POLICIES_ENABLED`):
 * edytor pokazuje tylko „Zasady i historia CV” i „Kartę klienta”. Wzór
 * „Karty przed CV” to osobny dokument klienta spoza katalogu zasad — jego
 * sekcja musi być widoczna także tutaj, inaczej nie da się go wgrać
 * (29.10.2026, Credit Agricole).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CvRuleEditor } from "@/components/cv-rules/CvRuleEditor";

vi.mock("@/components/cv-rules/CentralPolicyView", () => ({
  useCentralPolicy: () => ({ data: { managed: true }, isLoading: false, isError: false }),
  CentralPolicyView: () => <p>Reguły CV są zarządzane centralnie w backendzie.</p>,
}));

vi.mock("@/components/cv-rules/CoverSheetTemplateSection", () => ({
  CoverSheetTemplateSection: ({ clientId }: { clientId: number }) => (
    <section data-testid="cover-sheet-template-section">wzór karty klienta {clientId}</section>
  ),
}));

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn(() => new Promise(() => undefined)), put: vi.fn(), post: vi.fn(), delete: vi.fn() },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
}));

describe("CvRuleEditor przy zasadach centralnych", () => {
  it("pokazuje sekcję wzoru karty przed CV", () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={queryClient}>
        <CvRuleEditor clientId={116} onChanged={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(screen.getByText("Reguły CV są zarządzane centralnie w backendzie.")).toBeTruthy();
    expect(screen.getByTestId("cover-sheet-template-section")).toHaveTextContent("wzór karty klienta 116");
  });
});
