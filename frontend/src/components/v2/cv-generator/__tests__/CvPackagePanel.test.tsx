import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { CvPackagePanel } from "../CvPackagePanel";
const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api", () => ({ default: mocks }));
const data = { managed: true, ready: false, generic: false, fingerprint: "a".repeat(64), required_languages: ["pl", "en"], documents: [{ id: 1, language: "pl", status: "ready", filename: "pl.docx", approved_version_id: 10 }, { id: 2, language: "en", status: "failed", filename: "en.docx", approved_version_id: null }], note_id: null, notes: [{ id: 20, content: "Rekomendacja po rozmowie" }], reasons: ["Brak wygenerowanej wersji EN."], can_retry: true, generation_status: "failed", effective_policy: { require_recommendation_note: true } };
beforeEach(() => { vi.clearAllMocks(); mocks.get.mockResolvedValue({ data }); mocks.post.mockResolvedValue({ data }); });
function show() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><CvPackagePanel id={1} canWrite onEdit={vi.fn()} onDownload={vi.fn()} /></QueryClientProvider>); }
it("odróżnia wygenerowany PL od niegotowego pakietu i ponawia tylko brakujący język", async () => {
  show();
  expect(await screen.findByText(/Szkic — niegotowy do wysłania/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Pobierz PL" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Pobierz EN" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Potwierdź gotowość pakietu" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Ponów brakujący język" }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/cv-generator/generated/1/package/retry", {}));
});
it("wysyła wybraną notatkę, potwierdzenie źródeł i wersję podglądu", async () => {
  show(); await screen.findByText(/Szkic — niegotowy/);
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "20" } });
  await waitFor(() => expect(mocks.get).toHaveBeenCalledWith("/api/cv-generator/generated/1/package", { params: { note_id: 20 } }));
  fireEvent.click(await screen.findByRole("checkbox"));
  await waitFor(() => expect(screen.getByRole("button", { name: "Potwierdź gotowość pakietu" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Potwierdź gotowość pakietu" }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/cv-generator/generated/1/package/confirm", { note_id: 20, sources_checked: true, expected_fingerprint: data.fingerprint }));
});
