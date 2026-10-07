/**
 * Jeden formularz screeningu (0424): zapis tylko zmian jednym `PUT` z wersją,
 * wypełnienie z notatki (puste pola, „z notatki”, notatka idzie z zapisem),
 * tryb tylko do odczytu i konflikt wersji, który nie kasuje pracy.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ScreeningFormSave, ScreeningFormState } from "@/lib/api/screeningForm";
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
    candidatesApi: { update: vi.fn() },
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
  RejectionV2: () => <div data-testid="rejection-stub" />,
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
  });

  it("bez włączonej funkcji karty z notatki nie ma paska notatki", async () => {
    mount();
    await screen.findAllByLabelText("Odpowiedź");
    expect(screen.queryByRole("button", { name: /Wklej tekst/ })).toBeNull();
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
