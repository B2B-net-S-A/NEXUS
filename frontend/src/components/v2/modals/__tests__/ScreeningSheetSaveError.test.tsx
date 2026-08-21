/**
 * Arkusz screeningu: odrzucony zapis MUSI być widoczny.
 *
 * Mutacja miała tylko `onSuccess`, a modal zamyka się wyłącznie przy sukcesie —
 * więc widocznym efektem 403/422 było: spinner leci, spinner staje, sheet dalej
 * otwarty, przycisk znowu mówi „Zapisz screening". Nie do odróżnienia od
 * kliknięcia, które nie zadziałało.
 *
 * 403 jest tu DETERMINISTYCZNE, nie kapryśne: bramka odczytu jest szersza niż
 * bramka zapisu (`GET .../screening` = CandidatePIIAccess, `POST` = RecruiterPlus),
 * więc Head of Recruitment otwiera arkusz i nie może go zapisać — za każdym razem.
 * Screening niesie flagi `deal_breaker_hit`, które wykluczają kandydata
 * z shortlisty klienta, więc cicho utracony zapis kosztuje kandydata.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getForStage: vi.fn(),
  submit: vi.fn(),
  showError: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  screeningApi: {
    getForStage: (...a: unknown[]) => mocks.getForStage(...a),
    submit: (...a: unknown[]) => mocks.submit(...a),
  },
  // Prawdziwa funkcja jest osobno przetestowana; tu liczy się, że jej wynik
  // trafia na ekran, a nie że go poprawnie sformatowała.
  extractErrorMsg: (e: unknown) =>
    (e as { response?: { data?: { detail?: string } } }).response?.data?.detail ??
    "Błąd",
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: mocks.showError }),
}));

import { ScreeningSheet } from "@/components/v2/modals/ScreeningSheet";

const QUESTION = "Czy pracowałeś z Kafką?";

function stageResponse() {
  return {
    data: {
      stage_id: 1,
      candidate_id: 2,
      job_id: 3,
      champion_profile: {
        screening_questions: [
          {
            id: "q1",
            question: QUESTION,
            ideal_answer: "Tak, produkcyjnie",
            deal_breaker: "Brak doświadczenia",
          },
        ],
      },
      screening_answers: {
        answers: [
          { question_id: "q1", response: "Tak, 3 lata", deal_breaker_hit: false },
        ],
        overall_fit: "fit",
        notes: "",
      },
    },
  };
}

function httpError(status: number, detail: string) {
  return Object.assign(new Error(`HTTP ${status}`), {
    response: { status, data: { detail } },
  });
}

function renderSheet() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ScreeningSheet
        open
        onOpenChange={vi.fn()}
        stageId={1}
        candidateName="Jan Kowalski"
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mocks.getForStage.mockReset();
  mocks.submit.mockReset();
  mocks.showError.mockReset();
  mocks.getForStage.mockResolvedValue(stageResponse());
});

describe("ScreeningSheet — nieudany zapis", () => {
  it("403 z bramki zapisu pokazuje powód i zostawia odpowiedzi w formularzu", async () => {
    const detail = "Requires one of roles: ['recruiter']";
    mocks.submit.mockRejectedValue(httpError(403, detail));

    renderSheet();

    const submit = await screen.findByRole("button", { name: /Zapisz screening/ });
    await userEvent.click(submit);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        /Nie udało się zapisać screeningu/,
      ),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(detail);
    expect(mocks.showError).toHaveBeenCalledWith(detail);
    // Dane rekrutera nie mogą zniknąć razem z odrzuconym zapisem.
    expect(screen.getByDisplayValue("Tak, 3 lata")).toBeInTheDocument();
  });

  it("udany zapis nie zostawia komunikatu o błędzie", async () => {
    mocks.submit.mockResolvedValue({ data: { match_percent: 80 } });

    renderSheet();

    const submit = await screen.findByRole("button", { name: /Zapisz screening/ });
    await userEvent.click(submit);

    await waitFor(() => expect(mocks.submit).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mocks.showError).not.toHaveBeenCalled();
  });
});
