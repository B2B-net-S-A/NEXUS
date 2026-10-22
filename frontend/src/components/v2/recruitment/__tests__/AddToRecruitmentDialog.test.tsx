import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BulkProposalsResponse } from "@/lib/candidate-search-api";
import { useAuthStore } from "@/store/auth";

const mocks = vi.hoisted(() => ({ add: vi.fn(), send: vi.fn() }));

vi.mock("@/lib/candidate-search-api", () => ({
  proposalsBulkApi: { add: (...args: unknown[]) => mocks.add(...args) },
}));

// Ruch karty ma własne testy (`usePipelineMoveCore.test.tsx`); tu liczy się
// ładunek, z którym okno go woła.
vi.mock("@/hooks/usePipelineMoveCore", () => ({
  usePipelineMoveCore: () => ({
    send: (...args: unknown[]) => mocks.send(...args),
    dialogs: null,
  }),
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

const CLOSED_ROW = {
  candidate_id: 6,
  reason: "closed_in_job",
  reason_label: "Zamknięta karta w tej rekrutacji: Odrzucony 08.10.2026 (Jan Testowy)",
  closed: { candidate_name: "Ewa Testowa", state_version: 2, restore_stage: "new", restore_stage_def_id: 11 },
} as const;
const CLOSED: BulkProposalsResponse = { added: [], skipped: [CLOSED_ROW], total_added: 0, total_skipped: 1 };

async function addToJavaDeveloper() {
  fireEvent.click(screen.getByRole("button", { name: /Wybierz Java Developer/ }));
  fireEvent.click(screen.getByRole("button", { name: "Dodaj do „Java Developer”" }));
  await waitFor(() => expect(mocks.add).toHaveBeenCalled());
}

describe("AddToRecruitmentDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.add.mockResolvedValue(RESPONSE);
    mocks.send.mockResolvedValue({ ok: true, data: {} });
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

  it("podsumowanie nazywa rekrutację tytułem dla rekrutera, nie nazwą od klienta (16.10.2026)", () => {
    const job = { id: 42, title: "AI Engineer (ZOB-2984)", working_title: "Senior AI Engineer · Java, LLM · 5+ lat" };
    expect(
      addToRecruitmentSummary({ job, response: { added: [1], skipped: [], total_added: 1, total_skipped: 0 } }),
    ).toBe("Dodano 1 osobę do „Senior AI Engineer · Java, LLM · 5+ lat”.");
    expect(
      addToRecruitmentSummary({ job, response: { added: [1], skipped: [], total_added: 1, total_skipped: 0 }, restored: 1 }),
    ).toBe("Przywrócono 1 osobę do „Senior AI Engineer · Java, LLM · 5+ lat”.");
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

  it("zamknięta karta: okno zostaje, mówi skąd i od kiedy, a „Przywróć” rusza kartę", async () => {
    // Zgłoszenie 12.10.2026: „Nikogo nie dodano… Pominięto: 1” bez powodu,
    // a osoba stała w „Zamkniętych” tej rekrutacji od kilku dni.
    mocks.add.mockResolvedValue(CLOSED);
    const { onOpenChange, onAdded } = renderDialog({ candidateIds: [6] });
    await addToJavaDeveloper();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Ewa Testowa");
    expect(alert).toHaveTextContent("Odrzucony 08.10.2026 (Jan Testowy)");
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    expect(onAdded).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Przywróć do „Nowych”" }));
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
    expect(mocks.send).toHaveBeenCalledWith(
      { candidate_id: 6, job_id: 42, stage: "new", stage_def_id: 11, expected_state_version: 2 },
      expect.objectContaining({ candidateName: "Ewa Testowa" }),
    );
    expect(onAdded).toHaveBeenCalledTimes(1);
    const result = onAdded.mock.calls[0][0];
    expect(addToRecruitmentSummary(result)).toBe("Przywrócono 1 osobę do „Java Developer”.");
  });

  it("odmowa ruchu zostawia kartę do przywrócenia", async () => {
    mocks.add.mockResolvedValue(CLOSED);
    mocks.send.mockResolvedValue({ ok: false, refusal: { kind: "other", message: "Błąd" } });
    const { onOpenChange, onAdded } = renderDialog({ candidateIds: [6] });
    await addToJavaDeveloper();
    fireEvent.click(await screen.findByRole("button", { name: "Przywróć do „Nowych”" }));
    await waitFor(() => expect(mocks.send).toHaveBeenCalled());
    expect(await screen.findByRole("button", { name: "Przywróć do „Nowych”" })).toBeEnabled();
    expect(onAdded).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("rekrutacja bez szablonu: ruch idzie samym kodem etapu", async () => {
    mocks.add.mockResolvedValue({
      ...CLOSED,
      skipped: [{ ...CLOSED_ROW, closed: { ...CLOSED_ROW.closed, restore_stage_def_id: null } }],
    });
    renderDialog({ candidateIds: [6] });
    await addToJavaDeveloper();
    fireEvent.click(await screen.findByRole("button", { name: "Przywróć do „Nowych”" }));
    await waitFor(() => expect(mocks.send).toHaveBeenCalled());
    expect(mocks.send.mock.calls[0][0]).toEqual({
      candidate_id: 6, job_id: 42, stage: "new", expected_state_version: 2,
    });
  });

  it("nikogo nie dodano z innego powodu: okno zostaje i mówi powód z serwera", async () => {
    mocks.add.mockResolvedValue({
      added: [],
      skipped: [{ candidate_id: 6, reason: "rejected_by_hiring_manager", reason_label: "Hiring manager odrzucił tego kandydata po rozmowie 01.10.2026." }],
      total_added: 0,
      total_skipped: 1,
    });
    const { onOpenChange, onAdded } = renderDialog({ candidateIds: [6] });
    await addToJavaDeveloper();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Nikogo nie dodano do „Java Developer”.");
    expect(alert).toHaveTextContent("Hiring manager odrzucił tego kandydata po rozmowie 01.10.2026.");
    expect(screen.queryByRole("button", { name: /Przywróć/ })).not.toBeInTheDocument();
    expect(onAdded).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    // Dwa „Zamknij”: krzyżyk okna i przycisk w stopce — klikamy stopkę.
    fireEvent.click(screen.getAllByRole("button", { name: "Zamknij" }).at(-1)!);
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("część dodana, jedna zamknięta karta: dodani idą do ekranu, okno czeka z kartą", async () => {
    const partial: BulkProposalsResponse = { added: [5], skipped: [CLOSED_ROW], total_added: 1, total_skipped: 1 };
    mocks.add.mockResolvedValue(partial);
    const { onOpenChange, onAdded } = renderDialog();
    await addToJavaDeveloper();
    expect(await screen.findByRole("button", { name: "Przywróć do „Nowych”" })).toBeInTheDocument();
    expect(onAdded).toHaveBeenCalledWith({ job: { id: 42, title: "Java Developer" }, response: partial });
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
    // Lista kandydatów czyści zaznaczenie w `onAdded` — opis wyniku nie liczy
    // osób z propsa, tylko nazywa rekrutację.
    expect(screen.getByText("Rekrutacja „Java Developer”.")).toBeInTheDocument();
    expect(screen.queryByText(/Wybierz rekrutację/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Dodaj/ })).not.toBeInTheDocument();
  });

  it("dwie zamknięte karty przywraca się po kolei, a przycisk nazywa kolumnę", async () => {
    const second = {
      ...CLOSED_ROW,
      candidate_id: 7,
      closed: { ...CLOSED_ROW.closed, candidate_name: "Bartek Testowy", restore_stage: "screening" },
    };
    mocks.add.mockResolvedValue({ added: [], skipped: [CLOSED_ROW, second], total_added: 0, total_skipped: 2 });
    // Pierwszy ruch czeka (np. na okno „Przenieś mimo to”).
    mocks.send.mockReturnValue(new Promise(() => undefined));
    const { onOpenChange } = renderDialog({ candidateIds: [6, 7] });
    await addToJavaDeveloper();
    const toScreening = await screen.findByRole("button", { name: "Przywróć do „Screeningu”" });
    fireEvent.click(screen.getByRole("button", { name: "Przywróć do „Nowych”" }));
    await waitFor(() => expect(toScreening).toBeDisabled());
    fireEvent.click(toScreening);
    expect(mocks.send).toHaveBeenCalledTimes(1);
    // Zamknięcie w trakcie ruchu zostawiłoby jego okno bez rodzica.
    fireEvent.click(screen.getAllByRole("button", { name: "Zamknij" }).at(-1)!);
    expect(onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("podsumowanie liczy dodanych i mówi, dlaczego kogoś pominięto", () => {
    const job = { id: 42, title: "Java Developer" };
    expect(addToRecruitmentSummary({ job, response: RESPONSE })).toBe("Dodano 1 osobę do „Java Developer”. Pominięto: 1× już w rekrutacji.");
    expect(addToRecruitmentSummary({ job, response: CLOSED })).toBe("Nikogo nie dodano do „Java Developer”. Pominięto: 1× zamknięta karta w tej rekrutacji.");
    expect(addToRecruitmentSummary({ job, response: { ...RESPONSE, added: [], total_added: 0, total_skipped: 0, skipped: [] } })).toBe("Nikogo nie dodano do „Java Developer”.");
    expect(addToRecruitmentSummary({ job, response: { ...RESPONSE, total_added: 3, total_skipped: 0 } })).toBe("Dodano 3 osoby do „Java Developer”.");
    expect(addToRecruitmentSummary({ job, response: { ...RESPONSE, total_added: 12, total_skipped: 0 } })).toBe("Dodano 12 osób do „Java Developer”.");
    expect(addToRecruitmentSummary({ job, response: { ...RESPONSE, total_added: 22, total_skipped: 0 } })).toBe("Dodano 22 osoby do „Java Developer”.");
  });

  // 22.10.2026: Delivery Lead dodaje jedną osobę od razu na „Zweryfikowany”.
  describe("Delivery Lead wybiera etap", () => {
    afterEach(() => {
      useAuthStore.setState({ user: null } as never);
    });

    it("„Zweryfikowany”: dodanie, potem ruch karty dodanej osoby", async () => {
      useAuthStore.setState({ user: { id: 3, role: "delivery_lead", roles: ["delivery_lead"] } } as never);
      renderDialog({ candidateIds: [5], subject: "Marta Lis" });
      fireEvent.click(screen.getByRole("button", { name: /Wybierz Java Developer/ }));
      fireEvent.click(screen.getByRole("button", { name: "Zweryfikowany" }));
      fireEvent.click(screen.getByRole("button", { name: "Dodaj na „Zweryfikowany”" }));
      await waitFor(() => expect(mocks.send).toHaveBeenCalledTimes(1));
      expect(mocks.send.mock.calls[0][0]).toEqual({ candidate_id: 5, job_id: 42, stage: "verified" });
    });

    it("domyślnie „Nowi” — bez ruchu karty", async () => {
      useAuthStore.setState({ user: { id: 3, role: "delivery_lead", roles: ["delivery_lead"] } } as never);
      renderDialog({ candidateIds: [5] });
      await addToJavaDeveloper();
      expect(mocks.send).not.toHaveBeenCalled();
    });

    it("rekruter i wybór wielu osób nie widzą wyboru etapu", () => {
      useAuthStore.setState({ user: { id: 4, role: "recruiter", roles: ["recruiter"] } } as never);
      renderDialog({ candidateIds: [5] });
      expect(screen.queryByTestId("add-to-recruitment-stage")).toBeNull();
    });
  });
});
