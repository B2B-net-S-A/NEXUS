import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  post: vi.fn(),
  success: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { get: vi.fn(), post: mocks.post },
}));

vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: mocks.success, showError: vi.fn() }),
}));

import { JustificationDialog } from "../PremiumSkillsSection";

const TEMPLATE = "Kafka is part of the consultant's daily work on this assignment.";

function renderDialog(canDraft = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <JustificationDialog contractId={11} claimId={5} canDraft={canDraft} text={TEMPLATE} technology="Kafka" onClose={() => {}} />
    </QueryClientProvider>,
  );
}

const field = () => screen.getByLabelText("Uzasadnienie po angielsku") as HTMLTextAreaElement;

describe("JustificationDialog — „Zaproponuj uzasadnienie” (F5)", () => {
  beforeEach(() => {
    mocks.post.mockReset();
    mocks.success.mockReset();
  });

  it("zaczyna od szablonu i podmienia go szkicem z modelu z ostrzeżeniem", async () => {
    mocks.post.mockResolvedValue({
      data: {
        text: "Kafka is used every day for payment streams.",
        model_used: true,
        warnings: ["Szkic zawiera liczby, których nie ma w faktach NEXUSA (5) — sprawdź albo usuń przed wysłaniem."],
        message: null,
      },
    });
    renderDialog();
    expect(field().value).toBe(TEMPLATE);
    fireEvent.click(screen.getByRole("button", { name: "Zaproponuj uzasadnienie" }));
    await waitFor(() => expect(field().value).toBe("Kafka is used every day for payment streams."));
    expect(mocks.post).toHaveBeenCalledWith("/api/contracts/11/premium-skills/claims/5/justification-draft");
    expect(screen.getByRole("alert")).toHaveTextContent("liczby, których nie ma w faktach NEXUSA (5)");
    expect(screen.getByText(/Szkic z modelu AI/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zaproponuj ponownie" })).toBeInTheDocument();
  });

  it("bez modelu zostawia szablon i mówi po polsku, co zrobić", async () => {
    mocks.post.mockResolvedValue({
      data: {
        text: null,
        model_used: false,
        warnings: [],
        message: "Model AI nie jest teraz dostępny — popraw szablon uzasadnienia albo napisz je sam.",
      },
    });
    renderDialog();
    fireEvent.change(field(), { target: { value: "Moja wersja" } });
    fireEvent.click(screen.getByRole("button", { name: "Zaproponuj uzasadnienie" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Model AI nie jest teraz dostępny");
    expect(field().value).toBe("Moja wersja");
  });

  it("błąd zapytania nie gubi tekstu i pokazuje komunikat z serwera", async () => {
    mocks.post.mockRejectedValue(
      Object.assign(new Error("x"), { isAxiosError: true, response: { status: 422, data: { detail: "Ten wniosek jest już zamknięty." } } }),
    );
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: "Zaproponuj uzasadnienie" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Ten wniosek jest już zamknięty.");
    expect(field().value).toBe(TEMPLATE);
  });

  it("bez prawa edycji nie ma przycisku modelu, kopiowanie zostaje", () => {
    renderDialog(false);
    expect(screen.queryByRole("button", { name: "Zaproponuj uzasadnienie" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Kopiuj" })).toBeInTheDocument();
  });
});
