/**
 * Zgłoszenie 22.10.2026: edycja kontraktów bez „Stawki i kwoty: podgląd”
 * dodaje plik (wypowiedzenie, aneks), ale listy plików nie pobiera.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UploadOnlyDocuments } from "@/components/contracts/documents/UploadOnlyDocuments";

const api = vi.hoisted(() => ({
  documents: vi.fn(),
  uploadDocument: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  contractsApi: {
    documents: (...a: unknown[]) => api.documents(...a),
    uploadDocument: (...a: unknown[]) => api.uploadDocument(...a),
  },
}));

function renderTab() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <UploadOnlyDocuments contractId={3} />
    </QueryClientProvider>,
  );
}

async function addFile(name: string, docType: string) {
  fireEvent.click(screen.getByRole("button", { name: "Dodaj plik" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Plik do dodania"), {
    target: { files: [new File(["x"], name, { type: "application/pdf" })] },
  });
  fireEvent.change(within(dialog).getByLabelText("Typ dokumentu"), {
    target: { value: docType },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Dodaj plik" }));
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("UploadOnlyDocuments", () => {
  it("dodaje wypowiedzenie i pokazuje je, nie pobierając listy plików kontraktu", async () => {
    api.uploadDocument.mockResolvedValue({
      data: { id: 9, filename: "wypowiedzenie.pdf", doc_type: "termination_notice" },
    });
    renderTab();

    expect(screen.getByText(/Listę plików tego kontraktu widzą osoby/)).toBeInTheDocument();
    await addFile("wypowiedzenie.pdf", "termination_notice");

    await waitFor(() => expect(api.uploadDocument).toHaveBeenCalledTimes(1));
    const [contractId, body] = api.uploadDocument.mock.calls[0] as [number, FormData];
    expect(contractId).toBe(3);
    expect(body.get("doc_type")).toBe("termination_notice");
    expect(body.get("folder_id")).toBeNull();

    const added = await screen.findByRole("list", { name: "Dodane teraz" });
    expect(within(added).getByText("wypowiedzenie.pdf")).toBeInTheDocument();
    expect(within(added).getByText(/Wypowiedzenie/)).toBeInTheDocument();
    expect(api.documents).not.toHaveBeenCalled();
  });

  it("odmowa serwera zostaje w oknie jako komunikat", async () => {
    api.uploadDocument.mockRejectedValue({
      response: { status: 403, data: { detail: "Ten klient jest poza Twoim portfelem." } },
    });
    renderTab();

    await addFile("aneks.pdf", "annex");

    const dialog = screen.getByRole("dialog");
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Ten klient jest poza Twoim portfelem.",
    );
    expect(screen.queryByRole("list", { name: "Dodane teraz" })).not.toBeInTheDocument();
  });
});
