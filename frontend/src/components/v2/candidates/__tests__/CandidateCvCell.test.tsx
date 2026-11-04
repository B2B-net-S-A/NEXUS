import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CandidateCvCell } from "@/components/v2/candidates/CandidateCvCell";

describe("CandidateCvCell — otwarcie CV i ślad oglądania", () => {
  it("klik otwiera okno listy i nie przechodzi do wiersza", () => {
    const onOpen = vi.fn();
    const onRow = vi.fn();
    render(
      <div onClick={onRow}>
        <CandidateCvCell candidateName="Marta Kowalczyk" hasCv onOpen={onOpen} />
      </div>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Podgląd CV: Marta Kowalczyk" }));

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onRow).not.toHaveBeenCalled();
  });

  it("obejrzane CV: przycisk mówi, o której; nieobejrzane zostaje bez dopisku", () => {
    const seenAt = new Date(2026, 9, 23, 12, 27).getTime();
    const { rerender } = render(
      <CandidateCvCell candidateName="Marta Kowalczyk" hasCv seenAt={seenAt} onOpen={vi.fn()} />,
    );

    expect(
      screen.getByRole("button", { name: "Podgląd CV: Marta Kowalczyk (oglądane o 12:27)" }),
    ).toHaveAttribute("title", "Oglądałeś to CV dziś o 12:27");

    rerender(<CandidateCvCell candidateName="Marta Kowalczyk" hasCv seenAt={null} onOpen={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Podgląd CV: Marta Kowalczyk" })).not.toHaveAttribute(
      "title",
    );
  });

  it("w trakcie wczytywania przycisk jest zablokowany, a bez CV jest „brak”", () => {
    const { rerender } = render(
      <CandidateCvCell candidateName="Marta Kowalczyk" hasCv loading onOpen={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "Podgląd CV: Marta Kowalczyk" })).toBeDisabled();

    rerender(<CandidateCvCell candidateName="Marta Kowalczyk" hasCv={false} onOpen={vi.fn()} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText("brak")).toBeTruthy();
  });
});
