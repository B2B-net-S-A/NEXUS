import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Linki dla klienta są na produkcji wyłączone stałą (#1647). Testy niżej
// sprawdzają ścieżkę z linkami (stała = true); blok „linki wyłączone" sprawdza
// stan produkcyjny.
const linkFlags = vi.hoisted(() => ({ enabled: true }));
vi.mock("@/lib/cv-generator", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/cv-generator")>();
  return {
    ...actual,
    get CV_CLIENT_LINKS_UI_ENABLED() {
      return linkFlags.enabled;
    },
  };
});

const mocks = vi.hoisted(() => ({
  showSuccess: vi.fn(),
  showError: vi.fn(),
  copy: vi.fn(),
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({
    showSuccess: mocks.showSuccess,
    showError: mocks.showError,
    showToast: vi.fn(),
    showActionToast: vi.fn(),
  }),
}));
vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: mocks.copy }));

import {
  BulkCvHandoffDialog,
  type BulkCvHandoffDialogProps,
} from "@/components/v2/recruitment/BulkCvHandoffDialog";
import type { BulkCvHandoffOutcome } from "@/lib/bulk-cv-handoff";

const ORIGIN = "https://nexus.test";

const LINKED_ANNA: BulkCvHandoffOutcome = {
  kind: "linked", candidateId: 1, fullName: "Anna Nowak", sourceStageId: 100,
  suffix: "/cv/s/aaa", expiresInDays: 14, rateFailed: null,
};
const LINKED_JAN: BulkCvHandoffOutcome = {
  kind: "linked", candidateId: 2, fullName: "Jan Kowalski", sourceStageId: 200,
  suffix: "/cv/s/bbb", expiresInDays: 14, rateFailed: "Brak uprawnień",
};
const NO_LINK_EWA: BulkCvHandoffOutcome = {
  kind: "moved_no_link", candidateId: 3, fullName: "Ewa Pawlak", sourceStageId: 300,
  reason: "Błąd serwera", expiresInDays: 14, rateFailed: null,
};
const SKIPPED: BulkCvHandoffOutcome = {
  kind: "skipped", candidateId: 4, fullName: "Piotr Lis", sourceStageId: 400,
  reason: "brak CV firmowego",
};
const REFUSED: BulkCvHandoffOutcome = {
  kind: "move_refused", candidateId: 5, fullName: "Ola Mak", sourceStageId: 500,
  reason: "Kandydat został w międzyczasie przesunięty.",
};

function renderDialog(
  outcomes: BulkCvHandoffOutcome[],
  over: { onRetryLink?: BulkCvHandoffDialogProps["onRetryLink"] } = {},
) {
  const onRetryLink = over.onRetryLink ?? vi.fn<BulkCvHandoffDialogProps["onRetryLink"]>();
  const onClose = vi.fn<() => void>();
  render(
    <BulkCvHandoffDialog
      open
      outcomes={outcomes}
      onRetryLink={onRetryLink}
      onClose={onClose}
      origin={ORIGIN}
    />,
  );
  return { onRetryLink, onClose };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.copy.mockResolvedValue(true);
  window.localStorage.clear();
});

describe("BulkCvHandoffDialog", () => {
  it("pokazuje linki (pełny adres, widoczny), porażki z powodem i ostrzeżenie o jednorazowości", () => {
    renderDialog([LINKED_ANNA, LINKED_JAN, NO_LINK_EWA, SKIPPED, REFUSED]);

    expect(screen.getByLabelText("Anna Nowak")).toHaveValue(`${ORIGIN}/cv/s/aaa`);
    expect(screen.getByLabelText("Jan Kowalski")).toHaveValue(`${ORIGIN}/cv/s/bbb`);
    expect(screen.getByTestId("bulk-cv-link-2")).toHaveTextContent(
      "Stawki do klienta nie udało się zapisać (Brak uprawnień)",
    );
    expect(screen.getByText(/Skopiuj linki teraz/)).toBeInTheDocument();
    expect(screen.getByText(/nie da się go odtworzyć/)).toBeInTheDocument();

    expect(screen.getByTestId("bulk-cv-failure-3")).toHaveTextContent("Błąd serwera");
    expect(screen.getByTestId("bulk-cv-failure-4")).toHaveTextContent(
      "Pominięto — brak CV firmowego. Osoba nie została przeniesiona.",
    );
    expect(screen.getByTestId("bulk-cv-failure-5")).toHaveTextContent(
      "Nie przeniesiono: Kandydat został w międzyczasie przesunięty.",
    );
    // Ponowienie tylko tam, gdzie ruch się udał, a link nie.
    expect(screen.getAllByRole("button", { name: "Utwórz link ponownie" })).toHaveLength(1);
    expect(screen.getByText(/Przeniesiono na „CV Wysłane”: 3 z 5/)).toBeInTheDocument();
  });

  it("„Kopiuj wszystkie”: linie „Imię Nazwisko — link”, toast sukcesu TYLKO po udanym zapisie", async () => {
    renderDialog([LINKED_ANNA, LINKED_JAN]);
    await userEvent.click(screen.getByRole("button", { name: /Kopiuj wszystkie/ }));
    expect(mocks.copy).toHaveBeenCalledWith(
      `Anna Nowak — ${ORIGIN}/cv/s/aaa\nJan Kowalski — ${ORIGIN}/cv/s/bbb`,
    );
    await waitFor(() => expect(mocks.showSuccess).toHaveBeenCalledTimes(1));
    expect(mocks.showError).not.toHaveBeenCalled();
  });

  it("„Kopiuj wszystkie” przy nieudanym zapisie: błąd z instrukcją ręcznego kopiowania, bez „skopiowano”, zamknięcie dalej pyta", async () => {
    mocks.copy.mockResolvedValue(false);
    const { onClose } = renderDialog([LINKED_ANNA]);
    await userEvent.click(screen.getByRole("button", { name: /Kopiuj wszystkie/ }));
    await waitFor(() =>
      expect(mocks.showError).toHaveBeenCalledWith(expect.stringMatching(/skopiuj je ręcznie/)),
    );
    expect(mocks.showSuccess).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Zamknij" }));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog", { name: "Potwierdź zamknięcie" })).toBeInTheDocument();
  });

  it("zamknięcie z nieskopiowanym linkiem pyta W OKNIE: „Wróć do linków” zostaje, „Zamknij mimo to” zamyka", async () => {
    const { onClose } = renderDialog([LINKED_ANNA, LINKED_JAN]);
    // Jeden link skopiowany — drugi nadal nie.
    await userEvent.click(
      within(screen.getByTestId("bulk-cv-link-1")).getByRole("button", { name: /Kopiuj/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Zamknij" }));
    const confirm = screen.getByRole("alertdialog", { name: "Potwierdź zamknięcie" });
    expect(confirm).toHaveTextContent("Nieskopiowane linki: 1 osoba");
    expect(onClose).not.toHaveBeenCalled();

    await userEvent.click(within(confirm).getByRole("button", { name: "Wróć do linków" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Jan Kowalski")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Zamknij" }));
    await userEvent.click(screen.getByRole("button", { name: "Zamknij mimo to" }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("Escape z nieskopiowanym linkiem też pyta, zamiast zamknąć", async () => {
    const { onClose } = renderDialog([LINKED_ANNA]);
    await userEvent.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog", { name: "Potwierdź zamknięcie" })).toBeInTheDocument();
  });

  it("wszystko skopiowane → zamyka od razu, bez pytania", async () => {
    const { onClose } = renderDialog([LINKED_ANNA, LINKED_JAN, SKIPPED]);
    await userEvent.click(screen.getByRole("button", { name: /Kopiuj wszystkie/ }));
    await waitFor(() => expect(mocks.showSuccess).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: "Zamknij" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("„Utwórz link ponownie”: stan zajętości, potem wiersz porażki staje się wierszem z linkiem", async () => {
    let resolve!: (suffix: string) => void;
    const onRetryLink = vi.fn(() => new Promise<string>((r) => (resolve = r)));
    renderDialog([NO_LINK_EWA], { onRetryLink });

    await userEvent.click(screen.getByRole("button", { name: "Utwórz link ponownie" }));
    expect(onRetryLink).toHaveBeenCalledWith(NO_LINK_EWA);
    expect(screen.getByRole("button", { name: "Tworzę link…" })).toBeDisabled();

    resolve("/cv/s/ccc");
    await waitFor(() =>
      expect(screen.getByLabelText("Ewa Pawlak")).toHaveValue(`${ORIGIN}/cv/s/ccc`),
    );
    expect(screen.queryByTestId("bulk-cv-failure-3")).not.toBeInTheDocument();
  });

  it("nieudane ponowienie: powód w wierszu, przycisk wraca; zamknięcie pyta (link da się ponowić tylko stąd)", async () => {
    const onRetryLink = vi.fn().mockRejectedValue({
      response: { status: 409, data: { detail: "CV nie jest sfinalizowane" } },
    });
    const { onClose } = renderDialog([NO_LINK_EWA], { onRetryLink });
    await userEvent.click(screen.getByRole("button", { name: "Utwórz link ponownie" }));
    await waitFor(() =>
      expect(screen.getByTestId("bulk-cv-failure-3")).toHaveTextContent(
        "Ponowienie nie powiodło się: CV nie jest sfinalizowane",
      ),
    );
    expect(screen.getByRole("button", { name: "Utwórz link ponownie" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Zamknij" }));
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Bez linku mimo przeniesienia: 1 osoba");
  });

  it("niczego nie zapisuje w przeglądarce", async () => {
    renderDialog([LINKED_ANNA]);
    await userEvent.click(screen.getByRole("button", { name: /Kopiuj wszystkie/ }));
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });
});
