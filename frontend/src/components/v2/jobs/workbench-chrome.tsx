"use client";

/**
 * Wspólny szkielet warsztatów kroków 05–08 („flow w języku C2", fala 3 —
 * parytet z makietami).
 *
 * Makiety czterech kroków mają JEDEN układ: szyna po lewej (`.filters` —
 * nagłówek z ikoną i metą po prawej, sekcje z etykietą, wiersze kolejki
 * z kropką stanu, stopka z akcją), nagłówek środka (`.lhead` — tytuł
 * „Krok · Nazwisko", podtytuł, akcje po prawej, listwa pigułek stanu) i dok
 * (`.dock` — nazwa, kto, zakładki, treść, jedno zdanie reguły na dole).
 * Cztery kopie tego samego markupu rozjechałyby się przy pierwszej poprawce,
 * więc mieszka on tutaj — cztery ekrany różnią się TREŚCIĄ, nie chromem.
 *
 * Moduł jest czysto prezentacyjny (jeden wyjątek: {@link DockNotesPanel},
 * który wyniesiono z `InterviewDecisionDock`, żeby dok kroku 05 dostał
 * zakładkę „Notatki" bez drugiej implementacji tego samego endpointu).
 * Zero hardcodowanych kolorów — wszystko na tokenach.
 */

import type { ReactNode } from "react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Send } from "lucide-react";

import api, { extractErrorMsg } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { TabbedNav } from "@/components/ds";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";
import { cn, formatDate } from "@/lib/utils";

/** Tony makiety: `ok` (zielony), `warn`, `bad`, `info`, `neutral`. */
export type ChromeTone = "ok" | "warn" | "bad" | "info" | "neutral";

const DOT_TONE: Record<ChromeTone, string> = {
  ok: "bg-success",
  warn: "bg-warning",
  bad: "bg-destructive",
  info: "bg-primary",
  neutral: "bg-border",
};

const PILL_TONE: Record<ChromeTone, string> = {
  ok: "bg-success-muted text-success-muted-foreground",
  warn: "bg-warning-muted text-warning-muted-foreground",
  bad: "bg-destructive-muted text-destructive-muted-foreground",
  info: "bg-info-muted text-info-muted-foreground",
  neutral: "border border-border bg-muted/40 text-muted-foreground",
};

/** Inicjały do awatara doku — dwa pierwsze człony nazwiska. */
export function initialsOf(fullName: string): string {
  return (
    fullName
      .split(/\s+/)
      .filter(Boolean)
      .map((w) => w[0])
      .slice(0, 2)
      .join("")
      .toUpperCase() || "?"
  );
}

// ── Szyna (`.filters`) ──────────────────────────────────────────────────────

export function WorkbenchRail({
  icon,
  title,
  count,
  meta,
  children,
  footer,
}: {
  icon?: ReactNode;
  title: string;
  /** Licznik przy tytule — zostaje obok mety, nie zamiast niej. */
  count?: number;
  /** Meta po prawej (`SLA PKO: 5 d`, `2 do wysłania`). */
  meta?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <aside className="flex flex-col gap-3 self-start rounded-xl border border-border bg-card p-3">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
        {icon}
        <span>{title}</span>
        {count != null && (
          <span className="rounded-full border border-border px-1.5 text-[10px] font-medium tabular-nums text-muted-foreground">
            {count}
          </span>
        )}
        {meta != null && (
          <span className="ml-auto text-[10.5px] font-medium text-muted-foreground">
            {meta}
          </span>
        )}
      </div>
      {children}
      {footer && (
        <div className="mt-1 flex flex-col gap-1.5 border-t border-border pt-3">
          {footer}
        </div>
      )}
    </aside>
  );
}

/** Sekcja szyny (`.fsec`) — etykieta wersalikami + treść + opcjonalna notka. */
export function RailSection({
  label,
  children,
  note,
  className,
}: {
  label: string;
  children: ReactNode;
  note?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1.5 border-t border-border pt-3",
        className,
      )}
    >
      <span className="text-[9px] font-bold uppercase tracking-[0.11em] text-muted-foreground">
        {label}
      </span>
      {children}
      {note && <p className="text-[10.5px] text-muted-foreground">{note}</p>}
    </div>
  );
}

/**
 * Wiersz kolejki (`.q`) — kropka stanu, nazwisko, meta po prawej.
 *
 * `onSelect` robi z niego przycisk; bez niego to statyczny wiersz (np. lista
 * informacyjna). Aktywny wiersz niesie `aria-current`, nie tylko kolor.
 */
export function RailRow({
  tone = "neutral",
  label,
  secondary,
  meta,
  metaTone = "neutral",
  active = false,
  onSelect,
  title,
}: {
  tone?: ChromeTone;
  label: ReactNode;
  secondary?: ReactNode;
  meta?: ReactNode;
  metaTone?: ChromeTone;
  active?: boolean;
  onSelect?: () => void;
  title?: string;
}) {
  const body = (
    <>
      <span
        aria-hidden="true"
        className={cn("h-1.5 w-1.5 shrink-0 rounded-full", DOT_TONE[tone])}
      />
      <span className="min-w-0 flex-1 truncate">
        {label}
        {secondary != null && (
          <span className="ml-1 text-muted-foreground">· {secondary}</span>
        )}
      </span>
      {meta != null && (
        <span
          className={cn(
            "shrink-0 text-[10.5px] tabular-nums",
            metaTone === "warn"
              ? "text-warning-muted-foreground"
              : metaTone === "bad"
                ? "text-destructive-muted-foreground"
                : "text-muted-foreground",
          )}
        >
          {meta}
        </span>
      )}
    </>
  );

  const className = cn(
    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors",
    active
      ? "bg-primary/10 font-medium text-primary"
      : "text-foreground hover:bg-accent",
  );

  if (!onSelect) {
    return (
      <div className={className} title={title}>
        {body}
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={active ? "true" : undefined}
      title={title}
      className={className}
    >
      {body}
    </button>
  );
}

/**
 * Wiersz gotowości (`.ready .it`) — kwadracik stanu, tytuł, wyjaśnienie
 * i opcjonalna akcja po prawej.
 *
 * `z` (neutralny) znaczy „wiemy, że to nie jest wymagane / nie mamy danych" —
 * NIE jest zamiennikiem `y`, bo zielony haczyk przy nieznanym stanie kłamie.
 */
export function ReadyItem({
  tone,
  title,
  detail,
  action,
}: {
  tone: "y" | "n" | "z";
  title: ReactNode;
  detail?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-border bg-background/50 px-2 py-1.5 text-[11.5px] leading-tight">
      <span
        aria-hidden="true"
        className={cn(
          "mt-0.5 h-3.5 w-3.5 shrink-0 rounded",
          tone === "y"
            ? "bg-success"
            : tone === "n"
              ? "bg-warning"
              : "bg-border",
        )}
      />
      <span className="min-w-0 flex-1">
        <span className="block font-semibold text-foreground">{title}</span>
        {detail != null && (
          <span className="block text-[11px] text-muted-foreground">
            {detail}
          </span>
        )}
      </span>
      {action != null && <span className="shrink-0">{action}</span>}
    </div>
  );
}

// ── Nagłówek środka (`.lhead`) ──────────────────────────────────────────────

/**
 * Nagłówek warsztatu — `<h2>` „Krok · Nazwisko", podtytuł, akcje po prawej
 * i listwa pigułek stanu pod spodem.
 */
export function WorkbenchHeader({
  title,
  subtitle,
  actions,
  tools,
  toolsRight,
  badges,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  tools?: ReactNode;
  toolsRight?: ReactNode;
  /** Chipy przy tytule (Pending, weto HM) — obok, nie zamiast pigułek stanu. */
  badges?: ReactNode;
}) {
  return (
    <div className="rounded-xl border border-border bg-card px-4 pt-3">
      <div className="flex flex-wrap items-end gap-x-3 gap-y-1">
        <h2 className="text-base font-semibold tracking-tight text-foreground">
          {title}
        </h2>
        {subtitle != null && (
          <span className="text-xs text-muted-foreground">{subtitle}</span>
        )}
        {badges}
        {actions != null && (
          <span className="ml-auto flex flex-wrap items-center gap-1.5">
            {actions}
          </span>
        )}
      </div>
      {(tools != null || toolsRight != null) && (
        <div className="flex flex-wrap items-center gap-1.5 py-2.5">
          {tools}
          {toolsRight != null && (
            <span className="ml-auto flex items-center gap-1.5">
              {toolsRight}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/** Pigułka stanu z listwy `.tools`. */
export function ToolPill({
  tone = "neutral",
  children,
  title,
}: {
  tone?: ChromeTone;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex h-5 items-center gap-1 rounded-full px-2 text-[11px] font-medium whitespace-nowrap",
        PILL_TONE[tone],
      )}
    >
      {children}
    </span>
  );
}

// ── Karta środka (`.fsecx`) ─────────────────────────────────────────────────

export function WorkbenchCard({
  title,
  status,
  statusTone = "neutral",
  children,
  className,
}: {
  title: ReactNode;
  status?: ReactNode;
  statusTone?: ChromeTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "flex flex-col gap-2 rounded-xl border border-border bg-card p-4",
        className,
      )}
    >
      {/* Status stoi OBOK nagłówka, nie w nim: gdyby siedział w `<h3>`,
          nazwa dostępna nagłówka zmieniałaby się razem ze stanem karty. */}
      <div className="flex items-center gap-2">
        <h3 className="text-[10.5px] font-bold uppercase tracking-[0.1em] text-muted-foreground">
          {title}
        </h3>
        {status != null && (
          <span
            className={cn(
              "ml-auto text-[10.5px] font-medium normal-case tracking-normal",
              statusTone === "ok"
                ? "text-success-muted-foreground"
                : statusTone === "warn"
                  ? "text-warning-muted-foreground"
                  : statusTone === "bad"
                    ? "text-destructive-muted-foreground"
                    : "text-muted-foreground",
            )}
          >
            {status}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}

/** Wiersz listy wyników (`.req`) — znacznik, treść, tag po prawej. */
export function ReqRow({
  tone,
  label,
  tag,
}: {
  tone: "y" | "w" | "n";
  label: ReactNode;
  tag?: ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 border-b border-dashed border-border py-1.5 text-[11.5px] last:border-b-0">
      <span
        aria-hidden="true"
        className={cn(
          "h-3.5 w-3.5 shrink-0 rounded",
          tone === "y"
            ? "bg-success"
            : tone === "w"
              ? "bg-warning"
              : "bg-border",
        )}
      />
      <span className="min-w-0 flex-1 text-foreground">{label}</span>
      {tag != null && (
        <span className="shrink-0 text-[9.5px] font-bold uppercase tracking-[0.06em] text-muted-foreground">
          {tag}
        </span>
      )}
    </div>
  );
}

// ── Dok (`.dock`) ───────────────────────────────────────────────────────────

export interface DockTabItem {
  value: string;
  label: string;
}

/**
 * Dok warsztatu — `.dnav` (nazwa doku + akcje ikonowe), `.who` (awatar,
 * nazwisko, podtytuł), `.dtabs`, treść i `.dfoot` (jedno zdanie reguły).
 */
export function WorkbenchDock({
  name,
  headerRight,
  who,
  whoSub,
  tabs,
  activeTab,
  onTabChange,
  children,
  footer,
}: {
  name: string;
  headerRight?: ReactNode;
  /** Nazwisko w nagłówku doku; `null` = nikt nie wybrany (bez awatara). */
  who: string | null;
  whoSub?: ReactNode;
  tabs?: DockTabItem[];
  activeTab?: string;
  onTabChange?: (value: string) => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <div className="flex max-h-[calc(100vh-2rem)] flex-col rounded-xl border border-border bg-card">
      <div className="space-y-2.5 border-b border-border p-4">
        <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-primary">
          <span>{name}</span>
          {headerRight != null && (
            <span className="ml-auto flex items-center gap-1">
              {headerRight}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2.5">
          {who && (
            <span
              aria-hidden="true"
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-semibold text-primary"
            >
              {initialsOf(who)}
            </span>
          )}
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold text-foreground">
              {who ?? "Nikt nie wybrany"}
            </span>
            {whoSub != null && (
              <span className="block truncate text-xs text-muted-foreground">
                {whoSub}
              </span>
            )}
          </span>
        </div>
        {tabs && tabs.length > 1 && activeTab && onTabChange && (
          <TabbedNav
            ariaLabel={`Zakładki doku: ${name}`}
            value={activeTab}
            onValueChange={onTabChange}
            tabs={tabs}
            overflow="scroll"
          />
        )}
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto p-4">{children}</div>

      {footer != null && (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-border bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground">
          {footer}
        </div>
      )}
    </div>
  );
}

/** Sekcja doku (`.dsec`) — etykieta wersalikami + akcja po prawej. */
export function DockSection({
  title,
  right,
  children,
}: {
  title: string;
  right?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="space-y-2 rounded-lg border border-border bg-muted/20 px-3 py-2.5">
      <div className="flex items-center gap-2">
        <h4 className="text-[10px] font-bold uppercase tracking-[0.1em] text-muted-foreground">
          {title}
        </h4>
        {right != null && (
          <span className="ml-auto text-[10.5px] font-medium normal-case tracking-normal text-primary">
            {right}
          </span>
        )}
      </div>
      {children}
    </section>
  );
}

export interface KvRow {
  k: string;
  v: ReactNode;
}

/** Siatka klucz–wartość (`.kv`). */
export function KvList({ rows }: { rows: KvRow[] }) {
  return (
    <dl className="grid grid-cols-[104px_minmax(0,1fr)] gap-x-2.5 gap-y-1 text-xs">
      {rows.map((row) => (
        <div key={row.k} className="contents">
          <dt className="text-[11px] text-muted-foreground">{row.k}</dt>
          <dd className="min-w-0 text-foreground">{row.v}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Siatka akcji doku (`.acts4`) — dwie kolumny, `wide` na całą szerokość. */
export function DockActions({ children }: { children: ReactNode }) {
  return <div className="grid grid-cols-2 gap-1.5">{children}</div>;
}

/** Baner stanu bramki — ten sam kształt co `.banner` w makiecie. */
export function ChromeBanner({
  tone,
  icon,
  children,
}: {
  tone: ChromeTone;
  icon?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      role="status"
      className={cn(
        "flex items-start gap-2 rounded-lg px-2.5 py-2 text-[11.5px] leading-snug",
        PILL_TONE[tone],
      )}
    >
      {icon}
      <span className="min-w-0">{children}</span>
    </div>
  );
}

// ── Oś czasu (`.tl`) ────────────────────────────────────────────────────────

export function ChromeTimeline({ children }: { children: ReactNode }) {
  return <ol className="flex flex-col">{children}</ol>;
}

export function ChromeTimelineEntry({
  tone,
  title,
  meta,
  who,
}: {
  tone: "done" | "now" | "todo";
  title: ReactNode;
  meta?: ReactNode;
  who?: ReactNode;
}) {
  return (
    <li className="grid grid-cols-[14px_minmax(0,1fr)] gap-2 py-1 text-[11.5px]">
      <span className="flex justify-center pt-1">
        <span
          aria-hidden="true"
          className={cn(
            "h-2 w-2 rounded-full",
            tone === "done"
              ? "bg-success"
              : tone === "now"
                ? "bg-primary ring-3 ring-primary/20"
                : "bg-border",
          )}
        />
      </span>
      <span className="min-w-0">
        <span className="font-semibold text-foreground">{title}</span>
        {meta != null && (
          <span className="ml-1.5 text-[10.5px] text-muted-foreground">
            {meta}
          </span>
        )}
        {who != null && (
          <span className="block text-[11px] text-muted-foreground">{who}</span>
        )}
      </span>
    </li>
  );
}

// ── Notatki w doku ──────────────────────────────────────────────────────────

interface NoteListItem {
  id: number;
  content: string;
  content_rendered?: string | null;
  author_name?: string | null;
  created_at: string;
}

/**
 * Zakładka „Notatki" doku — wyniesiona z `InterviewDecisionDock` (krok 07),
 * żeby dok kroku 05 dostał ją bez drugiej implementacji `GET/POST /api/notes`.
 *
 * Zapytanie startuje dopiero, gdy zakładka jest widoczna (`enabled`) — dok
 * montuje się przy każdym wyborze kandydata i pobieranie notatek „na zapas"
 * byłoby zapytaniem per wiersz kolejki.
 */
export function DockNotesPanel({
  candidateId,
  jobId,
  readOnly,
  enabled = true,
}: {
  candidateId: number;
  jobId: number;
  readOnly: boolean;
  enabled?: boolean;
}) {
  const { showSuccess, showError } = useToast();
  const queryClient = useQueryClient();
  const [noteText, setNoteText] = useState("");

  const notesQuery = useQuery<{ items?: NoteListItem[] }>({
    queryKey: [...candidateQueryKeys.notes(candidateId), jobId],
    queryFn: () =>
      api
        .get(`/api/notes?candidate_id=${candidateId}&job_id=${jobId}`)
        .then((r) => r.data),
    enabled,
  });

  const addNoteMutation = useMutation({
    mutationFn: (content: string) =>
      api.post("/api/notes", {
        candidate_id: candidateId,
        job_id: jobId,
        content,
        note_type: "general",
      }),
    onSuccess: () => {
      setNoteText("");
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.notes(candidateId),
      });
      // Notatka jest też wpisem osi czasu profilu (lustro `PipelineCandidateDock`).
      queryClient.invalidateQueries({
        queryKey: candidateQueryKeys.timelineRoot(candidateId),
      });
      showSuccess("Notatka dodana.");
    },
    onError: (e) =>
      showError(extractErrorMsg(e) || "Nie udało się dodać notatki"),
  });

  const submitNote = () => {
    const content = noteText.trim();
    if (!content || addNoteMutation.isPending) return;
    addNoteMutation.mutate(content);
  };

  const items = notesQuery.data?.items ?? [];

  return (
    <div className="space-y-3">
      {!readOnly && (
        <div className="space-y-1.5">
          <textarea
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submitNote();
              }
            }}
            placeholder="Notatka z rozmowy… (Enter wysyła, Shift+Enter nowa linia)"
            rows={2}
            className="w-full rounded-md border border-border bg-card px-3 py-2 text-xs focus:ring-2 focus:ring-primary focus:outline-hidden"
          />
          <div className="flex justify-end">
            <Button
              size="sm"
              onClick={submitNote}
              disabled={!noteText.trim() || addNoteMutation.isPending}
              loading={addNoteMutation.isPending}
            >
              <Send className="h-3.5 w-3.5" />
              Dodaj notatkę
            </Button>
          </div>
        </div>
      )}
      {notesQuery.isLoading ? (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> Wczytywanie…
        </div>
      ) : items.length > 0 ? (
        <div className="space-y-2">
          {items.map((n) => (
            <div
              key={n.id}
              className="rounded-lg border border-border bg-muted/20 p-2.5 text-xs"
            >
              <div className="mb-1 flex items-center justify-between text-muted-foreground">
                <span className="font-medium text-foreground">
                  {n.author_name ?? "Nieznany autor"}
                </span>
                <span>{formatDate(n.created_at)}</span>
              </div>
              <p className="whitespace-pre-line text-foreground">
                {n.content_rendered ?? n.content}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          Brak notatek dla tej rekrutacji.
        </p>
      )}
    </div>
  );
}
