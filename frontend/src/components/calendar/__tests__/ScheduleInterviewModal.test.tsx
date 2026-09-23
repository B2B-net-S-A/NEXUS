/**
 * „Zaplanuj spotkanie" z profilu kandydata (audyt 17.09.2026, kalendarz P1/P2).
 *
 * * wydarzenie niesie rekrutację (bez niej feedback i eskalacja T+2h nie mają
 *   do czego się przypiąć), przy jednej rekrutacji wybraną automatycznie;
 * * okno stale zamontowane na profilu resetuje się przy każdym otwarciu —
 *   nie proponuje godziny z przeszłości ani uczestników z poprzedniej rozmowy;
 * * pusta/przeszła data i literówka w adresie są zatrzymane przed wysyłką.
 */
import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  createInvite: vi.fn(),
  apiGet: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => mocks.apiGet(...a) },
  calendarApi: {
    conflicts: vi.fn().mockResolvedValue({ data: { conflicts: [] } }),
  },
  microsoft365Api: {
    createInvite: (...a: unknown[]) => mocks.createInvite(...a),
    checkFreeBusy: vi.fn().mockRejectedValue(new Error("brak M365")),
  },
}));

vi.mock("@/lib/use-debounced-value", () => ({
  useDebouncedValue: (value: unknown) => value,
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (s: { user: { email: string } }) => unknown) =>
    selector({ user: { email: "rekruter@example.com" } }),
}));

import ScheduleInterviewModal from "@/components/calendar/ScheduleInterviewModal";

function Harness({ open }: { open: boolean }) {
  const [client] = React.useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  );
  return (
    <QueryClientProvider client={client}>
      <ScheduleInterviewModal
        candidateId={42}
        candidateName="Anna Testowa"
        candidateEmail="anna@example.com"
        open={open}
        onOpenChange={() => undefined}
      />
    </QueryClientProvider>
  );
}

function recruitments(
  list: Array<{ job_id: number; job_title: string; can_schedule?: boolean }>,
) {
  mocks.apiGet.mockResolvedValue({
    data: list.map((r, i) => ({ stage_id: i + 1, stage: "cv_sent", ready: true, ...r })),
  });
}

beforeEach(() => {
  mocks.createInvite.mockReset();
  mocks.apiGet.mockReset();
  mocks.createInvite.mockResolvedValue({ data: { online_meeting_url: null } });
});

describe("ScheduleInterviewModal", () => {
  it("wysyła rekrutację wybraną automatycznie, gdy kandydat ma jedną", async () => {
    recruitments([{ job_id: 44, job_title: "Java Dev" }]);
    render(<Harness open />);

    await waitFor(() => expect(screen.getByLabelText("Rekrutacja")).toHaveValue("44"));
    fireEvent.click(screen.getByRole("button", { name: /Zaplanuj w Outlook/ }));

    await waitFor(() =>
      expect(mocks.createInvite).toHaveBeenCalledWith(
        expect.objectContaining({ candidate_id: 42, job_id: 44, reminder_minutes: 15 }),
      ),
    );
    expect(mocks.apiGet).toHaveBeenCalledWith("/api/cv-generator/candidates/42/recruitments");
  });

  it("nie podstawia sam cudzej rekrutacji — zapis kończyłby się 403", async () => {
    recruitments([{ job_id: 44, job_title: "Java Dev", can_schedule: false }]);
    render(<Harness open />);

    const select = screen.getByLabelText("Rekrutacja") as HTMLSelectElement;
    await waitFor(() =>
      expect(Array.from(select.options).map((o) => o.textContent)).toContain(
        "Java Dev — nie jesteś w zespole tej rekrutacji",
      ),
    );
    const option = Array.from(select.options).find((o) => o.value === "44");
    expect(option?.disabled).toBe(true);
    expect(screen.getByLabelText("Rekrutacja")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: /Zaplanuj w Outlook/ }));
    await waitFor(() =>
      expect(mocks.createInvite).toHaveBeenCalledWith(expect.objectContaining({ job_id: null })),
    );
  });

  it("bez rekrutacji ostrzega, ale nie blokuje", async () => {
    recruitments([
      { job_id: 44, job_title: "Java Dev" },
      { job_id: 45, job_title: "QA" },
    ]);
    render(<Harness open />);

    expect(await screen.findByText(/Bez rekrutacji feedback po rozmowie/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Zaplanuj w Outlook/ }));
    await waitFor(() =>
      expect(mocks.createInvite).toHaveBeenCalledWith(expect.objectContaining({ job_id: null })),
    );
  });

  it("przeszła data i zły adres zatrzymują wysyłkę", async () => {
    recruitments([]);
    render(<Harness open />);

    fireEvent.change(screen.getByLabelText("Początek (czas lokalny)"), {
      target: { value: "2020-01-01T10:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Zaplanuj w Outlook/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/w przeszłości/);

    fireEvent.change(screen.getByLabelText("Początek (czas lokalny)"), {
      target: { value: "2099-01-01T10:00" },
    });
    fireEvent.change(screen.getByLabelText(/Dodatkowi uczestnicy/), {
      target: { value: "klient@firma.pl kolega@" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Zaplanuj w Outlook/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/kolega@/);
    expect(mocks.createInvite).not.toHaveBeenCalled();
  });

  it("uczestnicy dzieleni po spacji i średniku", async () => {
    recruitments([]);
    render(<Harness open />);
    fireEvent.change(screen.getByLabelText(/Dodatkowi uczestnicy/), {
      target: { value: "a@x.pl b@x.pl;c@x.pl" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Zaplanuj w Outlook/ }));
    await waitFor(() =>
      expect(mocks.createInvite).toHaveBeenCalledWith(
        expect.objectContaining({ extra_attendees: ["a@x.pl", "b@x.pl", "c@x.pl"] }),
      ),
    );
  });

  it("ponowienie po błędzie niesie ten sam identyfikator, nowe wydarzenie — nowy (FIX-08)", async () => {
    recruitments([]);
    mocks.createInvite
      .mockRejectedValueOnce(new Error("Network Error"))
      .mockResolvedValue({ data: { online_meeting_url: null } });
    render(<Harness open />);
    const submit = () =>
      fireEvent.click(screen.getByRole("button", { name: /Zaplanuj w Outlook/ }));

    submit();
    await waitFor(() => expect(mocks.createInvite).toHaveBeenCalledTimes(1));
    submit();
    await waitFor(() => expect(mocks.createInvite).toHaveBeenCalledTimes(2));
    submit();
    await waitFor(() => expect(mocks.createInvite).toHaveBeenCalledTimes(3));

    const ids = mocks.createInvite.mock.calls.map(
      (call: unknown[]) => (call[0] as { client_request_id?: string }).client_request_id,
    );
    expect(ids[0]).toMatch(/^[A-Za-z0-9-]{8,64}$/);
    expect(ids[1]).toBe(ids[0]);
    expect(ids[2]).not.toBe(ids[1]);
  });

  it("ponowne otwarcie czyści uczestników i proponuje przyszłą godzinę", async () => {
    recruitments([]);
    const { rerender } = render(<Harness open />);
    fireEvent.change(screen.getByLabelText(/Dodatkowi uczestnicy/), {
      target: { value: "stary@x.pl" },
    });
    fireEvent.change(screen.getByLabelText("Początek (czas lokalny)"), {
      target: { value: "2020-01-01T10:00" },
    });

    rerender(<Harness open={false} />);
    rerender(<Harness open />);

    expect(await screen.findByLabelText(/Dodatkowi uczestnicy/)).toHaveValue("");
    const start = (screen.getByLabelText("Początek (czas lokalny)") as HTMLInputElement).value;
    expect(new Date(start).getTime()).toBeGreaterThan(Date.now());
  });
});
