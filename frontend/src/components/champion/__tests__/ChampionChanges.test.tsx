/**
 * „Co się zmieniło w Profilu Championa” (17.11.2026): karta nad Briefem,
 * zakładka „Zmiany” i okno DL po zapisie. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ChampionChangeNoteHost,
  ChampionChangesCard,
  ChampionChangesTimeline,
  emitChampionChangeRecorded,
  unseenRevisions,
} from "@/components/champion/ChampionChanges";
import type { ChampionChangesResponse, ChampionProfileRevision } from "@/lib/api";

const changesMock = vi.fn();
const seenMock = vi.fn();
const noteMock = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    championApi: {
      ...actual.championApi,
      changes: (...args: unknown[]) => changesMock(...args),
      markChangesSeen: (...args: unknown[]) => seenMock(...args),
      setChangeNote: (...args: unknown[]) => noteMock(...args),
    },
  };
});

const JOB_ID = 7;
const daysAgo = (n: number) => new Date(Date.now() - n * 86_400_000).toISOString();

function revision(over: Partial<ChampionProfileRevision> = {}): ChampionProfileRevision {
  return {
    id: 11,
    created_at: daysAgo(1),
    author_id: 5,
    author_name: "Delivery Lead Przykładowy",
    note: "Najważniejsze są integracje i SQL.",
    changes: [
      { kind: "removed", text: "wzorce projektowe", detail: "usunięte z „Musi mieć”" },
      { kind: "moved", text: "Kafka", detail: "„Musi mieć” → „Mile widziane”" },
    ],
    mine: false,
    ...over,
  };
}

function response(
  revisions: ChampionProfileRevision[],
  lastSeen: number | null = null,
): { data: ChampionChangesResponse } {
  return { data: { job_id: JOB_ID, revisions, last_seen_revision_id: lastSeen } };
}

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  changesMock.mockReset();
  seenMock.mockReset();
  noteMock.mockReset();
});

describe("unseenRevisions", () => {
  it("pomija przeczytane i własne zmiany", () => {
    const data = response([
      revision({ id: 13 }),
      revision({ id: 12, mine: true }),
      revision({ id: 10 }),
    ], 10).data;
    expect(unseenRevisions(data).map((r) => r.id)).toEqual([13]);
  });
});

describe("ChampionChangesCard", () => {
  it("pokazuje nową zmianę ze zdaniem DL i po „Przeczytane” zwija się do linii", async () => {
    changesMock.mockResolvedValue(response([revision()]));
    seenMock.mockResolvedValue({ data: { last_seen_revision_id: 11 } });
    const onOpen = vi.fn();
    wrap(<ChampionChangesCard jobId={JOB_ID} onOpenChanges={onOpen} />);

    const card = await screen.findByTestId("champion-changes-card");
    expect(card).toHaveTextContent("Na co klient kładzie nacisk: Najważniejsze są integracje i SQL.");
    expect(card).toHaveTextContent("wzorce projektowe — usunięte z „Musi mieć”");

    await userEvent.click(screen.getByTestId("champion-changes-seen"));
    expect(seenMock).toHaveBeenCalledWith(JOB_ID, 11);
    const line = await screen.findByTestId("champion-changes-line");
    expect(line).toHaveTextContent("przeczytane");
    await userEvent.click(screen.getByRole("button", { name: /Wszystkie zmiany/ }));
    expect(onOpen).toHaveBeenCalled();
  });

  it("nic nie pokazuje bez zmian, po 14 dniach od przeczytanej i przy awarii zapytania", async () => {
    changesMock.mockResolvedValueOnce(response([]));
    const empty = wrap(<ChampionChangesCard jobId={JOB_ID} onOpenChanges={vi.fn()} />);
    await waitFor(() => expect(changesMock).toHaveBeenCalledTimes(1));
    expect(empty.container).toBeEmptyDOMElement();
    empty.unmount();

    changesMock.mockResolvedValueOnce(response([revision({ created_at: daysAgo(20) })], 11));
    const old = wrap(<ChampionChangesCard jobId={JOB_ID} onOpenChanges={vi.fn()} />);
    await waitFor(() => expect(changesMock).toHaveBeenCalledTimes(2));
    expect(old.container).toBeEmptyDOMElement();
    old.unmount();

    changesMock.mockRejectedValueOnce(new Error("boom"));
    const failed = wrap(<ChampionChangesCard jobId={JOB_ID} onOpenChanges={vi.fn()} />);
    await waitFor(() => expect(changesMock).toHaveBeenCalledTimes(3));
    expect(failed.container).toBeEmptyDOMElement();
  });

  it("własna zmiana autora nie jest dla niego „nowa”", async () => {
    changesMock.mockResolvedValue(response([revision({ mine: true })]));
    wrap(<ChampionChangesCard jobId={JOB_ID} onOpenChanges={vi.fn()} />);
    expect(await screen.findByTestId("champion-changes-line")).toHaveTextContent("Twoja zmiana");
    expect(screen.queryByTestId("champion-changes-card")).toBeNull();
  });
});

describe("ChampionChangesTimeline", () => {
  it("pokazuje historię z oznaczeniem nowych", async () => {
    changesMock.mockResolvedValue(
      response([revision({ id: 12 }), revision({ id: 11, note: null })], 11),
    );
    wrap(<ChampionChangesTimeline jobId={JOB_ID} />);
    const timeline = await screen.findByTestId("champion-changes-timeline");
    expect(timeline.querySelectorAll("li section")).toHaveLength(2);
    expect(screen.getAllByText("nowe dla Ciebie")).toHaveLength(1);
  });

  it("pusta historia to zdanie, a awaria to komunikat błędu, nie pusta lista", async () => {
    changesMock.mockResolvedValueOnce(response([]));
    const empty = wrap(<ChampionChangesTimeline jobId={JOB_ID} />);
    expect(await screen.findByTestId("champion-changes-empty")).toBeInTheDocument();
    empty.unmount();

    changesMock.mockRejectedValueOnce(new Error("boom"));
    wrap(<ChampionChangesTimeline jobId={JOB_ID} />);
    await waitFor(() => expect(screen.queryByTestId("champion-changes-empty")).toBeNull());
    await waitFor(() => expect(screen.queryByTestId("champion-changes-timeline")).toBeNull());
    expect(await screen.findByRole("button", { name: /Spróbuj|Ponów|Odśwież/i })).toBeInTheDocument();
  });
});

describe("ChampionChangeNoteHost", () => {
  it("otwiera się po zapisie tej rekrutacji i zapisuje zdanie", async () => {
    noteMock.mockResolvedValue({ data: revision() });
    wrap(<ChampionChangeNoteHost jobId={JOB_ID} />);
    expect(screen.queryByTestId("champion-change-note-dialog")).toBeNull();

    act(() => {
      emitChampionChangeRecorded({ jobId: 999, revision: { id: 1, changes: [] } });
    });
    expect(screen.queryByTestId("champion-change-note-dialog")).toBeNull();

    act(() => {
      emitChampionChangeRecorded({ jobId: JOB_ID, revision: { id: 11, changes: revision().changes } });
    });
    expect(await screen.findByTestId("champion-change-note-dialog")).toHaveTextContent("Kafka");
    const save = screen.getByTestId("champion-change-note-save");
    expect(save).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Na co klient teraz kładzie nacisk?"), "Liczy się SQL.");
    await userEvent.click(save);
    expect(noteMock).toHaveBeenCalledWith(JOB_ID, 11, "Liczy się SQL.");
    await waitFor(() => expect(screen.queryByTestId("champion-change-note-dialog")).toBeNull());
  });

  it("„Pomiń” zamyka okno bez zapisu", async () => {
    wrap(<ChampionChangeNoteHost jobId={JOB_ID} />);
    act(() => {
      emitChampionChangeRecorded({ jobId: JOB_ID, revision: { id: 11, changes: revision().changes } });
    });
    await userEvent.click(await screen.findByRole("button", { name: "Pomiń" }));
    expect(noteMock).not.toHaveBeenCalled();
    expect(screen.queryByTestId("champion-change-note-dialog")).toBeNull();
  });
});
