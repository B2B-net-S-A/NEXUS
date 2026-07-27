"use client";

/**
 * Kolejka zgłoszeń z publicznych aplikacji.
 *
 * Gdy kandydat aplikuje z linku publicznego, a jego e-mail już jest w bazie,
 * backend celowo NIE nadpisuje istniejącego rekordu — parkuje zgłoszenie jako
 * `pending_review` i zwraca aplikantowi neutralny sukces. To dobra ochrona
 * danych i była pełną ścieżką w jedną stronę: `/api/application-submissions`
 * nie miało ANI JEDNEGO konsumenta w całym `frontend/src`. Kandydat dostawał
 * „dziękujemy", a zgłoszenie nie trafiało nigdzie, gdzie ktokolwiek patrzy.
 *
 * Ten ekran jest tym miejscem. Sortowanie od najstarszych, bo jedyne, co
 * naprawdę boli w takiej kolejce, to zgłoszenie leżące tydzień.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  Inbox,
  Link2,
  Loader2,
  Merge,
  UserPlus,
  X,
} from "lucide-react";

import {
  applicationSubmissionsApi,
  type ApplicationResolveAction,
  type ApplicationSubmission,
} from "@/lib/api";
import { useToast } from "@/components/Toast";
import { cn } from "@/lib/utils";

/** Zgłoszenie starsze niż to jest sygnałem, że kolejka nie ma właściciela. */
const STALE_AFTER_HOURS = 24;

function ageHours(iso: string | null): number | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  return (Date.now() - then) / 3_600_000;
}

function formatAge(iso: string | null): string {
  const hours = ageHours(iso);
  if (hours === null) return "—";
  if (hours < 1) return `${Math.max(1, Math.floor(hours * 60))} min`;
  if (hours < 48) return `${Math.floor(hours)} h`;
  return `${Math.floor(hours / 24)} dni`;
}

interface ActionSpec {
  action: ApplicationResolveAction;
  label: string;
  hint: string;
  icon: React.ReactNode;
  tone: string;
}

/** `link`/`merge` mają sens tylko wtedy, gdy backend znalazł dopasowanie. */
function actionsFor(submission: ApplicationSubmission): ActionSpec[] {
  const matched = submission.matched_candidate_id !== null;
  const specs: ActionSpec[] = [];
  if (matched) {
    specs.push({
      action: "link",
      label: "Powiąż",
      hint: "Dopisz zgłoszenie do istniejącego kandydata bez zmiany jego danych.",
      icon: <Link2 className="h-3.5 w-3.5" />,
      tone: "border-primary/40 text-primary hover:bg-primary/10",
    });
    specs.push({
      action: "merge",
      label: "Scal",
      hint: "Uzupełnij istniejącego kandydata danymi i CV ze zgłoszenia.",
      icon: <Merge className="h-3.5 w-3.5" />,
      tone: "border-primary/40 text-primary hover:bg-primary/10",
    });
  } else {
    specs.push({
      action: "create",
      label: "Utwórz kandydata",
      hint: "Załóż nowy profil na podstawie zgłoszenia.",
      icon: <UserPlus className="h-3.5 w-3.5" />,
      tone: "border-emerald-500/40 text-emerald-700 hover:bg-emerald-500/10",
    });
  }
  specs.push({
    action: "reject",
    label: "Odrzuć",
    hint: "Zamknij zgłoszenie bez tworzenia ani zmieniania kandydata.",
    icon: <X className="h-3.5 w-3.5" />,
    tone: "border-border text-muted-foreground hover:bg-muted",
  });
  return specs;
}

export default function ApplicationsQueuePage() {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [busyId, setBusyId] = useState<number | null>(null);

  const { data = [], isLoading, isError } = useQuery({
    queryKey: ["application-submissions", "pending_review"],
    queryFn: () => applicationSubmissionsApi.list("pending_review"),
    refetchInterval: 60_000,
  });

  const resolve = useMutation({
    mutationFn: ({ id, action }: { id: number; action: ApplicationResolveAction }) =>
      applicationSubmissionsApi.resolve(id, action),
    onSuccess: (result) => {
      showSuccess(
        result.candidate_id
          ? `Zgłoszenie rozstrzygnięte (kandydat #${result.candidate_id}).`
          : "Zgłoszenie rozstrzygnięte.",
      );
      queryClient.invalidateQueries({ queryKey: ["application-submissions"] });
    },
    onError: (err: unknown) => {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Nie udało się rozstrzygnąć zgłoszenia.";
      showError(detail);
    },
    onSettled: () => setBusyId(null),
  });

  // Najstarsze na górze — zgłoszenie, które leży, jest jedynym realnym
  // problemem tej kolejki.
  const sorted = useMemo(
    () =>
      [...data].sort(
        (a, b) =>
          new Date(a.created_at ?? 0).getTime() -
          new Date(b.created_at ?? 0).getTime(),
      ),
    [data],
  );
  const stale = sorted.filter((s) => (ageHours(s.created_at) ?? 0) > STALE_AFTER_HOURS);

  return (
    <main className="mx-auto max-w-[1100px] space-y-6 px-4 py-6 sm:px-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            Sourcing
          </p>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">
            Zgłoszenia do rozpatrzenia
          </h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            Aplikacje z linków publicznych, których e-mail pasuje do kogoś już
            w bazie. Nie nadpisujemy istniejącego profilu automatycznie — decyzja
            należy do rekrutera.
          </p>
        </div>
        {sorted.length > 0 && (
          <span className="shrink-0 rounded-full bg-primary/10 px-3 py-1 text-sm font-medium text-primary">
            {sorted.length}
          </span>
        )}
      </header>

      {stale.length > 0 && (
        <p className="flex items-center gap-2 rounded-xl border border-amber-500/40 bg-amber-500/5 px-4 py-3 text-sm text-amber-700 dark:text-amber-400">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {stale.length}{" "}
          {stale.length === 1 ? "zgłoszenie czeka" : "zgłoszeń czeka"} dłużej niż{" "}
          {STALE_AFTER_HOURS} h.
        </p>
      )}

      {isLoading && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Wczytywanie kolejki…
        </div>
      )}

      {isError && (
        <p className="rounded-xl border border-border bg-card p-6 text-sm text-muted-foreground">
          Nie udało się pobrać kolejki zgłoszeń.
        </p>
      )}

      {!isLoading && !isError && sorted.length === 0 && (
        <div className="rounded-2xl border border-dashed border-border bg-muted/40 p-10 text-center">
          <CheckCircle2 className="mx-auto mb-2 h-8 w-8 text-emerald-600" />
          <p className="text-sm font-medium text-foreground">
            Brak zgłoszeń czekających na decyzję.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Nowe pojawią się tutaj, gdy ktoś zaaplikuje z linku publicznego
            adresem, który już znamy.
          </p>
        </div>
      )}

      <ul className="space-y-3">
        {sorted.map((s) => {
          const hours = ageHours(s.created_at) ?? 0;
          const isStale = hours > STALE_AFTER_HOURS;
          const busy = busyId === s.id;
          return (
            <li
              key={s.id}
              className={cn(
                "rounded-2xl border bg-card p-5",
                isStale ? "border-amber-500/40" : "border-border",
              )}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-base font-semibold text-foreground">
                    {s.submitted_first_name} {s.submitted_last_name}
                  </p>
                  <p className="truncate text-sm text-muted-foreground">
                    {s.submitted_email}
                    {s.submitted_phone ? ` · ${s.submitted_phone}` : ""}
                  </p>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  {s.job_id !== null && (
                    <a
                      href={`/jobs/${s.job_id}`}
                      className="rounded-full border border-border px-2.5 py-0.5 text-muted-foreground hover:text-foreground"
                    >
                      oferta #{s.job_id}
                    </a>
                  )}
                  <span
                    className={cn(
                      "rounded-full px-2.5 py-0.5",
                      isStale
                        ? "bg-amber-500/10 text-amber-700 dark:text-amber-400"
                        : "bg-muted text-muted-foreground",
                    )}
                  >
                    czeka {formatAge(s.created_at)}
                  </span>
                </div>
              </div>

              {s.submitted_message && (
                <p className="mt-3 line-clamp-3 rounded-lg bg-muted/50 px-3 py-2 text-sm text-muted-foreground">
                  {s.submitted_message}
                </p>
              )}

              <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                {s.cv_filename && (
                  <span className="inline-flex items-center gap-1">
                    <FileText className="h-3.5 w-3.5" />
                    {s.cv_filename}
                  </span>
                )}
                {s.submitted_linkedin && (
                  <a
                    href={s.submitted_linkedin}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1 hover:text-foreground"
                  >
                    <Link2 className="h-3.5 w-3.5" />
                    LinkedIn
                  </a>
                )}
                {s.matched_candidate_id !== null ? (
                  <a
                    href={`/candidates/${s.matched_candidate_id}`}
                    className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
                  >
                    <Inbox className="h-3.5 w-3.5" />
                    pasuje do kandydata #{s.matched_candidate_id}
                  </a>
                ) : (
                  <span className="inline-flex items-center gap-1">
                    <Inbox className="h-3.5 w-3.5" />
                    brak dopasowania w bazie
                  </span>
                )}
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                {actionsFor(s).map((spec) => (
                  <button
                    key={spec.action}
                    type="button"
                    title={spec.hint}
                    disabled={busy || resolve.isPending}
                    onClick={() => {
                      setBusyId(s.id);
                      resolve.mutate({ id: s.id, action: spec.action });
                    }}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50",
                      spec.tone,
                    )}
                  >
                    {busy && resolve.isPending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      spec.icon
                    )}
                    {spec.label}
                  </button>
                ))}
              </div>
            </li>
          );
        })}
      </ul>
    </main>
  );
}
