/**
 * Jeden formularz screeningu (0424): zapis tylko zmian jednym `PUT` z wersją,
 * wypełnienie z notatki (puste pola, „z notatki”, notatka idzie z zapisem),
 * tryb tylko do odczytu i konflikt wersji, który nie kasuje pracy. Od
 * 14.10.2026: stawka na start (D2), notatka z doku (D3), „przekazano dalej” (P3).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ScreeningFormSave, ScreeningFormState } from "@/lib/api/screeningForm";
import { createNoteFillChannel } from "@/lib/note-fill-channel";
import { emptyMemory } from "@/lib/screening-memory";
import { useAuthStore } from "@/store/auth";
import { readScreeningMemory, useScreeningMemoryStore, writeScreeningMemory } from "@/store/screening-memory";
import {
  FORM_CANDIDATE_ID,
  FORM_JOB_ID,
  formSaveResult,
  formState,
} from "@/components/v2/screening-form/__tests__/screening-form-fixtures";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn(),
  send: vi.fn(),
  showSuccess: vi.fn(),
  showError: vi.fn(),
  showInfo: vi.fn(),
  showActionToast: vi.fn(),
  candidate: vi.fn(),
}));

vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => mocks.get(...a),
    put: (...a: unknown[]) => mocks.put(...a),
    post: (...a: unknown[]) => mocks.post(...a),
  };
  return {
    __esModule: true,
    default: client,
    api: client,
    candidatesApi: { update: vi.fn(), get: (...a: unknown[]) => mocks.candidate(...a) },
    screeningApi: {
      reassignContext: () =>
        Promise.resolve({ data: { stage_id: 0, available: false, source: null, previous_answers_count: 0 } }),
      reassignSuggestions: vi.fn(),
    },
  };
});

vi.mock("@/hooks/usePipelineMoveCore", () => ({
  usePipelineMoveCore: () => ({ send: (...a: unknown[]) => mocks.send(...a), dialogs: null }),
}));

vi.mock("@/hooks/useCapability", () => ({ useCapability: () => true }));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: mocks.showSuccess,
    showError: mocks.showError,
    showInfo: mocks.showInfo,
    showActionToast: mocks.showActionToast,
  }),
}));

vi.mock("@/components/v2/modals/RejectionV2", () => ({
  RejectionV2: (props: {
    subject?: { name: string; stageLabel?: string | null } | null;
    nextPerson?: { name: string; stageLabel: string } | null;
    pending?: boolean;
    onConfirm: (...a: unknown[]) => void;
  }) => (
    <div data-testid="rejection-stub">
      {props.subject ? (
        <p>{props.subject.stageLabel ? `${props.subject.name} · ${props.subject.stageLabel}` : props.subject.name}</p>
      ) : null}
      {props.nextPerson !== undefined ? (
        <p>{props.nextPerson ? `Dalej: ${props.nextPerson.name}` : "ostatnia osoba"}</p>
      ) : null}
      <button
        type="button"
        disabled={props.pending}
        onClick={() => props.onConfirm("", "", false, null, "Brak Azure")}
      >
        potwierdź odrzucenie
      </button>
      <button
        type="button"
        onClick={() =>
          props.onConfirm("9", "", false, null, undefined, "recruiter", null, null, {
            maxOnsiteDays: 0,
            saveToProfile: true,
          })
        }
      >
        odrzuć za tryb pracy
      </button>
    </div>
  ),
}));

import { ScreeningFullForm } from "../ScreeningFullForm";

let serverState: ScreeningFormState;

function routeGet(url: string) {
  if (url === "/api/screening-form") return Promise.resolve({ data: serverState });
  if (url === "/api/screening-form/versions") return Promise.resolve({ data: { items: [], total: 0 } });
  return Promise.reject(new Error(`nieoczekiwany GET ${url}`));
}

function httpError(status: number, detail: unknown) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { detail } } });
}

function mount(props: Partial<ComponentProps<typeof ScreeningFullForm>> = {}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <ScreeningFullForm
        candidateId={FORM_CANDIDATE_ID}
        jobId={FORM_JOB_ID}
        candidateName="Tomasz Wzorcowy"
        jobBudgetHourly={160}
        showHistory={false}
        {...props}
      />
    </QueryClientProvider>,
  );
  return queryClient;
}

function lastPut(): ScreeningFormSave {
  const call = mocks.put.mock.calls.at(-1);
  expect(call?.[0]).toBe("/api/screening-form");
  return call?.[1] as ScreeningFormSave;
}

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset();
  serverState = formState();
  mocks.get.mockImplementation((url: string) => routeGet(url));
  mocks.candidate.mockResolvedValue({ data: {} });
});

describe("ScreeningFullForm — zapis", () => {
  it("wysyła tylko zmieniony arkusz z wersją; karta i stawka bez zmian = null", async () => {
    serverState = formState({ version: 2, versions_count: 2, state_token: "token-2" });
    mocks.put.mockImplementation((_url: string, body: ScreeningFormSave) =>
      Promise.resolve({ data: formSaveResult(serverState, { changed: ["answers"] }) }),
    );
    const user = userEvent.setup();
    mount();

    const answers = await screen.findAllByLabelText("Odpowiedź");
    expect(answers).toHaveLength(2);
    await user.type(answers[0], "6 lat w Javie");
    expect(screen.getByText("Niezapisane zmiany")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Zapisz$/ }));

    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    const body = lastPut();
    expect(body).toMatchObject({
      candidate_id: FORM_CANDIDATE_ID,
      job_id: FORM_JOB_ID,
      expected_version: 2,
      state_token: "token-2",
      card: null,
      rate: null,
      note_import: null,
    });
    expect(body.sheet?.answers[0]).toMatchObject({ question_id: "q1", response: "6 lat w Javie", origin: "manual" });
    expect(mocks.showSuccess).toHaveBeenCalledWith("Formularz screeningu zapisany.");
  });

  it("bez zmian nic nie wysyła", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findAllByLabelText("Odpowiedź");
    await user.click(screen.getByRole("button", { name: /^Zapisz$/ }));
    expect(mocks.put).not.toHaveBeenCalled();
    expect(mocks.showInfo).toHaveBeenCalledWith("Nie ma zmian do zapisania.");
  });

  it("odmowa zapisu (403) zostaje na ekranie, a wpisana odpowiedź w polu", async () => {
    mocks.put.mockRejectedValue(httpError(403, "Brak uprawnień do zapisu screeningu"));
    const user = userEvent.setup();
    mount();
    const [first] = await screen.findAllByLabelText("Odpowiedź");
    await user.type(first, "Tak, 3 lata");
    await user.click(screen.getByRole("button", { name: /^Zapisz$/ }));

    await waitFor(() =>
      expect(screen.getAllByRole("alert").some((el) => el.textContent?.includes("Brak uprawnień do zapisu screeningu"))).toBe(
        true,
      ),
    );
    expect(first).toHaveValue("Tak, 3 lata");
    expect(mocks.showError).toHaveBeenCalledWith("Brak uprawnień do zapisu screeningu");
  });
});

describe("ScreeningFullForm — wypełnienie z notatki", () => {
  it("wypełnia puste pola, a zapis niesie notatkę i pochodzenie pól", async () => {
    serverState = formState({ assist_enabled: true });
    mocks.post.mockImplementation((url: string) => {
      if (url !== "/api/recommendation-cards/note/read") return Promise.reject(new Error(url));
      return Promise.resolve({
        data: {
          fields: [
            {
              key: "availability",
              label: "Dostępność",
              current: null,
              current_source: null,
              proposed: "od zaraz",
              quote: "dostępny od zaraz",
              origin: "note_ai",
              changed: true,
            },
            {
              key: "rate",
              label: "Stawka",
              current: null,
              current_source: null,
              proposed: "150 zł/h",
              quote: null,
              origin: "note_rule",
              changed: true,
              rate: { amount: 150, unit: "hourly", currency: "PLN" },
            },
          ],
          answers: [
            {
              question_id: "q1",
              number: 1,
              question: "Ile lat pracujesz z Javą?",
              current: null,
              keywords: "java 6 lat",
              sentence: "Pracuje z Javą od 6 lat.",
              problem: null,
            },
          ],
          available: true,
          message: null,
          language: "pl",
          rate_change_notifies: false,
          text: "Rozmowa: java 6 lat, dostępny od zaraz, 150 zł/h na B2B.",
        },
      });
    });
    mocks.put.mockImplementation(() =>
      Promise.resolve({ data: formSaveResult(serverState, { changed: ["answers", "card", "rate"], note_id: 77 }) }),
    );
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole("button", { name: /Wklej tekst/ }));
    await user.type(
      screen.getByLabelText("Notatka z rozmowy"),
      "Rozmowa: java 6 lat, dostępny od zaraz, 150 zł/h na B2B.",
    );
    await user.click(screen.getByRole("button", { name: "Odczytaj notatkę" }));

    expect(await screen.findByTestId("note-fill-summary")).toHaveTextContent("wypełniono 3 miejsca");
    expect(screen.getByLabelText("Dostępność")).toHaveValue("od zaraz");
    expect(screen.getAllByLabelText("Odpowiedź")[0]).toHaveValue("Pracuje z Javą od 6 lat.");
    expect(screen.getByLabelText("Kwota")).toHaveValue(150);

    await user.click(screen.getByRole("button", { name: /^Zapisz$/ }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    const body = lastPut();
    expect(body.note_import).toEqual({ text: "Rozmowa: java 6 lat, dostępny od zaraz, 150 zł/h na B2B." });
    expect(body.card).toEqual({ fields: { availability: "od zaraz" }, origins: { availability: { origin: "note_ai" } } });
    expect(body.rate).toEqual({ amount: 150, unit: "hourly", currency: "PLN" });
    expect(body.sheet?.answers[0]).toMatchObject({
      question_id: "q1",
      response: "Pracuje z Javą od 6 lat.",
      origin: "phrased",
      keywords: "java 6 lat",
    });
  });

  it("„Cofnij wypełnienie” przywraca pola sprzed notatki", async () => {
    serverState = formState({ assist_enabled: true });
    mocks.post.mockResolvedValue({
      data: {
        fields: [
          {
            key: "availability",
            label: "Dostępność",
            current: null,
            current_source: null,
            proposed: "od zaraz",
            quote: null,
            origin: "note_rule",
            changed: true,
          },
        ],
        answers: [],
        available: true,
        message: null,
        language: "pl",
        rate_change_notifies: false,
        text: "Dostępny od zaraz, bez okresu wypowiedzenia, zdalnie.",
      },
    });
    const user = userEvent.setup();
    mount();
    await user.click(await screen.findByRole("button", { name: /Wklej tekst/ }));
    await user.type(screen.getByLabelText("Notatka z rozmowy"), "Dostępny od zaraz, bez okresu wypowiedzenia, zdalnie.");
    await user.click(screen.getByRole("button", { name: "Odczytaj notatkę" }));
    expect(await screen.findByLabelText("Dostępność")).toHaveValue("od zaraz");

    await user.click(screen.getByRole("button", { name: /Cofnij wypełnienie/ }));
    expect(screen.getByLabelText("Dostępność")).toHaveValue("");
    expect(screen.queryByTestId("note-fill-summary")).toBeNull();
    // Formularz wrócił do stanu sprzed notatki — nie ma czego zapisywać
    // (przeklik na produkcji 08.10.2026: stopka zostawała „Niezapisane zmiany”).
    await waitFor(() => expect(screen.queryByText("Niezapisane zmiany")).toBeNull());
  });

  it("bez włączonej funkcji karty z notatki nie ma paska notatki", async () => {
    mount();
    await screen.findAllByLabelText("Odpowiedź");
    expect(screen.queryByRole("button", { name: /Wklej tekst/ })).toBeNull();
  });
});

describe("ScreeningFullForm — kolejność sekcji (09.10.2026)", () => {
  const before = (first: Element, second: Element) =>
    Boolean(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING);

  it("„Warunki” stoją nad pytaniami, „Ocena” na końcu", async () => {
    mount();
    const terms = await screen.findByRole("region", { name: "Warunki" });
    const questions = screen.getByRole("region", { name: "Pytania z Profilu Championa" });
    const assessment = screen.getByRole("region", { name: "Ocena" });
    expect(before(terms, questions)).toBe(true);
    expect(before(questions, assessment)).toBe(true);
  });

  it("widok do odczytu trzyma tę samą kolejność: stawka nad odpowiedziami", async () => {
    serverState = formState({
      editable: false,
      read_only_reason: "process_closed",
      read_only_message: "Proces tej osoby jest zakończony — formularz jest tylko do odczytu.",
      sheet: { answers: [{ question_id: "q1", response: "6 lat", deal_breaker_hit: false }], overall_fit: "fit", notes: "" },
      rate: { amount: 150, unit: "hourly", currency: "PLN", source: "stage", at: null },
    });
    mount();
    const rate = await screen.findByText("150 zł/h");
    expect(before(rate, screen.getByText("6 lat"))).toBe(true);
  });
});

describe("ScreeningFullForm — tylko do odczytu i konflikt", () => {
  it("proces zakończony: widok do odczytu z powodem, bez „Zapisz”", async () => {
    serverState = formState({
      editable: false,
      read_only_reason: "process_closed",
      read_only_message: "Proces tej osoby jest zakończony — formularz jest tylko do odczytu.",
      sheet: { answers: [{ question_id: "q1", response: "6 lat", deal_breaker_hit: false }], overall_fit: "fit", notes: "" },
      rate: { amount: 150, unit: "hourly", currency: "PLN", source: "stage", at: null },
    });
    mount();
    expect(await screen.findByTestId("screening-form-readonly")).toBeInTheDocument();
    expect(screen.getByText(/Proces tej osoby jest zakończony/)).toBeInTheDocument();
    expect(screen.getByText("150 zł/h")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Zapisz$/ })).toBeNull();
    expect(screen.queryByLabelText("Odpowiedź")).toBeNull();
  });

  it("prop `readOnly` też blokuje edycję", async () => {
    mount({ readOnly: true });
    expect(await screen.findByTestId("screening-form-readonly")).toBeInTheDocument();
  });

  it("409 konfliktu wersji: komunikat z autorem, praca zostaje, formularz czyta się od nowa", async () => {
    mocks.put.mockRejectedValue(
      httpError(409, {
        code: "SCREENING_FORM_VERSION_CONFLICT",
        current_version: 3,
        saved_by_name: "Marta Testowa",
        saved_at: null,
        message: "Ktoś zapisał formularz w międzyczasie.",
      }),
    );
    const user = userEvent.setup();
    mount();
    const [first] = await screen.findAllByLabelText("Odpowiedź");
    await user.type(first, "Moja odpowiedź");
    const getsBefore = mocks.get.mock.calls.filter(([url]) => url === "/api/screening-form").length;

    // Serwer ma już wersję 3 kogoś innego (inna odpowiedź na pytanie 2).
    serverState = formState({
      version: 3,
      versions_count: 3,
      sheet: { answers: [{ question_id: "q2", response: "Tak", deal_breaker_hit: false }], overall_fit: "uncertain", notes: "" },
    });
    await user.click(screen.getByRole("button", { name: /^Zapisz$/ }));

    expect(await screen.findByText(/Marta Testowa zapisał\(a\) ten formularz w międzyczasie/)).toBeInTheDocument();
    await waitFor(() =>
      expect(mocks.get.mock.calls.filter(([url]) => url === "/api/screening-form").length).toBeGreaterThan(getsBefore),
    );
    await waitFor(() => expect(screen.getAllByLabelText("Odpowiedź")[1]).toHaveValue("Tak"));
    expect(screen.getAllByLabelText("Odpowiedź")[0]).toHaveValue("Moja odpowiedź");
    expect(mocks.showError).not.toHaveBeenCalled();
  });
});

describe("ScreeningFullForm — odświeżenie w tle i odcisk stanu", () => {
  it("odświeżenie przy niezapisanych zmianach: nieruszone pola biorą świeże wartości, zapis liczy się od nich", async () => {
    mocks.put.mockImplementation(() => Promise.resolve({ data: formSaveResult(serverState, { changed: ["answers"] }) }));
    const user = userEvent.setup();
    const queryClient = mount();
    const [first] = await screen.findAllByLabelText("Odpowiedź");
    await user.type(first, "Moja odpowiedź");

    // Ktoś odpowiedział na pytanie 2 obok formularza (bez nowej wersji).
    serverState = formState({
      state_token: "token-ext",
      sheet: { answers: [{ question_id: "q2", response: "Tak", deal_breaker_hit: false }], overall_fit: "uncertain", notes: "" },
    });
    await queryClient.invalidateQueries({ queryKey: ["screening-form", FORM_JOB_ID, FORM_CANDIDATE_ID] });

    await waitFor(() => expect(screen.getAllByLabelText("Odpowiedź")[1]).toHaveValue("Tak"));
    expect(screen.getAllByLabelText("Odpowiedź")[0]).toHaveValue("Moja odpowiedź");
    expect(screen.getByText(/obok formularza/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Zapisz$/ }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    const body = lastPut();
    // Odcisk stanu, który widać w polach — i odpowiedź kolegi nie jest cofana.
    expect(body.state_token).toBe("token-ext");
    expect(body.sheet?.answers.map((a) => a.response)).toEqual(["Moja odpowiedź", "Tak"]);
  });

  it("409 przez zmianę obok formularza (bez autora): zdanie serwera, praca zostaje", async () => {
    mocks.put.mockRejectedValue(
      httpError(409, {
        code: "SCREENING_FORM_VERSION_CONFLICT",
        current_version: 0,
        saved_by_name: null,
        saved_at: null,
        message: "Ktoś zmienił formularz w międzyczasie — wczytaliśmy nową wersję, Twoje zmiany zostały w polach.",
      }),
    );
    const user = userEvent.setup();
    mount();
    const [first] = await screen.findAllByLabelText("Odpowiedź");
    await user.type(first, "Moja odpowiedź");
    await user.click(screen.getByRole("button", { name: /^Zapisz$/ }));

    expect(await screen.findByText(/Ktoś zmienił formularz w międzyczasie/)).toBeInTheDocument();
    expect(screen.getAllByLabelText("Odpowiedź")[0]).toHaveValue("Moja odpowiedź");
    expect(mocks.showError).not.toHaveBeenCalled();
  });

  it("„Cofnij” po zapisie z notatki odsyła odcisk z odpowiedzi i mówi, że stawka została", async () => {
    serverState = formState({ assist_enabled: true, version: 1, versions_count: 1, state_token: "token-1" });
    mocks.post.mockImplementation((url: string) => {
      if (url === "/api/recommendation-cards/note/read") {
        return Promise.resolve({
          data: {
            fields: [
              {
                key: "availability",
                label: "Dostępność",
                current: null,
                current_source: null,
                proposed: "od zaraz",
                quote: "dostępny od zaraz",
                origin: "note_ai",
                changed: true,
              },
            ],
            answers: [],
            available: true,
            message: null,
            language: "pl",
            rate_change_notifies: false,
            text: "Rozmowa z kandydatem: dostępny od zaraz, szuka dłuższego projektu.",
          },
        });
      }
      if (url === "/api/screening-form/restore") {
        return Promise.resolve({
          data: {
            ...formSaveResult(formState({ version: 2, versions_count: 2 })),
            rate_not_restored: true,
            rate_not_restored_reason: "not_in_version",
            skipped_answers: [],
          },
        });
      }
      return Promise.reject(new Error(url));
    });
    mocks.put.mockImplementation(() =>
      Promise.resolve({
        data: formSaveResult(serverState, { changed: ["card"], note_id: 77, undo_to_version: 1, state_token: "token-2" }),
      }),
    );
    const user = userEvent.setup();
    mount();

    await user.click(await screen.findByRole("button", { name: /Wklej tekst/ }));
    await user.type(
      screen.getByLabelText("Notatka z rozmowy"),
      "Rozmowa z kandydatem: dostępny od zaraz, szuka dłuższego projektu.",
    );
    await user.click(screen.getByRole("button", { name: "Odczytaj notatkę" }));
    await screen.findByTestId("note-fill-summary");
    await user.click(screen.getByRole("button", { name: /^Zapisz$/ }));

    await waitFor(() => expect(mocks.showActionToast).toHaveBeenCalledTimes(1));
    const [, options] = mocks.showActionToast.mock.calls[0] as [string, { onAction: () => void }];
    options.onAction();

    await waitFor(() =>
      expect(mocks.post).toHaveBeenCalledWith("/api/screening-form/restore", {
        candidate_id: FORM_CANDIDATE_ID,
        job_id: FORM_JOB_ID,
        version_no: 1,
        expected_version: 2,
        state_token: "token-2",
        mode: "undo",
      }),
    );
    await waitFor(() =>
      expect(mocks.showSuccess).toHaveBeenCalledWith(
        "Cofnięto zapis — stawka kandydata została, zmień ją w formularzu.",
      ),
    );
  });
});

describe("ScreeningFullForm — „Zapisz i przekaż dalej”", () => {
  const forward = { stage: "verified", stageDefId: 12, label: "Zweryfikowany" };

  it("bez odpowiedzi na wszystkie pytania nie zapisuje i nie przesuwa", async () => {
    const user = userEvent.setup();
    mount({ forward });
    await screen.findAllByLabelText("Odpowiedź");
    await user.click(screen.getByRole("button", { name: /Zapisz i przekaż dalej/ }));
    expect(mocks.showError).toHaveBeenCalledWith("Uzupełnij 2 odpowiedzi przed przekazaniem dalej.");
    expect(mocks.put).not.toHaveBeenCalled();
    expect(mocks.send).not.toHaveBeenCalled();
  });

  it("zapisuje, potem przesuwa ze stawką i wersją procesu z odpowiedzi zapisu", async () => {
    mocks.put.mockImplementation(() =>
      Promise.resolve({ data: formSaveResult(serverState, { process_state_version: 4 }) }),
    );
    mocks.send.mockResolvedValue({ ok: true, data: {} });
    const onMoved = vi.fn();
    const user = userEvent.setup();
    mount({ forward, onMoved });
    const answers = await screen.findAllByLabelText("Odpowiedź");
    await user.type(answers[0], "6 lat");
    await user.type(answers[1], "Tak, 2 lata");
    await user.type(screen.getByLabelText("Kwota"), "150");
    await user.click(screen.getByRole("button", { name: /Zapisz i przekaż dalej/ }));

    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    expect(mocks.put).toHaveBeenCalledTimes(1);
    expect(mocks.send.mock.calls[0][0]).toMatchObject({
      candidate_id: FORM_CANDIDATE_ID,
      job_id: FORM_JOB_ID,
      stage: "verified",
      stage_def_id: 12,
      expected_rate_value: 150,
      expected_rate_unit: "hourly",
      expected_rate_currency: "PLN",
      expected_state_version: 4,
    });
    await waitFor(() => expect(onMoved).toHaveBeenCalled());
    expect(mocks.showSuccess).toHaveBeenCalledWith("Tomasz Wzorcowy — przekazano dalej: Zweryfikowany.");
  });
});

describe("ScreeningFullForm — rekrutacja bez pytań screeningowych (12.10.2026)", () => {
  const forward = { stage: "verified", stageDefId: 12, label: "Zweryfikowany" };

  beforeEach(() => {
    serverState = formState({ champion_profile: {} });
  });

  it("pusty stan mówi, co wystarcza do ruchu dalej, zamiast odsyłać po pytania", async () => {
    mount({ forward });
    const section = await screen.findByRole("region", { name: "Pytania z Profilu Championa" });
    expect(section).toHaveTextContent("Ta rekrutacja nie ma pytań screeningowych w Profilu Championa");
    expect(section).toHaveTextContent("wystarczy stawka kandydata i pole „Dlaczego ten kandydat”");
    expect(section).not.toHaveTextContent("TAC");
  });

  it("bez „Dlaczego ten kandydat” nie zapisuje i nie przesuwa — mówi, co wpisać", async () => {
    const user = userEvent.setup();
    mount({ forward });
    await screen.findByLabelText("Dlaczego ten kandydat");
    await user.type(screen.getByLabelText("Kwota"), "150");
    await user.click(screen.getByRole("button", { name: /Zapisz i przekaż dalej/ }));
    expect(mocks.showError).toHaveBeenCalledWith(
      "Ta rekrutacja nie ma pytań screeningowych — przed przekazaniem dalej wpisz „Dlaczego ten kandydat”.",
    );
    expect(await screen.findByText("Wpisz, dlaczego ten kandydat")).toBeTruthy();
    expect(mocks.put).not.toHaveBeenCalled();
    expect(mocks.send).not.toHaveBeenCalled();
    // Błąd nie zostaje pod polem po wpisaniu treści.
    await user.type(screen.getByLabelText("Dlaczego ten kandydat"), "SQL");
    await waitFor(() => expect(screen.queryByText("Wpisz, dlaczego ten kandydat")).toBeNull());
  });

  it("z „Dlaczego ten kandydat” i stawką zapisuje i przesuwa na „Zweryfikowany”", async () => {
    mocks.put.mockImplementation(() =>
      Promise.resolve({ data: formSaveResult(serverState, { process_state_version: 2 }) }),
    );
    mocks.send.mockResolvedValue({ ok: true, data: {} });
    const user = userEvent.setup();
    mount({ forward });
    await user.type(await screen.findByLabelText("Dlaczego ten kandydat"), "Raportowanie podatkowe, SQL");
    await user.type(screen.getByLabelText("Kwota"), "150");
    await user.click(screen.getByRole("button", { name: /Zapisz i przekaż dalej/ }));

    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    expect(lastPut().card?.fields).toMatchObject({ recommendation: "Raportowanie podatkowe, SQL" });
    expect(mocks.send.mock.calls[0][0]).toMatchObject({ stage: "verified", expected_rate_value: 150 });
    expect(mocks.showError).not.toHaveBeenCalled();
  });
});

describe("ScreeningFullForm — minimum dla Delivery Leada (21.10.2026)", () => {
  const forward = { stage: "verified", stageDefId: 12, label: "Zweryfikowany" };
  const carried = {
    location: { raw: "Warszawa", at: "2026-10-20T10:00:00+00:00", job_id: 7, job_title: "Java Developer — Bank A" },
  };

  function minimumState(overrides: Partial<ScreeningFormState["card"]> = {}): ScreeningFormState {
    const base = formState().card!;
    return formState({
      board_column: "screening",
      card: {
        ...base,
        labels: { ...base.labels, location: "Lokalizacja" },
        editable_fields: [...base.editable_fields, "location"],
        required: ["location", "work_mode", "availability", "recommendation"],
        ...overrides,
      },
    });
  }

  it("lokalizacja z innej rekrutacji wpisuje się sama, mówi skąd i zapisuje z „Zapisz”", async () => {
    serverState = minimumState({ carried });
    mocks.put.mockImplementation(() => Promise.resolve({ data: formSaveResult(serverState) }));
    const user = userEvent.setup();
    mount({ forward });

    expect(await screen.findByLabelText("Lokalizacja")).toHaveValue("Warszawa");
    expect(
      screen.getByText("z rozmowy 20.10.2026 · Java Developer — Bank A — sprawdź i zapisz"),
    ).toBeInTheDocument();
    // Sama podpowiedź nie zapala „Niezapisanych zmian”.
    expect(screen.queryByText("Niezapisane zmiany")).toBeNull();

    await user.click(screen.getByRole("button", { name: /^Zapisz$/ }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    expect(lastPut().card?.fields).toMatchObject({ location: "Warszawa" });
  });

  it("bez pól minimum nie zapisuje i nie przesuwa — stopka i komunikat mówią, czego brakuje", async () => {
    serverState = minimumState();
    const user = userEvent.setup();
    mount({ forward });
    const answers = await screen.findAllByLabelText("Odpowiedź");
    await user.type(answers[0], "6 lat");
    await user.type(answers[1], "Tak, 2 lata");
    await user.type(screen.getByLabelText("Kwota"), "150");
    await user.type(screen.getByLabelText("Lokalizacja"), "-");

    expect(screen.getByTestId("screening-form-minimum")).toHaveTextContent(
      "Minimum dla Delivery Leada — brakuje: Lokalizacja, Tryb pracy, Dostępność, Dlaczego ten kandydat",
    );
    await user.click(screen.getByRole("button", { name: /Zapisz i przekaż dalej/ }));
    expect(mocks.showError).toHaveBeenCalledWith(
      "Przed przekazaniem dalej uzupełnij: Lokalizacja, Tryb pracy, Dostępność, Dlaczego ten kandydat.",
    );
    expect(mocks.put).not.toHaveBeenCalled();
    expect(mocks.send).not.toHaveBeenCalled();
    expect(screen.getAllByText("Delivery Lead potrzebuje tego pola").length).toBeGreaterThan(0);
  });

  it("z kompletem minimum stopka mówi „komplet” i ruch idzie dalej", async () => {
    serverState = minimumState({ availability_in_profile: true });
    mocks.put.mockImplementation(() =>
      Promise.resolve({ data: formSaveResult(serverState, { process_state_version: 2 }) }),
    );
    mocks.send.mockResolvedValue({ ok: true, data: {} });
    const user = userEvent.setup();
    mount({ forward });
    const answers = await screen.findAllByLabelText("Odpowiedź");
    await user.type(answers[0], "6 lat");
    await user.type(answers[1], "Tak, 2 lata");
    await user.type(screen.getByLabelText("Kwota"), "150");
    await user.type(screen.getByLabelText("Lokalizacja"), "Kraków");
    await user.type(screen.getByLabelText("Tryb pracy"), "zdalnie");
    await user.type(screen.getByLabelText("Dlaczego ten kandydat"), "6 lat w Javie w bankowości.");

    expect(screen.getByTestId("screening-form-minimum")).toHaveTextContent("Minimum dla Delivery Leada: komplet");
    await user.click(screen.getByRole("button", { name: /Zapisz i przekaż dalej/ }));
    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    expect(lastPut().card?.fields).toMatchObject({ location: "Kraków", work_mode: "zdalnie" });
  });

  // 22.10.2026: Delivery Lead przekazuje dalej bez odpowiedzi i minimum —
  // serwer też go przepuszcza; stopka dalej mówi, czego brakuje.
  it("Delivery Lead przekazuje dalej bez odpowiedzi i bez minimum", async () => {
    useAuthStore.setState({
      user: { id: 3, role: "delivery_lead", roles: ["delivery_lead"], skips_fill_gates: true },
    } as never);
    try {
      serverState = minimumState();
      mocks.put.mockImplementation(() =>
        Promise.resolve({ data: formSaveResult(serverState, { process_state_version: 2 }) }),
      );
      mocks.send.mockResolvedValue({ ok: true, data: {} });
      const user = userEvent.setup();
      mount({ forward });
      await screen.findAllByLabelText("Odpowiedź");
      await user.type(screen.getByLabelText("Lokalizacja"), "Kraków");

      expect(screen.getByTestId("screening-form-minimum")).toHaveTextContent("brakuje");
      await user.click(screen.getByRole("button", { name: /Zapisz i przekaż dalej/ }));
      await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
      expect(mocks.showError).not.toHaveBeenCalled();
    } finally {
      useAuthStore.setState({ user: null } as never);
    }
  });

  // Audyt 22.10.2026 (F109): wyłącznik `DL_SKIPS_FILL_GATES=false` — DL jak
  // rekruter: bez odpowiedzi i minimum formularz nie przekazuje dalej.
  it("Delivery Lead przy wyłączonym DL_SKIPS_FILL_GATES nie przekazuje dalej bez kompletu", async () => {
    useAuthStore.setState({
      user: { id: 3, role: "delivery_lead", roles: ["delivery_lead"], skips_fill_gates: false },
    } as never);
    try {
      serverState = minimumState();
      const user = userEvent.setup();
      mount({ forward });
      await screen.findAllByLabelText("Odpowiedź");
      await user.click(screen.getByRole("button", { name: /Zapisz i przekaż dalej/ }));
      await waitFor(() => expect(mocks.showError).toHaveBeenCalled());
      expect(mocks.put).not.toHaveBeenCalled();
      expect(mocks.send).not.toHaveBeenCalled();
    } finally {
      useAuthStore.setState({ user: null } as never);
    }
  });
});

describe("ScreeningFullForm — prośba Delivery Leada o poprawki (D6)", () => {
  const fixRequest = {
    version_no: 3,
    stage_id: 901,
    requested_at: "2026-10-08T08:30:00Z",
    requested_by_name: "Dorota DL",
    remark: "Dopisz, jak używał Kafki",
    fields: [
      { key: "question:q2", label: "Pytanie 2: Czy pracowałeś z Kafką?", changed: false },
      { key: "field:availability", label: "Dostępność", changed: true },
      { key: "candidate_rate", label: "Stawka kandydata", changed: false },
    ],
    count: 3,
    changed_count: 1,
  };

  it("baner z polami i uwagą; pole oznaczone „Do poprawy”, a po edycji „Zmienione — zapisz”", async () => {
    serverState = formState({ board_column: "verified", fix_request: fixRequest, handback_stage_def_id: 13 });
    const user = userEvent.setup();
    mount();
    const banner = await screen.findByTestId("fix-request-banner");
    expect(banner).toHaveTextContent("Delivery Lead prosi o poprawki (3) · poprawione 1 z 3");
    expect(banner).toHaveTextContent("Uwaga: „Dopisz, jak używał Kafki”");
    const chips = Array.from(banner.querySelectorAll("[data-fix-key]"));
    expect(chips.map((c) => [c.getAttribute("data-fix-key"), c.getAttribute("data-fix-state")])).toEqual([
      ["question:q2", "todo"],
      ["field:availability", "done"],
      ["candidate_rate", "todo"],
    ]);
    const answers = await screen.findAllByLabelText("Odpowiedź");
    await user.type(answers[1], "Tak, produkcyjnie 3 lata");
    expect(banner.querySelector('[data-fix-key="question:q2"]')).toHaveAttribute("data-fix-state", "edited");
  });

  it("„Zapisz i oddaj do przeglądu DL” zapisuje, potem przesuwa na etap „QC CV” z wersją z zapisu", async () => {
    serverState = formState({ board_column: "verified", fix_request: fixRequest, handback_stage_def_id: 13 });
    mocks.put.mockImplementation(() =>
      Promise.resolve({ data: formSaveResult(serverState, { process_state_version: 7 }) }),
    );
    mocks.send.mockResolvedValue({ ok: true, data: {} });
    const onMoved = vi.fn();
    const user = userEvent.setup();
    mount({ onMoved });
    const answers = await screen.findAllByLabelText("Odpowiedź");
    await user.type(answers[1], "Tak");
    await user.click(screen.getByRole("button", { name: /Zapisz i oddaj do przeglądu DL/ }));
    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    expect(mocks.put).toHaveBeenCalledTimes(1);
    expect(mocks.send.mock.calls[0][0]).toEqual({
      candidate_id: FORM_CANDIDATE_ID,
      job_id: FORM_JOB_ID,
      stage_def_id: 13,
      expected_state_version: 7,
    });
    await waitFor(() => expect(onMoved).toHaveBeenCalled());
    expect(mocks.showSuccess).toHaveBeenCalledWith("Tomasz Wzorcowy — oddane do przeglądu Delivery Leada.");
  });

  it("bez otwartej prośby nie ma banera ani przycisku oddania", async () => {
    mount();
    await screen.findAllByLabelText("Odpowiedź");
    expect(screen.queryByTestId("fix-request-banner")).toBeNull();
    expect(screen.queryByRole("button", { name: /oddaj do przeglądu DL/ })).toBeNull();
  });
});

describe("ScreeningFullForm — to, co już wiemy, stoi pod swoim polem (12.10.2026)", () => {
  const field = (key: string) => document.querySelector(`[data-card-field="${key}"]`) as HTMLElement;

  it("dostępność z notatek jest pod polem „Dostępność”, a w bloku stawki zostaje sama stawka", async () => {
    serverState = formState({
      // Etap ma stawkę — formularz nie wpisuje podpowiedzi, więc obie stoją jako „Użyj”.
      rate: { amount: 150, unit: "hourly", currency: "PLN", source: "stage", at: null },
      suggestions_from_notes: {
        rate: { value: 130, unit: "hour", currency: "PLN", raw: "130/h", source_note_id: 1, noted_at: "2025-03-14" },
        availability: {
          raw: "miesiąc wypowiedzenia",
          notice_period: "1 miesiąc",
          available_from: null,
          source_note_id: 1,
          noted_at: "2025-03-14",
        },
      },
    });
    mount();
    await screen.findByRole("region", { name: "Warunki" });

    const rateBlock = screen.getByTestId("screening-form-rate");
    const rateChips = rateBlock.querySelectorAll('[data-testid="screening-suggestions"]');
    expect(rateChips).toHaveLength(1);
    expect(rateChips[0]).toHaveAttribute("data-only", "rate");
    expect(rateChips[0]).toHaveTextContent("130 zł/h · 14.03");
    expect(rateChips[0]).not.toHaveTextContent(/wypowiedzeni/);

    const availabilityChips = field("availability").querySelector('[data-testid="screening-suggestions"]');
    expect(availabilityChips).toHaveAttribute("data-only", "availability");
    expect(availabilityChips).toHaveTextContent(/Z notatek:.*14\.03/);
    expect(availabilityChips).not.toHaveTextContent("130 zł/h");
    // Tryb pracy nie dostaje podpowiedzi dostępności.
    expect(field("work_mode").querySelector('[data-testid="screening-suggestions"]')).toBeNull();
  });

  it("długa dostępność z notatek nie rozpycha kolumny — skrót z pełną treścią w title (28.10.2026)", async () => {
    const raw = "W lipcu 2025 zatrudniony na UoP, z 30-dniowym okresem wypowiedzenia, może zacząć od września";
    serverState = formState({
      suggestions_from_notes: {
        availability: { raw, notice_period: null, available_from: null, source_note_id: 1, noted_at: "2025-03-14" },
      },
    });
    mount();
    await screen.findByRole("region", { name: "Warunki" });

    const chips = field("availability").querySelector('[data-testid="screening-suggestions"]') as HTMLElement;
    const text = chips.querySelector("[title]") as HTMLElement;
    expect(text.getAttribute("title")).toContain(raw);
    expect(text).toHaveClass("truncate");
    // Kolumna `auto` (siatka bez grid-cols-1) rośnie do pełnej długości tekstu
    // z `truncate`: przy 1280 × 720 pola miały 1218 px w kolumnie 426 px.
    const grid = field("availability").closest(".grid") as HTMLElement;
    expect(grid).toHaveClass("grid-cols-1");
  });

  it("pod „Trybem pracy” stoi tryb z profilu kandydata; bez niego nic", async () => {
    mocks.candidate.mockResolvedValue({ data: { max_onsite_days_per_week: 2 } });
    mount();
    await screen.findByRole("region", { name: "Warunki" });
    await waitFor(() => expect(field("work_mode")).toHaveTextContent("W profilu: Do 2 dni w biurze"));
    expect(mocks.candidate).toHaveBeenCalledWith(FORM_CANDIDATE_ID);
    expect(field("availability")).not.toHaveTextContent("W profilu");
  });

  it("awaria odczytu profilu nie psuje formularza — po prostu brak podpowiedzi", async () => {
    mocks.candidate.mockRejectedValue(new Error("500"));
    mount();
    await screen.findByRole("region", { name: "Warunki" });
    await waitFor(() => expect(mocks.candidate).toHaveBeenCalled());
    expect(field("work_mode")).not.toHaveTextContent("W profilu");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("ScreeningFullForm — stawka na start, gdy etap jej nie ma (D2, 14.10.2026)", () => {
  const NOTE_RATE = {
    value: 160,
    unit: "hour" as const,
    currency: "PLN",
    raw: "160 na B2B, mniej nie zejdzie",
    source_note_id: null,
    noted_at: "2025-04-02",
  };
  const rateBlock = () => screen.getByTestId("screening-form-rate");

  it("niższa niż „Stawka od” stawka z notatki wpisuje się w pole, mówi skąd jest i idzie z zapisem", async () => {
    serverState = formState({
      suggestions_from_notes: { rate: NOTE_RATE },
      rate_hints: { card: null, rate_from: { amount: 180, unit: "hourly", currency: "PLN" } },
    });
    mocks.put.mockImplementation(() => Promise.resolve({ data: formSaveResult(serverState, { changed: ["rate"] }) }));
    const user = userEvent.setup();
    mount();

    expect(await screen.findByLabelText("Kwota")).toHaveValue(160);
    expect(screen.getByTestId("rate-prefill-origin")).toHaveTextContent(
      "z notatki 2.04.2025: „160 na B2B, mniej nie zejdzie” · zmień",
    );
    // Podpowiedź z tą samą wartością co w polu znika, inna zostaje jako „Użyj”.
    expect(rateBlock().querySelector('[data-testid="screening-suggestions"]')).toBeNull();
    expect(within(rateBlock()).getByRole("button", { name: "Użyj — Stawka od" })).toBeTruthy();
    // Stawka na start to podpowiedź, nie zmiana rekrutera — stopka nie mówi
    // „Niezapisane zmiany” zaraz po otwarciu (przeklikanie 18.10.2026, 200 zł/h
    // z notatki), a stawka i tak idzie z zapisem.
    expect(screen.queryByText("Niezapisane zmiany")).toBeNull();
    expect(screen.getByText("Formularz jeszcze niezapisany")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Zapisz$/ }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    expect(lastPut().rate).toEqual({ amount: 160, unit: "hourly", currency: "PLN" });
  });

  it("R1 (17.10.2026): „Stawka od” niższa niż notatka wpisuje się, notatka zostaje jako „Użyj”", async () => {
    serverState = formState({
      suggestions_from_notes: { rate: NOTE_RATE },
      rate_hints: { card: null, rate_from: { amount: 140, unit: "hourly", currency: "PLN" } },
    });
    mount();

    expect(await screen.findByLabelText("Kwota")).toHaveValue(140);
    expect(screen.getByTestId("rate-prefill-origin")).toHaveTextContent("Stawka od · najniższa z 18 mies. · zmień");
    expect(rateBlock().querySelector('[data-testid="screening-suggestions"]')).toHaveTextContent("160 zł/h");
  });

  it("R2: ponad budżet przy niższej znanej stawce w budżecie — ramka to mówi, „Użyj” ją wpisuje", async () => {
    serverState = formState({
      rate: { amount: 140, unit: "hourly", currency: "PLN", source: "stage", at: null },
      rate_hints: {
        card: null,
        rate_from: { amount: 90, unit: "hourly", currency: "PLN" },
        rate_from_at: "2026-10-08T14:30:45Z",
      },
    });
    const user = userEvent.setup();
    mount({ jobBudgetHourly: 135 });

    const note = await screen.findByTestId("rate-lower-known");
    expect(note).toHaveTextContent(
      "Znana też niższa stawka: 90 zł/h (Stawka od, 8.10.2026) — mieści się w budżecie.",
    );
    await user.click(within(note).getByRole("button", { name: "Użyj 90 zł/h" }));
    expect(screen.getByLabelText("Kwota")).toHaveValue(90);
    expect(screen.queryByTestId("rate-lower-known")).toBeNull();
  });

  it("R4: żywa umowa — „Stawka u nas · z umowy” w polu i „Zadeklarowana od” jako podpowiedź", async () => {
    serverState = formState({
      rate_hints: {
        card: null,
        rate_from: { amount: 150, unit: "hourly", currency: "PLN" },
        rate_from_source: "contract",
        declared_from: { amount: 120, unit: "hourly", currency: "PLN" },
        declared_from_at: "2026-09-01T10:00:00Z",
      },
    });
    mount();

    expect(await screen.findByLabelText("Kwota")).toHaveValue(150);
    expect(screen.getByTestId("rate-prefill-origin")).toHaveTextContent("Stawka u nas · z umowy · zmień");
    expect(within(rateBlock()).getByRole("button", { name: "Użyj — Zadeklarowana od" })).toBeTruthy();
    expect(rateBlock()).toHaveTextContent("Zadeklarowana od: 120 zł/h · 1.09.2026");
  });

  it("„zmień” stawia kursor w polu kwoty; inna kwota zdejmuje podpis", async () => {
    serverState = formState({ suggestions_from_notes: { rate: NOTE_RATE } });
    const user = userEvent.setup();
    mount();
    const amount = (await screen.findByLabelText("Kwota")) as HTMLInputElement;
    const select = vi.spyOn(amount, "select");
    await user.click(
      within(screen.getByTestId("rate-prefill-origin")).getByRole("button", { name: "Zmień stawkę kandydata" }),
    );
    expect(amount).toHaveFocus();
    expect(select).toHaveBeenCalled();

    await user.clear(amount);
    await user.type(amount, "170");
    expect(screen.queryByTestId("rate-prefill-origin")).toBeNull();
    expect(screen.getByText("Niezapisane zmiany")).toBeInTheDocument();
    // Notatka wraca jako zwykła podpowiedź „Użyj”.
    expect(rateBlock().querySelector('[data-testid="screening-suggestions"]')).toHaveTextContent("160 zł/h");
  });

  it("stawka z karty w polu: podpis „z karty rekomendacji” i zapis jej nie gubi (błąd do 14.10.2026)", async () => {
    serverState = formState({
      rate: { amount: 150, unit: "hourly", currency: "PLN", source: "card", at: null },
      rate_hints: { card: { amount: 150, unit: "hourly", currency: "PLN" }, card_raw: "150 zł/h", rate_from: null },
    });
    mocks.put.mockImplementation(() => Promise.resolve({ data: formSaveResult(serverState, { changed: ["rate"] }) }));
    const user = userEvent.setup();
    mount();
    expect(await screen.findByLabelText("Kwota")).toHaveValue(150);
    expect(screen.getByTestId("rate-prefill-origin")).toHaveTextContent("z karty rekomendacji: „150 zł/h” · zmień");
    expect(within(rateBlock()).queryByRole("button", { name: "Użyj — Z karty" })).toBeNull();

    await user.click(screen.getByRole("button", { name: /^Zapisz$/ }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    expect(lastPut().rate).toEqual({ amount: 150, unit: "hourly", currency: "PLN" });
  });

  it("stawka z notatki z rozmowy zastępuje wpisaną na start, „Cofnij wypełnienie” ją przywraca", async () => {
    serverState = formState({
      assist_enabled: true,
      rate_hints: { card: null, rate_from: { amount: 140, unit: "hourly", currency: "PLN" } },
    });
    mocks.post.mockResolvedValue({
      data: {
        fields: [
          {
            key: "rate",
            label: "Stawka",
            current: null,
            current_source: null,
            proposed: "155 zł/h",
            quote: "155 na B2B",
            origin: "note_rule",
            changed: true,
            rate: { amount: 155, unit: "hourly", currency: "PLN" },
          },
        ],
        answers: [],
        available: true,
        message: null,
        language: "pl",
        rate_change_notifies: false,
        text: "Rozmowa: 155 na B2B, od listopada.",
      },
    });
    const user = userEvent.setup();
    mount();
    expect(await screen.findByLabelText("Kwota")).toHaveValue(140);

    await user.click(screen.getByRole("button", { name: /Wklej tekst/ }));
    await user.type(screen.getByLabelText("Notatka z rozmowy"), "Rozmowa: 155 na B2B, od listopada.");
    await user.click(screen.getByRole("button", { name: "Odczytaj notatkę" }));

    await waitFor(() => expect(screen.getByLabelText("Kwota")).toHaveValue(155));
    expect(screen.queryByTestId("note-offer")).toBeNull();
    expect(screen.queryByTestId("rate-prefill-origin")).toBeNull();

    await user.click(screen.getByRole("button", { name: /Cofnij wypełnienie/ }));
    expect(screen.getByLabelText("Kwota")).toHaveValue(140);
    expect(screen.getByTestId("rate-prefill-origin")).toHaveTextContent("Stawka od");
  });

  it("bez notatki i karty — „Stawka od”", async () => {
    serverState = formState({ rate_hints: { card: null, rate_from: { amount: 140, unit: "hourly", currency: "PLN" } } });
    mount();
    expect(await screen.findByLabelText("Kwota")).toHaveValue(140);
    expect(screen.getByTestId("rate-prefill-origin")).toHaveTextContent("Stawka od · najniższa z 18 mies. · zmień");
  });

  it("etap ze stawką albo brak prawa do stawek — nic się nie wpisuje", async () => {
    serverState = formState({
      rate: { amount: 150, unit: "hourly", currency: "PLN", source: "stage", at: null },
      suggestions_from_notes: { rate: NOTE_RATE },
    });
    mount();
    expect(await screen.findByLabelText("Kwota")).toHaveValue(150);
    expect(screen.queryByTestId("rate-prefill-origin")).toBeNull();
    cleanup();

    serverState = formState({ can_edit_rate: false, suggestions_from_notes: { rate: NOTE_RATE } });
    mount();
    expect(await screen.findByLabelText("Kwota")).toHaveValue(null);
    expect(screen.queryByTestId("rate-prefill-origin")).toBeNull();
    expect(screen.queryByText("Niezapisane zmiany")).toBeNull();
  });
});

describe("ScreeningFullForm — przekazano dalej (P3, 14.10.2026)", () => {
  const forward = { stage: "verified", stageDefId: 12, label: "Zweryfikowany" };

  async function fillAndForward(user: ReturnType<typeof userEvent.setup>) {
    const answers = await screen.findAllByLabelText("Odpowiedź");
    await user.type(answers[0], "6 lat");
    await user.type(answers[1], "Tak, 2 lata");
    await user.type(screen.getByLabelText("Kwota"), "150");
    await user.click(screen.getByRole("button", { name: /Zapisz i przekaż dalej/ }));
  }

  it("po udanym ruchu woła `onForwarded`", async () => {
    mocks.put.mockImplementation(() => Promise.resolve({ data: formSaveResult(serverState) }));
    mocks.send.mockResolvedValue({ ok: true, data: {} });
    const onForwarded = vi.fn();
    const onMoved = vi.fn();
    const user = userEvent.setup();
    mount({ forward, onForwarded, onMoved });
    await fillAndForward(user);
    await waitFor(() => expect(onForwarded).toHaveBeenCalledTimes(1));
    expect(onMoved).toHaveBeenCalled();
  });

  it.each([
    ["konflikt wersji", { kind: "version_conflict" }],
    ["odmowa ruchu", { kind: "other", message: "Nie" }],
  ])("%s nie woła `onForwarded`", async (_label, refusal) => {
    mocks.put.mockImplementation(() => Promise.resolve({ data: formSaveResult(serverState) }));
    mocks.send.mockResolvedValue({ ok: false, refusal });
    const onForwarded = vi.fn();
    const user = userEvent.setup();
    mount({ forward, onForwarded });
    await fillAndForward(user);
    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole("button", { name: /Zapisz i przekaż dalej/ })).toBeEnabled());
    expect(onForwarded).not.toHaveBeenCalled();
  });
});

describe("ScreeningFullForm — notatka zapisana w doku wypełnia formularz (D3, 14.10.2026)", () => {
  const DOCK_TEXT = "Rozmowa: java 6 lat, dostępny od zaraz.";
  const PROPOSAL = {
    fields: [
      {
        key: "availability",
        label: "Dostępność",
        current: null,
        current_source: null,
        proposed: "od zaraz",
        quote: "dostępny od zaraz",
        origin: "note_ai",
        changed: true,
      },
    ],
    answers: [],
    available: true,
    message: null,
    language: "pl",
    rate_change_notifies: false,
    text: DOCK_TEXT,
  };

  it("formularz z odczytem notatki czeka na notatkę; bez funkcji albo do odczytu — nie", async () => {
    const channel = createNoteFillChannel();
    serverState = formState({ assist_enabled: true });
    mount({ noteFill: channel });
    await screen.findAllByLabelText("Odpowiedź");
    await waitFor(() => expect(channel.has(FORM_CANDIDATE_ID)).toBe(true));
    cleanup();
    expect(channel.has(FORM_CANDIDATE_ID)).toBe(false);

    serverState = formState({ assist_enabled: false });
    mount({ noteFill: channel });
    await screen.findAllByLabelText("Odpowiedź");
    expect(channel.has(FORM_CANDIDATE_ID)).toBe(false);
    cleanup();

    serverState = formState({ assist_enabled: true });
    mount({ noteFill: channel, readOnly: true });
    await screen.findByTestId("screening-form-readonly");
    expect(channel.has(FORM_CANDIDATE_ID)).toBe(false);
  });

  it("czyta notatkę trasą „Wklej tekst”, wypełnia puste pola, a zapis odsyła jej numer", async () => {
    const channel = createNoteFillChannel();
    serverState = formState({ assist_enabled: true });
    mocks.post.mockImplementation((url: string) =>
      url === "/api/recommendation-cards/note/read"
        ? Promise.resolve({ data: PROPOSAL })
        : Promise.reject(new Error(url)),
    );
    mocks.put.mockImplementation(() =>
      Promise.resolve({ data: formSaveResult(serverState, { changed: ["card"], note_id: 55 }) }),
    );
    const user = userEvent.setup();
    mount({ noteFill: channel });
    await waitFor(() => expect(channel.has(FORM_CANDIDATE_ID)).toBe(true));

    let taken: boolean | undefined;
    await act(async () => {
      taken = await channel.send(FORM_CANDIDATE_ID, { noteId: 55, text: DOCK_TEXT });
    });
    expect(taken).toBe(true);
    expect(mocks.post).toHaveBeenCalledWith(
      "/api/recommendation-cards/note/read",
      { candidate_id: FORM_CANDIDATE_ID, job_id: FORM_JOB_ID, text: DOCK_TEXT },
      expect.anything(),
    );
    expect(screen.getByLabelText("Dostępność")).toHaveValue("od zaraz");
    expect(screen.getByTestId("note-fill-summary")).toHaveTextContent("Notatka jest już w historii kandydata");

    await user.click(screen.getByRole("button", { name: /^Zapisz$/ }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    expect(lastPut().note_import).toEqual({ text: DOCK_TEXT, note_id: 55 });
    expect(lastPut().card).toEqual({
      fields: { availability: "od zaraz" },
      origins: { availability: { origin: "note_ai" } },
    });
  });

  it("awaria odczytu: komunikat z serwera, formularz bez zmian, dok dostaje odmowę", async () => {
    const channel = createNoteFillChannel();
    serverState = formState({ assist_enabled: true });
    mocks.post.mockRejectedValue(httpError(503, "Luna chwilowo nie odpowiada."));
    mount({ noteFill: channel });
    await waitFor(() => expect(channel.has(FORM_CANDIDATE_ID)).toBe(true));

    let refused: unknown = null;
    await act(async () => {
      await channel.send(FORM_CANDIDATE_ID, { noteId: 55, text: DOCK_TEXT }).catch((err: unknown) => {
        refused = err;
      });
    });
    expect(refused).not.toBeNull();
    expect(mocks.showError).toHaveBeenCalledWith("Luna chwilowo nie odpowiada.");
    expect(screen.getByLabelText("Dostępność")).toHaveValue("");
    expect(screen.queryByTestId("note-fill-summary")).toBeNull();
  });

  it("formularz z niezapisanym wypełnieniem z innej notatki nie przyjmuje drugiej", async () => {
    const channel = createNoteFillChannel();
    serverState = formState({ assist_enabled: true });
    mocks.post.mockResolvedValue({ data: PROPOSAL });
    mount({ noteFill: channel });
    await waitFor(() => expect(channel.has(FORM_CANDIDATE_ID)).toBe(true));
    await act(async () => {
      await channel.send(FORM_CANDIDATE_ID, { noteId: 55, text: DOCK_TEXT });
    });

    await expect(
      act(() => channel.send(FORM_CANDIDATE_ID, { noteId: 56, text: "Druga notatka z rozmowy." })),
    ).rejects.toThrow(/wypełnienie z innej notatki/);
    expect(mocks.post).toHaveBeenCalledTimes(1);
  });
});

// 13.10.2026: „Odrzuć” w stopce formularza w panelu osoby też przenosi panel
// do następnej osoby — migawka kolejności z chwili kliknięcia, przejście po
// udanym ruchu.
describe("ScreeningFullForm — odrzucenie z panelu osoby", () => {
  const REJECT_TARGET = {
    stage: "rejected",
    stageDefId: 9,
    previousStage: "new",
    previousCategory: "internal" as const,
  };

  it("okno dostaje migawkę następnej osoby, a po udanym ruchu panel dostaje powód", async () => {
    const onFollowUpMoved = vi.fn();
    const rejectFollowUp = vi.fn(() => ({
      stageLabel: "Nowi",
      next: { name: "Anna Wiśniewska", stageLabel: "Nowi" },
      onMoved: onFollowUpMoved,
    }));
    const onMoved = vi.fn();
    mocks.send.mockResolvedValue({ ok: true, data: {} });
    const user = userEvent.setup();
    mount({ reject: REJECT_TARGET, rejectFollowUp, onMoved });

    await user.click(await screen.findByRole("button", { name: /^Odrzuć$/ }));
    expect(rejectFollowUp).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Tomasz Wzorcowy · Nowi")).toBeInTheDocument();
    expect(screen.getByText("Dalej: Anna Wiśniewska")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "potwierdź odrzucenie" }));
    await waitFor(() => expect(onFollowUpMoved).toHaveBeenCalledWith({ reasonLabel: "Brak Azure" }));
    expect(onMoved).toHaveBeenCalled();
  });

  it("„Nie akceptuje trybu pracy” niesie dni w biurze i zapis na profilu (14.10.2026)", async () => {
    mocks.send.mockResolvedValue({ ok: true, data: {} });
    const user = userEvent.setup();
    mount({
      reject: REJECT_TARGET,
      rejectFollowUp: () => ({ stageLabel: "Nowi", next: null, onMoved: vi.fn() }),
    });

    await user.click(await screen.findByRole("button", { name: /^Odrzuć$/ }));
    await user.click(screen.getByRole("button", { name: "odrzuć za tryb pracy" }));
    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    expect(mocks.send.mock.calls[0][0]).toMatchObject({
      rejection_reason_id: "9",
      work_mode_max_onsite_days: 0,
      work_mode_save_to_profile: true,
    });
  });

  it("odmowa serwera nie przenosi panelu", async () => {
    const onFollowUpMoved = vi.fn();
    mocks.send.mockResolvedValue({ ok: false, refusal: { kind: "other", message: "Nie" } });
    const user = userEvent.setup();
    mount({
      reject: REJECT_TARGET,
      rejectFollowUp: () => ({ stageLabel: "Nowi", next: null, onMoved: onFollowUpMoved }),
    });

    await user.click(await screen.findByRole("button", { name: /^Odrzuć$/ }));
    expect(screen.getByText("ostatnia osoba")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "potwierdź odrzucenie" }));
    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    expect(onFollowUpMoved).not.toHaveBeenCalled();
  });
});

// Audyt 13.10.2026: drugi klik „Potwierdź” w trakcie zapisu wysyłał drugi ruch
// (już przy następnej osobie) — okno dostaje stan zapisu z mutacji.
describe("ScreeningFullForm — odrzucenie w toku", () => {
  it("w trakcie zapisu „Potwierdź” jest zablokowany i drugi klik nie wysyła drugiego ruchu", async () => {
    mocks.send.mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    mount({
      reject: { stage: "rejected", stageDefId: 9, previousStage: "new", previousCategory: "internal" },
      rejectFollowUp: () => ({ stageLabel: "Nowi", next: null, onMoved: vi.fn() }),
    });

    await user.click(await screen.findByRole("button", { name: /^Odrzuć$/ }));
    const confirm = screen.getByRole("button", { name: "potwierdź odrzucenie" });
    await user.click(confirm);
    await waitFor(() => expect(confirm).toBeDisabled());
    await user.click(confirm);
    expect(mocks.send).toHaveBeenCalledTimes(1);
  });
});

describe("ScreeningFullForm — pamięć rozmowy (16.10.2026, D1 A / D2 A / D3 B)", () => {
  const USER = 5;
  const link = {
    read: () => readScreeningMemory(USER, FORM_CANDIDATE_ID),
    write: (update: Parameters<typeof writeScreeningMemory>[2]) => void writeScreeningMemory(USER, FORM_CANDIDATE_ID, update),
  };

  beforeEach(() => {
    window.sessionStorage.clear();
    useScreeningMemoryStore.setState({ entries: {} });
    mocks.put.mockImplementation((_url: string, body: ScreeningFormSave) =>
      Promise.resolve({
        data: formSaveResult({
          ...serverState,
          sheet: { ...(body.sheet ?? {}), notes: "" } as never,
          card: {
            ...serverState.card,
            fields: Object.fromEntries(
              Object.entries(body.card?.fields ?? {}).map(([key, raw]) => [key, { raw, source: "manual" }]),
            ) as never,
          },
        }),
      }),
    );
  });

  it("takes the answers typed in the joint conversation and saves them, then memory is empty", async () => {
    const now = Date.now();
    writeScreeningMemory(USER, FORM_CANDIDATE_ID, () => ({
      ...emptyMemory(FORM_JOB_ID, now),
      pairs: { [FORM_JOB_ID]: { touchedAt: now, answers: { q1: "8 lat" } } },
      shared: { card: { availability: "od 1.12" } },
    }));
    const user = userEvent.setup();
    mount({ memory: link });
    const [first] = await screen.findAllByLabelText("Odpowiedź");
    await waitFor(() => expect(first).toHaveValue("8 lat"));
    expect(screen.getByDisplayValue("od 1.12")).toBeInTheDocument();
    expect(screen.getByText("Niezapisane zmiany")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Zapisz$/ }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(1));
    const body = lastPut();
    expect(body.sheet?.answers.find((a) => a.question_id === "q1")?.response).toBe("8 lat");
    expect(body.card?.fields?.availability).toBe("od 1.12");
    await waitFor(() => expect(readScreeningMemory(USER, FORM_CANDIDATE_ID)).toBeNull());
  });

  it("restored entries stay in memory for the next form (joint → single → joint)", async () => {
    const now = Date.now();
    writeScreeningMemory(USER, FORM_CANDIDATE_ID, () => ({
      ...emptyMemory(FORM_JOB_ID, now),
      pairs: { [FORM_JOB_ID]: { touchedAt: now, answers: { q1: "8 lat" } } },
      shared: { card: { availability: "od 1.12" } },
    }));
    mount({ memory: link });
    const [first] = await screen.findAllByLabelText("Odpowiedź");
    await waitFor(() => expect(first).toHaveValue("8 lat"));
    const memory = readScreeningMemory(USER, FORM_CANDIDATE_ID);
    expect(memory?.pairs[String(FORM_JOB_ID)]?.answers).toEqual({ q1: "8 lat" });
    expect(memory?.shared.card).toEqual({ availability: "od 1.12" });
  });

  it("what the recruiter types goes to memory; an untouched form leaves none", async () => {
    const user = userEvent.setup();
    mount({ memory: link });
    const [first] = await screen.findAllByLabelText("Odpowiedź");
    expect(readScreeningMemory(USER, FORM_CANDIDATE_ID)).toBeNull();
    await user.type(first, "6 lat");
    expect(readScreeningMemory(USER, FORM_CANDIDATE_ID)?.pairs[String(FORM_JOB_ID)]?.answers).toEqual({ q1: "6 lat" });
  });

  it("says before saving that entries of unchecked recruitments will be gone", async () => {
    mount({
      memory: link,
      pendingMemory: [{ jobId: 303, title: "Java Developer", answers: 2, canReselect: true }],
    });
    const warning = await screen.findByTestId("screening-memory-pending");
    expect(warning).toHaveTextContent("Zapis obejmie tylko tę rekrutację");
    expect(warning).toHaveTextContent("Java Developer — 2 odpowiedzi");
  });
});
