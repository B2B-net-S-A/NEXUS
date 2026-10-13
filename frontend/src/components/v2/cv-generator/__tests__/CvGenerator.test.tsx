import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { configure, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ToastProvider } from "@/components/Toast";
import { useAuthStore } from "@/store/auth";

import { CvGenerator, type CvGeneratorProps } from "../CvGenerator";
import { NO_RECRUITMENT_MISSING } from "../cv-generator-form";

// Kaskada zapytań — pod obciążeniem (pełny przebieg na współdzielonej
// maszynie) domyślna sekunda to za mało.
configure({ asyncUtilTimeout: 10000 });

vi.mock("@/components/v2/modals/CVBrandedEditModal", () => ({ CVBrandedEditModal: () => null }));

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
  if (url.endsWith("/recruitments")) return { data: recruitments };
  if (url.endsWith("/cv-sources")) return { data: SOURCES };
  if (url === "/api/cv-generator/policy") return { data: POLICY };
  if (url.includes("rule-for-generation")) return { data: { is_active: false } };
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

/** Generator żyje tylko w oknie z rekrutacji / profilu — osoba zawsze z góry. */
function renderGenerator(props: Partial<CvGeneratorProps> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <CvGenerator prefillCandidateId={1} prefillCandidateName="Jan Kowalski" {...props} />
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

describe("generacja w rekrutacji", () => {
  it("jedyny proces wybiera sam, plik główny domyślnie, Champion → Pod rekrutację", async () => {
    renderGenerator();
    expect(screen.getByRole("button", { name: /Generuj CV/ })).toBeDisabled();
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
    await waitForGenerateEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Obie" }));
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/ }));
    await waitFor(() => expect(generatePosts("/api/cv-generator/generate")).toHaveLength(1), { timeout: 10000 });
    expect(generatePosts("/api/cv-generator/generate")[0][1]).toMatchObject({ language: "pl", languages: "both" });
  });

  it("osoba bez rekrutacji: nie ma „Inny klient (bez procesu)”, CV nie powstanie (13.10.2026)", async () => {
    recruitments = [];
    renderGenerator();
    expect(await screen.findByText(/Ta osoba nie jest w żadnej rekrutacji/)).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /Inny klient/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Proces rekrutacyjny")).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Treść CV" })).not.toBeInTheDocument();
    expect(screen.getByTestId("cvgen-missing")).toHaveTextContent(NO_RECRUITMENT_MISSING);
    expect(screen.getByRole("button", { name: /Generuj CV/ })).toBeDisabled();
  });

  it("dopisana notatka zapisuje się w rekrutacji PRZED generacją", async () => {
    recruitments = [NO_CHAMPION];
    renderGenerator();
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
    await screen.findByText("rekrutacja nie ma Championa");
    drop(fileInput(".docx,.pdf"), new File(["x"], "Champion.docx"));
    fireEvent.click(await screen.findByRole("button", { name: "Zastosuj / zapisz szkic" }));
    expect(await screen.findByText(/nie zapisał się w rekrutacji \(Brak uprawnień do edycji Championa\) — użyjemy go tylko do tego CV/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Pod rekrutację" })).toHaveAttribute("aria-pressed", "true"));
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/ }));
    await waitFor(() => expect(generatePosts("/api/cv-generator/generate")).toHaveLength(1), { timeout: 10000 });
    expect(generatePosts("/api/cv-generator/generate")[0][1]).toHaveProperty("champion_profile");
  });

  it("zapis Championa w rekrutacji wysyła tylko pola z dokumentu, bez notatek zespołu", async () => {
    recruitments = [NO_CHAMPION];
    previewMock.mockImplementation(async () => {
      const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
      const profile = structuredClone(actual.EMPTY_CHAMPION_PROFILE) as unknown as Record<string, unknown>;
      (profile.stack as Record<string, unknown>).must = [{ name: "Java" }];
      profile.insights = [];
      return { data: { champion_profile: profile } };
    });
    renderGenerator();
    await screen.findByText("rekrutacja nie ma Championa");
    drop(fileInput(".docx,.pdf"), new File(["x"], "Champion.docx"));
    fireEvent.click(await screen.findByRole("button", { name: "Zastosuj / zapisz szkic" }));
    await waitFor(() => expect(generatePosts("/api/jobs/501/champion-profile/apply-import")).toHaveLength(1));
    const body = generatePosts("/api/jobs/501/champion-profile/apply-import")[0][1] as { profile: Record<string, unknown> };
    expect(body.profile).not.toHaveProperty("insights");
    // Mock `/validate` odsyła profil bez normalizacji — liczy się, że pole z
    // dokumentu jedzie, a puste nie.
    expect(Object.keys(body.profile.stack as object)).toEqual(["must"]);
    // Puste sekcje dokumentu nie nadpisują zapisanych pól.
    expect(body.profile).not.toHaveProperty("project");
    expect(body.profile).not.toHaveProperty("screening_questions");
  });
});

// Cytowane w CLAUDE.md („AI w generatorze to dodatek, nigdy bramka”). Do
// 13.10.2026 pilnowała tego ścieżka „plik spoza bazy”; generator został tylko
// w rekrutacji, więc ta sama zasada na jej podglądzie Championa.
describe("CvGenerator — the AI champion preview is an aid, not a gate", () => {
  it("nieudany podgląd Championa mówi, co dalej, a CV dalej da się wygenerować (Redakcja)", async () => {
    recruitments = [NO_CHAMPION];
    previewMock.mockRejectedValueOnce(new Error("Nie udało się odczytać profilu: nieparsowalny JSON profilu"));
    renderGenerator();
    await screen.findByText("rekrutacja nie ma Championa");
    drop(fileInput(".docx,.pdf"), new File(["x"], "ProfilChampiona.docx"));
    expect(await screen.findByText(/Nie udało się odczytać pliku Championa \(Nie udało się odczytać profilu: nieparsowalny JSON profilu\)/)).toBeInTheDocument();
    await waitForGenerateEnabled();
    expect(screen.getByRole("button", { name: "Redakcja" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/ }));
    await waitFor(() => expect(generatePosts("/api/cv-generator/generate")).toHaveLength(1), { timeout: 10000 });
    expect(generatePosts("/api/cv-generator/generate")[0][1]).not.toHaveProperty("champion_profile");
  });
});

describe("okno z procesu i uprawnienia", () => {
  it("osoba ustalona z góry — bez szukania, „Zmień” i wgrywania pliku, proces z rekrutacji", async () => {
    recruitments = [{ ...PKO, stage_id: 12, job_id: 900 }, PKO];
    renderGenerator({ prefillJobId: 501 });
    expect(screen.getByText("Jan Kowalski")).toBeInTheDocument();
    expect(screen.queryByLabelText("Znajdź osobę")).not.toBeInTheDocument();
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
    renderGenerator({ prefillJobId: 501, onEnqueued });
    await waitForGenerateEnabled();
    fireEvent.click(screen.getByRole("button", { name: /Generuj CV/ }));
    await waitFor(() => expect(onEnqueued).toHaveBeenCalledWith(77), { timeout: 10000 });
  });
});
