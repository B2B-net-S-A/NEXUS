import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ClosedJobWaitingBanner } from "@/components/v2/jobs/ClosedJobWaitingBanner";

describe("ClosedJobWaitingBanner", () => {
  it("mówi, kiedy i dlaczego zamknięto, wymienia osoby i otwiera odrzucenie pierwszej", () => {
    const onRejectFirst = vi.fn();
    render(
      <ClosedJobWaitingBanner
        closedOn="19.10"
        reasonLabel="Klient wybrał kandydata innej firmy"
        people={["Osoba Pierwsza", "Osoba Druga"]}
        onRejectFirst={onRejectFirst}
      />,
    );
    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent("Rekrutacja zamknięta · 19.10 · Klient wybrał kandydata innej firmy");
    expect(banner).toHaveTextContent("Twoje osoby nadal są w procesie (2): Osoba Pierwsza, Osoba Druga.");
    fireEvent.click(screen.getByRole("button", { name: "Odrzuć i napisz: Osoba Pierwsza" }));
    expect(onRejectFirst).toHaveBeenCalledTimes(1);
  });

  it("bez osób nie ma paska, bez uprawnień nie ma przycisku", () => {
    const { container, rerender } = render(
      <ClosedJobWaitingBanner closedOn={null} reasonLabel={null} people={[]} />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<ClosedJobWaitingBanner closedOn={null} reasonLabel={null} people={["A B"]} />);
    expect(screen.getByRole("status")).toHaveTextContent("Twoja osoba nadal jest w procesie: A B.");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("długą listę skraca", () => {
    render(
      <ClosedJobWaitingBanner
        closedOn={null}
        reasonLabel={null}
        people={["O1", "O2", "O3", "O4", "O5", "O6", "O7", "O8"]}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("O6 i 2 innych.");
  });
});
