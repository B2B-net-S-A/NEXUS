/**
 * Panel „Formularz screeningu” (zakładka „Rozmowy”, Tablica bez warsztatów):
 * odrzucony zapis MUSI być widoczny.
 *
 * Panel zamyka się wyłącznie przy sukcesie, więc bez komunikatu 403/422
 * wyglądałoby jak kliknięcie, które nie zadziałało — a wpisane odpowiedzi
 * (z flagami deal-breaker) przepadłyby po zamknięciu. Od 0424 panel renderuje
 * ten sam formularz co panel osoby (`ScreeningFullForm`, `PUT /api/screening-form`).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ScreeningFormState } from "@/lib/api/screeningForm";
import { FORM_CANDIDATE_ID, FORM_JOB_ID, formSaveResult, formState } from "@/test/fixtures/screening-form";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  showError: vi.fn(),
  showSuccess: vi.fn(),
  canWrite: true,
}));

vi.mock("@/lib/api", () => {
  const client = {
    get: (...a: unknown[]) => mocks.get(...a),
    put: (...a: unknown[]) => mocks.put(...a),
    post: vi.fn(),
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
  usePipelineMoveCore: () => ({ send: vi.fn(), dialogs: null }),
}));
vi.mock("@/hooks/useCapability", () => ({ useCapability: () => true }));
vi.mock("@/lib/section-access", () => ({ hasSectionAccess: () => mocks.canWrite }));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showError: mocks.showError,
    showSuccess: mocks.showSuccess,
    showInfo: vi.fn(),
    showActionToast: vi.fn(),
  }),
}));

import { ScreeningSheet } from "@/components/v2/modals/ScreeningSheet";

let serverState: ScreeningFormState;

function httpError(status: number, detail: string) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { detail } } });
}

function renderSheet(onOpenChange = vi.fn()) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ScreeningSheet
        open
        onOpenChange={onOpenChange}
        candidateId={FORM_CANDIDATE_ID}
        jobId={FORM_JOB_ID}
        candidateName="Jan Kowalski"
      />
    </QueryClientProvider>,
  );
  return onOpenChange;
}

beforeEach(() => {
  mocks.get.mockReset();
  mocks.put.mockReset();
  mocks.showError.mockReset();
  mocks.showSuccess.mockReset();
  mocks.canWrite = true;
  serverState = formState({
    sheet: { answers: [{ question_id: "q1", response: "Tak, 3 lata", deal_breaker_hit: false }], overall_fit: "fit", notes: "" },
    version: 1,
    versions_count: 1,
  });
  mocks.get.mockImplementation((url: string) =>
    url === "/api/screening-form"
      ? Promise.resolve({ data: serverState })
      : Promise.resolve({ data: { items: [], total: 0 } }),
  );
});

describe("ScreeningSheet — formularz screeningu w panelu", () => {
  it("403 z bramki zapisu pokazuje powód i zostawia odpowiedzi w formularzu", async () => {
    const detail = "Requires one of roles: ['recruiter']";
    mocks.put.mockRejectedValue(httpError(403, detail));
    const onOpenChange = renderSheet();
    expect(await screen.findByText("Formularz screeningu")).toBeInTheDocument();

    const [first] = await screen.findAllByLabelText("Odpowiedź");
    await userEvent.type(first, " produkcyjnie");
    await userEvent.click(screen.getByRole("button", { name: /^Zapisz$/ }));

    await waitFor(() =>
      expect(
        screen.getAllByRole("alert").some((el) => /Nie udało się zapisać screeningu/.test(el.textContent ?? "")),
      ).toBe(true),
    );
    // Surowa lista ról z `require_roles` dochodzi do ludzi po polsku.
    expect(mocks.showError).toHaveBeenCalledWith(
      "Nie masz uprawnień do tej operacji — poproś administratora o dostęp.",
    );
    // Dane rekrutera nie mogą zniknąć razem z odrzuconym zapisem.
    expect(screen.getByDisplayValue("Tak, 3 lata produkcyjnie")).toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("udany zapis zamyka panel bez komunikatu o błędzie", async () => {
    mocks.put.mockImplementation(() => Promise.resolve({ data: formSaveResult(serverState) }));
    const onOpenChange = renderSheet();
    const [first] = await screen.findAllByLabelText("Odpowiedź");
    await userEvent.type(first, " produkcyjnie");
    await userEvent.click(screen.getByRole("button", { name: /^Zapisz$/ }));

    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.put).toHaveBeenCalledWith("/api/screening-form", expect.objectContaining({ expected_version: 1 }));
    expect(mocks.showError).not.toHaveBeenCalled();
  });

  it("bez prawa zapisu w sekcji Pipeline formularz jest tylko do odczytu", async () => {
    mocks.canWrite = false;
    renderSheet();
    expect(await screen.findByTestId("screening-form-readonly")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Zapisz$/ })).toBeNull();
  });
});
