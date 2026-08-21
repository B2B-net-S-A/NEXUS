import { act, fireEvent, render, screen } from "@testing-library/react";
import { useEffect, useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider, useToast } from "@/components/Toast";

/**
 * Regresja, którą te testy chronią, jest CICHA: aplikacja działa poprawnie,
 * tylko re-renderuje wszystkich ~99 konsumentów useToast() (w tym listy
 * wirtualizowane) dwa razy na każdy toast. Nic nie pęka, nic nie krzyczy —
 * interfejs po prostu robi się lepki przy pracy masowej. Bez testu wystarczy,
 * żeby ktoś "uprościł" value={value} z powrotem do literału obiektu.
 */

function IdentityProbe({
  seen,
  renders,
}: {
  seen: unknown[];
  renders: { current: number };
}) {
  const toast = useToast();
  renders.current += 1;
  seen.push(toast);

  return (
    <button type="button" onClick={() => toast.showSuccess("Zapisano")}>
      Pokaż sukces
    </button>
  );
}

describe("tożsamość wartości ToastContext", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("nie zmienia się przez pełny cykl życia toasta", () => {
    const seen: unknown[] = [];
    const renders = { current: 0 };

    render(
      <ToastProvider>
        <IdentityProbe seen={seen} renders={renders} />
      </ToastProvider>,
    );

    const rendersAfterMount = renders.current;
    const initial = seen[0];

    // Pokazanie toasta = setState w providerze (render #1 providera).
    fireEvent.click(screen.getByRole("button", { name: "Pokaż sukces" }));
    expect(screen.getByRole("status")).toHaveTextContent("Zapisano");

    // Zniknięcie po 3 s = drugi setState (render #2 providera) — ten NIE jest
    // już zainicjowany przez użytkownika, więc re-render listy, po której
    // rekruter właśnie scrolluje, byłby dla niego całkowicie niespodziewany.
    act(() => {
      vi.advanceTimersByTime(3000);
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    // Konsument nie może być powiadomiony o zmianie kontekstu, bo kontekst
    // się nie zmienił — zmienił się wyłącznie stan wewnętrzny providera.
    expect(renders.current).toBe(rendersAfterMount);
    for (const value of seen) {
      expect(value).toBe(initial);
    }
  });

  it("nie napędza pętli u konsumenta trzymającego cały obiekt kontekstu w deps useEffect", () => {
    // Dokładnie kształt z InsightsView: `const toast = useToast()` w tablicy
    // zależności efektu, który sam woła showError. Przy niestabilnej wartości
    // każdy toast unieważnia deps → efekt leci znowu → kolejny toast: pętla,
    // która sama się napędza. Licznik zatrzymany na 50, żeby zepsuta wersja
    // kończyła się czytelną asercją, a nie zawieszeniem runnera.
    const effectRuns = { current: 0 };

    function LoopingConsumer() {
      const toast = useToast();
      const stop = useRef(false);

      useEffect(() => {
        if (stop.current) return;
        effectRuns.current += 1;
        if (effectRuns.current > 50) {
          stop.current = true;
          return;
        }
        toast.showError("Brak dostępu do tej zakładki");
      }, [toast]);

      return null;
    }

    render(
      <ToastProvider>
        <LoopingConsumer />
      </ToastProvider>,
    );

    act(() => {
      vi.advanceTimersByTime(8000);
    });

    expect(effectRuns.current).toBe(1);
  });
});
