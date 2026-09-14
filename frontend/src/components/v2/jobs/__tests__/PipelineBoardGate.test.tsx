import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PipelineBoardGate } from "../PipelineBoardGate";

describe("PipelineBoardGate (UAT A-B01)", () => {
  it("forbidden says access is missing instead of rendering an empty board", () => {
    render(
      <PipelineBoardGate state="forbidden" hasData={false} onRetry={vi.fn()}>
        <div>Brak kolumn w tej kategorii.</div>
      </PipelineBoardGate>,
    );

    expect(screen.queryByText("Brak kolumn w tej kategorii.")).toBeNull();
    expect(
      screen.getByText(/nie masz dostępu do tablicy kandydatów tej rekrutacji/i),
    ).toBeInTheDocument();
  });

  it("server error does not render the board either", () => {
    render(
      <PipelineBoardGate state="error" hasData={false} onRetry={vi.fn()}>
        <div>tablica</div>
      </PipelineBoardGate>,
    );

    expect(screen.queryByText("tablica")).toBeNull();
  });

  it("failed background refresh keeps the loaded board and offers a retry", () => {
    render(
      <PipelineBoardGate state="error" hasData onRetry={vi.fn()}>
        <div>tablica</div>
      </PipelineBoardGate>,
    );

    expect(screen.getByText("tablica")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      /nie udało się odświeżyć tablicy/i,
    );
  });

  it("ready renders the board", () => {
    render(
      <PipelineBoardGate state="ready" hasData onRetry={vi.fn()}>
        <div>tablica</div>
      </PipelineBoardGate>,
    );

    expect(screen.getByText("tablica")).toBeInTheDocument();
  });
});
