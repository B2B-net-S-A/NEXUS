/**
 * Zakładka „Przegląd” (04.10.2026): „Teraz” (zaległy telefon, procesy
 * w toku z tym, kto ma ruch) i „Ostatnia rozmowa”.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const followup = vi.hoisted(() => ({ data: undefined as unknown }));
vi.mock("@/lib/api/candidateFollowups", () => ({
  useCandidateFollowup: () => ({ data: followup.data }),
}));
vi.mock("@/components/v2/followups/CandidateFollowupDialog", () => ({
  CandidateFollowupDialog: () => <div role="dialog" aria-label="Follow-up" />,
}));

import { ProfileTab, type ProfileTabProps } from "../ProfileTab";

const HISTORY = [
  {
    job_id: 10,
    job_title: "Java Developer",
    client_name: "Bank X",
    job_status: "published",
    latest_stage: "cv_sent",
    latest_stage_name: "CV wysłane",
    last_seen: new Date(Date.now() - 4 * 86_400_000).toISOString(),
    next_action_owner: "client",
  },
  {
    job_id: 11,
    job_title: "Stara rekrutacja",
    client_name: "Bank Y",
    job_status: "closed",
    latest_stage: "rejected",
    next_action_owner: null,
  },
];

const NOTES = [
  {
    id: 1,
    group: "talks",
    content: "Przypięta, stara rozmowa",
    pinned_at: "2026-09-02T10:00:00Z",
    created_at: "2026-09-01T10:00:00Z",
    author_name: "Ola K",
  },
  {
    id: 2,
    group: "talks",
    content: "Szuka projektu od listopada.",
    created_at: "2026-09-28T10:00:00Z",
    author_name: "Marta Testowa",
    job_title: "Java Developer",
  },
];

function renderTab(overrides: Partial<ProfileTabProps> = {}) {
  const onNavigate = vi.fn();
  render(
    <ProfileTab
      candidate={{ id: 42 }}
      readOnly={false}
      recruitments={{ items: HISTORY, isPending: false, isError: false, refetch: vi.fn() }}
      notes={{
        items: NOTES,
        groupCounts: { talks: 2, contact: 3 },
        isPending: false,
        isError: false,
        refetch: vi.fn(),
      }}
      onNavigate={onNavigate}
      {...overrides}
    />,
  );
  return { onNavigate };
}

beforeEach(() => {
  followup.data = undefined;
});

describe("Przegląd — Teraz", () => {
  it("pokazuje tylko procesy w toku, z etapem, właścicielem ruchu i linkiem do Tablicy", () => {
    renderTab();
    const list = screen.getByTestId("now-recruitments");
    const row = within(list).getByText("Java Developer").closest("li")!;
    expect(row).toHaveTextContent("Bank X");
    expect(row).toHaveTextContent("ruch: klient · 4 dni");
    expect(within(row).getByRole("link", { name: /Tablica/ })).toHaveAttribute(
      "href",
      "/jobs/10?candidate=42",
    );
    expect(within(list).queryByText("Stara rekrutacja")).toBeNull();
  });

  it("bez procesów w toku mówi to zdaniem i prowadzi do zakończonych", async () => {
    const user = userEvent.setup();
    const { onNavigate } = renderTab({
      recruitments: { items: [HISTORY[1]], isPending: false, isError: false, refetch: vi.fn() },
    });
    expect(screen.getByText(/Nie jest teraz w żadnej rekrutacji/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zakończone rekrutacje (1)" }));
    expect(onNavigate).toHaveBeenCalledWith({ section: "recruitments" });
  });

  it("awaria historii to komunikat z „Ponów”, nie „brak rekrutacji”", () => {
    renderTab({
      recruitments: { items: [], isPending: false, isError: true, refetch: vi.fn() },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Nie udało się wczytać rekrutacji.");
    expect(screen.queryByText(/Nie jest teraz/)).toBeNull();
  });

  it("zaległy telefon po ciszy klienta otwiera zapis wyniku", async () => {
    followup.data = {
      followup: {
        state: "overdue",
        overdue_days: 3,
        due_on: "2026-10-01",
        caller_name: "Anna Kowalczyk",
        processes: [{}, {}],
      },
    };
    const user = userEvent.setup();
    renderTab();
    const callout = screen.getByTestId("now-followup");
    expect(callout).toHaveTextContent("Telefon po ciszy klienta: zaległy 3 dni");
    expect(callout).toHaveTextContent("dzwoni Anna K.");
    await user.click(within(callout).getByRole("button", { name: "Zapisz wynik telefonu" }));
    expect(screen.getByRole("dialog", { name: "Follow-up" })).toBeInTheDocument();
  });
});

describe("Przegląd — Ostatnia rozmowa", () => {
  it("pokazuje najnowszą rozmowę (nie przypiętą) i liczbę prób kontaktu", async () => {
    const user = userEvent.setup();
    const { onNavigate } = renderTab();
    const card = screen.getByTestId("last-talk");
    expect(card).toHaveTextContent("Szuka projektu od listopada.");
    expect(card).toHaveTextContent("Marta Testowa");
    expect(screen.getByText(/Prób kontaktu: 3/)).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Otwórz notatkę" }));
    expect(onNavigate).toHaveBeenCalledWith({ section: "activity", noteId: 2 });
  });

  it("bez rozmów mówi to zdaniem", () => {
    renderTab({
      notes: { items: [], groupCounts: {}, isPending: false, isError: false, refetch: vi.fn() },
    });
    expect(screen.getByText("Nikt jeszcze nie zapisał rozmowy z tą osobą.")).toBeInTheDocument();
  });
});
