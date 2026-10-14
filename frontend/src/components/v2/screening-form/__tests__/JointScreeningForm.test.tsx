/**
 * „Screening dla” (14.10.2026, D3–D4): jedna rozmowa pod dwie rekrutacje —
 * wspólne pytanie raz, zapis osobno do każdej pary z JEJ identyfikatorami
 * pytań, przekazanie per rekrutacja, deal-breaker zatrzymuje tylko swoją parę.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  screeningFormQueryKey,
  type JointContextPair,
  type ScreeningFormSave,
  type ScreeningFormState,
} from "@/lib/api/screeningForm";
import { formSaveResult, formState } from "@/components/v2/screening-form/__tests__/screening-form-fixtures";

const mocks = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), send: vi.fn(), readNote: vi.fn() }));

vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => mocks.get(...a),
    put: (...a: unknown[]) => mocks.put(...a),
  };
  return { __esModule: true, default: client, api: client };
});
vi.mock("@/lib/api/recommendationCards", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/recommendationCards")>()),
  recommendationCardsApi: { readNote: (...a: unknown[]) => mocks.readNote(...a) },
}));
// Pasek notatki ma własne testy — tu tylko oddaje odczyt kotwicy.
vi.mock("@/components/v2/screening-form/NoteFillBar", () => ({
  NoteFillBar: (props: { onProposal: (p: unknown, s: { text: string }) => void; onUndo: () => void }) => (
    <>
      <button
        type="button"
        onClick={() =>
          props.onProposal(
            { fields: [{ key: "availability", proposed: "od 1.11" }], answers: [], text: "Rozmowa: od 1.11", available: true },
            { text: "Rozmowa: od 1.11" },
          )
        }
      >
        wklej notatkę
      </button>
      <button type="button" onClick={props.onUndo}>
        cofnij notatkę
      </button>
    </>
  ),
}));
vi.mock("@/hooks/usePipelineMoveCore", () => ({
  usePipelineMoveCore: () => ({ send: (...a: unknown[]) => mocks.send(...a), dialogs: null }),
}));

import { JointScreeningForm } from "../JointScreeningForm";

const CANDIDATE = 101;
const QA = [
  { id: "q1", question: "Jak używałeś RxJS w produkcji?", ideal_answer: "", deal_breaker: "" },
  { id: "q2", question: "Czy 2 dni w biurze są OK?", ideal_answer: "", deal_breaker: "Tylko zdalnie" },
];
const QB = [
  { id: "q1", question: "Od kiedy możesz zacząć?", ideal_answer: "", deal_breaker: "" },
  { id: "q2", question: "Jak używałeś RxJS w produkcji?", ideal_answer: "", deal_breaker: "" },
];
const states: Record<number, ScreeningFormState> = {};

const OTHER: JointContextPair = {
  job_id: 202,
  title: "Angular Developer",
  client_id: 2,
  client_name: "Ubezpieczenia Demo",
  board_column: "new",
  process_state_version: 4,
  claim: null,
  selectable: true,
  reason: null,
  reason_message: null,
  budget_hourly: 130,
  verified_stage_def_id: 44,
};

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onForwarded = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <JointScreeningForm
        candidateId={CANDIDATE}
        candidateName="Oskar Wzorcowy"
        anchor={{
          jobId: 201,
          title: "Programista Frontend",
          clientId: 1,
          clientName: "Bank Przykładowy",
          budgetHourly: 95,
          verifiedStageDefId: 33,
        }}
        others={[OTHER]}
        onForwarded={onForwarded}
      />
    </QueryClientProvider>,
  );
  return { onForwarded, client };
}

function putFor(jobId: number): ScreeningFormSave | undefined {
  return mocks.put.mock.calls.map((c) => c[1] as ScreeningFormSave).find((b) => b.job_id === jobId);
}

beforeEach(() => {
  vi.clearAllMocks();
  states[201] = formState({ job_id: 201, process_state_version: 3, champion_profile: { screening_questions: QA } });
  states[202] = formState({ job_id: 202, process_state_version: 4, champion_profile: { screening_questions: QB } });
  mocks.get.mockImplementation((url: string, config?: { params?: { job_id?: number } }) => {
    if (url === "/api/screening-form") return Promise.resolve({ data: states[config!.params!.job_id!] });
    if (url.startsWith("/api/screening-form/question-groups")) {
      return Promise.resolve({
        data: { groups: [[{ job_id: 201, question_id: "q1" }, { job_id: 202, question_id: "q2" }]] },
      });
    }
    return Promise.reject(new Error(`nieoczekiwany GET ${url}`));
  });
  mocks.put.mockImplementation((_url: string, body: ScreeningFormSave) =>
    Promise.resolve({ data: formSaveResult(states[body.job_id], { process_state_version: 10 + body.job_id }) }),
  );
  mocks.send.mockResolvedValue({ ok: true, data: {} });
});

async function answerAll(user: ReturnType<typeof userEvent.setup>, { dealBreaker }: { dealBreaker: boolean }) {
  await user.type(await screen.findByLabelText("Jak używałeś RxJS w produkcji?"), "Formularze na strumieniach");
  await user.type(screen.getByLabelText("Czy 2 dni w biurze są OK?"), dealBreaker ? "Nie, tylko zdalnie" : "Tak");
  await user.type(screen.getByLabelText("Od kiedy możesz zacząć?"), "Od 1.11");
  if (dealBreaker) await user.click(screen.getByLabelText("Odpowiedź narusza deal-breaker"));
}

describe("JointScreeningForm", () => {
  it("„Cofnij wypełnienie” takes back only what the note filled in", async () => {
    const user = userEvent.setup();
    states[201] = { ...states[201], assist_enabled: true };
    mocks.readNote.mockResolvedValue({ fields: [], answers: [], text: "Rozmowa: od 1.11", available: true });
    mount();
    await user.type(await screen.findByLabelText("Jak używałeś RxJS w produkcji?"), "Strumienie");
    await user.click(screen.getByRole("button", { name: "wklej notatkę" }));
    expect(await screen.findByDisplayValue("od 1.11")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "cofnij notatkę" }));
    expect(screen.queryByDisplayValue("od 1.11")).toBeNull();
    expect(screen.getByLabelText("Jak używałeś RxJS w produkcji?")).toHaveValue("Strumienie");
  });

  it("someone else's save in between is not reverted by fields this conversation did not touch", async () => {
    const user = userEvent.setup();
    const { client } = mount();
    await user.type(await screen.findByLabelText("Od kiedy możesz zacząć?"), "Od 1.11");
    // Ktoś zapisał „Notatkę” w drugiej rekrutacji — formularz wspólny dostaje to w tle.
    const fresh = {
      ...states[202],
      version: 4,
      state_token: "token-4",
      card: { ...states[202].card, fields: { recommendation: { raw: "Zapis kogoś innego", source: "manual" } as never } },
    };
    states[202] = fresh;
    act(() => client.setQueryData(screeningFormQueryKey(202, CANDIDATE), fresh));
    await user.click(screen.getByRole("tab", { name: /Angular Developer/ }));
    expect(await screen.findByDisplayValue("Zapis kogoś innego")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zapisz w 2" }));
    await waitFor(() => expect(putFor(202)).toBeDefined());
    const b = putFor(202)!;
    expect(b.expected_version).toBe(4);
    expect(b.card?.fields ?? {}).not.toHaveProperty("recommendation");
    expect(b.sheet?.answers.find((x) => x.question_id === "q1")?.response).toBe("Od 1.11");
  });

  it("a field typed for one recruitment is saved only there", async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByText("Wspólne · zadajesz raz");
    await user.click(screen.getByRole("tab", { name: /Angular Developer/ }));
    await user.type(screen.getByLabelText(/· dla Angular Developer/), "Mocny w RxJS");
    await user.click(screen.getByRole("button", { name: "Zapisz w 2" }));
    await waitFor(() => expect(putFor(202)).toBeDefined());
    expect(putFor(202)?.card?.fields?.recommendation).toBe("Mocny w RxJS");
    expect(putFor(201)?.card?.fields ?? {}).not.toHaveProperty("recommendation");
  });

  it("a shared question shows another recruitment's saved answer that stays unless edited", async () => {
    const sheet = (question_id: string, response: string) =>
      ({ answers: [{ question_id, response, deal_breaker_hit: false }], overall_fit: "uncertain", notes: "" }) as never;
    states[201] = { ...states[201], sheet: sheet("q1", "Formularze na strumieniach") };
    states[202] = { ...states[202], sheet: sheet("q2", "Tylko w testach") };
    mount();
    expect(await screen.findByLabelText("Jak używałeś RxJS w produkcji?")).toHaveValue("Formularze na strumieniach");
    expect(screen.getByText("W Angular Developer: Tylko w testach")).toBeInTheDocument();
  });

  it("one conversation note: read for every recruitment, created by the first save, linked by the next", async () => {
    const user = userEvent.setup();
    states[201] = { ...states[201], assist_enabled: true };
    mocks.readNote.mockResolvedValue({
      fields: [],
      answers: [{ question_id: "q1", sentence: "Od 1.11", keywords: "od 1.11" }],
      text: "Rozmowa: od 1.11",
      available: true,
    });
    mocks.put.mockImplementation((_url: string, body: ScreeningFormSave) =>
      Promise.resolve({ data: formSaveResult(states[body.job_id], { note_id: 777 }) }),
    );
    mount();
    await user.click(await screen.findByRole("button", { name: "wklej notatkę" }));
    await waitFor(() => expect(mocks.readNote).toHaveBeenCalledWith(CANDIDATE, 202, "Rozmowa: od 1.11"));
    expect(await screen.findByDisplayValue("Od 1.11")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zapisz w 2" }));
    await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(2));
    expect(putFor(201)?.note_import).toEqual({ text: "Rozmowa: od 1.11" });
    expect(putFor(202)?.note_import).toEqual({ text: "Rozmowa: od 1.11", note_id: 777 });
  });

  it("asks the shared question once and sorts the rest by recruitment", async () => {
    mount();
    expect(await screen.findByText("Wspólne · zadajesz raz")).toBeInTheDocument();
    expect(screen.getAllByText("Jak używałeś RxJS w produkcji?")).toHaveLength(1);
    expect(screen.getByText("Tylko Programista Frontend · 1")).toBeInTheDocument();
    expect(screen.getByText("Tylko Angular Developer · 1")).toBeInTheDocument();
    expect(screen.getByText(/3 pytania zamiast 4/)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Programista Frontend/ })).toHaveAttribute("aria-selected", "true");
  });

  it("saves each pair under its own question ids and forwards both", async () => {
    const user = userEvent.setup();
    const { onForwarded } = mount();
    await answerAll(user, { dealBreaker: false });
    await user.click(screen.getByRole("button", { name: /Zapisz i przekaż dalej w 2/ }));

    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(2));
    const a = putFor(201)!;
    const b = putFor(202)!;
    expect(a.sheet?.answers.find((x) => x.question_id === "q1")?.response).toBe("Formularze na strumieniach");
    expect(b.sheet?.answers.find((x) => x.question_id === "q2")?.response).toBe("Formularze na strumieniach");
    expect(b.sheet?.answers.find((x) => x.question_id === "q1")?.response).toBe("Od 1.11");
    // Ruch każdej pary z jej etapem i wersją procesu z wyniku JEJ zapisu.
    expect(mocks.send.mock.calls.map((c) => [c[0].job_id, c[0].stage_def_id, c[0].expected_state_version])).toEqual([
      [201, 33, 211],
      [202, 44, 212],
    ]);
    const results = screen.getByRole("status", { name: "Wynik zapisu" });
    expect(within(results).getByTestId("joint-result-202")).toHaveTextContent("→ Zweryfikowany");
    await user.click(screen.getByRole("button", { name: "Zamknij wynik" }));
    expect(onForwarded).toHaveBeenCalled();
  });

  it("a deal-breaker stops only its own recruitment and offers to forward anyway", async () => {
    const user = userEvent.setup();
    mount();
    await answerAll(user, { dealBreaker: true });
    await user.click(screen.getByRole("button", { name: /Zapisz i przekaż dalej w 2/ }));

    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
    expect(mocks.send.mock.calls[0][0].job_id).toBe(202);
    expect(putFor(201)?.sheet?.answers.find((x) => x.question_id === "q2")?.deal_breaker_hit).toBe(true);
    const row = screen.getByTestId("joint-result-201");
    expect(row).toHaveTextContent("odpowiedź narusza deal-breaker");
    await user.click(within(row).getByRole("button", { name: "Przekaż mimo to" }));
    await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(2));
    expect(mocks.send.mock.calls[1][0].job_id).toBe(201);
  });

  it("a refused save in one pair is reported and the other still saves", async () => {
    const user = userEvent.setup();
    mocks.put.mockImplementation((_url: string, body: ScreeningFormSave) =>
      body.job_id === 202
        ? Promise.reject({
            response: { status: 423, data: { detail: { code: "CANDIDATE_CLAIMED", message: "Tę osobę prowadzi Kasia do 14.10 18:40." } } },
          })
        : Promise.resolve({ data: formSaveResult(states[body.job_id]) }),
    );
    mount();
    await user.type(await screen.findByLabelText("Jak używałeś RxJS w produkcji?"), "Strumienie");
    await user.click(screen.getByRole("button", { name: "Zapisz w 2" }));

    const failed = await screen.findByTestId("joint-result-202");
    expect(failed).toHaveTextContent("nie zapisano");
    expect(failed).toHaveTextContent("Kasia");
    expect(screen.getByTestId("joint-result-201")).toHaveTextContent("zapisano");
  });

  it("names what is missing per recruitment before forwarding and saves nothing", async () => {
    const user = userEvent.setup();
    mount();
    await user.type(await screen.findByLabelText("Jak używałeś RxJS w produkcji?"), "Strumienie");
    await user.click(screen.getByRole("button", { name: /Zapisz i przekaż dalej w 2/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Programista Frontend: 1 pytanie bez odpowiedzi");
    expect(alert).toHaveTextContent("Angular Developer: 1 pytanie bez odpowiedzi");
    expect(mocks.put).not.toHaveBeenCalled();
  });
});
