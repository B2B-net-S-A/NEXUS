/**
 * „Format pliku dla klienta” przy zasadach centralnych (25.11.2026): reguła jest
 * tylko do odczytu, a format ma własny zapis (`PUT …/cv-rule/file-format`)
 * z kontrolą wersji. W przeciwieństwie do układu nie zależy od flagi „Nowego CV”.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CvRuleFileFormatSection } from "@/components/cv-rules/CvRuleFileFormatField";
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
      <CvRuleFileFormatSection clientId={9} />
    </QueryClientProvider>,
  );
}

describe("CvRuleFileFormatSection", () => {
  beforeEach(() => vi.clearAllMocks());

  it("bez flagi „Nowego CV” też zapisuje format od razu, z wersją edycji reguły", async () => {
    mocks.get.mockResolvedValue({
      data: makeCvRule({ client_id: 9, edit_revision: 6, new_layout_enabled: false, cv_file_format: null }),
    });
    mocks.put.mockResolvedValue({
      data: makeCvRule({ client_id: 9, edit_revision: 7, version: 3, cv_file_format: "pdf" }),
    });
    renderSection();
    expect(await screen.findByRole("radio", { name: /^Bez wymagań/ })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: /^PDF/ }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith("/api/clients/9/cv-rule/file-format", {
        cv_file_format: "pdf",
        expected_revision: 6,
      }),
    );
    expect(await screen.findByText(/Zapisano \(wersja 3\) — format pliku: PDF/)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /^PDF/ })).toBeChecked();
  });

  it("„Bez wymagań” wysyła null; błąd zapisu mówi po polsku i nie udaje zmiany", async () => {
    mocks.get.mockResolvedValue({ data: makeCvRule({ client_id: 9, edit_revision: 2, cv_file_format: "docx" }) });
    mocks.put.mockRejectedValue(new Error("boom"));
    renderSection();
    fireEvent.click(await screen.findByRole("radio", { name: /^Bez wymagań/ }));
    await waitFor(() =>
      expect(mocks.put).toHaveBeenCalledWith("/api/clients/9/cv-rule/file-format", {
        cv_file_format: null,
        expected_revision: 2,
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(/formatu pliku/);
    await waitFor(() => expect(screen.getByRole("radio", { name: /najpierw plik Word/ })).toBeChecked());
  });
});
