import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AddCandidateModal } from "@/components/AppShell";
import api, { phase5Api } from "@/lib/api";

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
  aiWriterApi: {},
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

function renderModal(onSuccess = vi.fn(), onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AddCandidateModal onClose={onClose} onSuccess={onSuccess} />
    </QueryClientProvider>,
  );
  return { onSuccess, onClose };
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
    expect(body.get("email")).toBe("");
    expect(body.get("linkedin")).toBeNull(); // CV nie miało LinkedIna — nic do czyszczenia
    expect(JSON.parse(String(body.get("candidate")))).toEqual({ tags: ["java", "sql"] });
    expect(apiPatch).not.toHaveBeenCalled();
  });

  it("zajęty e-mail (409 także przy „Zapisz mimo to”) pokazuje się przy polu e-mail", async () => {
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

  it("CV rozpoznane przez sito jako istniejący kandydat — link i „Wczytaj mimo to”", async () => {
    apiPost.mockImplementation((url: string) => {
      if (url === "/api/candidates/cv/preview") {
        return Promise.reject({
          response: {
            status: 409,
            data: {
              detail: {
                detail: "Kandydat wygląda na duplikat istniejącego rekordu.",
                existing_candidate_id: 41,
                matches: [
                  {
                    candidate_id: 41,
                    name: "Anna",
                    lastname: "Nowak",
                    email: null,
                    match_score: 1,
                    match_reasons: ["cv_hash"],
                  },
                ],
              },
            },
          },
        });
      }
      if (url === "/api/candidates/cv/preview?force=true") {
        return Promise.resolve({ data: PREVIEW } as never);
      }
      return Promise.resolve({ data: [] } as never);
    });
    const user = userEvent.setup();
    renderModal();
    pickCv();

    expect(await screen.findByText(/To CV wygląda na kandydata z bazy: Anna Nowak/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Otwórz istniejącego" })).toHaveAttribute(
      "href",
      "/candidates/41",
    );
    await user.click(screen.getByRole("button", { name: "Wczytaj mimo to" }));
    expect(await screen.findByText(/Uzupełniono z CV/)).toBeInTheDocument();
  });
});
