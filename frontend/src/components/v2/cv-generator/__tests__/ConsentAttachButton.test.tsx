import { beforeEach, describe, expect, it, vi } from "vitest";
import { configure, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";

import { ConsentAttachButton } from "../ConsentAttachButton";

const uploadMock = vi.fn(async (_id: number, _file: File) => ({ data: { consent_token: "tok-1", filename: "zgoda.png" } }));
const attachMock = vi.fn(async (_id: number, _token: string) => ({ data: {} }));
// Wyszukiwanie z debounce i kaskada zapytań — pod obciążeniem (pełny
// przebieg na współdzielonej maszynie) domyślna sekunda to za mało.
configure({ asyncUtilTimeout: 10000 });

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    cvGeneratorApi: {
      listGenerated: vi.fn(),
      identifyUpload: vi.fn(),
      uploadConsentForGenerated: (id: number, file: File) => uploadMock(id, file),
      attachConsent: (id: number, token: string) => attachMock(id, token),
      deleteGenerated: vi.fn(),
    },
  };
});

function renderButton(props: Partial<Parameters<typeof ConsentAttachButton>[0]> = {}) {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <ConsentAttachButton generatedId={42} hasConsent={false} {...props} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function pick(file: File) {
  const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
}

beforeEach(() => {
  uploadMock.mockClear();
  attachMock.mockClear();
});

describe("ConsentAttachButton", () => {
  it("wgrywa zrzut przypięty do CV, a potem dołącza go do dokumentu", async () => {
    const onAttached = vi.fn();
    renderButton({ onAttached });
    const file = new File(["img"], "zgoda.png", { type: "image/png" });
    pick(file);
    await waitFor(() => expect(onAttached).toHaveBeenCalled());
    expect(uploadMock).toHaveBeenCalledWith(42, file);
    expect(attachMock).toHaveBeenCalledWith(42, "tok-1");
  });

  it("gdy zrzut już jest — „Wymień zrzut”", () => {
    renderButton({ hasConsent: true });
    expect(screen.getByRole("button", { name: "Wymień zrzut" })).toBeInTheDocument();
  });

  it("odrzuca plik, który nie jest obrazem, bez wołania serwera", () => {
    renderButton();
    pick(new File(["x"], "zgoda.pdf", { type: "application/pdf" }));
    expect(screen.getByRole("alert")).toHaveTextContent("PNG, JPG albo WEBP");
    expect(uploadMock).not.toHaveBeenCalled();
  });

  it("pokazuje powód odmowy serwera (np. CV jeszcze się generuje)", async () => {
    attachMock.mockRejectedValueOnce({ response: { status: 409, data: { detail: { code: "processing", message: "Poczekaj, aż CV się wygeneruje." } } } });
    renderButton();
    pick(new File(["img"], "zgoda.png", { type: "image/png" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Poczekaj, aż CV się wygeneruje.");
  });
});
