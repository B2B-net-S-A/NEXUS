import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { JobFileItem, JobFilesOwner, JobFilesResponse } from "@/lib/api/jobFiles";

const mocks = vi.hoisted(() => ({
  fetchJobFiles: vi.fn(),
  uploadJobFile: vi.fn(),
  deleteJobFile: vi.fn(),
  downloadJobFile: vi.fn(),
  fetchJobFileBlob: vi.fn(),
}));

vi.mock("@/lib/api/jobFiles", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/jobFiles")>()),
  fetchJobFiles: (...a: unknown[]) => mocks.fetchJobFiles(...a),
  uploadJobFile: (...a: unknown[]) => mocks.uploadJobFile(...a),
  deleteJobFile: (...a: unknown[]) => mocks.deleteJobFile(...a),
  downloadJobFile: (...a: unknown[]) => mocks.downloadJobFile(...a),
  fetchJobFileBlob: (...a: unknown[]) => mocks.fetchJobFileBlob(...a),
}));
// Okno podglądu ciągnie pdf.js — tu wystarczy wiedzieć, który plik otwarto.
vi.mock("@/components/v2/files/FilePreviewModal", () => ({
  formatFileSize: (bytes: number) => `${Math.round(bytes / 1024)} KB`,
  FilePreviewModal: ({ doc }: { doc: { filename: string } | null }) =>
    doc ? <div data-testid="file-preview">{doc.filename}</div> : null,
}));

import { JobFilesPanel } from "../JobFilesPanel";

const JOB: JobFilesOwner = { kind: "job", id: 7 };

const file = (over: Partial<JobFileItem> = {}): JobFileItem => ({
  id: 1,
  filename: "Zapytanie.pdf",
  content_type: "application/pdf",
  size_bytes: 204_800,
  source: "request",
  uploaded_by: 3,
  uploaded_by_name: "Marta Testowa",
  created_at: "2026-10-09T08:15:00Z",
  ...over,
});

const response = (over: Partial<JobFilesResponse> = {}): JobFilesResponse => ({
  items: [file(), file({ id: 2, filename: "Opis projektu.xlsx", source: "upload" })],
  can_edit: true,
  max_files: 20,
  max_file_bytes: 20 * 1024 * 1024,
  ...over,
});

function renderPanel(props: Partial<React.ComponentProps<typeof JobFilesPanel>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <JobFilesPanel owner={JOB} {...props} />
    </QueryClientProvider>,
  );
}

const pick = (files: File[]) =>
  fireEvent.change(screen.getByLabelText("Dodaj pliki do rekrutacji"), { target: { files } });

const pdf = (name = "nowy.pdf", size = 1024) => {
  const made = new File(["x"], name, { type: "application/pdf" });
  Object.defineProperty(made, "size", { value: size });
  return made;
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.fetchJobFiles.mockResolvedValue(response());
  mocks.uploadJobFile.mockResolvedValue(file({ id: 3 }));
  mocks.deleteJobFile.mockResolvedValue(undefined);
  mocks.downloadJobFile.mockResolvedValue(undefined);
});

describe("JobFilesPanel", () => {
  it("lista: nazwa, plakietka requestu klienta, kto i kiedy dodał", async () => {
    renderPanel();
    const list = await screen.findByRole("list", { name: "Pliki rekrutacji" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Zapytanie.pdf");
    expect(rows[0]).toHaveTextContent("Request klienta");
    expect(rows[0]).toHaveTextContent("Marta Testowa");
    expect(rows[1]).not.toHaveTextContent("Request klienta");
    // Podgląd tylko dla typów, które okno umie pokazać.
    expect(screen.getByRole("button", { name: "Podgląd: Zapytanie.pdf" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Podgląd: Opis projektu.xlsx" })).toBeNull();
  });

  it("bez prawa redakcji: lista i pobranie zostają, dodawania i usuwania nie ma", async () => {
    mocks.fetchJobFiles.mockResolvedValue(response({ can_edit: false }));
    renderPanel();
    await screen.findByRole("list", { name: "Pliki rekrutacji" });
    expect(screen.queryByRole("button", { name: "Dodaj pliki" })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Usuń:/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Pobierz: Zapytanie.pdf" }));
    await waitFor(() => expect(mocks.downloadJobFile).toHaveBeenCalledWith(JOB, expect.objectContaining({ id: 1 })));
  });

  it("awaria odczytu to komunikat z „Ponów”, nie pusta lista", async () => {
    mocks.fetchJobFiles.mockRejectedValueOnce(new Error("503"));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się wczytać plików.");
    expect(screen.queryByTestId("job-files-empty")).toBeNull();
    expect(screen.queryByRole("button", { name: "Dodaj pliki" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ponów" }));
    expect(await screen.findByRole("list", { name: "Pliki rekrutacji" })).toBeInTheDocument();
  });

  it("pusta lista mówi to wprost", async () => {
    mocks.fetchJobFiles.mockResolvedValue(response({ items: [] }));
    renderPanel();
    expect(await screen.findByTestId("job-files-empty")).toHaveTextContent(
      "Nikt nie dodał jeszcze plików",
    );
  });

  it("dodanie pliku wysyła go i odświeża listę", async () => {
    renderPanel();
    await screen.findByRole("list", { name: "Pliki rekrutacji" });
    const added = pdf();
    pick([added]);
    await waitFor(() => expect(mocks.uploadJobFile).toHaveBeenCalledWith(JOB, added));
    await waitFor(() => expect(mocks.fetchJobFiles).toHaveBeenCalledTimes(2));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("zły typ i za duży plik odpadają przed wysłaniem, z powodem", async () => {
    renderPanel();
    await screen.findByRole("list", { name: "Pliki rekrutacji" });
    pick([new File(["x"], "skrypt.exe"), pdf("wielki.pdf", 21 * 1024 * 1024)]);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("„skrypt.exe”: tego typu pliku nie da się dodać");
    expect(alert).toHaveTextContent("„wielki.pdf”: plik jest za duży — najwyżej 20 MB.");
    expect(mocks.uploadJobFile).not.toHaveBeenCalled();
  });

  it("odmowa serwera przy jednym pliku nie zatrzymuje pozostałych", async () => {
    mocks.uploadJobFile
      .mockRejectedValueOnce({ response: { data: { detail: "Plik jest pusty." } } })
      .mockResolvedValueOnce(file({ id: 4 }));
    renderPanel();
    await screen.findByRole("list", { name: "Pliki rekrutacji" });
    pick([pdf("a.pdf"), pdf("b.pdf")]);
    expect(await screen.findByRole("alert")).toHaveTextContent("„a.pdf”: Plik jest pusty.");
    expect(mocks.uploadJobFile).toHaveBeenCalledTimes(2);
  });

  it("limit plików: nadmiar nie jest wysyłany, przycisk gaśnie przy komplecie", async () => {
    mocks.fetchJobFiles.mockResolvedValue(response({ max_files: 3 }));
    renderPanel();
    await screen.findByRole("list", { name: "Pliki rekrutacji" });
    pick([pdf("a.pdf"), pdf("b.pdf")]);
    expect(await screen.findByRole("alert")).toHaveTextContent("najwyżej 3 plików");
    expect(mocks.uploadJobFile).toHaveBeenCalledTimes(1);
  });

  it("usunięcie pyta o potwierdzenie; „Anuluj” niczego nie kasuje", async () => {
    renderPanel();
    await screen.findByRole("list", { name: "Pliki rekrutacji" });
    fireEvent.click(screen.getByRole("button", { name: "Usuń: Zapytanie.pdf" }));
    const dialog = await screen.findByRole("dialog", { name: "Usunąć plik?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(mocks.deleteJobFile).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Usuń: Zapytanie.pdf" }));
    fireEvent.click(
      within(await screen.findByRole("dialog", { name: "Usunąć plik?" })).getByRole("button", {
        name: "Usuń plik",
      }),
    );
    await waitFor(() => expect(mocks.deleteJobFile).toHaveBeenCalledWith(JOB, 1));
  });

  it("podgląd otwiera okno z wybranym plikiem", async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Podgląd: Zapytanie.pdf" }));
    expect(screen.getByTestId("file-preview")).toHaveTextContent("Zapytanie.pdf");
  });

  describe("formularz „Nowa rekrutacja” (właściciela jeszcze nie ma)", () => {
    it("pierwszy plik najpierw zapisuje formularz, potem idzie na jego konto", async () => {
      const ensureOwner = vi.fn().mockResolvedValue({ kind: "form", id: 55 });
      renderPanel({ owner: null, ensureOwner, emptyText: "Nie dodano jeszcze żadnego pliku." });
      expect(screen.getByTestId("job-files-empty")).toHaveTextContent("Nie dodano jeszcze");
      expect(mocks.fetchJobFiles).not.toHaveBeenCalled();
      const added = pdf();
      pick([added]);
      await waitFor(() =>
        expect(mocks.uploadJobFile).toHaveBeenCalledWith({ kind: "form", id: 55 }, added),
      );
      expect(ensureOwner).toHaveBeenCalledTimes(1);
    });

    it("formularz się nie zapisał: plik nie jest wysyłany, a panel mówi dlaczego", async () => {
      renderPanel({ owner: null, ensureOwner: vi.fn().mockResolvedValue(null) });
      pick([pdf()]);
      expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się zapisać formularza");
      expect(mocks.uploadJobFile).not.toHaveBeenCalled();
    });

    it("gotowe dane z podglądu nie odpytują serwera", () => {
      renderPanel({ owner: { kind: "form", id: 0 }, seed: response() });
      expect(screen.getByRole("list", { name: "Pliki rekrutacji" })).toBeInTheDocument();
      expect(mocks.fetchJobFiles).not.toHaveBeenCalled();
    });
  });
});
