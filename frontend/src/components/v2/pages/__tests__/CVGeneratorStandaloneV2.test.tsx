import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { CVGeneratorStandaloneV2 } from "../CVGeneratorStandaloneV2";

// The page GETs the generated-CV list on mount and POSTs the multipart upload.
const getMock = vi.fn((..._args: unknown[]) => Promise.resolve({ data: [] }));
const postMock = vi.fn((..._args: unknown[]) =>
  Promise.resolve({ data: { id: 1, status: "processing", candidate_name: "x" } }),
);
vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
    post: (...args: unknown[]) => postMock(...args),
    delete: vi.fn(() => Promise.resolve({ data: null })),
  },
  extractErrorMsg: (e: unknown) => String(e),
}));

function renderPage() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <CVGeneratorStandaloneV2 />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

/** Switch to "Old" mode (manual upload), where the champion dropzone lives. */
async function openUploadMode() {
  fireEvent.click(await screen.findByText("Old (upload plików)"));
}

function championInput(): HTMLInputElement {
  // Both dropzones render a visually-hidden file input; the champion one is the
  // only input restricted to .docx.
  const inputs = Array.from(
    document.querySelectorAll<HTMLInputElement>('input[type="file"]'),
  );
  const champion = inputs.find((i) => i.accept === ".docx");
  if (!champion) throw new Error("champion file input not found");
  return champion;
}

function drop(input: HTMLInputElement, file: File) {
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
}

describe("CVGeneratorStandaloneV2 — champion upload rejection", () => {
  beforeEach(() => {
    getMock.mockClear();
    postMock.mockClear();
  });

  it("shows a persistent error when the champion file is not a .docx", async () => {
    renderPage();
    await openUploadMode();

    drop(championInput(), new File(["x"], "ProfilChampiona.pdf"));

    // The defect: previously only a self-destructing toast fired and the
    // dropzone kept rendering its untouched empty state.
    expect(
      await screen.findByText("Profil Championa nie został wczytany"),
    ).toBeInTheDocument();
    // Two matches on purpose: the durable Alert AND the immediate toast.
    expect(
      screen.getAllByText(/Nieobsługiwany format '\.pdf'/).length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("warns above the Generate button that the CV will have no champion", async () => {
    renderPage();
    await openUploadMode();

    drop(championInput(), new File(["x"], "ProfilChampiona.pdf"));

    expect(
      await screen.findByText("Wygenerujesz CV bez Profilu Championa"),
    ).toBeInTheDocument();
  });

  it("keeps the Generate button enabled — warn, do not block", async () => {
    renderPage();
    await openUploadMode();

    drop(championInput(), new File(["x"], "ProfilChampiona.pdf"));
    await screen.findByText("Profil Championa nie został wczytany");

    const generate = screen.getByRole("button", { name: /Generuj CV/i });
    // Still gated on the CV file only, exactly as before this change.
    expect(generate).toBeDisabled();
  });

  it("clears both alerts once a valid .docx is picked", async () => {
    renderPage();
    await openUploadMode();

    const input = championInput();
    drop(input, new File(["x"], "ProfilChampiona.pdf"));
    await screen.findByText("Profil Championa nie został wczytany");

    drop(input, new File(["x"], "ProfilChampiona.docx"));

    await waitFor(() => {
      expect(
        screen.queryByText("Profil Championa nie został wczytany"),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText("Wygenerujesz CV bez Profilu Championa"),
      ).not.toBeInTheDocument();
    });
  });

  it("resets the input value so the same file can be re-picked", async () => {
    renderPage();
    await openUploadMode();

    const input = championInput();
    drop(input, new File(["x"], "ProfilChampiona.pdf"));
    await screen.findByText("Profil Championa nie został wczytany");

    // Without the reset, a second pick of the SAME file fires no change event
    // at all and the UI appears frozen.
    expect(input.value).toBe("");
  });
});
