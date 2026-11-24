/**
 * „Nad którą rekrutacją pracujesz dziś?” (zgłoszenie rekruterów 16.11.2026):
 * liczby pod zaznaczoną rekrutacją są z serwera (ten sam plan co wybór), kto
 * już wybrał, widać przy rekrutacji, a „Biorę” zapisuje wybór i zamyka listę.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewBatchFocusPicker, releasedLine } from "@/components/v2/review-batch/ReviewBatchFocusPicker";
import type { ReviewBatchFocusOptions, ReviewBatchFocusPreview } from "@/lib/api/reviewBatch";

const api = vi.hoisted(() => ({
  options: {} as Record<string, unknown>,
  preview: {} as Record<string, unknown>,
  previewFor: [] as (number | null)[],
  setFocus: vi.fn(),
  invalidate: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("@tanstack/react-query", async (original) => ({
  ...(await original<typeof import("@tanstack/react-query")>()),
  useQueryClient: () => ({}),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: api.error, showSuccess: api.success }),
}));
vi.mock("@/lib/api/reviewBatch", () => ({
  invalidateReviewBatch: api.invalidate,
  setReviewBatchFocus: api.setFocus,
  useReviewBatchFocusOptions: () => api.options,
  useReviewBatchFocusPreview: (jobId: number | null) => {
    api.previewFor.push(jobId);
    return api.preview;
  },
}));

const options: ReviewBatchFocusOptions = {
  seats: 20,
  focus: null,
  items: [
    {
      job_id: 11,
      title: "RFX Analityk Biznesowy",
      pending: 0,
      p0: true,
      group: "p0",
      team_size: 3,
      picked_by: [{ user_id: 5, name: "Anna Testowa", at: "2026-11-24T08:05:00Z", cards: 4 }],
    },
    { job_id: 12, title: "AMLA", pending: 2, p0: true, group: "p0", team_size: 11, picked_by: [] },
    { job_id: 13, title: "Scrum Master", pending: 8, p0: false, group: "p1", team_size: 3, picked_by: [] },
  ],
};

function given(
  data: Partial<ReviewBatchFocusOptions> = {},
  preview: Partial<ReviewBatchFocusPreview> | "error" | "loading" = {},
) {
  api.options = { isSuccess: true, isError: false, data: { ...options, ...data } };
  api.preview =
    preview === "error"
      ? { isSuccess: false, isError: true, error: new Error("boom") }
      : preview === "loading"
        ? { isSuccess: false, isError: false }
        : {
            isSuccess: true,
            isError: false,
            data: { job_id: 11, available: 12, take: 3, release: 2, ...preview },
          };
}

describe("ReviewBatchFocusPicker", () => {
  beforeEach(() => {
    api.setFocus.mockReset();
    api.invalidate.mockReset();
    api.success.mockReset();
    api.error.mockReset();
    api.previewFor = [];
    given();
  });

  it("pokazuje rekrutacje w poziomach i kto już wybrał (kto pierwszy, ten bierze)", () => {
    render(<ReviewBatchFocusPicker onClose={vi.fn()} />);
    expect(screen.getByText("Nad którą rekrutacją pracujesz dziś?")).toBeTruthy();
    expect(screen.getByText(/Dziś dalej 20 osób do decyzji/)).toBeTruthy();
    expect(screen.getByText("P0")).toBeTruthy();
    expect(screen.getByText("P1 Pilne")).toBeTruthy();
    expect(screen.getByTestId("review-focus-picked-by").textContent).toMatch(
      /Wybór na dziś: Anna Testowa, 09:05 · ma stąd 4 osoby/,
    );
    // Bez zaznaczenia nie ma podglądu ani zapytania o niego.
    expect(screen.queryByTestId("review-focus-summary")).toBeNull();
    expect(api.previewFor).toEqual([]);
  });

  it("po zaznaczeniu mówi, ile przyjdzie stąd i ile nieruszonych wróci do zespołu", () => {
    render(<ReviewBatchFocusPicker onClose={vi.fn()} />);
    fireEvent.click(screen.getByLabelText(/RFX Analityk Biznesowy/));
    expect(api.previewFor).toContain(11);
    expect(screen.getByTestId("review-focus-summary").textContent).toBe(
      "Przyjdzie stąd 3 osoby. 2 nieruszone osoby z innych rekrutacji wracają do puli zespołu." +
        " Kto wybrał wcześniej, ma już najlepsze osoby; Tobie przyjdą kolejne.",
    );
  });

  it("rekrutacja, z której nikt nie przechodzi reguł, mówi to wprost", () => {
    given({}, { job_id: 12, available: 0, take: 0, release: 0 });
    render(<ReviewBatchFocusPicker onClose={vi.fn()} />);
    fireEvent.click(screen.getByLabelText(/AMLA/));
    expect(screen.getByTestId("review-focus-summary").textContent).toBe(
      "Stąd nie przyjdzie nikt nowy: nikt z puli nie przechodzi reguł tej rekrutacji.",
    );
  });

  it("gdy wolne osoby wziął już ktoś, kto wybrał wcześniej, mówi to zamiast „przyjdą kolejne”", () => {
    given({}, { job_id: 11, available: 0, take: 0, release: 0 });
    render(<ReviewBatchFocusPicker onClose={vi.fn()} />);
    fireEvent.click(screen.getByLabelText(/RFX Analityk Biznesowy/));
    expect(screen.getByTestId("review-focus-summary").textContent).toBe(
      "Stąd nie przyjdzie nikt nowy: wolne osoby są już u tych, którzy wybrali ją wcześniej.",
    );
  });

  it("bez nadwyżki reszta porcji zostaje", () => {
    given({}, { job_id: 13, available: 30, take: 5, release: 0 });
    render(<ReviewBatchFocusPicker onClose={vi.fn()} />);
    fireEvent.click(screen.getByLabelText(/Scrum Master/));
    expect(screen.getByTestId("review-focus-summary").textContent).toBe(
      "Przyjdzie stąd 5 osób. Reszta Twojej porcji zostaje.",
    );
  });

  it("błąd podglądu nie wygląda jak zero osób", () => {
    given({}, "error");
    render(<ReviewBatchFocusPicker onClose={vi.fn()} />);
    fireEvent.click(screen.getByLabelText(/AMLA/));
    expect(screen.getByRole("alert").textContent).toMatch(/boom|Nie udało się policzyć/);
    expect(screen.queryByTestId("review-focus-summary")).toBeNull();
  });

  it("„Biorę tę rekrutację” zapisuje wybór, odświeża porcję i zamyka listę", async () => {
    api.setFocus.mockResolvedValue({ focus: { job_id: 13, at: "x" }, added: 5, released: 2 });
    const onClose = vi.fn();
    const onChosen = vi.fn();
    render(<ReviewBatchFocusPicker onClose={onClose} onChosen={onChosen} />);
    const take = screen.getByRole("button", { name: "Biorę tę rekrutację" });
    expect((take as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText(/Scrum Master/));
    await act(async () => {
      fireEvent.click(take);
    });
    expect(api.setFocus).toHaveBeenCalledWith(13);
    expect(api.invalidate).toHaveBeenCalled();
    expect(api.success).toHaveBeenCalledWith(
      "Doszło 5 osób z „Scrum Master”. 2 nieruszone osoby z innych rekrutacji wracają do puli zespołu.",
    );
    expect(onChosen).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("odmowa serwera zostaje na liście z komunikatem", async () => {
    api.setFocus.mockRejectedValue(new Error("403"));
    const onClose = vi.fn();
    render(<ReviewBatchFocusPicker onClose={onClose} />);
    fireEvent.click(screen.getByLabelText(/AMLA/));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Biorę tę rekrutację" }));
    });
    expect(api.error).toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("obecny wybór jest zaznaczony, a „Biorę” przy nim nieaktywne", () => {
    given({ focus: { job_id: 12, at: "2026-11-24T08:00:00Z" } });
    render(<ReviewBatchFocusPicker onClose={vi.fn()} />);
    expect((screen.getByLabelText(/AMLA/) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText("wybrana")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Biorę tę rekrutację" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });

  it("odmienia „wraca” po liczbie", () => {
    expect(releasedLine(1)).toBe("1 nieruszona osoba z innych rekrutacji wraca do puli zespołu.");
    expect(releasedLine(3)).toBe("3 nieruszone osoby z innych rekrutacji wracają do puli zespołu.");
    expect(releasedLine(7)).toBe("7 nieruszonych osób z innych rekrutacji wraca do puli zespołu.");
  });
});
