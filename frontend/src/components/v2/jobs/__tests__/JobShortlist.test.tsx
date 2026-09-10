/**
 * Tablica shortlisty — pola notatki i terminu NIE mogą po cichu nadpisywać
 * nowszej zmiany kolegi.
 *
 * Do 09.2026 oba pola były niekontrolowane z wartością z pierwszego renderu:
 * po zmianie wpisu przez kogoś innego pole dalej pokazywało stary tekst,
 * a samo przejście przez nie (blur bez zmiany) zapisywało ten stary tekst
 * z NOWĄ wersją — blokada optymistyczna nie miała czego odrzucić.
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShortlistEntry } from "@/lib/candidate-search-api";

const list = vi.fn();
const update = vi.fn();

vi.mock("@/lib/candidate-search-api", () => ({
  shortlistApi: {
    list: (...a: unknown[]) => list(...a),
    update: (...a: unknown[]) => update(...a),
    remove: vi.fn(),
    promote: vi.fn(),
  },
}));

vi.mock("@/lib/api", () => ({
  __esModule: true,
  default: { get: vi.fn(async () => ({ data: [] })) },
}));

const showError = vi.fn();
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showSuccess: vi.fn(), showError }),
}));

import { JobShortlist, jobShortlistQueryKey } from "@/components/v2/jobs/JobShortlist";

function entry(over: Partial<ShortlistEntry> = {}): ShortlistEntry {
  return {
    id: 1,
    job_id: 10,
    candidate_id: 5,
    candidate_name: "Anna",
    candidate_lastname: "Kowalska",
    evaluation_status: "do_oceny",
    outreach_status: "nie_kontaktowano",
    version: 1,
    note: "stara notatka",
    next_action_at: null,
    ...over,
  } as ShortlistEntry;
}

function renderShortlist() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <JobShortlist jobId={10} />
    </QueryClientProvider>,
  );
  return qc;
}

async function refetchAs(qc: QueryClient, next: ShortlistEntry) {
  list.mockResolvedValue([next]);
  await act(async () => {
    await qc.invalidateQueries({ queryKey: jobShortlistQueryKey(10) });
  });
}

describe("JobShortlist — pola zsynchronizowane z serwerem", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    update.mockResolvedValue(entry({ version: 2 }));
  });

  it("zmiana kolegi pojawia się w polu, a blur bez zmiany NIE zapisuje starego tekstu", async () => {
    list.mockResolvedValue([entry()]);
    const qc = renderShortlist();
    const note = (await screen.findByLabelText(
      "Notatka: Anna Kowalska",
    )) as HTMLInputElement;
    expect(note.value).toBe("stara notatka");

    await refetchAs(qc, entry({ version: 2, note: "nowsza notatka kolegi" }));
    await waitFor(() => expect(note.value).toBe("nowsza notatka kolegi"));

    fireEvent.focus(note);
    fireEvent.blur(note);
    expect(update).not.toHaveBeenCalled();
  });

  it("zmiana użytkownika idzie z wersją, od której ZACZĄŁ edycję — serwer odpowie 409 zamiast nadpisać", async () => {
    list.mockResolvedValue([entry()]);
    const qc = renderShortlist();
    const note = (await screen.findByLabelText(
      "Notatka: Anna Kowalska",
    )) as HTMLInputElement;

    fireEvent.focus(note);
    fireEvent.change(note, { target: { value: "moja poprawka" } });
    // W trakcie edycji ktoś zapisał wpis — pole NIE przeskakuje pod palcami.
    await refetchAs(qc, entry({ version: 2, note: "nowsza notatka kolegi" }));
    expect(note.value).toBe("moja poprawka");

    fireEvent.blur(note);
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    expect(update).toHaveBeenCalledWith(1, { version: 1, note: "moja poprawka" });
  });

  it("termin: blur bez zmiany nie zapisuje, zmiana zapisuje ISO z wersją bazową", async () => {
    list.mockResolvedValue([entry({ next_action_at: "2026-09-20T08:00:00.000Z" })]);
    renderShortlist();
    const deadline = (await screen.findByLabelText(
      "Termin następnej akcji: Anna Kowalska",
    )) as HTMLInputElement;

    fireEvent.focus(deadline);
    fireEvent.blur(deadline);
    expect(update).not.toHaveBeenCalled();

    fireEvent.focus(deadline);
    fireEvent.change(deadline, { target: { value: "2026-09-25T10:30" } });
    fireEvent.blur(deadline);
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
    expect(update).toHaveBeenCalledWith(1, {
      version: 1,
      next_action_at: new Date("2026-09-25T10:30").toISOString(),
    });
  });
});
