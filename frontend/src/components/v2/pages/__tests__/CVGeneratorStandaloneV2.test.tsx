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

function fileInput(accept: string): HTMLInputElement {
  const inputs = Array.from(
    document.querySelectorAll<HTMLInputElement>('input[type="file"]'),
  );
  const found = inputs.find((i) => i.accept === accept);
  if (!found) throw new Error(`file input with accept="${accept}" not found`);
  return found;
}

/** The champion dropzone is the only input restricted to .docx. */
const championInput = () => fileInput(".docx");
/** The CV dropzone — required, gates the Generate button. */
const cvInput = () => fileInput(".pdf,.docx");

function drop(input: HTMLInputElement, file: File) {
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
}

/** Generacja bez klienta wymaga jawnego potwierdzenia (0267) — bez klienta
 * nie działa żadna reguła, więc rekruter musi to zaznaczyć świadomie. */
function confirmOutsideAssignment() {
  fireEvent.click(screen.getByLabelText(/Generuję CV poza zleceniem/));
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

    // The CV file is what gates the button, so it MUST be attached for this
    // assertion to mean anything: without it the button is disabled anyway and
    // the test would pass even if a champion rejection started blocking submit.
    drop(cvInput(), new File(["x"], "kandydat.pdf"));
    drop(championInput(), new File(["x"], "ProfilChampiona.pdf"));
    await screen.findByText("Profil Championa nie został wczytany");

    // Bez klienta i bez potwierdzenia „poza zleceniem" przycisk jest
    // wyłączony — to bramka reguł klienta, nie odrzucenie championa.
    expect(screen.getByRole("button", { name: /Generuj CV/i })).toBeDisabled();
    confirmOutsideAssignment();
    expect(screen.getByRole("button", { name: /Generuj CV/i })).toBeEnabled();
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

describe("CVGeneratorStandaloneV2 — tryb obróbki treści", () => {
  beforeEach(() => {
    getMock.mockClear();
    postMock.mockClear();
  });

  /** Attach the required CV file and fire the Generate button. */
  async function submitUpload() {
    drop(cvInput(), new File(["x"], "kandydat.pdf"));
    confirmOutsideAssignment();
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/i }));
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    return postMock.mock.calls[0] as [string, FormData];
  }

  it("sends content_mode on the multipart upload, defaulting to Redakcja", async () => {
    renderPage();
    await openUploadMode();

    const [url, body] = await submitUpload();

    expect(url).toContain("/generate-upload");
    // The default is deliberately NOT "tailored" — see DEFAULT_CV_CONTENT_MODE.
    expect(body.get("content_mode")).toBe("polished");
  });

  it("sends the recruiter's pick instead of the default", async () => {
    renderPage();
    await openUploadMode();

    fireEvent.click(screen.getByRole("radio", { name: /Przepisanie/ }));
    const [, body] = await submitUpload();

    expect(body.get("content_mode")).toBe("basic");
  });

  it("spells out the unprofiled-client caution instead of hiding it in a tooltip", async () => {
    renderPage();

    expect(
      await screen.findByText(
        /Nie używaj dla klientów wymagających profili nieprofilowanych/,
      ),
    ).toBeInTheDocument();
  });
});
