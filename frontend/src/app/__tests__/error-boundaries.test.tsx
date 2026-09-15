import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ErrorPage from "@/app/error";
import GlobalError from "@/app/global-error";

const mocks = vi.hoisted(() => ({
  captureException: vi.fn(),
  reloadOnceForChunkError: vi.fn(),
}));

vi.mock("@sentry/nextjs", () => ({
  captureException: (...args: unknown[]) => mocks.captureException(...args),
}));

vi.mock("@/lib/chunk-reload", () => ({
  reloadOnceForChunkError: (...args: unknown[]) =>
    mocks.reloadOnceForChunkError(...args),
}));

type BoundaryError = Error & { digest?: string };

function makeError(message: string, digest?: string): BoundaryError {
  const error: BoundaryError = new Error(message);
  if (digest) error.digest = digest;
  return error;
}

/*
 * global-error renderuje własne <html>/<body>. React 19 obsługuje je jako
 * singletony dokumentu, więc montujemy komponent w `document` — tak jak robi
 * to Next przy awarii root layoutu — zamiast wsadzać <html> do <div>.
 *
 * React oznacza `document` znacznikiem „nasłuchuje” już przy pierwszym roocie
 * w <div> (tylko dla selectionchange), a root założony później na `document`
 * widzi znacznik i nie podpina delegowanych zdarzeń — kliknięcia by nie
 * działały. W Next to jedyny root, więc to artefakt wyłącznie środowiska
 * testowego; zdejmujemy znacznik RAZ, żeby root dostał zdarzenia jak
 * w przeglądarce. Listenery na `document` zostają po odmontowaniu, więc
 * ponowne zdjęcie znacznika zdublowałoby je (jedno kliknięcie = N wywołań).
 */
let documentListenersAttached = false;

function resetReactListeningMarker() {
  if (documentListenersAttached) return;
  documentListenersAttached = true;
  const doc = document as unknown as Record<string, unknown>;
  for (const key of Object.keys(doc)) {
    if (key.startsWith("_reactListening")) delete doc[key];
  }
}

function renderGlobal(error: BoundaryError, reset = vi.fn()) {
  resetReactListeningMarker();
  const utils = render(<GlobalError error={error} reset={reset} />, {
    container: document,
  });
  return { ...utils, view: screen, reset };
}

function renderApp(error: BoundaryError, reset = vi.fn()) {
  const utils = render(<ErrorPage error={error} reset={reset} />);
  return { ...utils, view: screen, reset };
}

const boundaries = [
  {
    name: "app/error.tsx",
    boundary: "app-router",
    retryLabel: "Spróbuj ponownie",
    heading: "Coś poszło nie tak",
    renderBoundary: renderApp,
  },
  {
    name: "app/global-error.tsx",
    boundary: "global",
    retryLabel: "Odśwież",
    heading: "Aplikacja nie odpowiada",
    renderBoundary: renderGlobal,
  },
] as const;

beforeEach(() => {
  mocks.captureException.mockReset();
  mocks.reloadOnceForChunkError.mockReset();
});

describe.each(boundaries)("$name", ({ boundary, retryLabel, heading, renderBoundary }) => {
  it("błąd chunka: przeładowuje raz i nie raportuje do Sentry", () => {
    mocks.reloadOnceForChunkError.mockReturnValue(true);
    const error = makeError("Loading chunk 123 failed.");

    renderBoundary(error);

    expect(mocks.reloadOnceForChunkError).toHaveBeenCalledTimes(1);
    expect(mocks.reloadOnceForChunkError).toHaveBeenCalledWith(error);
    expect(mocks.captureException).not.toHaveBeenCalled();
  });

  it("inny błąd: raportuje do Sentry z tagiem granicy i digestem", () => {
    mocks.reloadOnceForChunkError.mockReturnValue(false);
    const error = makeError("boom", "digest-abc");

    const { view } = renderBoundary(error);

    expect(view.getByRole("heading", { name: heading })).toBeInTheDocument();
    expect(mocks.captureException).toHaveBeenCalledTimes(1);
    expect(mocks.captureException).toHaveBeenCalledWith(error, {
      tags: { boundary, digest: "digest-abc" },
    });
  });

  it("brak digestu → tag 'unknown'", () => {
    mocks.reloadOnceForChunkError.mockReturnValue(false);
    const error = makeError("boom");

    renderBoundary(error);

    expect(mocks.captureException).toHaveBeenCalledWith(error, {
      tags: { boundary, digest: "unknown" },
    });
  });

  it("przycisk ponowienia woła reset", () => {
    mocks.reloadOnceForChunkError.mockReturnValue(false);
    const { reset, view } = renderBoundary(makeError("boom"));

    fireEvent.click(view.getByRole("button", { name: retryLabel }));

    expect(reset).toHaveBeenCalledTimes(1);
  });
});
