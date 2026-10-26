/**
 * Runda 10 (F08): okno „Zaplanuj Prep” podpowiada termin PRZED rozmową
 * u klienta i ostrzega, gdy prep na nią nachodzi.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  followup: [] as unknown[],
  // Pola stanowiska i opisu roli (26.10.2026); pusty obiekt = starszy serwer.
  role: {} as Record<string, unknown>,
}));

vi.mock("@/lib/api/prepMeetings", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api/prepMeetings")>()),
  prepMeetingsApi: { create: mocks.create },
  usePrepOptions: () => ({
    isPending: false,
    isError: false,
    data: {
      enabled: true,
      auto_transcribe: true,
      notice: "Spotkanie jest nagrywane.",
      team: [{ id: 5, name: "Delivery Lead" }],
      suggested: { "1": { id: 5 }, "2": { id: 5 } },
      invitation: {
        "1": {
          title: "Przygotowanie do spotkania z Klientem Alior - Piotr Nowak",
          body: "Dzień dobry,\n\nZapraszam na spotkanie przygotowujące do rozmowy z Klientem Alior na stanowisko Senior Java.\n\nTermin rozmowy z Klientem: w poniedziałek\n\n{note}\n\nW razie pytań pozostaję do dyspozycji.\n\nPozdrawiam\n{organizer}",
          interview_line: "Termin rozmowy z Klientem: w poniedziałek",
        },
        "2": {
          title: "Przygotowanie do spotkania z Klientem Alior - Piotr Nowak (spotkanie 2)",
          body: "Dzień dobry,\n\nZapraszam na drugie spotkanie.\n\n{note}\n\nPozdrawiam\n{organizer}",
          interview_line: null,
        },
      },
      prep1_followup: mocks.followup,
      ...mocks.role,
    },
  }),
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showError: vi.fn(), showSuccess: vi.fn() }),
}));

import { PlanPrepDialog } from "@/components/calendar/cycle/PlanPrepDialog";
import { defaultPrepStart, toLocalInput } from "@/lib/prep-timing";

const PAIR = {
  candidate_id: 11,
  candidate_name: "Piotr Nowak",
  candidate_email: "piotr@example.com",
  job_id: 22,
  job_title: "Senior Java",
  client_id: 33,
  client_name: "Alior",
};

function renderDialog(interview: { start: string; end: string }, prepNo: 1 | 2 = 1) {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <PlanPrepDialog open onOpenChange={() => {}} pair={PAIR} prepNo={prepNo} interview={interview} />
    </QueryClientProvider>,
  );
}

describe("PlanPrepDialog — termin względem rozmowy u klienta", () => {
  it("podpowiada termin przed rozmową, a prep na rozmowie ostrzega", () => {
    const start = new Date();
    start.setDate(start.getDate() + 4);
    start.setHours(10, 0, 0, 0);
    const end = new Date(start.getTime() + 60 * 60_000);
    const interview = { start: start.toISOString(), end: end.toISOString() };

    renderDialog(interview);

    const input = screen.getByLabelText("Termin") as HTMLInputElement;
    expect(input.value).toBe(defaultPrepStart(interview, 1, 45));
    expect(new Date(input.value).getTime()).toBeLessThan(start.getTime());
    expect(screen.queryByTestId("prep-timing-warning")).toBeNull();

    fireEvent.change(input, { target: { value: toLocalInput(start) } });
    expect(screen.getByTestId("prep-timing-warning")).toHaveTextContent(
      /nakłada się na rozmowę u klienta/,
    );
  });

  it("termin, który już minął, ostrzega przed zaproszeniem na przeszłość", () => {
    const start = new Date();
    start.setDate(start.getDate() + 4);
    start.setHours(10, 0, 0, 0);
    renderDialog({
      start: start.toISOString(),
      end: new Date(start.getTime() + 60 * 60_000).toISOString(),
    });
    expect(screen.queryByTestId("prep-past-warning")).toBeNull();

    const earlier = new Date(Date.now() - 3 * 60 * 60_000);
    fireEvent.change(screen.getByLabelText("Termin"), {
      target: { value: toLocalInput(earlier) },
    });
    expect(screen.getByTestId("prep-past-warning")).toHaveTextContent(/Ten termin już minął/);
  });

  it("pokazuje zaproszenie, które dostanie kandydat, z dopiskiem i podpisem prowadzącego", () => {
    const start = new Date();
    start.setDate(start.getDate() + 4);
    start.setHours(10, 0, 0, 0);
    const end = new Date(start.getTime() + 60 * 60_000);
    renderDialog({ start: start.toISOString(), end: end.toISOString() });

    const preview = screen.getByTestId("prep-invitation-preview");
    expect(preview).toHaveTextContent("Przygotowanie do spotkania z Klientem Alior - Piotr Nowak");
    expect(preview).toHaveTextContent("Termin rozmowy z Klientem: w poniedziałek");
    expect(preview).toHaveTextContent("Pozdrawiam Delivery Lead");
    expect(preview).toHaveTextContent("Spotkanie jest nagrywane.");
    expect(preview).not.toHaveTextContent("{note}");

    fireEvent.change(screen.getByLabelText(/Dopisek do zaproszenia/), {
      target: { value: "Proszę o włączoną kamerę." },
    });
    expect(preview).toHaveTextContent("Proszę o włączoną kamerę.");

    // Prep po rozmowie nie zapowiada jej terminu (serwer też go wtedy pomija).
    const after = new Date(end.getTime() + 24 * 60 * 60_000);
    fireEvent.change(screen.getByLabelText("Termin"), { target: { value: toLocalInput(after) } });
    expect(preview).not.toHaveTextContent("Termin rozmowy z Klientem");
  });
});

describe("PlanPrepDialog — Prep 2 z notatką z Prepu 1 (22.10.2026)", () => {
  function interview() {
    const start = new Date();
    start.setDate(start.getDate() + 4);
    start.setHours(10, 0, 0, 0);
    return { start: start.toISOString(), end: new Date(start.getTime() + 3_600_000).toISOString() };
  }

  it("pokazuje punkty do powtórzenia i na życzenie dopisuje je do zaproszenia bez ocen", () => {
    mocks.followup = [
      { key: "must:Kafka", label: "Kafka", reason: "weak", note: "Jeden przypadek z liczbami." },
      { key: "topic:1", label: "Przebieg rozmowy u klienta", reason: "missing_topic", note: null },
    ];
    renderDialog(interview(), 2);

    const note = screen.getByTestId("prep2-followup-note");
    expect(note).toHaveTextContent("Kafka");
    expect(note).toHaveTextContent("Słaba odp.");
    expect(note).toHaveTextContent("Przećwicz: Jeden przypadek z liczbami.");

    const preview = screen.getByTestId("prep-invitation-preview");
    expect(preview).not.toHaveTextContent("Na spotkaniu wrócimy do");
    fireEvent.click(screen.getByRole("checkbox", { name: /Dopisz do zaproszenia kandydata/ }));
    expect(preview).toHaveTextContent("Na spotkaniu wrócimy do: Kafka oraz Przebieg rozmowy u klienta.");
    expect(preview).not.toHaveTextContent("Słaba");
  });

  it("Prep 1 nie pokazuje notatki", () => {
    mocks.followup = [{ key: "a", label: "Kafka", reason: "weak", note: null }];
    renderDialog(interview(), 1);
    expect(screen.queryByTestId("prep2-followup-note")).toBeNull();
  });
});

describe("PlanPrepDialog — prowadzący ma wtedy zajęte (22.10.2026)", () => {
  it("409 PREP_SLOT_BUSY pokazuje ostrzeżenie i „Zapisz mimo to” z accept_busy", async () => {
    const start = new Date();
    start.setDate(start.getDate() + 4);
    start.setHours(10, 0, 0, 0);
    mocks.create.mockReset();
    mocks.create.mockRejectedValueOnce({
      response: {
        status: 409,
        data: {
          detail: {
            code: "PREP_SLOT_BUSY",
            message: "Delivery Lead ma wtedy zajęte (09:30–10:30). Wybierz inną godzinę albo zapisz mimo to, jeśli to uzgodnione.",
          },
        },
      },
    });
    mocks.create.mockResolvedValueOnce({ transcription_setup: "enabled" });
    renderDialog({ start: start.toISOString(), end: new Date(start.getTime() + 3_600_000).toISOString() });

    fireEvent.click(screen.getByRole("button", { name: "Zaplanuj w Teams" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Delivery Lead ma wtedy zajęte (09:30–10:30)");
    expect(mocks.create.mock.calls[0][0]).toMatchObject({ accept_busy: false });

    fireEvent.click(screen.getByRole("button", { name: "Zapisz mimo to" }));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(2));
    expect(mocks.create.mock.calls[1][0]).toMatchObject({ accept_busy: true });
  });

  it("po zmianie terminu „Zapisz mimo to” znika — ostrzeżenie dotyczyło innej godziny", async () => {
    const start = new Date();
    start.setDate(start.getDate() + 4);
    start.setHours(10, 0, 0, 0);
    mocks.create.mockReset();
    mocks.create.mockRejectedValueOnce({
      response: { status: 409, data: { detail: { code: "PREP_SLOT_BUSY", message: "Delivery Lead ma wtedy zajęte." } } },
    });
    renderDialog({ start: start.toISOString(), end: new Date(start.getTime() + 3_600_000).toISOString() });
    fireEvent.click(screen.getByRole("button", { name: "Zaplanuj w Teams" }));
    expect(await screen.findByRole("button", { name: "Zapisz mimo to" })).toBeInTheDocument();
    const field = document.querySelector<HTMLInputElement>('input[type="datetime-local"]')!;
    const later = new Date(start.getTime() - 2 * 3_600_000);
    fireEvent.change(field, { target: { value: toLocalInput(later) } });
    expect(screen.queryByRole("button", { name: "Zapisz mimo to" })).toBeNull();
  });
});

describe("PlanPrepDialog — stanowisko i opis roli (26.10.2026)", () => {
  const ROLE_BODY =
    "Dzień dobry,\n\nZapraszam na spotkanie przygotowujące do rozmowy z Klientem Nordea na stanowisko {role}.\n\n{role_hint}\n\n{note}\n\nW razie pytań pozostaję do dyspozycji.\n\nPozdrawiam\n{organizer}";
  const ROLE = {
    role_title: "Senior ETL / Snowflake Engineer",
    role_title_source: "champion",
    role_title_needs_fix: false,
    role_description: "Projekt hurtowni danych.\n\nZakres obowiązków:\n• ETL w Snowflake",
    role_description_findings: [],
    invitation: {
      "1": {
        title: "Przygotowanie do spotkania z Klientem Nordea - Piotr Nowak",
        body: ROLE_BODY,
        interview_line: null,
        role_hint: "Przed spotkaniem przejrzyj, proszę, opis roli poniżej.",
      },
    },
  };

  function interview() {
    const start = new Date();
    start.setDate(start.getDate() + 4);
    start.setHours(10, 0, 0, 0);
    return { start: start.toISOString(), end: new Date(start.getTime() + 3_600_000).toISOString() };
  }

  it("podgląd ma stanowisko z Championa, zdanie o opisie i sekcję „O roli”", () => {
    mocks.role = ROLE;
    renderDialog(interview());
    const preview = screen.getByTestId("prep-invitation-preview");
    expect(preview).toHaveTextContent("na stanowisko Senior ETL / Snowflake Engineer.");
    expect(preview).toHaveTextContent("Przed spotkaniem przejrzyj, proszę, opis roli poniżej.");
    expect(screen.getByTestId("prep-invitation-role")).toHaveTextContent(
      "O roli: Senior ETL / Snowflake Engineer",
    );
    expect(preview).not.toHaveTextContent("{role");
    expect(screen.queryByTestId("prep-role-title-warning")).toBeNull();

    fireEvent.click(screen.getByLabelText(/Dołącz opis roli/));
    expect(screen.queryByTestId("prep-invitation-role")).toBeNull();
    expect(preview).not.toHaveTextContent("opis roli poniżej");
  });

  it("kod klienta w stanowisku ostrzega, a poprawka idzie do zapisu", async () => {
    mocks.role = { ...ROLE, role_title: "PL_IT_Developer_expert_TP#40379", role_title_source: "client" };
    mocks.create.mockReset();
    mocks.create.mockResolvedValue({ prep_no: 1, transcription_setup: "enabled" });
    renderDialog(interview());
    expect(screen.getByTestId("prep-role-title-warning")).toHaveTextContent(/nie wygląda na nazwę roli/);

    fireEvent.change(screen.getByLabelText("Stanowisko w zaproszeniu"), {
      target: { value: "IT Developer (Expert)" },
    });
    expect(screen.queryByTestId("prep-role-title-warning")).toBeNull();
    fireEvent.click(screen.getByText("Edytuj w tym zaproszeniu"));
    fireEvent.change(screen.getByLabelText("Opis roli w zaproszeniu"), {
      target: { value: "Krótki opis." },
    });
    fireEvent.click(screen.getByText("Zaplanuj w Teams"));
    await waitFor(() => expect(mocks.create).toHaveBeenCalled());
    expect(mocks.create.mock.calls[0][0]).toMatchObject({
      role_title: "IT Developer (Expert)",
      role_description: "Krótki opis.",
    });
  });

  it("wyłączony opis = pusty opis w zapisie; Champion bez opisu mówi to wprost", async () => {
    mocks.role = ROLE;
    mocks.create.mockReset();
    mocks.create.mockResolvedValue({ prep_no: 1, transcription_setup: "enabled" });
    const first = renderDialog(interview());
    fireEvent.click(screen.getByLabelText(/Dołącz opis roli/));
    fireEvent.click(screen.getByText("Zaplanuj w Teams"));
    await waitFor(() => expect(mocks.create).toHaveBeenCalled());
    expect(mocks.create.mock.calls[0][0]).toMatchObject({ role_description: "" });
    first.unmount();

    mocks.role = { ...ROLE, role_description: "" };
    renderDialog(interview());
    expect(screen.getByTestId("prep-role-missing")).toHaveTextContent(/nie ma opisu projektu/);
    expect(screen.queryByTestId("prep-invitation-role")).toBeNull();
  });

  it("starszy serwer bez pól roli — okno ich nie pokazuje i nie wysyła", async () => {
    mocks.role = {};
    mocks.create.mockReset();
    mocks.create.mockResolvedValue({ prep_no: 1, transcription_setup: "enabled" });
    renderDialog(interview());
    expect(screen.queryByTestId("prep-role")).toBeNull();
    fireEvent.click(screen.getByText("Zaplanuj w Teams"));
    await waitFor(() => expect(mocks.create).toHaveBeenCalled());
    expect(mocks.create.mock.calls[0][0]).not.toHaveProperty("role_description");
  });
});
