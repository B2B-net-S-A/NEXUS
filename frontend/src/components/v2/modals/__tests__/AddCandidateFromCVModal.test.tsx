import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AddCandidateFromCVModal } from "@/components/v2/modals/AddCandidateFromCVModal";
import api from "@/lib/api";

const stageUpload = vi.fn();
const stageRefresh = vi.fn();
const candidatePipelines = vi.fn();
vi.mock("@/lib/api", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  candidateStageCvApi: {
    original: {
      upload: (...a: unknown[]) => stageUpload(...a),
      refresh: (...a: unknown[]) => stageRefresh(...a),
    },
  },
  phase3Api: { candidatePipelines: (...a: unknown[]) => candidatePipelines(...a) },
  // Zapas komunikatu błędu (`assignErrorMessage`) — zdanie serwera i tak wygrywa.
  extractErrorMsg: () => undefined,
}));
const bulkAdd = vi.fn();
vi.mock("@/lib/candidate-search-api", () => ({
  proposalsBulkApi: { add: (...a: unknown[]) => bulkAdd(...a) },
}));
vi.mock("@/lib/celebrate", () => ({ celebrate: vi.fn() }));
// Przywrócenie karty ma własne testy (ruch karty, okno „Przenieś mimo to”).
vi.mock("@/components/v2/recruitment/ClosedCardRestore", () => ({
  ClosedCardRestore: (props: { headline: string; row: { reason_label: string }; onRestored: () => void }) => (
    <div>
      <p>{props.headline}</p>
      <p>{props.row.reason_label}</p>
      <button type="button" onClick={props.onRestored}>
        Przywróć do „Nowych”
      </button>
    </div>
  ),
}));

const apiPost = vi.mocked(api.post);
const JOB = { id: 7, title: "Senior Java Developer" };

function conflict(reason: string) {
  return {
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
              email: "anna.nowak@firma.pl",
              match_score: 1,
              match_reasons: [reason],
            },
          ],
        },
      },
    },
  };
}

function bulk(extra: Partial<{ total_added: number; skipped: unknown[] }> = {}) {
  return { added: [], skipped: [], warnings: [], total_added: 0, total_skipped: 0, ...extra };
}

function pipelines(rows: unknown[]) {
  return Promise.resolve({ data: { candidate_id: 41, candidate_name: "Anna Nowak", count: rows.length, pipelines: rows } });
}

function callsTo(url: string) {
  return apiPost.mock.calls.filter(([called]) => String(called).startsWith(url));
}

function renderModal() {
  const onChanged = vi.fn();
  const onOpenPerson = vi.fn();
  const onOpenChange = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AddCandidateFromCVModal
        open
        onOpenChange={onOpenChange}
        job={JOB}
        onChanged={onChanged}
        onOpenPerson={onOpenPerson}
      />
    </QueryClientProvider>,
  );
  return { onChanged, onOpenPerson, onOpenChange };
}

async function uploadCv(user: ReturnType<typeof userEvent.setup>, name = "anna-nowak.pdf") {
  const handlers = renderModal();
  const file = new File(["%PDF-1.4"], name, { type: "application/pdf" });
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
  await user.click(screen.getByRole("button", { name: /Parsuj CV/ }));
  return handlers;
}

function fromCvConflict(reason: string) {
  apiPost.mockImplementation((url: string) =>
    url === "/api/candidates/from-cv"
      ? Promise.reject(conflict(reason))
      : Promise.resolve({
          data: { candidate: { id: 77, name: "Anna", lastname: "Nowak" }, confidence: {} },
        } as never),
  );
}

// 13.10.2026 (prośba rekruterów): osoba z bazy nie zatrzymuje dodawania —
// „Dodaj do rekrutacji z tym CV” wgrywa CV na górę profilu i wpisuje osobę do
// „Nowych”; osoba w toku dostaje nowe CV przy swoim zgłoszeniu.
describe("AddCandidateFromCVModal — osoba już jest w bazie", () => {
  beforeEach(() => {
    apiPost.mockReset();
    bulkAdd.mockReset();
    stageUpload.mockReset();
    stageRefresh.mockReset();
    candidatePipelines.mockReset();
  });

  it("ten sam e-mail, nie ma jej w rekrutacji: CV jako główne i osoba w „Nowych”", async () => {
    fromCvConflict("email_exact");
    candidatePipelines.mockReturnValue(pipelines([]));
    bulkAdd.mockResolvedValue(bulk({ total_added: 1 }));
    const user = userEvent.setup();
    const { onChanged, onOpenPerson, onOpenChange } = await uploadCv(user);

    expect(await screen.findByText("Anna Nowak już jest w bazie")).toBeInTheDocument();
    expect(await screen.findByText(/Trafi do „Nowych” w rekrutacji Senior Java Developer/)).toBeInTheDocument();
    expect(screen.queryByText(/match:/)).toBeNull();
    expect(screen.getByRole("link", { name: /Otwórz profil/ })).toHaveAttribute("href", "/candidates/41");

    await user.click(screen.getByRole("button", { name: /Dodaj do rekrutacji z tym CV/ }));

    await waitFor(() => expect(callsTo("/api/candidates/41/documents")).toHaveLength(1));
    const body = callsTo("/api/candidates/41/documents")[0][1] as FormData;
    expect(body.get("document_kind")).toBe("cv");
    expect(body.get("is_primary")).toBe("true");
    expect(bulkAdd).toHaveBeenCalledWith(7, { candidate_ids: [41], source: "quick_add" });
    expect(await screen.findByText("Anna Nowak jest w „Nowych”")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Otwórz w panelu" }));
    expect(onOpenPerson).toHaveBeenCalledWith(41);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("ten sam telefon oraz imię i nazwisko: mówi to wprost i pozwala założyć osobny profil", async () => {
    fromCvConflict("phone_exact");
    candidatePipelines.mockReturnValue(pipelines([]));
    const user = userEvent.setup();
    await uploadCv(user);

    expect(await screen.findByText(/Ten sam telefon oraz imię i nazwisko co w CV/)).toBeInTheDocument();
    expect(screen.queryByText(/Ten sam adres e-mail/)).toBeNull();

    await user.click(screen.getByRole("button", { name: "To inna osoba? Załóż osobny profil" }));
    await waitFor(() =>
      expect(callsTo("/api/candidates/from-cv").map(([url]) => url)).toContain(
        "/api/candidates/from-cv?force=true",
      ),
    );
  });

  it("osoba w toku: „Podmień CV w tej rekrutacji” wgrywa CV na jej zgłoszenie jednym żądaniem", async () => {
    fromCvConflict("email_exact");
    candidatePipelines.mockReturnValue(
      pipelines([
        { candidate_stage_id: 900, job_id: 7, stage_name: "Screening", is_terminal: false, board_column: "screening" },
      ]),
    );
    stageUpload.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    await uploadCv(user);

    expect(await screen.findByText(/Jest już w tej rekrutacji \(Screening\)/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Podmień CV w tej rekrutacji/ }));

    await waitFor(() => expect(stageUpload).toHaveBeenCalledWith(900, expect.any(File)));
    expect(callsTo("/api/candidates/41/documents")).toHaveLength(0);
    expect(bulkAdd).not.toHaveBeenCalled();
    expect(await screen.findByText("Anna Nowak jest już w tej rekrutacji · Screening")).toBeInTheDocument();
  });

  // 15.10.2026: plik nazwany jak CV do klienta serwer zapisuje jako CV do klienta.
  it("osoba w toku, plik „B2B_…”: okno mówi, że plik jest CV do klienta, a CV kandydata bez zmian", async () => {
    fromCvConflict("email_exact");
    candidatePipelines.mockReturnValue(
      pipelines([
        { candidate_stage_id: 900, job_id: 7, stage_name: "Screening", is_terminal: false, board_column: "screening" },
      ]),
    );
    stageUpload.mockResolvedValue({
      data: {
        has_snapshot: true,
        outcome: "client_cv",
        client_cv_stage_id: 900,
        replaced: "none",
        undo_available: true,
        uploaded_filename: "B2B_Tester_Jan_Testowy.docx",
      },
    });
    const user = userEvent.setup();
    await uploadCv(user, "B2B_Tester_Jan_Testowy.docx");

    await user.click(await screen.findByRole("button", { name: /Podmień CV w tej rekrutacji/ }));

    await waitFor(() => expect(stageUpload).toHaveBeenCalledWith(900, expect.any(File)));
    expect(await screen.findByText("Anna Nowak jest już w tej rekrutacji · Screening")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Plik B2B_Tester_Jan_Testowy.docx jest teraz CV do klienta w tej rekrutacji. CV kandydata w profilu bez zmian.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/AI odświeży profil/)).toBeNull();
  });

  it("osoba w toku, klient ma już jej CV: plik tylko w profilu, CV do klienta bez zmian", async () => {
    fromCvConflict("email_exact");
    candidatePipelines.mockReturnValue(
      pipelines([
        { candidate_stage_id: 900, job_id: 7, stage_name: "CV wysłane", is_terminal: false, board_column: "sent" },
      ]),
    );
    stageUpload.mockResolvedValue({
      data: { has_snapshot: true, outcome: "client_cv_kept", stored_in_profile: true, uploaded_filename: "B2B_Tester_Jan_Testowy.docx" },
    });
    const user = userEvent.setup();
    await uploadCv(user, "B2B_Tester_Jan_Testowy.docx");

    await user.click(await screen.findByRole("button", { name: /Podmień CV w tej rekrutacji/ }));

    expect(
      await screen.findByText(
        "Klient ma już CV tej osoby, więc CV do klienta zostało bez zmian. Plik B2B_Tester_Jan_Testowy.docx jest w profilu w „CV dla klientów”.",
      ),
    ).toBeInTheDocument();
  });

  it("CV z nagłówkiem innej osoby: zdanie serwera w oknie, bez widoku sukcesu", async () => {
    fromCvConflict("email_exact");
    candidatePipelines.mockReturnValue(
      pipelines([
        { candidate_stage_id: 900, job_id: 7, stage_name: "Screening", is_terminal: false, board_column: "screening" },
      ]),
    );
    stageUpload.mockRejectedValue({
      response: {
        status: 422,
        data: {
          detail: {
            code: "client_cv_other_person",
            message: "Ten plik to CV innej osoby (Piotr Przykładowy) — nie wgrałem go.",
          },
        },
      },
    });
    const user = userEvent.setup();
    await uploadCv(user, "B2B_Tester_Piotr_Przykladowy.docx");

    await user.click(await screen.findByRole("button", { name: /Podmień CV w tej rekrutacji/ }));

    expect(await screen.findByText("Ten plik to CV innej osoby (Piotr Przykładowy) — nie wgrałem go.")).toBeInTheDocument();
    expect(screen.queryByText(/jest teraz CV do klienta/)).toBeNull();
  });

  it("serwer mówi „już w rekrutacji”, choć odczyt karty tego nie znał: CV tylko w profilu, bez zgadywania", async () => {
    fromCvConflict("email_exact");
    candidatePipelines.mockReturnValue(pipelines([]));
    bulkAdd.mockResolvedValue(bulk({ skipped: [{ candidate_id: 41, reason: "already_in_job" }] }));
    const user = userEvent.setup();
    await uploadCv(user);

    await user.click(await screen.findByRole("button", { name: /Dodaj do rekrutacji z tym CV/ }));

    expect(await screen.findByText("Anna Nowak jest już w tej rekrutacji")).toBeInTheDocument();
    expect(screen.getByText(/podmienisz w panelu osoby/)).toBeInTheDocument();
    expect(stageUpload).not.toHaveBeenCalled();
    expect(stageRefresh).not.toHaveBeenCalled();
  });

  it("lista rezerwowa to zamknięta karta (reguła Tablicy), nie osoba w toku", async () => {
    fromCvConflict("email_exact");
    candidatePipelines.mockReturnValue(
      pipelines([
        { candidate_stage_id: 902, job_id: 7, stage_name: "Lista rezerwowa", is_terminal: false, board_column: "closed" },
      ]),
    );
    bulkAdd.mockResolvedValue(
      bulk({
        skipped: [
          {
            candidate_id: 41,
            reason: "closed_in_job",
            reason_label: "Zamknięta karta w tej rekrutacji: Lista rezerwowa 9.10.2026",
            closed: { candidate_name: "Anna Nowak", state_version: 2, restore_stage: "new" },
          },
        ],
      }),
    );
    const user = userEvent.setup();
    await uploadCv(user);

    expect(await screen.findByText(/Ma w tej rekrutacji zamkniętą kartę \(Lista rezerwowa\)/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Dodaj do rekrutacji z tym CV/ }));

    expect(await screen.findByText("CV jest na górze profilu")).toBeInTheDocument();
    expect(stageUpload).not.toHaveBeenCalled();
  });

  it("zatrudniony: CV tylko do profilu, kopia przy zgłoszeniu bez zmian", async () => {
    fromCvConflict("email_exact");
    candidatePipelines.mockReturnValue(
      pipelines([
        { candidate_stage_id: 903, job_id: 7, stage_name: "Zatrudniony", is_terminal: true, board_column: "hired" },
      ]),
    );
    const user = userEvent.setup();
    await uploadCv(user);

    await user.click(await screen.findByRole("button", { name: "Dodaj CV do profilu" }));

    await waitFor(() => expect(callsTo("/api/candidates/41/documents")).toHaveLength(1));
    expect(bulkAdd).not.toHaveBeenCalled();
    expect(stageUpload).not.toHaveBeenCalled();
    expect(await screen.findByText("CV dodane do profilu · Anna Nowak · Zatrudniony")).toBeInTheDocument();
  });

  it("zamknięta karta: CV w profilu, powód z serwera i „Przywróć”", async () => {
    fromCvConflict("email_exact");
    candidatePipelines.mockReturnValue(
      pipelines([
        { candidate_stage_id: 901, job_id: 7, stage_name: "Odrzucony", is_terminal: true, board_column: "closed" },
      ]),
    );
    bulkAdd.mockResolvedValue(
      bulk({
        skipped: [
          {
            candidate_id: 41,
            reason: "closed_in_job",
            reason_label: "Zamknięta karta w tej rekrutacji: Odrzucony 9.10.2026 (M. Lis)",
            closed: { candidate_name: "Anna Nowak", state_version: 4, restore_stage: "new" },
          },
        ],
      }),
    );
    const user = userEvent.setup();
    await uploadCv(user);

    expect(await screen.findByText(/Ma w tej rekrutacji zamkniętą kartę \(Odrzucony\)/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Dodaj do rekrutacji z tym CV/ }));

    expect(await screen.findByText("CV jest na górze profilu")).toBeInTheDocument();
    expect(screen.getByText(/Odrzucony 9\.10\.2026 \(M\. Lis\)/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Przywróć do „Nowych”" }));
    expect(await screen.findByText("Anna Nowak jest znowu w „Nowych”")).toBeInTheDocument();
  });

  it("czarna lista: zostaje w oknie z powodem, bez widoku sukcesu", async () => {
    fromCvConflict("email_exact");
    candidatePipelines.mockReturnValue(pipelines([]));
    bulkAdd.mockResolvedValue(
      bulk({ skipped: [{ candidate_id: 41, reason: "blacklisted", reason_label: "czarna lista klienta" }] }),
    );
    const user = userEvent.setup();
    await uploadCv(user);

    await user.click(await screen.findByRole("button", { name: /Dodaj do rekrutacji z tym CV/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "CV jest na górze profilu, ale osoba nie trafiła do tej rekrutacji: czarna lista klienta",
    );
    expect(screen.getByText("Anna Nowak już jest w bazie")).toBeInTheDocument();
  });

  it("ten sam plik: „Dodaj do rekrutacji”, a drugi profil tylko z pytaniem", async () => {
    fromCvConflict("identical_file");
    candidatePipelines.mockReturnValue(pipelines([]));
    bulkAdd.mockResolvedValue(bulk({ total_added: 1 }));
    const user = userEvent.setup();
    await uploadCv(user);

    expect(await screen.findByText(/Ten plik leży już w profilu tej osoby/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz mimo to" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "To CV innej osoby? Załóż osobny profil" }));
    await waitFor(() => expect(callsTo("/api/candidates/from-cv?force=true")).toHaveLength(1));
  });

  it("ten sam plik: dodanie ustawia plik jako główne CV i wpisuje osobę do „Nowych”", async () => {
    fromCvConflict("identical_file");
    candidatePipelines.mockReturnValue(pipelines([]));
    bulkAdd.mockResolvedValue(bulk({ total_added: 1 }));
    const user = userEvent.setup();
    await uploadCv(user);

    await user.click(await screen.findByRole("button", { name: /^Dodaj do rekrutacji$/ }));

    await waitFor(() => expect(callsTo("/api/candidates/41/documents")).toHaveLength(1));
    expect((callsTo("/api/candidates/41/documents")[0][1] as FormData).get("is_primary")).toBe("true");
    expect(await screen.findByText("Anna Nowak jest w „Nowych”")).toBeInTheDocument();
  });
});

describe("AddCandidateFromCVModal — nowa osoba z CV", () => {
  beforeEach(() => {
    apiPost.mockReset();
    bulkAdd.mockReset();
  });

  it("okno samo dodaje osobę do „Nowych” i mówi o tym", async () => {
    apiPost.mockResolvedValue({
      data: { candidate: { id: 77, name: "Jan", lastname: "Lis" }, confidence: {} },
    } as never);
    bulkAdd.mockResolvedValue(bulk({ total_added: 1 }));
    const user = userEvent.setup();
    const { onChanged } = await uploadCv(user);

    expect(await screen.findByText(/Osoba jest w „Nowych” w rekrutacji Senior Java Developer/)).toBeInTheDocument();
    expect(bulkAdd).toHaveBeenCalledWith(7, { candidate_ids: [77], source: "quick_add" });
    expect(onChanged).toHaveBeenCalled();
  });

  it("Spacja na polu pliku otwiera wybór pliku", () => {
    renderModal();
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const click = vi.spyOn(input, "click");

    fireEvent.keyDown(screen.getByRole("button", { name: /Przeciągnij CV lub kliknij/ }), { key: " " });

    expect(click).toHaveBeenCalled();
  });
});
