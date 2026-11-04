/**
 * Powód zamknięcia w nagłówku zamkniętej rekrutacji: krótka plakietka,
 * pełny powód i grupa hit ratio w dymku. Gdy obok stoi status „Zamknięta”,
 * plakietka go nie powtarza (28.10.2026).
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { JobCloseReasonBadge } from "@/components/v2/jobs/JobCloseReasonBadge";

const badge = () => screen.getByTestId("job-close-reason-badge");

describe("JobCloseReasonBadge", () => {
  it("bez statusu obok mówi „Zamknięta · powód”", () => {
    render(<JobCloseReasonBadge reason="competitor" />);
    expect(badge()).toHaveTextContent("Zamknięta · wzięła inna firma");
  });

  it("ze statusem „Zamknięta” obok mówi sam powód, bez drugiego „Zamknięta”", () => {
    render(<JobCloseReasonBadge reason="competitor" statusShown />);
    expect(badge()).toHaveTextContent(/^Wzięła inna firma$/);
    expect(badge().textContent).not.toMatch(/Zamknięta/);
  });

  it("dymek ma pełny powód, grupę hit ratio i uzasadnienie także bez „Zamknięta” w tekście", () => {
    render(
      <JobCloseReasonBadge reason="competitor" notes="Klient wybrał tańszą ofertę." statusShown />,
    );
    expect(badge()).toHaveAttribute(
      "title",
      "Klient wybrał kandydata innej firmy\nLiczy się do hit ratio jako przegrana.\nKlient wybrał tańszą ofertę.",
    );
  });

  it("brak powodu = „Powód do przejrzenia” jak przegrana", () => {
    render(<JobCloseReasonBadge reason={null} statusShown />);
    expect(badge()).toHaveTextContent(/^Powód do przejrzenia$/);
    expect(badge().getAttribute("title")).toContain(
      "Liczy się jak przegrana, dopóki ktoś nie wybierze powodu.",
    );
  });

  it("neutralny powód mówi, że nie liczy się do hit ratio", () => {
    render(<JobCloseReasonBadge reason="duplicate" statusShown />);
    expect(badge()).toHaveTextContent(/^Duplikat$/);
    expect(badge().getAttribute("title")).toContain("Nie liczy się do hit ratio.");
  });
});
