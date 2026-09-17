/**
 * „Pokaż CV obok" w screeningu — trzy różne powody pustego okna, trzy zdania.
 *
 * Audyt B19: każdy błąd zapytania o metadane snapshotu czytał się jako
 * „Nie udało się wczytać CV" — także 403 (rekrutacja spoza zespołu) i etap bez
 * snapshotu (backend odpowiadał 404 nieodróżnialnym od nieistniejącego etapu).
 * Rekruter nie wiedział, czy prosić o dostęp, czy sięgnąć po aktualne CV na
 * profilu — a to aktualne CV NIE może udawać historycznego snapshotu.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ getOriginal: vi.fn() }));

vi.mock("@/lib/api", () => ({
  candidateStageCvApi: {
    original: { get: (...a: unknown[]) => mocks.getOriginal(...a) },
  },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }),
}));

vi.mock("@/lib/authenticated-files", () => ({
  downloadAuthenticatedFile: vi.fn(),
  fetchAuthenticatedBlob: vi.fn(),
}));

import { CVOriginalPreviewModal } from "@/components/v2/modals/CVOriginalPreviewModal";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

function renderModal() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CVOriginalPreviewModal
        open
        onOpenChange={() => {}}
        stageId={77}
        jobTitle="Rekrutacja testowa"
        candidateName="Kandydat Testowy"
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.getOriginal.mockReset();
});

describe("CVOriginalPreviewModal — powody pustego okna (audyt B19)", () => {
  it("403 mówi o braku dostępu do rekrutacji, nie o awarii", async () => {
    mocks.getOriginal.mockRejectedValue(httpError(403));
    renderModal();

    expect(await screen.findByRole("alert")).toHaveTextContent(/Nie masz dostępu do tej rekrutacji/);
    expect(screen.queryByText(/Nie udało się wczytać CV/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ponów" })).not.toBeInTheDocument();
  });

  it("404 mówi o nieistniejącym etapie", async () => {
    mocks.getOriginal.mockRejectedValue(httpError(404));
    renderModal();

    expect(await screen.findByRole("alert")).toHaveTextContent(/etap rekrutacji nie istnieje/);
  });

  it("awaria 500 zostaje awarią — z przyciskiem ponowienia", async () => {
    mocks.getOriginal.mockRejectedValue(httpError(500));
    renderModal();

    expect(await screen.findByRole("alert")).toHaveTextContent(/Nie udało się wczytać CV/);
    expect(screen.getByRole("button", { name: "Ponów" })).toBeInTheDocument();
  });

  it("brak snapshotu to stan, nie błąd — z jawnym przejściem do aktualnego CV na profilu", async () => {
    mocks.getOriginal.mockResolvedValue({
      data: {
        candidate_stage_id: 77,
        candidate_id: 4242,
        job_id: 9,
        has_snapshot: false,
        original_cv_filename: null,
        original_cv_language: null,
        original_snapshot_at: null,
        original_snapshot_source: null,
        download_url: null,
      },
    });
    renderModal();

    expect(await screen.findByText(/Brak snapshotu CV z momentu zgłoszenia/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    const link = screen.getByRole("link", { name: /aktualne CV na profilu kandydata/ });
    expect(link).toHaveAttribute("href", "/candidates/4242");
    // Aktualne CV nie jest renderowane w tym oknie jako snapshot.
    expect(
      screen.queryByRole("document", { name: "CV oryginalne" }),
    ).not.toBeInTheDocument();
  });
});
