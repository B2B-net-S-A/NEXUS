import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AddCandidateModal } from "@/components/AppShell";
import api, { phase5Api } from "@/lib/api";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/candidates",
}));
vi.mock("@/components/jobs/AutoAssignedCollaborators", () => ({
  AutoAssignedCollaborators: () => null,
}));
vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
  phase5Api: { clientsLookup: vi.fn() },
  pipelineTemplatesApi: { list: vi.fn() },
  requestHistoryApi: { preview: vi.fn() },
  clientTeamApi: { get: vi.fn() },
}));

const apiPost = vi.mocked(api.post);
const apiPatch = vi.mocked(api.patch);

const PREVIEW = {
  cv_sha256: "a".repeat(64),
  name: "Anna",
  lastname: "Nowak",
  email: "anna.nowak@firma.pl",
  phone: "+48 500 600 700",
  city: "Kraków",
  linkedin: null,
  current_position: "Tester",
  confidence: {},
  source: "claude",
};

function renderModal(onSuccess = vi.fn(), onClose = vi.fn(), onCreated = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AddCandidateModal onClose={onClose} onSuccess={onSuccess} onCreated={onCreated} />
    </QueryClientProvider>,
  );
  return { onSuccess, onClose, onCreated };
}

const EXISTING = {
  candidate_id: 41,
  name: "Anna",
  lastname: "Nowak",
  email: "anna.nowak@firma.pl",
  match_score: 1,
  match_reasons: ["email_exact"],
};

/** Odmowa 409 z `/cv/preview` i `/from-cv` — kształt z serwera. */
function conflict(match: Record<string, unknown>) {
  return {
    response: {
      status: 409,
      data: {
        detail: {
          detail: "Kandydat wygląda na duplikat istniejącego rekordu.",
          existing_candidate_id: match.candidate_id,
          matches: [match],
        },
      },
    },
  };
}

function callsTo(url: string) {
  return apiPost.mock.calls.filter(([called]) => String(called).startsWith(url));
}

function pickCv() {
  const file = new File(["%PDF-1.4"], "anna-nowak.pdf", { type: "application/pdf" });
  fireEvent.change(screen.getByTestId("add-candidate-cv-input"), {
    target: { files: [file] },
  });
  return file;
}

describe("AddCandidateModal — start od CV", () => {
  beforeEach(() => {
    apiPost.mockReset();
    apiPatch.mockReset();
    vi.mocked(api.get).mockResolvedValue({ data: [] } as never);
    vi.mocked(phase5Api.clientsLookup).mockResolvedValue({ data: [] } as never);
    apiPost.mockImplementation((url: string) => {
      if (url.startsWith("/api/candidates/cv/preview")) {
        return Promise.resolve({ data: PREVIEW } as never);
      }
      if (url === "/api/candidates/check-duplicates") {
        return Promise.resolve({ data: [] } as never);
      }
      if (url.startsWith("/api/candidates/from-cv")) {
        return Promise.resolve({ data: { candidate: { id: 77 } } } as never);
      }
      return Promise.resolve({ data: { id: 1 } } as never);
    });
  });

  it("czyta CV i wypełnia tylko puste pola", async () => {
    const user = userEvent.setup();
    renderModal();
    await user.type(screen.getByPlaceholderText("Jan"), "Ania");

    pickCv();

    expect(await screen.findByText(/Uzupełniono z CV: nazwisko, e-mail, telefon, miasto/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Jan")).toHaveValue("Ania");
    expect(screen.getByPlaceholderText("Kowalski")).toHaveValue("Nowak");
    expect(screen.getByPlaceholderText("Warszawa")).toHaveValue("Kraków");
    expect(callsTo("/api/candidates/cv/preview")).toHaveLength(1);
    // Odczyt liczy model: 12.10.2026 trwał 36,8 s, a okno czekało 30 s.
    expect(callsTo("/api/candidates/cv/preview")[0][2]).toMatchObject({
      timeout: SLOW_ENDPOINT_TIMEOUT_MS,
    });
  });

  it("w trakcie odczytu mówi, że to może potrwać do minuty", async () => {
    apiPost.mockImplementation((url: string) =>
      url.startsWith("/api/candidates/cv/preview")
        ? (new Promise(() => undefined) as never)
        : Promise.resolve({ data: [] } as never),
    );
    renderModal();

    pickCv();

    expect(await screen.findByText(/Czytam CV… to może potrwać do minuty/)).toBeInTheDocument();
  });

  it("przekroczenie czasu odczytu ma własny komunikat i „Spróbuj ponownie”", async () => {
    let attempt = 0;
    apiPost.mockImplementation((url: string) => {
      if (url.startsWith("/api/candidates/cv/preview")) {
        attempt += 1;
        return attempt === 1
          ? Promise.reject(Object.assign(new Error("timeout of 120000ms exceeded"), { code: "ECONNABORTED" }))
          : Promise.resolve({ data: PREVIEW } as never);
      }
      return Promise.resolve({ data: [] } as never);
    });
    const user = userEvent.setup();
    renderModal();
    pickCv();

    expect(await screen.findByText(/Odczyt CV trwa dłużej niż zwykle/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));

    expect(await screen.findByText(/Uzupełniono z CV/)).toBeInTheDocument();
    expect(callsTo("/api/candidates/cv/preview")).toHaveLength(2);
  });

  it("zapis z plikiem idzie przez /from-cv z polami formularza, nie przez zwykłe tworzenie", async () => {
    const user = userEvent.setup();
    const { onSuccess } = renderModal();
    pickCv();
    await screen.findByText(/Uzupełniono z CV/);
    const lastname = screen.getByPlaceholderText("Kowalski");
    await user.clear(lastname);
    await user.type(lastname, "Nowak-Kowalska");

    await user.click(screen.getByRole("button", { name: "Dodaj kandydata" }));

    await waitFor(() => expect(callsTo("/api/candidates/from-cv")).toHaveLength(1));
    const body = callsTo("/api/candidates/from-cv")[0][1] as FormData;
    expect(body.get("file")).toBeInstanceOf(File);
    expect(body.get("name")).toBe("Anna");
    expect(body.get("lastname")).toBe("Nowak-Kowalska");
    expect(body.get("email")).toBe("anna.nowak@firma.pl");
    expect(apiPost.mock.calls.some(([url]) => url === "/api/candidates")).toBe(false);
    expect(body.get("candidate")).toBeNull();
    expect(apiPatch).not.toHaveBeenCalled();
    expect(callsTo("/api/candidates/from-cv")[0][0]).toBe("/api/candidates/from-cv");
    expect(callsTo("/api/candidates/from-cv")[0][2]).toMatchObject({
      timeout: SLOW_ENDPOINT_TIMEOUT_MS,
    });
    await waitFor(() => expect(onSuccess).toHaveBeenCalledWith("Kandydat dodany pomyślnie"));
  });

  it("wyczyszczone pole idzie jako jawne \"\", a reszta formularza w tym samym żądaniu", async () => {
    const user = userEvent.setup();
    renderModal();
    pickCv();
    await screen.findByText(/Uzupełniono z CV/);
    await user.clear(screen.getByPlaceholderText("jan@mail.pl"));
    const tagsField = screen.getByPlaceholderText("React, TypeScript, Remote...");
    await user.type(tagsField, "java, sql");

    await user.click(screen.getByRole("button", { name: "Dodaj kandydata" }));

    await waitFor(() => expect(callsTo("/api/candidates/from-cv")).toHaveLength(1));
    const body = callsTo("/api/candidates/from-cv")[0][1] as FormData;
    // Pusty napis w multipart FastAPI czyta jak brak pola — wyczyszczone idą listą.
    expect(body.get("email")).toBeNull();
    expect(body.get("cleared")).toBe("email");
    expect(body.get("linkedin")).toBeNull(); // CV nie miało LinkedIna — nic do czyszczenia
    expect(JSON.parse(String(body.get("candidate")))).toEqual({ tags: ["java", "sql"] });
    expect(apiPatch).not.toHaveBeenCalled();
  });

  it("zajęty e-mail zwrócony przez serwer samym zdaniem (409) pokazuje się przy polu e-mail", async () => {
    apiPost.mockImplementation((url: string) => {
      if (url.startsWith("/api/candidates/cv/preview")) {
        return Promise.resolve({ data: PREVIEW } as never);
      }
      if (url === "/api/candidates/check-duplicates") {
        return Promise.resolve({ data: [] } as never);
      }
      if (url.startsWith("/api/candidates/from-cv")) {
        return Promise.reject({
          response: { status: 409, data: { detail: "Kandydat z tym adresem e-mail już istnieje." } },
        });
      }
      return Promise.resolve({ data: { id: 1 } } as never);
    });
    const user = userEvent.setup();
    const { onSuccess } = renderModal();
    pickCv();
    await screen.findByText(/Uzupełniono z CV/);

    await user.click(screen.getByRole("button", { name: "Dodaj kandydata" }));

    expect(await screen.findByText("Kandydat z tym adresem e-mail już istnieje.")).toBeInTheDocument();
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("ten sam plik jest już w czyimś profilu — link, „Wczytaj mimo to” i zapis z force", async () => {
    apiPost.mockImplementation((url: string) => {
      if (url === "/api/candidates/cv/preview") {
        return Promise.reject(
          conflict({ ...EXISTING, email: null, match_reasons: ["identical_file"] }),
        );
      }
      if (url === "/api/candidates/cv/preview?force=true") {
        return Promise.resolve({ data: { ...PREVIEW, email: "inny.adres@firma.pl" } } as never);
      }
      if (url.startsWith("/api/candidates/from-cv")) {
        return Promise.resolve({ data: { candidate: { id: 77 } } } as never);
      }
      return Promise.resolve({ data: [] } as never);
    });
    const user = userEvent.setup();
    renderModal();
    pickCv();

    expect(await screen.findByText("To CV jest już w profilu")).toBeInTheDocument();
    expect(screen.getByText(/Anna Nowak/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Otwórz profil" })).toHaveAttribute("href", "/candidates/41");
    // Plik już tam leży — nie ma czego dodawać.
    expect(screen.queryByRole("button", { name: "Dodaj to CV do profilu" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Wczytaj mimo to" }));
    expect(await screen.findByText(/Uzupełniono z CV/)).toBeInTheDocument();

    // Zapis pamięta decyzję rekrutera — bez `force` sito odmówiłoby drugi raz,
    // a okno nie ma już „Zapisz mimo to”.
    await user.click(screen.getByRole("button", { name: "Dodaj kandydata" }));
    await waitFor(() => expect(callsTo("/api/candidates/from-cv")).toHaveLength(1));
    expect(callsTo("/api/candidates/from-cv")[0][0]).toBe("/api/candidates/from-cv?force=true");
  });

  it("telefon z CV z tym samym imieniem i nazwiskiem (inny e-mail) — ramka przy CV i zapis z force", async () => {
    apiPost.mockImplementation((url: string) => {
      if (url.startsWith("/api/candidates/cv/preview")) {
        return Promise.resolve({ data: PREVIEW } as never);
      }
      if (url === "/api/candidates/check-duplicates") {
        return Promise.resolve({ data: [] } as never);
      }
      if (url === "/api/candidates/from-cv") {
        return Promise.reject(
          conflict({ ...EXISTING, email: "stary.adres@firma.pl", match_reasons: ["phone_exact", "name_exact"] }),
        );
      }
      if (url === "/api/candidates/from-cv?force=true") {
        return Promise.resolve({ data: { candidate: { id: 77 } } } as never);
      }
      return Promise.resolve({ data: { id: 1 } } as never);
    });
    const user = userEvent.setup();
    renderModal();
    pickCv();
    await screen.findByText(/Uzupełniono z CV/);

    await user.click(screen.getByRole("button", { name: "Dodaj kandydata" }));

    expect(await screen.findByText("Ten kandydat już jest w bazie")).toBeInTheDocument();
    expect(screen.getByText(/Ten sam telefon oraz imię i nazwisko co w CV/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dodaj to CV do profilu" })).toBeInTheDocument();

    // To inna osoba: odczyt z `force`, a zapis pamięta tę decyzję.
    await user.click(screen.getByRole("button", { name: "Wczytaj mimo to" }));
    await waitFor(() => expect(callsTo("/api/candidates/cv/preview?force=true")).toHaveLength(1));
    await user.click(await screen.findByRole("button", { name: "Dodaj kandydata" }));
    await waitFor(() =>
      expect(callsTo("/api/candidates/from-cv").map(([url]) => url)).toContain(
        "/api/candidates/from-cv?force=true",
      ),
    );
  });

  it("e-mail z CV należy do kandydata z bazy — „Dodaj to CV do profilu” jednym żądaniem", async () => {
    apiPost.mockImplementation((url: string) => {
      if (url === "/api/candidates/cv/preview") return Promise.reject(conflict(EXISTING));
      return Promise.resolve({ data: { id: 501 } } as never);
    });
    const user = userEvent.setup();
    const { onSuccess, onClose, onCreated } = renderModal();
    const file = pickCv();

    expect(await screen.findByText("Ten kandydat już jest w bazie")).toBeInTheDocument();
    expect(screen.getByText(/Anna Nowak · anna.nowak@firma.pl/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dodaj to CV do profilu" }));

    await waitFor(() => expect(callsTo("/api/candidates/41/documents")).toHaveLength(1));
    const body = callsTo("/api/candidates/41/documents")[0][1] as FormData;
    expect(body.get("file")).toBe(file);
    expect(body.get("document_kind")).toBe("cv");
    // Główne CV = AI od razu czyta je w tle i odświeża profil.
    expect(body.get("is_primary")).toBe("true");
    // W rekrutacji osoba trafia też do „Nowych” — jak nowy kandydat.
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(41, "Anna Nowak"));
    expect(onSuccess).toHaveBeenCalledWith(expect.stringMatching(/^CV dodane do profilu/));
    expect(onClose).toHaveBeenCalled();
    expect(callsTo("/api/candidates/from-cv")).toHaveLength(0);
  });

  it("e-mail wpisany w formularzu jest zajęty, a plik wybrany — ramka proponuje dodanie CV", async () => {
    apiPost.mockImplementation((url: string) => {
      if (url.startsWith("/api/candidates/cv/preview")) {
        return Promise.resolve({ data: PREVIEW } as never);
      }
      if (url === "/api/candidates/check-duplicates") {
        return Promise.resolve({ data: [EXISTING] } as never);
      }
      return Promise.resolve({ data: { id: 501 } } as never);
    });
    const user = userEvent.setup();
    const { onCreated } = renderModal();
    pickCv();
    await screen.findByText(/Uzupełniono z CV/);

    expect(await screen.findByText("Ten kandydat już jest w bazie")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dodaj kandydata" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Dodaj to CV do profilu" }));

    await waitFor(() => expect(callsTo("/api/candidates/41/documents")).toHaveLength(1));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(41, "Anna Nowak"));
  });

  it("odmowa po e-mailu dopiero przy zapisie pokazuje tę samą ramkę", async () => {
    apiPost.mockImplementation((url: string) => {
      if (url.startsWith("/api/candidates/cv/preview")) {
        // Odczyt nie znalazł adresu — serwer rozpozna go dopiero przy zapisie.
        return Promise.resolve({ data: { ...PREVIEW, email: null } } as never);
      }
      if (url.startsWith("/api/candidates/from-cv")) return Promise.reject(conflict(EXISTING));
      return Promise.resolve({ data: [] } as never);
    });
    const user = userEvent.setup();
    const { onSuccess } = renderModal();
    pickCv();
    await screen.findByText(/Uzupełniono z CV/);

    await user.click(screen.getByRole("button", { name: "Dodaj kandydata" }));

    expect(await screen.findByText("Ten kandydat już jest w bazie")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dodaj to CV do profilu" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz mimo to" })).toBeNull();
    expect(onSuccess).not.toHaveBeenCalled();

    // Pole e-mail jest puste, więc nie ma czego poprawić — wyjściem jest
    // wczytanie CV mimo odmowy (adres trafia wtedy do formularza).
    await user.click(screen.getByRole("button", { name: "Wczytaj mimo to" }));
    await waitFor(() =>
      expect(callsTo("/api/candidates/cv/preview?force=true")).toHaveLength(1),
    );
  });
});
