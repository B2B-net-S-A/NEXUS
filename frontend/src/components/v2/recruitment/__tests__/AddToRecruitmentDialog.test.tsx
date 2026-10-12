import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BulkProposalsResponse } from "@/lib/candidate-search-api";

const mocks = vi.hoisted(() => ({ add: vi.fn() }));

vi.mock("@/lib/candidate-search-api", () => ({
  proposalsBulkApi: { add: (...args: unknown[]) => mocks.add(...args) },
}));

vi.mock("@/components/v2/recruitment/JobPicker", () => ({
  JobPicker: ({ onChange }: { onChange: (job: { id: number; title: string }) => void }) => (
    <button type="button" onClick={() => onChange({ id: 42, title: "Java Developer" })}>
      Wybierz Java Developer (mock)
    </button>
  ),
}));

import {
  AddToRecruitmentDialog,
  addToRecruitmentSummary,
} from "@/components/v2/recruitment/AddToRecruitmentDialog";

function renderDialog(props: Partial<React.ComponentProps<typeof AddToRecruitmentDialog>> = {}) {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const onOpenChange = vi.fn();
  const onAdded = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <AddToRecruitmentDialog
        open
        onOpenChange={onOpenChange}
        candidateIds={[5, 6]}
        source="candidate_list"
        onAdded={onAdded}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { invalidate, onOpenChange, onAdded };
}

const RESPONSE: BulkProposalsResponse = { added: [5], skipped: [{ candidate_id: 6, reason: "already_in_job" }], total_added: 1, total_skipped: 1 };

describe("AddToRecruitmentDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.add.mockResolvedValue(RESPONSE);
  });

  it("bez wyboru rekrutacji nie da się zapisać", () => {
    renderDialog();
    expect(screen.getByText("Wybierz rekrutację dla 2 osób.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dodaj" })).toBeDisabled();
  });

  it("zapisuje przez bulk API z właściwym źródłem, bez run_id gdy go nie ma", async () => {
    const { invalidate, onOpenChange, onAdded } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /Wybierz Java Developer/ }));
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do „Java Developer”" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.add).toHaveBeenCalledWith(42, { candidate_ids: [5, 6], source: "candidate_list" });
    expect(onAdded).toHaveBeenCalledWith({ job: { id: 42, title: "Java Developer" }, response: RESPONSE });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", "42"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["kanban", 42] });
  });

  it("Talent Radar przekazuje run_id przeglądu", async () => {
    renderDialog({ candidateIds: [5], source: "talent_radar", runId: "run-1", subject: "Wybierz rekrutację dla: Anna." });
    expect(screen.getByText("Wybierz rekrutację dla: Anna.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Wybierz Java Developer/ }));
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do „Java Developer”" }));
    await waitFor(() => expect(mocks.add).toHaveBeenCalled());
    expect(mocks.add).toHaveBeenCalledWith(42, { candidate_ids: [5], source: "talent_radar", run_id: "run-1" });
  });

  it("403 pokazuje powód z serwera (nie członkostwo w zespole) i zostawia okno otwarte", async () => {
    // Od 07.10.2026 dodanie nie wymaga członkostwa — odmowa ma inny powód
    // (sekcja, rola podglądu), więc mówi ją serwer.
    mocks.add.mockRejectedValue(
      Object.assign(new Error("HTTP 403"), {
        response: { status: 403, data: { detail: "Brak uprawnień do sekcji Pipeline." } },
      }),
    );
    const { onOpenChange } = renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /Wybierz Java Developer/ }));
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do „Java Developer”" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Brak uprawnień do sekcji Pipeline.");
    expect(alert).not.toHaveTextContent("zespołu");
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("inny błąd pokazuje treść z API", async () => {
    mocks.add.mockRejectedValue(Object.assign(new Error("HTTP 422"), { response: { status: 422, data: { detail: "Rekrutacja jest zamknięta." } } }));
    renderDialog();
    fireEvent.click(screen.getByRole("button", { name: /Wybierz Java Developer/ }));
    fireEvent.click(screen.getByRole("button", { name: "Dodaj do „Java Developer”" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Rekrutacja jest zamknięta.");
  });

  describe("osoby, które u nas pracują", () => {
    const marker = {
      phase: "working" as const,
      source: "contract" as const,
      clients: [
        {
          client_id: 4,
          client_name: "Bank Przykładowy",
          contract_id: 40,
          phase: "working" as const,
          order_end_date: "2026-12-31",
        },
      ],
    };
    const anna = { id: 5, name: "Anna Przykładowa", marker };

    it("okno mówi, kto z wyboru u nas pracuje, i domyślnie dodaje wszystkich", async () => {
      renderDialog({ candidateIds: [5, 6, 7], employed: [anna, { id: 99, name: "Spoza wyboru", marker }] });

      const notice = screen.getByRole("note");
      expect(notice).toHaveTextContent("1 z 3 osób pracuje u nas");
      expect(notice).toHaveTextContent("Anna Przykładowa — pracuje u nas · Bank Przykładowy · do 31.12.2026");
      expect(notice).not.toHaveTextContent("Spoza wyboru");

      fireEvent.click(screen.getByRole("button", { name: /Wybierz Java Developer/ }));
      fireEvent.click(screen.getByRole("button", { name: "Dodaj do „Java Developer”" }));
      await waitFor(() => expect(mocks.add).toHaveBeenCalled());
      expect(mocks.add).toHaveBeenCalledWith(42, { candidate_ids: [5, 6, 7], source: "candidate_list" });
    });

    it("„Dodaj bez tej osoby” zdejmuje ją z zapisu, „Przywróć” cofa", async () => {
      renderDialog({ candidateIds: [5, 6, 7], employed: [anna] });

      fireEvent.click(screen.getByRole("button", { name: "Dodaj bez tej osoby" }));
      expect(screen.getByText("Wybierz rekrutację dla 2 osób.")).toBeInTheDocument();
      expect(screen.getByRole("note")).toHaveTextContent("Bez 1 osoby, która u nas pracuje.");

      fireEvent.click(screen.getByRole("button", { name: /Wybierz Java Developer/ }));
      fireEvent.click(screen.getByRole("button", { name: "Dodaj do „Java Developer”" }));
      await waitFor(() => expect(mocks.add).toHaveBeenCalled());
      expect(mocks.add).toHaveBeenCalledWith(42, { candidate_ids: [6, 7], source: "candidate_list" });
    });

    it("„Przywróć” wraca do pełnego wyboru", () => {
      renderDialog({ candidateIds: [5, 6], employed: [anna] });

      fireEvent.click(screen.getByRole("button", { name: "Dodaj bez tej osoby" }));
      fireEvent.click(screen.getByRole("button", { name: "Przywróć" }));

      expect(screen.getByText("Wybierz rekrutację dla 2 osób.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Dodaj bez tej osoby" })).toBeInTheDocument();
    });

    it("jedna osoba: pełne szczegóły i bez przycisku, który zostawiłby pusty wybór", () => {
      renderDialog({ candidateIds: [5], employed: [anna], subject: "Anna Przykładowa" });

      expect(screen.getByRole("note")).toHaveTextContent("Anna Przykładowa pracuje u nas · Bank Przykładowy");
      expect(screen.queryByRole("button", { name: /Dodaj bez/ })).toBeNull();
    });

    it("bez osób pracujących okno wygląda jak dotąd", () => {
      renderDialog();

      expect(screen.queryByRole("note")).toBeNull();
    });
  });

  it("podsumowanie mówi o ostrzeżeniach przy dodanych osobach", () => {
    const job = { id: 42, title: "Java Developer" };
    expect(
      addToRecruitmentSummary({
        job,
        response: {
          added: [5, 6],
          skipped: [],
          warnings: [
            { candidate_id: 5, reason: "current_employment" },
            { candidate_id: 6, reason: "client_nda" },
          ],
          total_added: 2,
          total_skipped: 0,
        },
      }),
    ).toBe(
      "Dodano 2 osoby do „Java Developer”. Uwaga: 1× obecne zatrudnienie u klienta, 1× konflikt: NDA z klientem.",
    );
  });

  it("podsumowanie liczy dodanych i pominiętych", () => {
    const job = { id: 42, title: "Java Developer" };
    expect(addToRecruitmentSummary({ job, response: RESPONSE })).toBe("Dodano 1 osobę do „Java Developer”. Pominięto: 1.");
    expect(addToRecruitmentSummary({ job, response: { ...RESPONSE, added: [], total_added: 0, total_skipped: 0, skipped: [] } })).toBe("Nikogo nie dodano do „Java Developer”.");
    expect(addToRecruitmentSummary({ job, response: { ...RESPONSE, total_added: 3, total_skipped: 0 } })).toBe("Dodano 3 osoby do „Java Developer”.");
    expect(addToRecruitmentSummary({ job, response: { ...RESPONSE, total_added: 12, total_skipped: 0 } })).toBe("Dodano 12 osób do „Java Developer”.");
    expect(addToRecruitmentSummary({ job, response: { ...RESPONSE, total_added: 22, total_skipped: 0 } })).toBe("Dodano 22 osoby do „Java Developer”.");
  });
});
