import { describe, expect, it, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api", () => ({ default: api, api }));
const toast = vi.hoisted(() => ({ showSuccess: vi.fn(), showError: vi.fn() }));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));

import { CVGeneratorV2 } from "../CVGeneratorV2";

const RULE = {
  client_id: 5, client_name: "Klient", is_active: true, client_policy: "Reguły klienta",
  version: 3, cv_language: "en", requires_en_copy: false, auto_second_language: false,
  requires_rodo_consent_block: false, content_mode: "basic", content_mode_locked: true,
  require_screening_notes_min_chars: null, require_project_ref: true, require_position: false,
  require_champion: false, filename_pattern: "B2B_{IMIE_NAZWISKO}_{PROJEKT}",
  filename_preview: "B2B_Jan_4521.docx", notes: null, generator_instructions: null,
};

function mockApi() {
  api.get.mockImplementation(async (url: string) => {
    if (url === "/api/cv-generator/candidates/7/recruitments") {
      return { data: [{ stage_id: 30, job_id: 40, job_title: "Analityk", stage: "verified",
        has_champion: true, has_notes: true, has_cv: true, ready: true, client_id: 5, client_name: "Klient" }] };
    }
    if (url === "/api/cv-generator/candidates/7/cv-sources") {
      return { data: [{ id: 11, filename: "cv.pdf", is_primary: true }] };
    }
    if (url === "/api/cv-generator/clients/5/rule-for-generation") return { data: RULE };
    return { data: [] };
  });
}

function renderModal() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <CVGeneratorV2 open onOpenChange={() => {}} candidateId={7} candidateName="Jan Kowalski" />
    </QueryClientProvider>,
  );
}

/**
 * Okno generatora z profilu kandydata stosuje te same reguły klienta co strona
 * generatora: wymuszony język, zablokowany tryb, numer projektu i braki.
 * Do 09.2026 ignorowało je i kończyło na 422 o polach, których tu nie było.
 */
describe("CVGeneratorV2 — reguły klienta", () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
    toast.showError.mockReset();
    mockApi();
  });

  it("forces the language, locks the mode and requires the project number", async () => {
    renderModal();
    expect(await screen.findByText(/Tryb ustalony w regułach CV klienta/, {}, { timeout: 4000 })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("radio", { name: /English/ })).toHaveAttribute("aria-checked", "true"),
    );
    await waitFor(() => expect(screen.getByRole("radio", { name: /Polski/ })).toBeDisabled());
    expect(screen.getByText(/Tryb ustalony w regułach CV klienta/)).toBeInTheDocument();
    expect(screen.getByText("Klient wymaga uzupełnienia danych przed generacją")).toBeInTheDocument();

    await screen.findByRole("option", { name: /cv\.pdf/ });
    fireEvent.change(screen.getByLabelText("Plik do generacji"), { target: { value: "11" } });
    const submit = screen.getByRole("button", { name: /Generuj CV w tle/ });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Numer / nazwa projektu"), { target: { value: "4521" } });
    await waitFor(() => expect(submit).toBeEnabled());
    api.post.mockResolvedValueOnce({ data: { id: 1, status: "processing", candidate_name: "Jan" } });
    fireEvent.click(submit);
    await waitFor(() => expect(api.post).toHaveBeenCalled());
    const [url, body] = api.post.mock.calls[0];
    expect(url).toBe("/api/cv-generator/generate");
    expect(body).toMatchObject({ project_ref: "4521", language: "en", content_mode: "basic", client_id: 5 });
  }, 15_000);

  it("shows the quota reason instead of a generic failure", async () => {
    api.get.mockImplementation(async (url: string) => {
      if (url === "/api/cv-generator/clients/5/rule-for-generation") {
        return { data: { ...RULE, require_project_ref: false, filename_pattern: null } };
      }
      if (url === "/api/cv-generator/candidates/7/recruitments") {
        return { data: [{ stage_id: 30, job_id: 40, job_title: "Analityk", stage: "verified",
          has_champion: true, has_notes: true, has_cv: true, ready: true, client_id: 5, client_name: "Klient" }] };
      }
      if (url === "/api/cv-generator/candidates/7/cv-sources") {
        return { data: [{ id: 11, filename: "cv.pdf", is_primary: true }] };
      }
      return { data: [] };
    });
    api.post.mockRejectedValueOnce({
      response: { status: 503, data: { detail: { feature: "cv_generator", reason: "Limit wyczerpany.", used: 5, limit: 5 } } },
    });
    renderModal();
    await screen.findByRole("option", { name: /cv\.pdf/ });
    fireEvent.change(screen.getByLabelText("Plik do generacji"), { target: { value: "11" } });
    const submit = screen.getByRole("button", { name: /Generuj CV w tle/ });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    expect(await screen.findByText("Limit wyczerpany. (wykorzystano 5/5)")).toBeInTheDocument();
  }, 15_000);
});
