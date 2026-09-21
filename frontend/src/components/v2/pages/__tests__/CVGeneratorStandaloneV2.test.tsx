import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { CVGeneratorStandaloneV2 } from "../CVGeneratorStandaloneV2";
import { useAuthStore } from "@/store/auth";

vi.mock("@/components/v2/modals/CVBrandedEditModal", () => ({
  CVBrandedEditModal: ({onRegenerate, onOpenChange}: {
    onRegenerate: () => void; onOpenChange: (open: boolean) => void;
  }) => <button onClick={() => { onOpenChange(false); onRegenerate(); }}>Recover saved draft</button>,
}));

// The page GETs the generated-CV list on mount and POSTs the multipart upload.
const getMock = vi.fn((..._args: unknown[]): Promise<{data: unknown}> => Promise.resolve({ data: [] }));
const postMock = vi.fn((..._args: unknown[]) =>
  Promise.resolve<{ data: unknown }>({ data: { id: 1, status: "processing", candidate_name: "x" } }),
);
// The AI preview of an uploaded champion; a test may make it fail.
const previewMock = vi.fn(async (): Promise<{ data: unknown }> => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { data: { champion_profile: structuredClone(actual.EMPTY_CHAMPION_PROFILE) } };
});
vi.mock("@/lib/api", async importOriginal => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  const client = {
    get: (...args: unknown[]) => getMock(...args),
    post: (...args: unknown[]) => args[0] === "/api/champion/preview"
      ? previewMock()
      : postMock(...args),
    delete: vi.fn(() => Promise.resolve({ data: null })),
  };
  return { ...actual, default: client, api: client, extractErrorMsg: (e: unknown) => String(e) };
});

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
  fireEvent.click(await screen.findByRole("button", { name: "Mam tylko plik CV (bez procesu)" }));
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

it("recovers uploaded history without reusing the current source or losing its client", async () => {
  setSourcingAccess("write");
  getMock.mockImplementation(async (url) => ({data: url === "/api/cv-generator/generated" ? [{
    id: 902, candidate_id: null, job_id: null, candidate_name: "Uploaded Person",
    client_id: 51, client_name: "Original Client", position: "Source role",
    language: "en", blind: false, mode: "upload", status: "ready", filename: "cv.docx",
    can_download: true, can_delete: false,
  }] : []}));
  const assign = vi.fn();
  vi.stubGlobal("location", {...window.location, assign});
  try {
    renderPage();
    await openUploadMode();
    drop(cvInput(), new File(["unrelated"], "unrelated.pdf"));
    confirmOutsideAssignment();
    expect(screen.getByRole("button", {name: /Generuj CV/i})).toBeEnabled();
    fireEvent.click(await screen.findByTitle("Edytuj i zatwierdź CV"));
    fireEvent.click(screen.getByText("Recover saved draft"));
    expect(assign).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/^Stanowisko/)).toHaveValue("Source role");
    expect(screen.getByText("Original Client")).toBeInTheDocument();
    expect(screen.getByRole("button", {name: /Generuj CV/i})).toBeDisabled();
    expect(screen.queryByText("unrelated.pdf")).not.toBeInTheDocument();
  } finally {
    vi.unstubAllGlobals();
    getMock.mockImplementation(async () => ({data: []}));
  }
});

it.each([88, null])("recovers the history document context after closing its editor (job %s)", async (jobId) => {
  setSourcingAccess("write");
  getMock.mockImplementation(async (url) => ({data: url === "/api/cv-generator/generated" ? [{
    id: 901, candidate_id: 77, job_id: jobId, candidate_name: "History Person",
    language: "pl", mode: "new", status: "ready", filename: "cv.docx",
    can_download: true, can_delete: false,
  }] : []}));
  const assign = vi.fn();
  vi.stubGlobal("location", {...window.location, assign});
  try {
    renderPage({prefillCandidateId: 999, prefillJobId: 1000});
    fireEvent.click(await screen.findByTitle("Edytuj i zatwierdź CV"));
    fireEvent.click(screen.getByText("Recover saved draft"));
    expect(assign).toHaveBeenCalledWith(`/cv-generator?candidate_id=77${jobId == null ? "" : "&job_id=88"}`);
  } finally {
    vi.unstubAllGlobals();
    getMock.mockImplementation(async () => ({data: []}));
  }
});

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

describe("CVGeneratorStandaloneV2 — the AI champion preview is an aid, not a gate", () => {
  beforeEach(() => {
    setSourcingAccess("write");
    getMock.mockClear();
    postMock.mockClear();
  });
  afterEach(() => {
    previewMock.mockReset();
    previewMock.mockImplementation(async () => {
      const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
      return { data: { champion_profile: structuredClone(actual.EMPTY_CHAMPION_PROFILE) } };
    });
  });

  it("keeps the champion attached and generates with it when the preview fails", async () => {
    // 10.09: Haiku returned broken JSON for an older-format champion DOCX and
    // the whole step read "Profil Championa nie został wczytany" — the file
    // was never attached, so the CV had no champion. Generation itself never
    // needed the preview: the backend parses the DOCX deterministically.
    previewMock.mockRejectedValueOnce(
      new Error("Nie udało się odczytać profilu: nieparsowalny JSON profilu"),
    );
    renderPage();
    await openUploadMode();

    drop(cvInput(), new File(["x"], "kandydat.pdf"));
    const champion = new File(["x"], "ProfilChampiona.docx");
    drop(championInput(), champion);

    expect(
      await screen.findByText("Profil Championa przypięty bez podglądu"),
    ).toBeInTheDocument();
    expect(screen.getByText(/nieparsowalny JSON profilu/)).toBeInTheDocument();
    expect(
      screen.queryByText("Profil Championa nie został wczytany"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Wygenerujesz CV bez Profilu Championa"),
    ).not.toBeInTheDocument();

    confirmOutsideAssignment();
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/i }));

    await waitFor(() => expect(postMock).toHaveBeenCalled());
    const [url, body] = postMock.mock.calls[0] as [string, FormData];
    expect(url).toBe("/api/cv-generator/generate-upload");
    expect(body.get("champion_file")).toBe(champion);
    expect(body.get("champion_profile_json")).toBeNull();
  });

  it("drops the preview notice together with the file", async () => {
    previewMock.mockRejectedValueOnce(new Error("preview down"));
    renderPage();
    await openUploadMode();

    drop(championInput(), new File(["x"], "ProfilChampiona.docx"));
    await screen.findByText("Profil Championa przypięty bez podglądu");

    // With a file attached the dropzone shows a file card with a remove
    // control instead of the input — that is the only way to a second pick.
    fireEvent.click(screen.getByRole("button", { name: "Usuń plik" }));
    await waitFor(() =>
      expect(
        screen.queryByText("Profil Championa przypięty bez podglądu"),
      ).not.toBeInTheDocument(),
    );
    expect(championInput()).toBeInTheDocument();
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
    fireEvent.click(await screen.findByRole("radio", { name: /Pod rekrutację/ }));

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
    // Zrzut zgody pokazuje się tylko klientowi, który go wymaga (PKO BP).
    getMock.mockReset().mockImplementation(async (url) => ({ data: String(url).endsWith("/policy")
      ? { managed: true, content_mode: "polished", effective_policy: { requires_en_copy: false, requires_rodo_consent_block: true, filename_pattern: "X" } }
      : [] }) as never);
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
  it("waits for the policy and language count before allowing generation", async () => {
    let resolvePolicy!: (value: { data: unknown }) => void;
    const pending = new Promise<{ data: unknown }>(resolve => { resolvePolicy = resolve; });
    getMock.mockImplementation(url => String(url).endsWith("/policy") ? pending : Promise.resolve({ data: [] }));
    renderPage();
    await openUploadMode();
    drop(cvInput(), new File(["synthetic"], "cv.pdf"));
    confirmOutsideAssignment();
    const submit = screen.getByRole("button", { name: /Generuj CV/i });
    expect(submit).toBeDisabled();
    expect(screen.getByText(/Wczytuję zasady CV i liczbę wersji/)).toBeInTheDocument();
    resolvePolicy({ data: { managed: true, content_mode: "polished", effective_policy: { requires_en_copy: false, filename_pattern: "B2B_{STANOWISKO}_{IMIE_NAZWISKO}" } } });
    await screen.findByText("Powstanie 1 wersja: PL.");
    await waitFor(() => expect(submit).toBeEnabled());
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
  it("explains why Generate is disabled when the recruitment's client rule requires a position", async () => {
    // Klient przychodzi z przypisanej rekrutacji, nie z pickera — Alert wisiał
    // dotąd tylko na pickerze, więc przycisk był wyłączony bez wyjaśnienia.
    getMock.mockImplementation(async (url) => {
      const u = String(url);
      if (u.endsWith("/recruitments")) return {data: [{stage_id: 30, job_id: 40, job_title: "Test job", client_id: 5, client_name: "Test client", ready: true}]};
      if (u === "/api/cv-generator/clients/5/rule-for-generation") return {data: {
        client_id: 5, client_name: "Test client", is_active: true, client_policy: "Stanowisko wymagane",
        version: 2, cv_language: null, requires_en_copy: false, auto_second_language: false,
        requires_rodo_consent_block: false, content_mode: null, content_mode_locked: false,
        require_screening_notes_min_chars: null, require_project_ref: false, require_position: true,
        require_champion: false, filename_pattern: null, filename_preview: null, notes: null, generator_instructions: null,
      }};
      return {data: []};
    });
    renderPage({embedded: true, prefillCandidateId: 2, prefillCandidateName: "Test Person", prefillJobId: 40});
    await openUploadMode();
    await screen.findByText("Klient rekrutacji: Test client");
    drop(cvInput(), new File(["synthetic"], "cv.pdf"));
    expect(await screen.findByText("Klient wymaga uzupełnienia danych przed generacją")).toBeInTheDocument();
    // Ten sam brak w alercie i w liście braków przy przycisku.
    expect(screen.getAllByText(/Ten klient wymaga stanowiska/)).toHaveLength(2);
    expect(screen.getByRole("button", {name: /Generuj CV/i})).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/^Stanowisko/), {target: {value: "Analityk"}});
    await waitFor(() => expect(screen.getByRole("button", {name: /Generuj CV/i})).toBeEnabled());
    expect(screen.queryByText("Klient wymaga uzupełnienia danych przed generacją")).not.toBeInTheDocument();
  });

  it("shows the search validation message instead of „Brak wyników” for a too long query", async () => {
    renderPage();
    fireEvent.click(await screen.findByRole("combobox"));
    fireEvent.change(screen.getByPlaceholderText("Szukaj kandydata…"), {target: {value: "x".repeat(121)}});
    expect(await screen.findByText(/Wpisz najwyżej 120 znaków/)).toBeInTheDocument();
    expect(screen.queryByText("Brak wyników.")).not.toBeInTheDocument();
    await new Promise((resolve) => setTimeout(resolve, 350));
    expect(getMock).not.toHaveBeenCalledWith("/api/cv-generator/candidates", {params: {q: "x".repeat(121), limit: 20}});
  });

  it("shows a readable quota reason when generation is refused", async () => {
    getMock.mockImplementation(async (url) => ({data: String(url).endsWith("/recruitments") ? [{stage_id: 30, job_id: 40, job_title: "Test job", client_id: 5, client_name: "Test client", ready: true}] : []}) as never);
    postMock.mockRejectedValue({response: {status: 503, data: {detail: {feature: "cv_generator", reason: "Limit generacji CV został wyczerpany.", used: 10, limit: 10}}}});
    renderPage({embedded: true, prefillCandidateId: 2, prefillCandidateName: "Test Person", prefillJobId: 40});
    await openUploadMode();
    await screen.findByText("Klient rekrutacji: Test client");
    drop(cvInput(), new File(["synthetic"], "cv.pdf"));
    fireEvent.click(screen.getByRole("button", {name: /Generuj CV/i}));
    expect(await screen.findByText("Limit generacji CV został wyczerpany. (wykorzystano 10/10)", {}, {timeout: 5000})).toBeInTheDocument();
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


describe("plakietka niezależnej kontroli AI (0327)", () => {
  const row = (factual_review: unknown) => ({
    id: 7, candidate_name: "Jan Kowalski", language: "pl", mode: "upload",
    status: "ready", filename: "cv.docx", warnings: [], can_download: false,
    can_delete: false, factual_review,
  });

  const renderWithReview = (factual_review: unknown) => {
    getMock.mockImplementation(async (url) =>
      String(url) === "/api/cv-generator/generated" ? {data: [row(factual_review)]} : {data: []});
    renderPage({embedded: true});
  };

  it("mówi „OK”, gdy recenzent potwierdził całe CV", async () => {
    renderWithReview({status: "verified", findings: 0, model: "gpt-5.6-luna"});
    expect(await screen.findByText("Kontrola AI: OK")).toBeInTheDocument();
  });

  it("pokazuje liczbę uwag, a nie samo „są uwagi”", async () => {
    renderWithReview({status: "advisory", findings: 3, model: "gpt-5.6-luna"});
    expect(await screen.findByText("Kontrola AI: 3 uwagi")).toBeInTheDocument();
  });

  it("odróżnia nieudaną kontrolę od czystego CV", async () => {
    renderWithReview({status: "unavailable", findings: 0, reason: "CVGeneratorTimeoutError"});
    expect(await screen.findByText("Kontrola AI: niedostępna")).toBeInTheDocument();
  });

  it("dla CV sprzed wdrożenia nie rysuje nic — brak raportu to nie awaria", async () => {
    renderWithReview(null);
    expect(await screen.findByText("Jan Kowalski")).toBeInTheDocument();
    expect(screen.queryByText(/Kontrola AI/)).not.toBeInTheDocument();
  });
});


describe("auto-CV na liście wygenerowanych (automaty 21.09.2026)", () => {
  const row = (extra: Record<string, unknown>) => ({
    id: 9, candidate_name: "Jan Kowalski", language: "pl", mode: "new",
    status: "ready", filename: "cv.docx", warnings: [], can_download: true,
    can_delete: false, ...extra,
  });
  const renderRow = (extra: Record<string, unknown>) => {
    getMock.mockImplementation(async (url) =>
      String(url) === "/api/cv-generator/generated" ? {data: [row(extra)]} : {data: []});
    renderPage({embedded: true});
  };

  it("czekające na przegląd mówi wprost: sprawdź przed wysyłką", async () => {
    renderRow({origin: "auto", needs_review: true});
    expect(await screen.findByText("wygenerowane automatycznie — sprawdź przed wysyłką")).toBeInTheDocument();
  });

  it("po zatwierdzeniu zostaje samo pochodzenie, bez wezwania do przeglądu", async () => {
    renderRow({origin: "auto", needs_review: false});
    expect(await screen.findByText("wygenerowane automatycznie")).toBeInTheDocument();
    expect(screen.queryByText(/sprawdź przed wysyłką/)).not.toBeInTheDocument();
  });

  it("dokument wygenerowany przez człowieka (i starsza odpowiedź bez pola) nie ma plakietki", async () => {
    renderRow({});
    expect(await screen.findByText("Jan Kowalski")).toBeInTheDocument();
    expect(screen.queryByText(/wygenerowane automatycznie/)).not.toBeInTheDocument();
  });
});

describe("CV readiness follows the selected content mode", () => {
  it("allows CV-only redaction and refetches requirements for tailored mode", async () => {
    setSourcingAccess("write");
    getMock.mockReset();
    getMock.mockImplementation(async (url, options) => {
      if (String(url).endsWith("/cv-sources")) return {data: [{id: 71, filename: "source.pdf", is_primary: true, uploaded_at: null}]};
      if (!String(url).endsWith("/recruitments")) return {data: String(url).includes("cv-rule") ? null : []};
      const mode = (options as {params: {content_mode: string}}).params.content_mode;
      return {data: [{stage_id: 30, job_id: 40, job_title: "Test job", has_cv: true,
        has_champion: false, has_notes: false, ready: mode !== "tailored", content_mode: mode,
        required_champion: mode === "tailored", required_notes_min_chars: 0,
        missing_inputs: mode === "tailored" ? ["Tryb dopasowany wymaga Profilu Championa."] : []}]};
    });
    renderPage({embedded: true, prefillCandidateId: 2, prefillCandidateName: "Test Person", prefillJobId: 40});
    expect(await screen.findByText("Profil Championa (opcjonalny)")).toBeInTheDocument();
    expect(screen.getByRole("button", {name: /Generuj CV/})).toBeDisabled();
    await screen.findByRole("option", {name: "source.pdf · główne"});
    fireEvent.change(screen.getByLabelText("Plik do generacji"), {target: {value: "71"}});
    expect(screen.getByRole("button", {name: /Generuj CV/})).toBeEnabled();
    fireEvent.click(screen.getByRole("radio", {name: /Pod rekrutację/}));
    expect((await screen.findAllByText("Tryb dopasowany wymaga Profilu Championa.")).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", {name: /Generuj CV/})).toBeDisabled();
  });
});


describe("Explicit CV source selection", () => {
  it("submits the chosen non-primary file and blocks generation before selection", async () => {
    setSourcingAccess("write");
    postMock.mockClear();
    getMock.mockReset();
    getMock.mockImplementation(async (url) => {
      if (String(url).endsWith("/cv-sources")) return {data: [
        {id: 71, filename: "primary.pdf", is_primary: true, uploaded_at: null},
        {id: 72, filename: "chosen.docx", is_primary: false, uploaded_at: null},
      ]};
      if (String(url).endsWith("/recruitments")) return {data: [{stage_id: 30, job_id: 40,
        job_title: "Synthetic job", has_cv: true, has_champion: false, has_notes: false,
        ready: true, required_champion: false, required_notes_min_chars: 0, missing_inputs: []}]};
      return {data: String(url).includes("cv-rule") ? null : []};
    });
    renderPage({embedded: true, prefillCandidateId: 2, prefillCandidateName: "Synthetic", prefillJobId: 40});
    await screen.findByRole("option", {name: "chosen.docx"});
    expect(screen.getByRole("button", {name: /Generuj CV/})).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Plik do generacji"), {target: {value: "72"}});
    await waitFor(() => expect(screen.getByRole("button", {name: /Generuj CV/})).toBeEnabled());
    fireEvent.click(screen.getByRole("button", {name: /Generuj CV/}));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith(
      "/api/cv-generator/generate", expect.objectContaining({candidate_id: 2, stage_id: 30, cv_document_id: 72}),
      expect.anything(),
    ));
  });
});

describe("durable generation status", () => {
  it("distinguishes queued and interrupted work in history", async () => {
    setSourcingAccess("write");
    getMock.mockReset();
    getMock.mockImplementation(async (url) => ({data: String(url) === "/api/cv-generator/generated" ? [
      {id: 901, candidate_name: "Queued Person", language: "pl", mode: "upload", status: "processing", job_status: "queued", filename: "", can_download: false, can_delete: false},
      {id: 902, candidate_name: "Interrupted Person", language: "en", mode: "upload", status: "failed", job_status: "interrupted", filename: "", error_message: "Generacja przerwana", can_download: false, can_delete: false},
    ] : []}));
    renderPage();
    expect(await screen.findByText("Oczekuje w kolejce")).toBeInTheDocument();
    expect(screen.getByText("Przerwano")).toBeInTheDocument();
    expect(screen.getByText("Generacja przerwana")).toBeInTheDocument();
  });

  it("loads the interrupted row's settings back into the form", async () => {
    setSourcingAccess("write");
    getMock.mockReset();
    getMock.mockImplementation(async (url) => {
      const u = String(url);
      if (u === "/api/cv-generator/generated") return {data: [
        {id: 903, candidate_id: 77, job_id: 88, candidate_name: "Interrupted Person", language: "en", blind: true, mode: "new", content_mode: "basic", status: "failed", job_status: "interrupted", filename: "", can_download: false, can_delete: false},
      ]};
      if (u.endsWith("/candidates/77/recruitments")) return {data: [{stage_id: 99, job_id: 88, job_title: "Retry job", client_id: null, client_name: null, ready: true, has_cv: true, has_champion: true, has_notes: true}]};
      return {data: []};
    });
    renderPage();
    fireEvent.click(await screen.findByRole("button", {name: /Wygeneruj ponownie/}));
    await waitFor(() => expect(screen.getAllByText("Interrupted Person").length).toBeGreaterThan(1));
    expect(screen.getByRole("radio", {name: /English/})).toHaveAttribute("aria-checked", "true");
    await waitFor(() => expect(getMock).toHaveBeenCalledWith("/api/cv-generator/candidates/77/recruitments", {params: {content_mode: "basic"}}));
    expect(await screen.findByText(/Retry job/)).toBeInTheDocument();
  });
});

it("keeps candidate and recruitment fixed in the embedded generator", async () => {
  setSourcingAccess("write");
  getMock.mockImplementation(async (url) => ({data: String(url).endsWith("/recruitments") ? [{
    stage_id: 71, job_id: 88, job_title: "Data Engineer", client_id: 11,
    stage: "verified", ready: true, has_cv: true, has_champion: false, has_notes: false,
  }] : []}));
  try {
    renderPage({embedded: true, prefillCandidateId: 77, prefillCandidateName: "Test Person", prefillJobId: 88});
    const context = await screen.findByTestId("cvgen-context");
    await waitFor(() => expect(context).toHaveTextContent("Kandydat: Test Person · Rekrutacja: Data Engineer"));
    // Bez wyłączonych comboboxów i bez dużego przełącznika trybu.
    expect(screen.queryAllByRole("combobox").filter((el) => el.tagName === "BUTTON")).toHaveLength(0);
    expect(screen.queryByText("Old (upload plików)")).not.toBeInTheDocument();
    expect(screen.queryByText("New (z procesu)")).not.toBeInTheDocument();
    expect(screen.queryByText("Krok 1 — Konsultant")).not.toBeInTheDocument();
  } finally { getMock.mockImplementation(async () => ({data: []})); }
});

describe("simplified options", () => {
  const managedPolicy = { managed: true, content_mode: "polished", content_mode_locked: true, effective_policy: { requires_en_copy: false, cv_language: "pl", filename_pattern: "B2B_{IMIE_NAZWISKO}" } };
  afterEach(() => { getMock.mockImplementation(async () => ({data: []})); });

  it("renders a centrally locked content mode and language as text, not tiles", async () => {
    setSourcingAccess("write");
    getMock.mockImplementation(async (url) => ({data: String(url).endsWith("/policy") ? managedPolicy : []}) as never);
    renderPage();
    await openUploadMode();
    const summary = await screen.findByTestId("cvgen-policy-summary");
    expect(summary).toHaveTextContent("Obróbka treści: automatyczna — CV ogólne");
    expect(summary).toHaveTextContent("Język CV: PL (wymóg klienta) — powstanie 1 wersja.");
    expect(screen.queryByRole("radio", { name: /^Redakcja/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /English/ })).not.toBeInTheDocument();
  });

  it("announces two language versions in the summary", async () => {
    setSourcingAccess("write");
    getMock.mockImplementation(async (url) => ({data: String(url).endsWith("/policy") ? {
      ...managedPolicy, effective_policy: { requires_en_copy: true, filename_pattern: "X" },
    } : []}) as never);
    renderPage();
    await openUploadMode();
    expect(await screen.findByTestId("cvgen-policy-summary")).toHaveTextContent("PL + EN — powstaną dwie wersje");
  });

  it("shows the tiles when nothing is locked", async () => {
    setSourcingAccess("write");
    renderPage();
    await openUploadMode();
    expect(await screen.findByRole("radio", { name: /^Redakcja/ })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /English/ })).toBeInTheDocument();
    expect(screen.queryByTestId("cvgen-policy-summary")).not.toBeInTheDocument();
  });

  it("hides the consent screenshot for a client that does not require it", async () => {
    setSourcingAccess("write");
    renderPage();
    await openUploadMode();
    await screen.findByRole("radio", { name: /^Redakcja/ });
    expect(screen.queryByText(/Zrzut zgody/)).not.toBeInTheDocument();
  });

  it("keeps Blind CV and auto-download behind „Więcej opcji”", async () => {
    setSourcingAccess("write");
    renderPage();
    const trigger = await screen.findByRole("button", { name: /Więcej opcji/ });
    expect(screen.queryByText("Blind CV")).not.toBeInTheDocument();
    expect(screen.queryByText("Pobierz automatycznie po wygenerowaniu")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    expect(await screen.findByText("Blind CV")).toBeInTheDocument();
    expect(screen.getByText("Pobierz automatycznie po wygenerowaniu")).toBeInTheDocument();
  });

  it("switches back from upload to the process path with the small link", async () => {
    setSourcingAccess("write");
    renderPage();
    await openUploadMode();
    fireEvent.click(screen.getByRole("button", { name: "Wróć do generowania z procesu" }));
    expect(await screen.findByText("Krok 1 — Konsultant")).toBeInTheDocument();
  });
});

describe("required vs optional and the readiness checklist", () => {
  afterEach(() => { getMock.mockImplementation(async () => ({data: []})); });

  it("marks required and optional inputs in the upload path", async () => {
    setSourcingAccess("write");
    getMock.mockImplementation(async () => ({data: []}));
    renderPage();
    await openUploadMode();
    const cvStep = screen.getByText(/Krok 1 — Plik CV/);
    expect(cvStep.querySelector('[data-field-mark="required"]')).not.toBeNull();
    const champion = screen.getByText(/Krok 2 — Profil Championa/);
    expect(champion.querySelector('[data-field-mark="optional"]')).not.toBeNull();
    expect(screen.getByText(/Champion \(opcjonalnie\) — z nim CV powstaje pod rekrutację/)).toBeInTheDocument();
    const position = screen.getByText(/^Stanowisko/, { selector: "label" });
    expect(position.querySelector('[data-field-mark="optional"]')).not.toBeNull();
  });

  it("marks the consultant and recruitment as required in the process path", async () => {
    setSourcingAccess("write");
    renderPage();
    const step1 = await screen.findByText(/Krok 1 — Konsultant/);
    expect(step1.querySelector('[data-field-mark="required"]')).not.toBeNull();
  });

  it("lists what is missing and explains the disabled button, then says ready", async () => {
    setSourcingAccess("write");
    getMock.mockImplementation(async () => ({data: []}));
    renderPage();
    await openUploadMode();
    const checklist = await screen.findByTestId("cvgen-checklist");
    await waitFor(() => expect(checklist).toHaveTextContent("Do wygenerowania CV brakuje:"));
    expect(checklist).toHaveTextContent("Plik CV (PDF / DOCX)");
    expect(checklist).toHaveTextContent("Klient albo zaznaczenie „Generuję CV poza zleceniem”");
    const submit = screen.getByRole("button", { name: /Generuj CV/i });
    expect(submit).toBeDisabled();
    expect(submit.getAttribute("title")).toMatch(/Do wygenerowania CV brakuje: .*Plik CV/);

    drop(cvInput(), new File(["synthetic"], "cv.pdf"));
    expect(screen.getByTestId("cvgen-checklist")).not.toHaveTextContent("Plik CV (PDF / DOCX)");
    confirmOutsideAssignment();
    await waitFor(() => expect(screen.getByTestId("cvgen-checklist")).toHaveTextContent("Wszystko gotowe"));
    expect(submit).toBeEnabled();
    expect(submit).not.toHaveAttribute("title");
  });

  it("asks for a consultant first in the process path", async () => {
    setSourcingAccess("write");
    renderPage();
    const checklist = await screen.findByTestId("cvgen-checklist");
    await waitFor(() => expect(checklist).toHaveTextContent("Konsultant"));
    expect(screen.getByRole("button", { name: /Generuj CV/i })).toBeDisabled();
  });

  it("labels the PKO consent as needed for sending, without blocking generation", async () => {
    setSourcingAccess("write");
    getMock.mockImplementation(async (url) => ({ data: String(url).endsWith("/policy")
      ? { managed: true, content_mode: "polished", effective_policy: { requires_en_copy: false, requires_rodo_consent_block: true, filename_pattern: "X" } }
      : [] }) as never);
    renderPage();
    await openUploadMode();
    expect(await screen.findByText(/wymagane do wysyłki klientowi/)).toBeInTheDocument();
    drop(cvInput(), new File(["synthetic"], "cv.pdf"));
    confirmOutsideAssignment();
    await waitFor(() => expect(screen.getByRole("button", { name: /Generuj CV/i })).toBeEnabled());
  });

  it("keeps the content mode editable when the server does not lock it and hints the Champion", async () => {
    setSourcingAccess("write");
    getMock.mockImplementation(async (url) => ({ data: String(url).endsWith("/policy")
      ? { managed: true, content_mode: "tailored", content_mode_locked: false, effective_policy: { requires_en_copy: false, filename_pattern: "X" } }
      : [] }) as never);
    renderPage();
    await openUploadMode();
    const tailored = await screen.findByRole("radio", { name: /Pod rekrutację/ });
    expect(tailored).toBeEnabled();
    expect(screen.getByText(/wymaga Championa — bez niego powstanie Redakcja/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: /^Przepisanie/ }));
    expect(screen.getByRole("radio", { name: /^Przepisanie/ })).toHaveAttribute("aria-checked", "true");
  });
});

describe("central default content mode (21.09.2026 regression)", () => {
  afterEach(() => { getMock.mockImplementation(async () => ({data: []})); });

  // Produkcja: /policy bez rekrutacji podaje tryb domyślny „polished" (brak
  // Championa), z rekrutacją — „tailored". Lista rekrutacji ma tryb w kluczu
  // zapytania, więc każda zmiana trybu na chwilę gubiła wybraną rekrutację,
  // polityka wracała do „polished", a potem znowu do „tailored" — w pętli,
  // aż React przerywał render błędem #185 (Maximum update depth exceeded).
  it("preselects the recruitment default once, without ping-ponging with the client-less policy", async () => {
    setSourcingAccess("write");
    const policy = (stageId: unknown) => ({
      managed: true,
      content_mode: stageId ? "tailored" : "polished",
      default_mode: stageId ? "tailored" : "polished",
      content_mode_locked: false,
      content_mode_notice: null,
      effective_policy: { key: "credit_agricole", version: 1, requires_en_copy: false, cv_language: "pl", filename_pattern: "CV_{IMIE_NAZWISKO}_{DATA}", require_recommendation_note: false, requires_rodo_consent_block: false, require_project_ref: false },
    });
    getMock.mockImplementation(async (url, config) => {
      const u = String(url);
      const params = (config as {params?: Record<string, unknown>} | undefined)?.params ?? {};
      if (u.endsWith("/policy")) return {data: policy(params.stage_id)};
      if (u.endsWith("/cv-sources")) return {data: [{id: 71, filename: "source.pdf", is_primary: true, uploaded_at: null}]};
      if (u.endsWith("/recruitments")) return {data: [{stage_id: 30, job_id: 404748, job_title: "CA job", client_id: 5, client_name: "Credit Agricole", ready: true, has_cv: true, has_champion: true, has_notes: true, notes_chars: 400}]};
      return {data: u.includes("cv-rule") ? null : []};
    });
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const loopReported = () => errors.mock.calls.flat().map(String).join(" ").match(/Maximum update depth/);
    try {
      renderPage({prefillCandidateId: 463921, prefillCandidateName: "Test Person", prefillJobId: 404748});
      await waitFor(() => expect(screen.getByRole("radio", { name: /Pod rekrutację/ })).toHaveAttribute("aria-checked", "true"));
      // Daj ewentualnej pętli czas, żeby się ujawniła.
      await new Promise((r) => setTimeout(r, 300));
      expect(screen.queryByText(/chwilowo niedostępny/)).not.toBeInTheDocument();
      expect(loopReported()).toBeNull();
      expect(screen.getByRole("radio", { name: /Pod rekrutację/ })).toHaveAttribute("aria-checked", "true");
      // Bramka pakietu zniknęła — podsumowanie nie straszy „szkicem”.
      const summary = screen.getByTestId("cvgen-policy-summary");
      expect(summary).toHaveTextContent("Przed wysłaniem sprawdź CV i w razie potrzeby popraw je w edytorze.");
      expect(summary).not.toHaveTextContent(/Niekompletny pakiet/);
      // Wybór rekrutera zostaje — nie jest cofany do trybu domyślnego.
      fireEvent.click(screen.getByRole("radio", { name: /^Redakcja/ }));
      await new Promise((r) => setTimeout(r, 300));
      expect(screen.getByRole("radio", { name: /^Redakcja/ })).toHaveAttribute("aria-checked", "true");
      expect(loopReported()).toBeNull();
    } finally {
      errors.mockRestore();
    }
  });
});
