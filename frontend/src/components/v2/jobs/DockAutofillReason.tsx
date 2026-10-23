import { Sparkles } from "lucide-react";
import type { KanbanItem } from "@/components/v2/pages/kanban-shared";
import { workdaysText } from "@/lib/board-card-badges";
import { cn } from "@/lib/utils";

/**
 * „Dlaczego system dodał” na górze panelu osoby (silnik „Nowi na 20”,
 * makieta A2 z 23.10.2026): wynik, spełnione i brakujące wymagania oraz to,
 * czego system NIE wiedział w chwili dodania (stawka, dostępność). Ta
 * migawka rozstrzyga potem, czy odrzucenie to błąd wyszukiwania, czy brak
 * danych. Dla osób dodanych przez ludzi nic nie rysuje.
 */
export function DockAutofillReason({
  item,
}: {
  item: Pick<KanbanItem, "entry_source" | "entry_autofill">;
}) {
  const meta = item.entry_autofill;
  if (item.entry_source !== "system" || !meta) return null;
  const unknown = [
    meta.rate_known ? null : "stawki",
    meta.availability_known ? null : "dostępności",
  ].filter(Boolean);
  return (
    <section
      aria-label="Dlaczego system dodał tę osobę"
      data-testid="dock-autofill-reason"
      className="space-y-1.5 rounded-lg border border-border bg-muted/40 px-3 py-2 text-xs"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <Sparkles className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
        <span className="font-semibold">Od systemu · {meta.score}%</span>
        {meta.decision_due && meta.waiting_days != null ? (
          <span className="rounded-full bg-warning-muted px-2 py-0.5 font-semibold text-warning-muted-foreground">
            {workdaysText(meta.waiting_days)} bez decyzji
          </span>
        ) : null}
      </div>
      {meta.matched_must.length || meta.missing_must.length ? (
        <ul className="flex flex-wrap gap-1" aria-label="Wymagania „musi mieć”">
          {meta.matched_must.map((name) => (
            <li
              key={`met-${name}`}
              className="rounded-full bg-success-muted px-2 py-0.5 text-success-muted-foreground"
            >
              ✓ {name}
            </li>
          ))}
          {meta.missing_must.map((name) => (
            <li
              key={`gap-${name}`}
              className="rounded-full bg-destructive-muted px-2 py-0.5 text-destructive-muted-foreground"
            >
              ✕ {name}
            </li>
          ))}
        </ul>
      ) : null}
      <p className={cn("text-[11px]", unknown.length ? "text-foreground" : "text-muted-foreground")}>
        {unknown.length
          ? `System nie znał ${unknown.join(" ani ")} — zapytaj w rozmowie.`
          : "System znał stawkę i dostępność w chwili dodania."}
      </p>
      {!meta.decided ? (
        <p className="text-[11px] text-muted-foreground">
          Zdecyduj: „Dzwonię” albo odrzuć z powodem — powody uczą system.
        </p>
      ) : null}
    </section>
  );
}
