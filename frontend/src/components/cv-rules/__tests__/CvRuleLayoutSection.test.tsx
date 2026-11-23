/**
 * „Układ CV” przy zasadach centralnych (22.11.2026): reguła jest tylko do
 * odczytu, a układ ma własny zapis (`PUT …/cv-rule/layout`) z kontrolą wersji.
 * Bez flagi „Nowego CV” sekcji nie ma.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CvRuleLayoutSection } from "@/components/cv-rules/CvRuleLayoutField";
import { makeCvRule } from "@/test/fixtures/cv-rule";

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: mocks.get, put: mocks.put, post: vi.fn(), delete: vi.fn() },
  extractErrorMsg: (e: unknown) => (e instanceof Error ? e.message : "Błąd"),
}));

function renderSection() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CvRuleLayoutSection clientId={9} />
    </QueryClientProvider>,
  );
}

describe("CvRuleLayoutSection", () => {
  beforeEach(() => vi.clearAllMocks());

  it("zapisuje układ od razu, z wersją edycji reguły", async () => {
    mocks.get.mockResolvedValue({
      data: makeCvRule({ client_id: 9, edit_revision: 6, new_layout_enabled: true, cv_layout: "classic" }),
    });
    mocks.put.mockResolvedValue({
      data: makeCvRule({ client_id: 9, edit_revision: 7, version: 3, new_layout_enabled: true, cv_layout: "new" }),
    });
    renderSection();
    fireEvent.click(await screen.findByRole("radio", { name: /^Nowe CV \(PDF\)/ }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith("/api/clients/9/cv-rule/layout", {
        cv_layout: "new",
        expected_revision: 6,
      }),
    );
    expect(await screen.findByText(/Zapisano \(wersja 3\)/)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /^Nowe CV \(PDF\)/ })).toBeChecked();
  });

  it("błąd zapisu mówi po polsku i nie udaje zmiany", async () => {
    mocks.get.mockResolvedValue({
      data: makeCvRule({ client_id: 9, new_layout_enabled: true, cv_layout: "classic" }),
    });
    mocks.put.mockRejectedValue(new Error("boom"));
    renderSection();
    fireEvent.click(await screen.findByRole("radio", { name: /^Nowe CV \(PDF\)/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/układu CV/);
    await waitFor(() =>
      expect(screen.getByRole("radio", { name: /^Klasyczne \(Word\)/ })).toBeChecked(),
    );
  });

  it("bez flagi „Nowego CV” sekcji nie ma", async () => {
    mocks.get.mockResolvedValue({ data: makeCvRule({ client_id: 9, new_layout_enabled: false }) });
    const view = renderSection();
    await waitFor(() => expect(mocks.get).toHaveBeenCalled());
    expect(view.container.querySelector("[data-testid='cvrule-layout-section']")).toBeNull();
  });
});
