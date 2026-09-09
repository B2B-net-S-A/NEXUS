import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { CVGeneratorStandaloneV2 } from "../CVGeneratorStandaloneV2";
import { useAuthStore } from "@/store/auth";

// The page GETs the generated-CV list on mount and POSTs the multipart upload.
const getMock = vi.fn((..._args: unknown[]): Promise<{data: unknown}> => Promise.resolve({ data: [] }));
const postMock = vi.fn((..._args: unknown[]) =>
  Promise.resolve<{ data: unknown }>({ data: { id: 1, status: "processing", candidate_name: "x" } }),
);
vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
    post: (...args: unknown[]) => postMock(...args),
    delete: vi.fn(() => Promise.resolve({ data: null })),
  },
  extractErrorMsg: (e: unknown) => String(e),
}));

function setSourcingAccess(
  access: "read" | "write",
  impersonating = false,
) {
  const user = {
    id: 12,
    email: "rekruter@example.com",
    name: "Rekruter",
    role: "recruiter",
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    effective_section_access: { sourcing: access },
  } as const;
  useAuthStore.setState({
    user: user as never,
    realUser: impersonating ? ({ ...user, id: 1, role: "admin" } as never) : null,
    hydrated: true,
  });
}

function renderPage(props: import("../CVGeneratorStandaloneV2").CVGeneratorStandaloneV2Props = {}) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <CVGeneratorStandaloneV2 {...props} />
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
    setSourcingAccess("write");
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
    setSourcingAccess("write");
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

describe("CVGeneratorStandaloneV2 — sourcing read-only", () => {
  beforeEach(() => {
    getMock.mockClear();
    getMock.mockImplementation((..._args: unknown[]) =>
      Promise.resolve({ data: [] }),
    );
    postMock.mockClear();
  });

  it.each([
    ["read access", "read", false],
    ["impersonation", "write", true],
  ] as const)("blocks generation for %s", async (_label, access, impersonating) => {
    setSourcingAccess(access, impersonating);

    renderPage();

    expect(
      await screen.findByText("Tryb tylko do odczytu"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Generuj CV/i }),
    ).not.toBeInTheDocument();
    expect(postMock).not.toHaveBeenCalled();
    expect(
      await screen.findByText(/Brak wygenerowanych CV/),
    ).toBeInTheDocument();
  });

  it("keeps downloads available but hides share and delete actions", async () => {
    setSourcingAccess("read");
    getMock.mockResolvedValue({
      data: [
        {
          id: 21,
          candidate_name: "Jan Kowalski",
          language: "pl",
          blind: false,
          mode: "candidate",
          filename: "Jan_Kowalski.docx",
          status: "ready",
          warnings: [],
          can_download: true,
          can_delete: true,
        },
      ],
    } as never);

    renderPage();

    expect(await screen.findByTitle("Pobierz DOCX")).toBeInTheDocument();
    expect(
      screen.queryByTitle("Udostępnij klientowi (link)"),
    ).not.toBeInTheDocument();
    expect(screen.queryByTitle("Usuń z listy")).not.toBeInTheDocument();
  });
});

it("does not send person A's consent when generating the next uploaded CV", async () => {
  const { webcrypto } = await import("node:crypto");
  vi.stubGlobal("crypto", webcrypto);
  try {
    setSourcingAccess("write");
    getMock.mockReset().mockResolvedValue({ data: [] });
    postMock.mockReset().mockImplementation((url) => Promise.resolve(
      String(url).endsWith("consent-screenshot")
        ? { data: { consent_token: "person-a-token", filename: "a-consent.png" } }
        : { data: { id: 1, status: "processing", candidate_name: "Synthetic" } },
    ));
    renderPage();
    await openUploadMode();
    const sourceA = new File(["A"], "a.pdf");
    Object.defineProperty(sourceA, "arrayBuffer", { value: async () => new Uint8Array([65]).buffer });
    drop(cvInput(), sourceA);
    confirmOutsideAssignment();
    drop(fileInput("image/png,image/jpeg,image/webp"), new File(["png"], "a.png", { type: "image/png" }));
    await screen.findByTestId("consent-screenshot-attached");
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/i }));
    await waitFor(() => expect(postMock.mock.calls.filter(([url]) => String(url).endsWith("generate-upload"))).toHaveLength(1));
    await waitFor(() => expect(screen.queryByTestId("consent-screenshot-attached")).not.toBeInTheDocument());

    drop(cvInput(), new File(["B"], "b.pdf"));
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/i }));
    await waitFor(() => expect(postMock.mock.calls.filter(([url]) => String(url).endsWith("generate-upload"))).toHaveLength(2));
    const uploads = postMock.mock.calls.filter(([url]) => String(url).endsWith("generate-upload"));
    expect((uploads[0][1] as FormData).get("consent_screenshot_token")).toBe("person-a-token");
    expect((uploads[1][1] as FormData).get("consent_screenshot_token")).toBeNull();
    expect((uploads[1][1] as FormData).get("consent_screenshot_key")).toBeNull();
  } finally {
    vi.unstubAllGlobals();
  }
});

describe("CV upload context and server history", () => {
  beforeEach(() => {
    setSourcingAccess("write");
    getMock.mockReset();
    getMock.mockResolvedValue({ data: [] });
    postMock.mockReset();
    postMock.mockResolvedValue({ data: {id: 500, status: "processing", candidate_name: "Synthetic"} });
  });
  it("sends the pipeline candidate and exact recruitment with the uploaded CV", async () => {
    getMock.mockImplementation(async (url) => ({data: String(url).endsWith("/recruitments") ? [{stage_id: 30, job_id: 40, job_title: "Test job", client_id: 5, client_name: "Test client", ready: true}] : String(url).includes("cv-rule") ? null : []}) as never);
    renderPage({embedded: true, prefillCandidateId: 2, prefillCandidateName: "Test Person", prefillJobId: 40});
    await openUploadMode();
    await screen.findByText("Klient rekrutacji: Test client");
    drop(cvInput(), new File(["synthetic"], "cv.pdf"));
    fireEvent.click(screen.getByRole("button", {name: /Generuj CV/i}));
    await waitFor(() => expect(postMock).toHaveBeenCalled());
    const form = postMock.mock.calls.find(([url]) => String(url).endsWith("/generate-upload"))![1] as FormData;
    expect(form.get("candidate_id")).toBe("2");
    expect(form.get("stage_id")).toBe("30");
    expect(form.get("client_id")).toBe("5");
    expect(getMock).toHaveBeenCalledWith("/api/cv-generator/generated", {params:{candidate_id:2,job_id:40,before_id:undefined,limit:60}});
  });
  it("loads older documents using the same server filters and a cursor", async () => {
    const row = (id: number) => ({id,candidate_name:`Document ${id}`, language:"pl",mode:"upload",status:"ready",filename:"cv.docx",warnings:[],can_download:false,can_delete:false});
    getMock.mockImplementation(async (url, options) => {
      if (String(url) !== "/api/cv-generator/generated") return {data: []};
      const cursor = (options as {params:{before_id?:number}}).params.before_id;
      return {data: cursor ? [row(50)] : Array.from({length:60},(_,i)=>row(200-i))};
    });
    renderPage({embedded:true,prefillCandidateId:2,prefillJobId:40});
    // The 60-row page includes hundreds of controls. Text lookup avoids
    // repeated JSDOM visibility calculations while waiting for the query.
    const next = (await screen.findByText("Pokaż starsze CV")).closest("button");
    expect(next).not.toBeNull();
    fireEvent.click(next!);
    expect(await screen.findByText("Document 50")).toBeInTheDocument();
    expect(getMock).toHaveBeenCalledWith("/api/cv-generator/generated", {params:{candidate_id:2,job_id:40,before_id:141,limit:60}});
    expect(screen.queryByText("Pokaż starsze CV")).not.toBeInTheDocument();
  });
});
