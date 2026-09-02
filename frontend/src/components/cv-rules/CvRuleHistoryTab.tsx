"use client";

/**
 * Zakładka „Historia": kto, kiedy i co zmienił w regule (z diffem pól) oraz
 * sygnał zwrotny z produkcji — które instrukcje model pomijał i jak często
 * kod domykał politykę prezentacji. Instrukcja pomijana w co drugim CV to
 * instrukcja do przepisania; bez tej listy DL widział wyłącznie pojedyncze
 * ostrzeżenia u rekruterów, którzy nie mają powodu ich zgłaszać.
 */

import { useQuery } from "@tanstack/react-query";

import {
  RULE_EVENT_LABELS,
  RULE_FIELD_LABELS,
  cvRulesApi,
  type RuleEvent,
} from "@/lib/cv-rules";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" });
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "tak" : "nie";
  if (Array.isArray(value)) {
    return value
      .map((v) =>
        v && typeof v === "object" && "from" in (v as object)
          ? `${(v as { from: string }).from} → ${(v as { to: string }).to}`
          : String(v),
      )
      .join(", ") || "—";
  }
  return String(value);
}

function ChangeList({ event }: { event: RuleEvent }) {
  const entries = Object.entries(event.changes ?? {});
  if (entries.length === 0) return null;
  return (
    <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
      {entries.map(([field, change]) => {
        const label = RULE_FIELD_LABELS[field] ?? field;
        if (
          change &&
          typeof change === "object" &&
          "from" in (change as object) &&
          "to" in (change as object)
        ) {
          const c = change as { from: unknown; to: unknown };
          return (
            <li key={field}>
              <span className="font-medium text-foreground">{label}:</span>{" "}
              <span className="line-through">{renderValue(c.from)}</span> →{" "}
              {renderValue(c.to)}
            </li>
          );
        }
        return (
          <li key={field}>
            <span className="font-medium text-foreground">{label}:</span>{" "}
            {renderValue(change)}
          </li>
        );
      })}
    </ul>
  );
}

export function CvRuleHistoryTab({ clientId }: { clientId: number }) {
  const history = useQuery({
    queryKey: ["cv-rule-history", clientId],
    queryFn: () => cvRulesApi.history(clientId),
  });
  const feedback = useQuery({
    queryKey: ["cv-rule-feedback", clientId],
    queryFn: () => cvRulesApi.feedback(clientId, 90),
  });

  return (
    <div className="space-y-6">
      <section className="space-y-2">
        <h4 className="text-xs font-medium">Sygnał zwrotny z ostatnich 90 dni</h4>
        {feedback.isError ? (
          <p className="text-xs text-destructive">Nie udało się pobrać sygnału zwrotnego.</p>
        ) : feedback.isLoading ? (
          <p className="text-xs text-muted-foreground">Ładowanie…</p>
        ) : feedback.data ? (
          <>
            <p className="text-sm">
              Wygenerowanych CV: {feedback.data.generated_total} · z pominiętą
              instrukcją: {feedback.data.with_skipped_instructions} · z polityką
              domkniętą w kodzie: {feedback.data.with_policy_enforced}
            </p>
            {feedback.data.skipped_by_instruction.length > 0 ? (
              <ul className="space-y-1 text-sm">
                {feedback.data.skipped_by_instruction.map((s) => (
                  <li key={s.text} className="flex items-start justify-between gap-2 rounded-md border p-2">
                    <span>„{s.text}”</span>
                    <span className="shrink-0 rounded-full bg-destructive/10 px-2 text-xs text-destructive">
                      pominięta {s.count}×
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-muted-foreground">
                Model nie pominął żadnej instrukcji w tym okresie.
              </p>
            )}
            {feedback.data.recent.length > 0 ? (
              <details className="text-xs">
                <summary className="cursor-pointer text-muted-foreground">
                  Ostatnie generacje ({feedback.data.recent.length})
                </summary>
                <ul className="mt-1 divide-y rounded-md border">
                  {feedback.data.recent.map((g) => (
                    <li key={g.id} className="flex flex-wrap items-center gap-2 p-2">
                      <span className="font-medium">{g.candidate_name}</span>
                      <span className="text-muted-foreground">
                        {g.language.toUpperCase()} · {g.content_mode} ·{" "}
                        {formatDate(g.created_at)}
                        {g.created_by_name ? ` · ${g.created_by_name}` : ""}
                        {g.client_rule_version != null
                          ? ` · reguła v${g.client_rule_version}`
                          : " · bez reguły"}
                      </span>
                      {g.skipped.length ? (
                        <span className="rounded-full bg-destructive/10 px-2 text-destructive">
                          pominięte: {g.skipped.length}
                        </span>
                      ) : null}
                      {g.policy_enforced ? (
                        <span className="rounded-full bg-amber-500/10 px-2 text-amber-700 dark:text-amber-400">
                          domknięto w kodzie
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </>
        ) : null}
      </section>

      <section className="space-y-2">
        <h4 className="text-xs font-medium">Historia zmian</h4>
        {history.isError ? (
          <p className="text-xs text-destructive">Nie udało się pobrać historii.</p>
        ) : history.isLoading ? (
          <p className="text-xs text-muted-foreground">Ładowanie…</p>
        ) : !history.data?.length ? (
          <p className="text-xs text-muted-foreground">Brak wpisów.</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {history.data.map((event) => (
              <li key={event.id} className="p-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">
                    {RULE_EVENT_LABELS[event.action] ?? event.action}
                  </span>
                  <span className="rounded-full border px-2 text-xs text-muted-foreground">
                    v{event.rule_version}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {formatDate(event.created_at)}
                    {event.actor_name ? ` · ${event.actor_name}` : ""}
                  </span>
                </div>
                <ChangeList event={event} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
