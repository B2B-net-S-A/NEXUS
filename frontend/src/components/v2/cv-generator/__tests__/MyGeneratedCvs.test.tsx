/**
 * „Moje wygenerowane CV” (07.11.2026) — lista CV z generatora zalogowanej
 * osoby z `GET /api/cv-generator/generated?mine=true`.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { GeneratedCvItem } from "@/lib/api";
import {
  MY_CVS_PAGE_SIZE,
  MyGeneratedCvs,
  formatCvDate,
  myCvState,
} from "@/components/v2/cv-generator/MyGeneratedCvs";

const listGenerated = vi.fn();
const getMock = vi.fn();
const downloadGeneratedCv = vi.fn();
const fetchStageCvFile = vi.fn();
const downloadBlob = vi.fn();
const toast = vi.hoisted(() => ({ showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn() }));

vi.mock("@/lib/api", () => ({
  default: { get: (...args: unknown[]) => getMock(...args) },
  cvGeneratorApi: { listGenerated: (...args: unknown[]) => listGenerated(...args) },
  cvGeneratedEditorApi: { get: vi.fn() },
}));
vi.mock("@/components/Toast", () => ({ useToast: () => toast }));
vi.mock("@/components/v2/cv-generator/cv-generated-files", () => ({
  downloadGeneratedCv: (...args: unknown[]) => downloadGeneratedCv(...args),
  generatedCvFileUrl: () => "/x",
}));
vi.mock("@/lib/stage-cv-file", () => ({
  fetchStageCvFile: (...args: unknown[]) => fetchStageCvFile(...args),
}));
vi.mock("@/lib/cv-generator", () => ({
  downloadBlob: (...args: unknown[]) => downloadBlob(...args),
}));
// Podgląd ma własne testy — tu wystarczy, że dostaje wiersz.
vi.mock("@/components/v2/cv-generator/GeneratedCvPreviewModal", () => ({
  GeneratedCvPreviewModal: ({ item }: { item: GeneratedCvItem | null }) =>
    item ? <div data-testid="preview-open">{item.filename}</div> : null,
}));

function cv(id: number, extra: Partial<GeneratedCvItem> = {}): GeneratedCvItem {
  return {
    id,
    candidate_id: 100 + id,
    candidate_name: `Kandydat ${id}`,
    job_id: 500 + id,
    job_title: `Rekrutacja ${id}`,
    client_name: "Klient Testowy",
    language: "pl",
    blind: false,
    mode: "new",
    filename: `CV_${id}.docx`,
    status: "ready",
    created_at: "2026-11-07T13:05:00Z",
    can_download: true,
    can_delete: true,
    ...extra,
  };
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MyGeneratedCvs />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  listGenerated.mockReset();
  downloadGeneratedCv.mockReset();
  fetchStageCvFile.mockReset();
  downloadBlob.mockReset();
  toast.showError.mockReset();
});

describe("pomocnicze", () => {
  it("data w czasie firmy", () => {
    expect(formatCvDate("2026-11-07T13:05:00Z")).toBe("07.11.2026, 14:05");
    expect(formatCvDate(null)).toBe("—");
  });

  it("stan pliku: CV etapu przed generatorem, awaria i odrzucenie słowami", () => {
    expect(myCvState(cv(1))).toBe("Z generatora");
    expect(myCvState(cv(1, { stage_cv_status: "finalized" }))).toBe("Zatwierdzone w rekrutacji");
    expect(myCvState(cv(1, { stage_cv_status: "draft" }))).toBe("Szkic w rekrutacji");
    expect(myCvState(cv(1, { discarded: true }))).toBe("Odrzucone w rekrutacji");
    expect(myCvState(cv(1, { status: "failed" }))).toBe("Nie powstało");
    expect(myCvState(cv(1, { status: "processing" }))).toBe("W trakcie generowania");
  });
});

describe("MyGeneratedCvs", () => {
  it("pyta tylko o CV zalogowanej osoby i pokazuje datę, kandydata, rekrutację i plik", async () => {
    listGenerated.mockResolvedValue({ data: [cv(1)] });
    renderPage();

    const row = await screen.findByTestId("my-cv-row-1");
    expect(listGenerated).toHaveBeenCalledWith({ mine: true, limit: MY_CVS_PAGE_SIZE });
    expect(within(row).getByText("07.11.2026, 14:05")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: "Kandydat 1" })).toHaveAttribute(
      "href",
      "/candidates/101",
    );
    expect(within(row).getByRole("link", { name: "Rekrutacja 1" })).toHaveAttribute(
      "href",
      "/jobs/501?candidate=101",
    );
    expect(within(row).getByText("CV_1.docx")).toBeInTheDocument();
    expect(within(row).getByText("Z generatora · PL")).toBeInTheDocument();
  });

  it("pobiera plik z generatora, a CV podpięte w rekrutacji — z CV etapu", async () => {
    listGenerated.mockResolvedValue({
      data: [cv(1), cv(2, { stage_cv_stage_id: 77, stage_cv_status: "finalized" })],
    });
    downloadGeneratedCv.mockResolvedValue(null);
    fetchStageCvFile.mockResolvedValue({ blob: new Blob(["x"]), filename: "CV_etap.docx" });
    renderPage();
    const user = userEvent.setup();

    await user.click(await screen.findByRole("button", { name: "Pobierz CV: Kandydat 1" }));
    expect(downloadGeneratedCv).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }), "docx", "mine");

    await user.click(screen.getByRole("button", { name: "Pobierz CV: Kandydat 2" }));
    await waitFor(() => expect(fetchStageCvFile).toHaveBeenCalledWith(77, { download: "mine" }));
    expect(downloadBlob).toHaveBeenCalledWith(expect.any(Blob), "CV_etap.docx");
  });

  it("nazwa pliku otwiera podgląd tego wiersza", async () => {
    listGenerated.mockResolvedValue({ data: [cv(3)] });
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Podgląd CV: Kandydat 3" }));
    expect(screen.getByTestId("preview-open")).toHaveTextContent("CV_3.docx");
  });

  it("wiersz bez pliku (w toku, awaria) nie ma podglądu ani pobrania", async () => {
    listGenerated.mockResolvedValue({
      data: [
        cv(4, { status: "failed", can_download: false, error_message: "Brak CV źródłowego" }),
      ],
    });
    renderPage();
    const row = await screen.findByTestId("my-cv-row-4");
    expect(within(row).getByText("Nie powstało · PL")).toBeInTheDocument();
    expect(within(row).queryByRole("button")).not.toBeInTheDocument();
  });

  it("pusta lista to pusty stan z drogą do generatora", async () => {
    listGenerated.mockResolvedValue({ data: [] });
    renderPage();
    expect(await screen.findByText("Nie masz jeszcze wygenerowanych CV")).toBeInTheDocument();
  });

  it("awaria nie udaje pustej listy", async () => {
    listGenerated.mockRejectedValue({ isAxiosError: true, response: { status: 500, data: {} } });
    renderPage();
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("Nie masz jeszcze wygenerowanych CV")).not.toBeInTheDocument();
  });

  it("brak uprawnień to komunikat o uprawnieniach, nie pusta lista", async () => {
    listGenerated.mockRejectedValue({ isAxiosError: true, response: { status: 403, data: {} } });
    renderPage();
    await waitFor(() => expect(listGenerated).toHaveBeenCalled());
    expect(await screen.findByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("Nie masz jeszcze wygenerowanych CV")).not.toBeInTheDocument();
  });

  it("pełna strona daje „Pokaż starsze” z kursorem po id", async () => {
    const page = Array.from({ length: MY_CVS_PAGE_SIZE }, (_, i) => cv(1000 - i));
    listGenerated.mockResolvedValueOnce({ data: page }).mockResolvedValueOnce({ data: [cv(1)] });
    renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Pokaż starsze" }));
    await waitFor(() =>
      expect(listGenerated).toHaveBeenLastCalledWith({
        mine: true,
        limit: MY_CVS_PAGE_SIZE,
        before_id: 1000 - MY_CVS_PAGE_SIZE + 1,
      }),
    );
    expect(await screen.findByTestId("my-cv-row-1")).toBeInTheDocument();
  });

  it("szukanie przekazuje frazę do serwera", async () => {
    listGenerated.mockResolvedValue({ data: [cv(1)] });
    renderPage();
    const user = userEvent.setup();
    await user.type(await screen.findByRole("textbox", { name: "Szukaj w moich CV" }), "Kowal");
    await waitFor(() =>
      expect(listGenerated).toHaveBeenLastCalledWith({
        mine: true,
        limit: MY_CVS_PAGE_SIZE,
        q: "Kowal",
      }),
    );
  });
});
