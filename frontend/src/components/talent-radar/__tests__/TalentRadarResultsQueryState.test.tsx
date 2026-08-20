/**
 * Radar: awaria wyszukiwania ≠ ekran startowy (audyt F-20).
 *
 * Workspace przy błędzie robił `setResponse(null)` i zgłaszał go WYŁĄCZNIE
 * toastem. Po zniknięciu toasta zostawało „Zacznij od wklejenia requestu” —
 * zdanie o tym, że rekruter jeszcze nic nie zrobił, w sytuacji, w której
 * zrobił i to serwer nie odpowiedział.
 */
import * as React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

import { TalentRadarResults } from "@/components/talent-radar/TalentRadarResults";

const START_SCREEN = "Zacznij od wklejenia requestu";

function httpError(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status } });
}

describe("TalentRadarResults — awaria zapytania", () => {
  it("500 renderuje awarię zamiast ekranu startowego", () => {
    render(
      <TalentRadarResults
        meta={null}
        results={[]}
        pending={false}
        error={httpError(500)}
      />,
    );

    expect(
      screen.getByText("Wyszukiwanie nie doszło do skutku"),
    ).toBeInTheDocument();
    expect(screen.getByText(/nie znaczy, że nikt nie pasuje/)).toBeInTheDocument();
    expect(screen.queryByText(START_SCREEN)).not.toBeInTheDocument();
  });

  it("brak sieci mówi o połączeniu, nie o serwerze", () => {
    render(
      <TalentRadarResults
        meta={null}
        results={[]}
        pending={false}
        error={new Error("Network Error")}
      />,
    );

    expect(
      screen.getByText(/Nie udało się połączyć z serwerem/),
    ).toBeInTheDocument();
    expect(screen.queryByText(START_SCREEN)).not.toBeInTheDocument();
  });

  it("403 to inne zdanie niż awaria i nie proponuje ponowienia", () => {
    const onRetry = vi.fn();
    render(
      <TalentRadarResults
        meta={null}
        results={[]}
        pending={false}
        error={httpError(403)}
        onRetry={onRetry}
      />,
    );

    expect(
      screen.getByText("Brak uprawnień do tego wyszukiwania"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Spróbuj ponownie/ }),
    ).not.toBeInTheDocument();
  });

  it("bez błędu ekran startowy dalej działa", () => {
    render(<TalentRadarResults meta={null} results={[]} pending={false} />);

    expect(screen.getByText(START_SCREEN)).toBeInTheDocument();
  });
});
