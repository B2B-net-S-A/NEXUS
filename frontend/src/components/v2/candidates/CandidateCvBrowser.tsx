"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, UserPlus } from "lucide-react";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { useToast } from "@/components/Toast";
import {
  FilePreviewModal,
  downloadDocumentBlob,
  type CandidateDocument,
} from "@/components/v2/files/FilePreviewModal";

export interface CvBrowserPerson {
  id: number;
  name: string;
}

interface Loaded {
  person: CvBrowserPerson;
  documents: CandidateDocument[];
  primaryId: number;
}

/**
 * Okno CV listy kandydatów z przejściem do poprzedniej/następnej osoby
 * (prośba rekruterów 23.10.2026: przegląd kilkunastu CV bez zamykania okna
 * i szukania kolejnego wiersza). `people` to osoby z CV w kolejności listy
 * (bieżąca strona); `current` — kogo pokazać, `null` = okno zamknięte.
 * Do czasu wczytania dokumentów następnej osoby zostaje CV poprzedniej.
 */
export function CandidateCvBrowser({
  people,
  current,
  onChange,
  onOpened,
  onLoadingChange,
  onAssign,
  focusPerson,
}: {
  people: readonly CvBrowserPerson[];
  current: CvBrowserPerson | null;
  onChange: (person: CvBrowserPerson | null) => void;
  /** Dokumenty wczytane i okno pokazuje tę osobę. */
  onOpened: (person: CvBrowserPerson) => void;
  onLoadingChange?: (candidateId: number | null) => void;
  /** „Przypisz do rekrutacji” — bez niego (okno rekrutacji) przycisku nie ma. */
  onAssign?: (person: CvBrowserPerson) => void;
  /** Po zamknięciu: fokus na wiersz ostatnio oglądanej osoby; `false` = domyślnie. */
  focusPerson?: (candidateId: number) => boolean;
}) {
  const { showError } = useToast();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [loadingId, setLoadingId] = useState<number | null>(null);
  // Najnowsze wywołania zwrotne bez restartu pobierania przy każdym renderze listy.
  const callbacks = useRef({ onChange, onOpened, onLoadingChange });
  callbacks.current = { onChange, onOpened, onLoadingChange };

  const currentId = current?.id ?? null;
  useEffect(() => {
    if (!current) {
      setLoaded(null);
      setLoadingId(null);
      callbacks.current.onLoadingChange?.(null);
      return;
    }
    let cancelled = false;
    setLoadingId(current.id);
    callbacks.current.onLoadingChange?.(current.id);
    (async () => {
      try {
        const { data: docs } = await api.get<CandidateDocument[]>(
          `/api/candidates/${current.id}/documents?kind=cv`,
        );
        if (cancelled) return;
        const primary = docs.find((d) => d.is_primary) ?? docs[0];
        if (!primary) {
          showError(`${current.name} nie ma zapisanego pliku CV.`);
          // Przy przechodzeniu zostaje poprzednia osoba; przy otwarciu — zamknij.
          callbacks.current.onChange(loaded?.person ?? null);
          return;
        }
        setLoaded({ person: current, documents: docs, primaryId: primary.id });
        callbacks.current.onOpened(current);
      } catch (error) {
        if (cancelled) return;
        showError(apiErrorMessage(error, "Nie udało się otworzyć CV kandydata."));
        callbacks.current.onChange(loaded?.person ?? null);
      } finally {
        if (!cancelled) {
          setLoadingId(null);
          callbacks.current.onLoadingChange?.(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
    // `loaded` czytamy tylko jako punkt powrotu po błędzie — nie restartuje pobierania.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId]);

  const shown = loaded?.person ?? null;
  // Okno zamyka się z `loaded = null`, a fokus wraca dopiero po animacji.
  const lastShownId = useRef<number | null>(null);
  if (shown) lastShownId.current = shown.id;
  const index = shown ? people.findIndex((p) => p.id === shown.id) : -1;
  const prev = index > 0 ? people[index - 1] : null;
  const next = index >= 0 && index < people.length - 1 ? people[index + 1] : null;
  const busy = loadingId !== null;

  useEffect(() => {
    if (!loaded) return;
    // Shift + strzałka = osoba; same strzałki przełączają pliki CV jednej osoby.
    const onKeyDown = (event: KeyboardEvent) => {
      if (!event.shiftKey || busy) return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable || target.tagName === "INPUT" || target.tagName === "TEXTAREA")
      ) {
        return;
      }
      const to = event.key === "ArrowLeft" ? prev : event.key === "ArrowRight" ? next : null;
      if (!to) return;
      event.preventDefault();
      callbacks.current.onChange(to);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [loaded, prev, next, busy]);

  // Napisy przy strzałkach: obok stoją strzałki plików CV jednej osoby.
  const navButton =
    "inline-flex items-center gap-1 px-2 py-2.5 text-sm text-muted-foreground md:py-1 transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40";

  return (
    <FilePreviewModal
      documents={loaded?.documents ?? []}
      initialDocumentId={loaded?.primaryId ?? null}
      candidateId={shown?.id ?? 0}
      candidateName={shown?.name}
      onClose={() => onChange(null)}
      onCloseAutoFocus={(event) => {
        // Bez tego fokus wraca na przycisk „CV” pierwszej osoby i lista
        // przewija się do niej, choć oglądało się kogoś dalej.
        if (lastShownId.current != null && focusPerson?.(lastShownId.current)) {
          event.preventDefault();
        }
      }}
      onDownload={(doc) => {
        if (shown) downloadDocumentBlob(shown.id, doc).catch(() => {});
      }}
      headerActions={
        shown ? (
          <>
            <div
              className="inline-flex items-center rounded-md border border-border"
              aria-label="Przejście między osobami z listy"
            >
              <button
                type="button"
                onClick={() => prev && onChange(prev)}
                disabled={!prev || busy}
                className={`rounded-l-md ${navButton}`}
                aria-label={prev ? `Poprzednia osoba: ${prev.name}` : "Poprzednia osoba"}
                title={prev ? `Poprzednia osoba: ${prev.name} (Shift + ←)` : "To pierwsza osoba z CV na tej stronie listy"}
                aria-keyshortcuts="Shift+ArrowLeft"
              >
                <ChevronLeft className="h-4 w-4" aria-hidden />
                <span>Poprzednia</span>
              </button>
              <span
                className="border-x border-border px-2 text-xs tabular-nums text-muted-foreground"
                aria-live="polite"
              >
                {busy ? "Wczytuję…" : index >= 0 ? `Osoba ${index + 1} z ${people.length}` : "Osoba"}
              </span>
              <button
                type="button"
                onClick={() => next && onChange(next)}
                disabled={!next || busy}
                className={`rounded-r-md ${navButton}`}
                aria-label={next ? `Następna osoba: ${next.name}` : "Następna osoba"}
                title={next ? `Następna osoba: ${next.name} (Shift + →)` : "To ostatnia osoba z CV na tej stronie listy"}
                aria-keyshortcuts="Shift+ArrowRight"
              >
                <span>Następna</span>
                <ChevronRight className="h-4 w-4" aria-hidden />
              </button>
            </div>
            {onAssign ? (
              <button
                type="button"
                // Panel przypisania to Sheet (z-50) — pod oknem CV (z-110) byłby
                // niewidoczny, więc okno CV zamykamy; ślad „✓ CV” zostaje w wierszu.
                onClick={() => {
                  onChange(null);
                  onAssign(shown);
                }}
                className="inline-flex h-8 items-center gap-1.5 rounded-md border border-primary/40 bg-primary/5 px-2.5 text-sm font-medium text-primary transition-colors hover:bg-primary hover:text-primary-foreground"
              >
                <UserPlus className="h-3.5 w-3.5" aria-hidden />
                Przypisz do rekrutacji
              </button>
            ) : null}
          </>
        ) : null
      }
    />
  );
}
