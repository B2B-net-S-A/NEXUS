import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { useAuthStore } from "@/store/auth";

import { CvGenerator, type CvGeneratorProps } from "../CvGenerator";

// Wyszukiwanie z debounce i kaskada zapytań — pod obciążeniem (pełny
// przebieg na współdzielonej maszynie) domyślna sekunda to za mało.
configure({ asyncUtilTimeout: 10000 });

vi.mock("@/components/v2/modals/CVBrandedEditModal", () => ({ CVBrandedEditModal: () => null }));

const JAN = { id: 1, name: "Jan", lastname: "Kowalski", full_name: "Jan Kowalski", position: "Senior Java Developer", email: "jan@example.com" };
const PKO = {
  stage_id: 11, job_id: 501, job_title: "Senior Java Developer", stage: "verified",
  has_champion: true, has_notes: true, has_cv: true, notes_chars: 900, ready: true,
  client_id: 7, client_name: "PKO BP", required_champion: false, required_notes_min_chars: 0, missing_inputs: [],
};
const NO_CHAMPION = { ...PKO, has_champion: false, has_notes: false, notes_chars: 0 };
const SOURCES = [
  { id: 30, filename: "stare.docx", is_primary: false, uploaded_at: "2025-01-01T00:00:00Z" },
  { id: 31, filename: "glowne.pdf", is_primary: true, uploaded_at: "2026-09-01T00:00:00Z" },
];
const POLICY = {
  managed: true, default_mode: "tailored", content_mode: "tailored",
  effective_policy: { key: "x", version: 1, filename_pattern: "CV_{NAZWISKO}.docx", cv_language: null, requires_en_copy: false, require_recommendation_note: false, requires_rodo_consent_block: false, require_project_ref: false },
};

let recruitments: unknown[] = [PKO];
const getMock = vi.fn(async (url: string, _config?: unknown): Promise<{ data: unknown }> => {
  if (url === "/api/cv-generator/candidates") return { data: [JAN] };
  if (url.endsWith("/recruitments")) return { data: recruitments };
  if (url.endsWith("/cv-sources")) return { data: SOURCES };
  if (url === "/api/cv-generator/policy") return { data: POLICY };
  if (url.includes("rule-for-generation")) return { data: { is_active: false } };
  if (url === "/api/clients-lookup") return { data: [{ id: 15, name: "Polkomtel" }] };
  if (url === "/api/cv-generator/generated") return { data: [] };
  if (url.endsWith("/champion-profile")) return { data: { fingerprint: "f".repeat(64) } };
  throw new Error(`unexpected GET ${url}`);
});
const previewMock = vi.fn(async (): Promise<{ data: unknown }> => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return { data: { champion_profile: structuredClone(actual.EMPTY_CHAMPION_PROFILE) } };
});
async function defaultPost(url: string, body?: unknown, _config?: unknown): Promise<{ data: unknown }> {
  if (url === "/api/champion/preview") return previewMock();
  if (url === "/api/champion/validate") return { data: { champion_profile: (body as { profile: unknown }).profile } };
  if (url === "/api/cv-generator/identify-upload") return { data: { matches: [] } };
  return { data: { id: 77, status: "processing", candidate_name: "Jan Kowalski" } };
}
const postMock = vi.fn(defaultPost);

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  const client = {
    get: (url: string, config?: unknown) => getMock(url, config),
    post: (url: string, body?: unknown, config?: unknown) => postMock(url, body, config),
    delete: vi.fn(async () => ({ data: null })),
    patch: vi.fn(async () => ({ data: null })),
  };
  return {
    ...actual,
    default: client,
    api: client,
    cvGeneratorApi: {
      listGenerated: (params: unknown) => client.get("/api/cv-generator/generated", { params }),
      identifyUpload: (file: File) => client.post("/api/cv-generator/identify-upload", file),
      uploadConsentForGenerated: vi.fn(),
      attachConsent: vi.fn(),
      deleteGenerated: vi.fn(),
    },
  };
});

function setUser(access: "read" | "write" = "write", role = "recruiter") {
  useAuthStore.setState({
    user: {
      id: 12, email: "r@example.com", name: "Rekruter", role, roles: [role],
      profile_completed: true, profile_completed_at: null, force_password_change: false,
      effective_section_access: { sourcing: access },
    } as never,
    realUser: null,
    hydrated: true,
  });
}

function renderGenerator(props: CvGeneratorProps = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <CvGenerator {...props} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function drop(input: HTMLInputElement, file: File) {
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  fireEvent.change(input);
}

function fileInput(accept: string): HTMLInputElement {
  const found = Array.from(document.querySelectorAll<HTMLInputElement>('input[type="file"]')).find((i) => i.accept === accept);
  if (!found) throw new Error(`file input ${accept} not found`);
  return found;
}

function generatePosts(url: string) {
  return postMock.mock.calls.filter(([u]) => u === url);
}

/** Pod obciążeniem (pełny przebieg) zapytania schodzą wolniej niż domyślna sekunda. */
async function waitForGenerateEnabled() {
  await waitFor(() => expect(screen.getByRole("button", { name: /Generuj CV/ })).toBeEnabled(), { timeout: 10000 });
}

async function pickJan() {
  fireEvent.change(screen.getByLabelText("Znajdź osobę"), { target: { value: "Kowal" } });
  fireEvent.click(await screen.findByRole("button", { name: /Jan Kowalski/ }));
}

beforeEach(() => {
  recruitments = [PKO];
  setUser();
  getMock.mockClear();
  postMock.mockReset();
  postMock.mockImplementation(defaultPost);
  sessionStorage.clear();
});
afterEach(() => {
  previewMock.mockReset();
  previewMock.mockImplementation(async () => {
    const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    return { data: { champion_profile: structuredClone(actual.EMPTY_CHAMPION_PROFILE) } };
  });
});

describe("start od osoby", () => {
  it("jedyny proces wybiera sam, plik główny domyślnie, Champion → Pod rekrutację", async () => {
    renderGenerator();
    expect(screen.getByRole("button", { name: /Generuj CV/ })).toBeDisabled();
    await pickJan();
    expect(await screen.findByText("Jedyny proces tej osoby, więc wybraliśmy go sami.")).toBeInTheDocument();
    await waitForGenerateEnabled();
    expect(screen.getByRole("button", { name: "Pod rekrutację" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/ }));
    await waitFor(() => expect(generatePosts("/api/cv-generator/generate")).toHaveLength(1), { timeout: 10000 });
    const [, body, config] = generatePosts("/api/cv-generator/generate")[0] as [string, Record<string, unknown>, { headers: Record<string, string> }];
    expect(body).toMatchObject({
      candidate_id: 1, stage_id: 11, client_id: 7, cv_document_id: 31,
      language: "pl", languages: "one", content_mode: "tailored", position: "Senior Java Developer",
    });
    expect(config.headers["Idempotency-Key"]).toBeTruthy();
    expect(await screen.findByRole("region", { name: "Wynik generacji" })).toHaveTextContent(/jako CV do klienta/);
  });

  it("„Obie” wysyła languages=both jednym kliknięciem", async () => {
    renderGenerator();
    await pickJan();
    await waitForGenerateEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Obie" }));
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/ }));
    await waitFor(() => expect(generatePosts("/api/cv-generator/generate")).toHaveLength(1), { timeout: 10000 });
    expect(generatePosts("/api/cv-generator/generate")[0][1]).toMatchObject({ language: "pl", languages: "both" });
  });

  it("„Inny klient (bez procesu)” wymaga klienta i wysyła stage_id=null", async () => {
    recruitments = [];
    renderGenerator();
    await pickJan();
    expect(await screen.findByText(/Kandydat nie jest w żadnym procesie/)).toBeInTheDocument();
    expect(screen.getByTestId("cvgen-missing")).toHaveTextContent("Klient");
    fireEvent.click(screen.getByRole("button", { name: /Wybierz klienta/ }));
    fireEvent.click(await screen.findByText("Polkomtel"));
    await waitForGenerateEnabled();
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/ }));
    await waitFor(() => expect(generatePosts("/api/cv-generator/generate")).toHaveLength(1), { timeout: 10000 });
    expect(generatePosts("/api/cv-generator/generate")[0][1]).toMatchObject({ stage_id: null, client_id: 15, content_mode: "polished" });
  });

  it("dopisana notatka zapisuje się w rekrutacji PRZED generacją", async () => {
    recruitments = [NO_CHAMPION];
    renderGenerator();
    await pickJan();
    fireEvent.change(await screen.findByLabelText("Notatka ze screeningu"), { target: { value: "Zna Kafkę i Kubernetes." } });
    await waitForGenerateEnabled();
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/ }));
    await waitFor(() => expect(generatePosts("/api/cv-generator/generate")).toHaveLength(1), { timeout: 10000 });
    const urls = postMock.mock.calls.map(([u]) => u);
    expect(urls.indexOf("/api/notes")).toBeLessThan(urls.indexOf("/api/cv-generator/generate"));
    expect(generatePosts("/api/notes")[0][1]).toMatchObject({ candidate_id: 1, job_id: 501, content: "Zna Kafkę i Kubernetes." });
  });

  it("Champion, który nie zapisał się w rekrutacji, idzie tylko do tego CV", async () => {
    recruitments = [NO_CHAMPION];
    postMock.mockImplementation(async (url: string, body?: unknown) => {
      if (url.endsWith("/apply-import")) throw Object.assign(new Error("403"), { response: { status: 403, data: { detail: "Brak uprawnień do edycji Championa" } } });
      return defaultPost(url, body);
    });
    renderGenerator();
    await pickJan();
    await screen.findByText("rekrutacja nie ma Championa");
    drop(fileInput(".docx,.pdf"), new File(["x"], "Champion.docx"));
    fireEvent.click(await screen.findByRole("button", { name: "Zastosuj / zapisz szkic" }));
    expect(await screen.findByText(/nie zapisał się w rekrutacji \(Brak uprawnień do edycji Championa\) — użyjemy go tylko do tego CV/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Pod rekrutację" })).toHaveAttribute("aria-pressed", "true"));
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/ }));
    await waitFor(() => expect(generatePosts("/api/cv-generator/generate")).toHaveLength(1), { timeout: 10000 });
    expect(generatePosts("/api/cv-generator/generate")[0][1]).toHaveProperty("champion_profile");
  });
});

describe("osoba spoza bazy", () => {
  async function uploadCv() {
    fireEvent.click(screen.getByRole("button", { name: /Osoby nie ma w bazie/ }));
    drop(fileInput(".pdf,.docx"), new File(["x"], "Anna_Nowak.pdf"));
  }

  it("podobna osoba w bazie — „użyj jej” przełącza na ścieżkę osoby", async () => {
    postMock.mockImplementation(async (url: string, body?: unknown) =>
      url === "/api/cv-generator/identify-upload"
        ? { data: { matches: [{ candidate_id: 1, full_name: "Jan Kowalski", match_reasons: ["ten sam telefon"] }] } }
        : defaultPost(url, body));
    renderGenerator();
    await uploadCv();
    fireEvent.click(await screen.findByRole("button", { name: /To ta osoba — użyj jej/ }));
    expect(await screen.findByText("Jan Kowalski")).toBeInTheDocument();
    expect(await screen.findByText("Jedyny proces tej osoby, więc wybraliśmy go sami.")).toBeInTheDocument();
  });

  it("bez prawa dodawania kandydatów przycisk „Dodaj do bazy” znika", async () => {
    setUser("write", "user");
    renderGenerator();
    await uploadCv();
    expect(await screen.findByRole("button", { name: "Generuj bez dodawania" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dodaj do bazy kandydatów" })).not.toBeInTheDocument();
  });

  it("„Generuj bez dodawania” wymaga klienta i wysyła multipart z languages", async () => {
    renderGenerator();
    await uploadCv();
    fireEvent.click(await screen.findByRole("button", { name: "Generuj bez dodawania" }));
    expect(screen.getByTestId("cvgen-missing")).toHaveTextContent("Klient");
    fireEvent.click(screen.getByRole("button", { name: /Wybierz klienta/ }));
    fireEvent.click(await screen.findByText("Polkomtel"));
    await waitForGenerateEnabled();
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/ }));
    await waitFor(() => expect(generatePosts("/api/cv-generator/generate-upload")).toHaveLength(1), { timeout: 10000 });
    const fd = generatePosts("/api/cv-generator/generate-upload")[0][1] as FormData;
    expect(fd.get("client_id")).toBe("15");
    expect(fd.get("languages")).toBe("one");
    expect(fd.get("must_requirements")).toBeNull();
  });
});

// Cytowane w CLAUDE.md („AI w generatorze to dodatek, nigdy bramka”).
describe("CvGenerator — the AI champion preview is an aid, not a gate", () => {
  it("keeps the champion attached and generates with it when the preview fails", async () => {
    previewMock.mockRejectedValueOnce(new Error("Nie udało się odczytać profilu: nieparsowalny JSON profilu"));
    renderGenerator();
    fireEvent.click(screen.getByRole("button", { name: /Osoby nie ma w bazie/ }));
    drop(fileInput(".pdf,.docx"), new File(["x"], "kandydat.pdf"));
    fireEvent.click(await screen.findByRole("button", { name: "Generuj bez dodawania" }));
    const champion = new File(["x"], "ProfilChampiona.docx");
    drop(fileInput(".docx"), champion);

    expect(await screen.findByText("Profil Championa przypięty bez podglądu")).toBeInTheDocument();
    expect(screen.getByText(/nieparsowalny JSON profilu/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Wybierz klienta/ }));
    fireEvent.click(await screen.findByText("Polkomtel"));
    await waitForGenerateEnabled();
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/ }));
    await waitFor(() => expect(generatePosts("/api/cv-generator/generate-upload")).toHaveLength(1), { timeout: 10000 });
    const fd = generatePosts("/api/cv-generator/generate-upload")[0][1] as FormData;
    expect(fd.get("champion_file")).toBe(champion);
    expect(fd.get("champion_profile_json")).toBeNull();
  });

  it("drops the preview notice together with the file", async () => {
    previewMock.mockRejectedValueOnce(new Error("preview down"));
    renderGenerator();
    fireEvent.click(screen.getByRole("button", { name: /Osoby nie ma w bazie/ }));
    drop(fileInput(".pdf,.docx"), new File(["x"], "kandydat.pdf"));
    fireEvent.click(await screen.findByRole("button", { name: "Generuj bez dodawania" }));
    drop(fileInput(".docx"), new File(["x"], "ProfilChampiona.docx"));
    await screen.findByText("Profil Championa przypięty bez podglądu");
    fireEvent.click(screen.getByRole("button", { name: "Usuń plik Championa" }));
    await waitFor(() => expect(screen.queryByText("Profil Championa przypięty bez podglądu")).not.toBeInTheDocument());
  });

  it("rejects a champion that is not .docx with a persistent error", async () => {
    renderGenerator();
    fireEvent.click(screen.getByRole("button", { name: /Osoby nie ma w bazie/ }));
    drop(fileInput(".pdf,.docx"), new File(["x"], "kandydat.pdf"));
    fireEvent.click(await screen.findByRole("button", { name: "Generuj bez dodawania" }));
    drop(fileInput(".docx"), new File(["x"], "Champion.pdf"));
    const region = screen.getByRole("region", { name: "Klient i źródła" });
    expect(within(region).getByRole("alert")).toHaveTextContent(/Dozwolone formaty/);
  });
});

describe("okno z procesu i uprawnienia", () => {
  it("osoba ustalona z góry — bez „Zmień” i bez wgrywania pliku, proces z rekrutacji", async () => {
    recruitments = [{ ...PKO, stage_id: 12, job_id: 900 }, PKO];
    renderGenerator({ embedded: true, prefillCandidateId: 1, prefillCandidateName: "Jan Kowalski", prefillJobId: 501 });
    expect(screen.getByText("Jan Kowalski")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zmień" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Osoby nie ma w bazie/ })).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Proces rekrutacyjny")).toHaveValue("11"));
  });

  it("bez zapisu w Sourcing — tryb tylko do odczytu", () => {
    setUser("read");
    renderGenerator();
    expect(screen.getByText("Tryb tylko do odczytu")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Generuj CV/ })).not.toBeInTheDocument();
  });

  it("onEnqueued dostaje id wygenerowanego CV", async () => {
    const onEnqueued = vi.fn();
    renderGenerator({ embedded: true, prefillCandidateId: 1, prefillCandidateName: "Jan Kowalski", prefillJobId: 501, onEnqueued });
    await waitForGenerateEnabled();
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/ }));
    await waitFor(() => expect(onEnqueued).toHaveBeenCalledWith(77), { timeout: 10000 });
  });
});
