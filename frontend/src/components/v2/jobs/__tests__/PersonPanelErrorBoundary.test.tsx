import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PersonPanelErrorBoundary } from "@/components/v2/jobs/PersonPanelErrorBoundary";

const mocks = vi.hoisted(() => ({ captureException: vi.fn() }));

vi.mock("@sentry/nextjs", () => ({
  captureException: (...args: unknown[]) => mocks.captureException(...args),
}));

let shouldThrow = true;

function Panel() {
  if (shouldThrow) throw new Error("pętla w panelu");
  return <p>Treść panelu</p>;
}

describe("PersonPanelErrorBoundary", () => {
  beforeEach(() => {
    shouldThrow = true;
    mocks.captureException.mockReset();
    // React loguje złapany błąd na konsolę — w teście to szum.
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("wyjątek w panelu zostaje w panelu i idzie do Sentry ze stosem komponentów", () => {
    render(
      <div>
        <p>Tablica</p>
        <PersonPanelErrorBoundary onClose={() => {}}>
          <Panel />
        </PersonPanelErrorBoundary>
      </div>,
    );

    expect(screen.getByText("Tablica")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Panel osoby się zawiesił");
    expect(mocks.captureException).toHaveBeenCalledTimes(1);
    const [error, options] = mocks.captureException.mock.calls[0];
    expect((error as Error).message).toBe("pętla w panelu");
    expect(options.tags).toEqual({ boundary: "person-panel" });
    expect(options.contexts.react.componentStack).toContain("Panel");
  });

  it("„Otwórz panel ponownie” renderuje panel od nowa", () => {
    render(
      <PersonPanelErrorBoundary onClose={() => {}}>
        <Panel />
      </PersonPanelErrorBoundary>,
    );

    shouldThrow = false;
    fireEvent.click(screen.getByRole("button", { name: /Otwórz panel ponownie/ }));

    expect(screen.getByText("Treść panelu")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("„Zamknij panel” woła onClose", () => {
    const onClose = vi.fn();
    render(
      <PersonPanelErrorBoundary onClose={onClose}>
        <Panel />
      </PersonPanelErrorBoundary>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Zamknij panel" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
