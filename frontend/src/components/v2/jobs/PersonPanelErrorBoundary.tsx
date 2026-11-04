"use client";

/**
 * Granica błędu panelu osoby na Tablicy (29.10.2026).
 *
 * Zgłoszenie zespołu: przy generowaniu CV wyskakiwał pełny ekran „Coś poszło
 * nie tak” (Sentry NEXUS-FE-R, React #185 — pętla aktualizacji w refie
 * Radixa). Bez lokalnej granicy każdy wyjątek renderu w panelu osoby kładł
 * cały ekran rekrutacji, a Sentry dostawał stos bez naszego komponentu.
 * Teraz pada tylko panel: tablica zostaje, panel da się otworzyć ponownie,
 * a zgłoszenie niesie stos komponentów, żeby wskazać winny element.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";
import * as Sentry from "@sentry/nextjs";
import { AlertTriangle, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";

interface Props {
  children: ReactNode;
  /** Zamyka panel — po nim osobę otwiera się z tablicy od nowa. */
  onClose: () => void;
}

interface State {
  failed: boolean;
}

export class PersonPanelErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    Sentry.captureException(error, {
      tags: { boundary: "person-panel" },
      contexts: { react: { componentStack: info.componentStack ?? "" } },
    });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div
        role="alert"
        data-testid="person-panel-error"
        className="m-3 flex flex-col gap-3 rounded-lg border border-warning/40 bg-warning-muted p-4 text-sm text-warning-muted-foreground"
      >
        <p className="flex items-center gap-2 font-medium">
          <AlertTriangle className="h-4 w-4" aria-hidden="true" />
          Panel osoby się zawiesił
        </p>
        <p className="text-xs">
          Tablica i zapisane zmiany są na miejscu. Otwórz panel ponownie — jeśli
          błąd wróci, przenieś osobę na QC CV i wygeneruj CV stamtąd. Zespół
          dostał zgłoszenie.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => this.setState({ failed: false })}>
            <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" /> Otwórz panel ponownie
          </Button>
          <Button size="sm" variant="outline" onClick={this.props.onClose}>
            Zamknij panel
          </Button>
        </div>
      </div>
    );
  }
}
