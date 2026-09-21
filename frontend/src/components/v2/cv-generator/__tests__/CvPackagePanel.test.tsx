import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { CvPackagePanel } from "../CvPackagePanel";
const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api", () => ({ default: mocks }));
const data = { managed: true, ready: false, required_languages: ["pl", "en"], documents: [{ id: 1, language: "pl", status: "ready", filename: "pl.docx", approved_version_id: null }, { id: 2, language: "en", status: "failed", filename: "en.docx", approved_version_id: null }], reasons: ["Brak wygenerowanej wersji EN."], hints: [], can_retry: true };
beforeEach(() => { vi.clearAllMocks(); mocks.get.mockResolvedValue({ data }); mocks.post.mockResolvedValue({ data }); });
function show() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><CvPackagePanel id={1} canWrite onEdit={vi.fn()} onDownload={vi.fn()} /></QueryClientProvider>); }
it("pokazuje wersje językowe do pobrania i ponawia tylko brakujący język", async () => {
  show();
  expect(await screen.findByText("Wersje CV: PL + EN")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Pobierz PL" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Pobierz EN" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Ponów brakujący język" }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledWith("/api/cv-generator/generated/1/package/retry", {}));
});
it("nie ma bramki wysyłki: bez notatki, checkboxa i potwierdzenia gotowości", async () => {
  show(); await screen.findByText("Wersje CV: PL + EN");
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  expect(screen.queryByText(/Potwierdź gotowość/)).not.toBeInTheDocument();
  expect(screen.queryByText(/niegotowy do wysłania/)).not.toBeInTheDocument();
});
