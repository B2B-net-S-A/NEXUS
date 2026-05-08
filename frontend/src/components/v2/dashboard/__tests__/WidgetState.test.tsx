import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { WidgetState, WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState";

describe("WidgetState", () => {
  it("renders loading fallback when isLoading is true", () => {
    render(
      <WidgetState
        isLoading
        isError={false}
        loadingFallback={<div data-testid="skeleton">loading…</div>}
      >
        <div>data</div>
      </WidgetState>
    );
    expect(screen.getByTestId("skeleton")).toBeInTheDocument();
    expect(screen.queryByText("data")).not.toBeInTheDocument();
  });

  it("renders default error state when isError is true and no errorFallback", () => {
    render(
      <WidgetState
        isLoading={false}
        isError
        loadingFallback={<div>loading…</div>}
      >
        <div>data</div>
      </WidgetState>
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(
      screen.getByText("Nie udało się załadować danych.")
    ).toBeInTheDocument();
    expect(screen.queryByText("data")).not.toBeInTheDocument();
  });

  it("renders custom errorFallback when provided", () => {
    render(
      <WidgetState
        isLoading={false}
        isError
        loadingFallback={null}
        errorFallback={<div data-testid="custom-error">custom</div>}
      >
        <div>data</div>
      </WidgetState>
    );
    expect(screen.getByTestId("custom-error")).toBeInTheDocument();
    expect(screen.queryByText("data")).not.toBeInTheDocument();
  });

  it("renders emptyFallback when isEmpty is true and not loading/erroring", () => {
    render(
      <WidgetState
        isLoading={false}
        isError={false}
        isEmpty
        loadingFallback={null}
        emptyFallback={<div data-testid="empty">empty</div>}
      >
        <div>data</div>
      </WidgetState>
    );
    expect(screen.getByTestId("empty")).toBeInTheDocument();
    expect(screen.queryByText("data")).not.toBeInTheDocument();
  });

  it("renders children when not loading, erroring, or empty", () => {
    render(
      <WidgetState
        isLoading={false}
        isError={false}
        loadingFallback={null}
      >
        <div data-testid="data">data</div>
      </WidgetState>
    );
    expect(screen.getByTestId("data")).toBeInTheDocument();
  });

  it("calls onRetry when retry button clicked in default error state", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(
      <WidgetState
        isLoading={false}
        isError
        onRetry={onRetry}
        loadingFallback={null}
      >
        <div>data</div>
      </WidgetState>
    );
    await user.click(screen.getByRole("button", { name: /Spróbuj ponownie/ }));
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("loading takes precedence over error", () => {
    render(
      <WidgetState
        isLoading
        isError
        loadingFallback={<div data-testid="skeleton">loading</div>}
      >
        <div>data</div>
      </WidgetState>
    );
    expect(screen.getByTestId("skeleton")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("error takes precedence over empty", () => {
    render(
      <WidgetState
        isLoading={false}
        isError
        isEmpty
        loadingFallback={null}
        emptyFallback={<div data-testid="empty">empty</div>}
      >
        <div>data</div>
      </WidgetState>
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByTestId("empty")).not.toBeInTheDocument();
  });
});

describe("WidgetErrorBlock", () => {
  it("translates 403 errors to a permissions message", () => {
    render(<WidgetErrorBlock error={{ response: { status: 403 } }} />);
    expect(screen.getByText("Brak uprawnień do tego widoku.")).toBeInTheDocument();
  });

  it("translates 404 errors to a not-found message", () => {
    render(<WidgetErrorBlock error={{ response: { status: 404 } }} />);
    expect(screen.getByText("Nie znaleziono danych.")).toBeInTheDocument();
  });

  it("translates 5xx errors to a server-error message", () => {
    render(<WidgetErrorBlock error={{ response: { status: 500 } }} />);
    expect(
      screen.getByText("Błąd serwera. Spróbuj ponownie za chwilę.")
    ).toBeInTheDocument();
  });

  it("falls back to generic message when no error provided", () => {
    render(<WidgetErrorBlock />);
    expect(screen.getByText("Spróbuj ponownie za chwilę.")).toBeInTheDocument();
  });

  it("uses custom title when provided", () => {
    render(<WidgetErrorBlock title="Custom title" />);
    expect(screen.getByText("Custom title")).toBeInTheDocument();
  });

  it("hides retry button when no onRetry provided", () => {
    render(<WidgetErrorBlock />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
