import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { JobIdleBanner } from "@/components/v2/jobs/JobIdleBanner";
import type { JobIdle } from "@/lib/job-idle-api";

const base: JobIdle = {
  stage: "remind",
  days: 16,
  last_move_at: "2026-07-15T10:00:00+00:00",
  last_move_kind: "cv",
  hor_on: "2026-11-05",
  close_on: "2026-11-12",
  snooze_count: 0,
};

describe("JobIdleBanner", () => {
  it("mówi, od kiedy cisza, kiedy HoR i kiedy zamknięcie; dwa przyciski", () => {
    const onClose = vi.fn();
    const onSnooze = vi.fn();
    render(<JobIdleBanner idle={base} onClose={onClose} onSnooze={onSnooze} />);
    const bar = screen.getByRole("status");
    expect(bar).toHaveTextContent(
      "Bez ruchu od 16 dni: ostatnie CV do klienta 15.07, bez odpowiedzi.",
    );
    expect(bar).toHaveTextContent(
      "Jeśli nic się nie zmieni, 05.11 dostanie to Head of Recruitment, a 12.11 NEXUS zamknie rekrutację jako przegraną.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Zamknij…" }));
    fireEvent.click(screen.getByRole("button", { name: "Jeszcze trwa" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onSnooze).toHaveBeenCalledTimes(1);
  });

  it("po 21 dniach nie wspomina już o HoR, a bez CV mówi to wprost", () => {
    render(
      <JobIdleBanner
        idle={{ ...base, stage: "hor", days: 23, last_move_at: null, last_move_kind: null }}
        onClose={() => {}}
        onSnooze={() => {}}
      />,
    );
    const bar = screen.getByRole("status");
    expect(bar).toHaveTextContent("Bez ruchu od 23 dni: żadnego CV do klienta.");
    expect(bar).toHaveTextContent("Jeśli nic się nie zmieni, 12.11 NEXUS zamknie");
    expect(bar).not.toHaveTextContent("Head of Recruitment");
  });

  it("odpowiedź klienta i etap zamknięcia", () => {
    render(
      <JobIdleBanner
        idle={{ ...base, stage: "close", days: 30, last_move_kind: "client" }}
        onClose={() => {}}
        onSnooze={() => {}}
        snoozing
      />,
    );
    const bar = screen.getByRole("status");
    expect(bar).toHaveTextContent("ostatnia odpowiedź klienta 15.07");
    expect(bar).toHaveTextContent("przy najbliższym przeglądzie");
    expect(screen.getByRole("button", { name: "Zapisuję…" })).toBeDisabled();
  });

  it("poniżej 14 dni i bez danych nie ma paska", () => {
    const { container, rerender } = render(
      <JobIdleBanner idle={{ ...base, stage: null }} onClose={() => {}} onSnooze={() => {}} />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<JobIdleBanner idle={undefined} onClose={() => {}} onSnooze={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });
});
