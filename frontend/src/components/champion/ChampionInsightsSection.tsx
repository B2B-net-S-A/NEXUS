"use client";

/**
 * Sekcja 8 Profilu Championa — „Wiedza z rozmów”.
 *
 * Dwie kolumny: od klienta i od naszego konsultanta. Każda notatka ma
 * widoczność („Tylko zespół” / „Można powiedzieć kandydatowi”), autora i datę
 * (stempluje serwer). Wpisy z weryfikacji są tylko do odczytu — zmienia je
 * ponowna weryfikacja w doku „Gotowość”. Pod kolumnami blok „Z historii
 * klienta”, liczony przez AI (Luna) z werdyktów HM i odrzuceń — nigdy pusty
 * bez wyjaśnienia: awaria ma komunikat i „Odśwież”.
 *
 * Logika zmian (w tym łatka starych pól `client.*` dla wpisów „z importu”)
 * żyje w `lib/champion-insights.ts`; tu jest tylko widok.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ChevronDown,
  ChevronRight,
  History,
  Loader2,
  MessageSquarePlus,
  Pencil,
  RefreshCw,
  Trash2,
} from "lucide-react";

import {
  championApi,
  type ClientHistorySummary,
  type InsightNote,
  type InsightSource,
  type InsightTopic,
} from "@/lib/api";
import {
  applyInsightEdit,
  askClientItems,
  INSIGHT_AUDIENCE_LABEL,
  INSIGHT_PROMPTS,
  INSIGHT_SOURCE_LABEL,
  INSIGHT_TOPIC_LABEL,
  insightOriginLabel,
  newInsight,
  removeInsight,
  visibleInsights,
  type InsightChange,
  type InsightFilter,
} from "@/lib/champion-insights";
import { apiErrorMessage } from "@/lib/api-error";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

const TOPIC_FROM_HISTORY: Record<string, InsightTopic> = {
  rejections: "rejections",
  needs: "needs",
  process: "process",
  pitch: "pitch",
};

export interface ChampionInsightsSectionProps {
  jobId: number;
  notes: readonly InsightNote[];
  clientHistory: ClientHistorySummary | undefined;
  hasClient: boolean;
  disabled?: boolean;
  onChange: (change: InsightChange) => void;
  onClientHistory: (history: ClientHistorySummary) => void;
}

export function ChampionInsightsSection({
  jobId,
  notes,
  clientHistory,
  hasClient,
  disabled = false,
  onChange,
  onClientHistory,
}: ChampionInsightsSectionProps) {
  const [filter, setFilter] = useState<InsightFilter>("all");
  const [editingId, setEditingId] = useState<string | null>(null);

  const add = (source: InsightSource, topic: InsightTopic = "other") => {
    const note = newInsight(source, topic);
    onChange({ insights: [...notes, note] });
    setEditingId(note.id);
  };

  const counts = {
    client: notes.filter((n) => n.source === "client" && n.topic !== "ask_client").length,
    consultant: notes.filter((n) => n.source === "consultant").length,
  };
  const askClient = askClientItems(notes);

  return (
    <div className="flex flex-col gap-4" data-testid="champion-insights">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {INSIGHT_SOURCE_LABEL.client}: {counts.client} ·{" "}
          {INSIGHT_SOURCE_LABEL.consultant}: {counts.consultant}
        </p>
        <div
          role="radiogroup"
          aria-label="Pokaż notatki"
          className="inline-flex rounded-md border border-border p-0.5 text-xs"
        >
          {(
            [
              ["all", "Wszystko"],
              ["team", INSIGHT_AUDIENCE_LABEL.team],
              ["candidate", "Dla kandydata"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={filter === value}
              onClick={() => setFilter(value)}
              className={cn(
                "rounded px-2 py-0.5",
                filter === value
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {askClient.length > 0 ? (
        <AskClientChecklist
          items={askClient}
          disabled={disabled}
          onToggle={(id, done) => onChange(applyInsightEdit(notes, id, { done }))}
          onRemove={(id) => onChange(removeInsight(notes, id))}
        />
      ) : null}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {(["client", "consultant"] as const).map((source) => (
          <InsightColumn
            key={source}
            source={source}
            notes={visibleInsights(notes, source, filter)}
            disabled={disabled}
            editingId={editingId}
            onEdit={setEditingId}
            onAdd={(topic) => add(source, topic)}
            onPatch={(id, patch) => onChange(applyInsightEdit(notes, id, patch))}
            onRemove={(id) => {
              onChange(removeInsight(notes, id));
              if (editingId === id) setEditingId(null);
            }}
          />
        ))}
      </div>

      <ClientHistoryBlock
        jobId={jobId}
        history={clientHistory}
        hasClient={hasClient}
        disabled={disabled}
        onHistory={onClientHistory}
        onPromote={(topic, text) =>
          onChange({ insights: [...notes, newInsight("client", topic, text)] })
        }
      />
      <p className="text-[11px] text-muted-foreground">
        Notatki „{INSIGHT_AUDIENCE_LABEL.team}” widzi wyłącznie zespół rekrutacji —
        nie trafiają na kartę dla hiring managera ani na stronę kariery. Zapisują się
        przyciskiem „Zapisz” profilu.
      </p>
    </div>
  );
}

function InsightColumn({
  source,
  notes,
  disabled,
  editingId,
  onEdit,
  onAdd,
  onPatch,
  onRemove,
}: {
  source: InsightSource;
  notes: InsightNote[];
  disabled: boolean;
  editingId: string | null;
  onEdit: (id: string | null) => void;
  onAdd: (topic?: InsightTopic) => void;
  onPatch: (id: string, patch: Partial<InsightNote>) => void;
  onRemove: (id: string) => void;
}) {
  const [promptsOpen, setPromptsOpen] = useState(false);
  const prompts = INSIGHT_PROMPTS[source];
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid={`champion-insights-${source}`}>
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-foreground">{INSIGHT_SOURCE_LABEL[source]}</h4>
        {!disabled ? (
          <button
            type="button"
            onClick={() => onAdd()}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-xs font-medium text-foreground hover:bg-accent"
          >
            <MessageSquarePlus className="h-3.5 w-3.5" aria-hidden="true" />
            Dodaj notatkę
          </button>
        ) : null}
      </div>
      {!disabled ? (
        <div>
          <button
            type="button"
            onClick={() => setPromptsOpen((v) => !v)}
            aria-expanded={promptsOpen}
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            {promptsOpen ? (
              <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            O co zapytać ({prompts.length})
          </button>
          {promptsOpen ? (
            <ul className="mt-1.5 flex flex-col gap-1">
              {prompts.map((prompt) => (
                <li key={prompt.question}>
                  <button
                    type="button"
                    onClick={() => onAdd(prompt.topic)}
                    className="w-full rounded-md px-2 py-1 text-left text-xs text-foreground hover:bg-accent"
                  >
                    {prompt.question}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      {notes.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          {source === "client"
            ? "Brak notatek z rozmowy z klientem."
            : "Brak notatek od konsultanta, który pracuje u tego klienta."}
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {notes.map((note) => (
            <InsightCard
              key={note.id}
              note={note}
              disabled={disabled || !note.editable}
              editing={editingId === note.id}
              onEdit={() => onEdit(editingId === note.id ? null : note.id)}
              onPatch={(patch) => onPatch(note.id, patch)}
              onRemove={() => onRemove(note.id)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function InsightCard({
  note,
  disabled,
  editing,
  onEdit,
  onPatch,
  onRemove,
}: {
  note: InsightNote;
  disabled: boolean;
  editing: boolean;
  onEdit: () => void;
  onPatch: (patch: Partial<InsightNote>) => void;
  onRemove: () => void;
}) {
  const origin = insightOriginLabel(note);
  const prompt = INSIGHT_PROMPTS[note.source].find((p) => p.topic === note.topic)?.question;
  const when = note.updated_at || note.created_at;
  return (
    <li
      className="flex flex-col gap-1.5 rounded-md border border-border bg-card p-2"
      data-testid="champion-insight-card"
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="outline" size="sm">
          {INSIGHT_TOPIC_LABEL[note.topic]}
        </Badge>
        {origin ? (
          <Badge variant="info" size="sm">
            {origin}
          </Badge>
        ) : null}
        <AudienceToggle
          value={note.audience}
          disabled={disabled}
          onChange={(audience) => onPatch({ audience })}
        />
        {!disabled ? (
          <span className="ml-auto inline-flex items-center gap-0.5">
            <button
              type="button"
              onClick={onEdit}
              aria-label={editing ? "Zakończ edycję notatki" : "Edytuj notatkę"}
              className="rounded p-1 text-muted-foreground hover:text-foreground"
            >
              <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
            <button
              type="button"
              onClick={onRemove}
              aria-label="Usuń notatkę"
              className="rounded p-1 text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
            </button>
          </span>
        ) : null}
      </div>
      {editing && !disabled ? (
        <div className="flex flex-col gap-1.5">
          <select
            value={note.topic}
            onChange={(e) => onPatch({ topic: e.target.value as InsightTopic })}
            aria-label="Temat notatki"
            className="w-full rounded-md border border-border bg-card px-2 py-1 text-xs"
          >
            {(Object.keys(INSIGHT_TOPIC_LABEL) as InsightTopic[])
              .filter((t) => t !== "ask_client")
              .map((topic) => (
                <option key={topic} value={topic}>
                  {INSIGHT_TOPIC_LABEL[topic]}
                </option>
              ))}
          </select>
          <textarea
            autoFocus
            value={note.text}
            onChange={(e) => onPatch({ text: e.target.value })}
            rows={3}
            maxLength={2000}
            aria-label="Treść notatki"
            placeholder={prompt ?? "Co usłyszałeś w rozmowie?"}
            className="w-full resize-y rounded-md border border-border bg-card px-2 py-1 text-xs"
          />
        </div>
      ) : (
        <p className="whitespace-pre-line text-xs text-foreground">
          {note.text || <span className="text-muted-foreground">(pusta — uzupełnij albo usuń)</span>}
        </p>
      )}
      <p className="text-[10px] text-muted-foreground">
        {note.consultant_name ? `Rozmowa z: ${note.consultant_name} · ` : ""}
        {note.author_name ? note.author_name : note.origin === "manual" ? "Ty (niezapisane)" : ""}
        {when ? ` · ${formatDate(when)}` : ""}
        {note.origin === "verification" ? " · zmień przez ponowną weryfikację w doku „Gotowość”" : ""}
      </p>
    </li>
  );
}

function AudienceToggle({
  value,
  disabled,
  onChange,
}: {
  value: InsightNote["audience"];
  disabled: boolean;
  onChange: (value: InsightNote["audience"]) => void;
}) {
  const next = value === "team" ? "candidate" : "team";
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange(next)}
      aria-label={`Widoczność: ${INSIGHT_AUDIENCE_LABEL[value]}. Zmień na: ${INSIGHT_AUDIENCE_LABEL[next]}`}
      className={cn(
        "rounded-full px-2 py-0.5 text-[10px] font-medium",
        value === "candidate"
          ? "bg-primary text-primary-foreground"
          : "bg-muted text-muted-foreground",
        disabled && "cursor-default",
      )}
    >
      {INSIGHT_AUDIENCE_LABEL[value]}
    </button>
  );
}

function AskClientChecklist({
  items,
  disabled,
  onToggle,
  onRemove,
}: {
  items: InsightNote[];
  disabled: boolean;
  onToggle: (id: string, done: boolean) => void;
  onRemove: (id: string) => void;
}) {
  const open = items.filter((i) => !i.done).length;
  return (
    <div className="rounded-lg border border-warning/30 bg-warning-muted p-3" data-testid="champion-ask-client">
      <h4 className="text-sm font-semibold text-warning-muted-foreground">
        Do dopytania u klienta · {open} z {items.length}
      </h4>
      <ul className="mt-1.5 flex flex-col gap-1">
        {items.map((item) => (
          <li key={item.id} className="flex items-start gap-2 text-xs">
            <input
              type="checkbox"
              checked={Boolean(item.done)}
              disabled={disabled}
              onChange={(e) => onToggle(item.id, e.target.checked)}
              aria-label={`Dopytane: ${item.text}`}
              className="mt-0.5"
            />
            <span className={cn("flex-1 text-foreground", item.done && "line-through opacity-60")}>
              {item.text}
            </span>
            {!disabled ? (
              <button
                type="button"
                onClick={() => onRemove(item.id)}
                aria-label={`Usuń: ${item.text}`}
                className="rounded p-0.5 text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="h-3 w-3" aria-hidden="true" />
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-[11px] text-muted-foreground">
        Odpowiedzi klienta zapisz jako notatki w kolumnie „{INSIGHT_SOURCE_LABEL.client}”.
      </p>
    </div>
  );
}

function ClientHistoryBlock({
  jobId,
  history,
  hasClient,
  disabled,
  onHistory,
  onPromote,
}: {
  jobId: number;
  history: ClientHistorySummary | undefined;
  hasClient: boolean;
  disabled: boolean;
  onHistory: (history: ClientHistorySummary) => void;
  onPromote: (topic: InsightTopic, text: string) => void;
}) {
  const refresh = useMutation({
    mutationFn: () => championApi.refreshClientHistory(jobId).then((r) => r.data),
    onSuccess: (data) => {
      const next = data.champion_profile?.client_history;
      if (next) onHistory(next);
    },
  });
  const status = history?.status ?? "none";
  const items = history?.items ?? [];
  const questions = history?.debrief_questions ?? [];

  return (
    <div className="rounded-lg border border-border bg-muted/40 p-3" data-testid="champion-client-history">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="inline-flex items-center gap-1.5 text-sm font-semibold text-foreground">
          <History className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
          Z historii klienta
          <Badge variant="outline" size="sm">
            AI
          </Badge>
        </h4>
        {hasClient && !disabled ? (
          <button
            type="button"
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
            className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-0.5 text-xs font-medium text-foreground hover:bg-accent disabled:opacity-60"
          >
            {refresh.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {status === "none" ? "Podsumuj historię klienta" : "Odśwież"}
          </button>
        ) : null}
      </div>
      {!hasClient ? (
        <p className="mt-1.5 text-xs text-muted-foreground">
          Rekrutacja nie ma klienta — nie ma czyjej historii podsumować.
        </p>
      ) : refresh.isError ? (
        <p className="mt-1.5 text-xs text-destructive" role="alert">
          {apiErrorMessage(refresh.error, "Nie udało się podsumować historii klienta.")}
        </p>
      ) : status === "none" ? (
        <p className="mt-1.5 text-xs text-muted-foreground">
          Jeszcze nie podsumowano. AI przejrzy werdykty hiring managerów, odrzucenia po
          wysłaniu CV i zastrzeżenia kandydatów u tego klienta z ostatnich 18 miesięcy.
        </p>
      ) : (
        <>
          {history?.message ? (
            <p
              className={cn(
                "mt-1.5 text-xs",
                status === "failed" ? "text-destructive" : "text-muted-foreground",
              )}
            >
              {history.message}
            </p>
          ) : null}
          {items.length > 0 ? (
            <ul className="mt-2 flex flex-col gap-1.5">
              {items.map((item, i) => (
                <li key={`${item.text}-${i}`} className="flex items-start gap-2 text-xs text-foreground">
                  <span className="flex-1">
                    {item.text}
                    {typeof item.basis_count === "number" ? (
                      <span className="text-muted-foreground"> ({item.basis_count} zdarz.)</span>
                    ) : null}
                  </span>
                  {!disabled ? (
                    <button
                      type="button"
                      onClick={() => onPromote(TOPIC_FROM_HISTORY[item.topic] ?? "other", item.text)}
                      title="Przenieś do notatek (możesz ją potem poprawić)"
                      aria-label={`Przenieś do notatek: ${item.text}`}
                      className="rounded p-0.5 text-muted-foreground hover:text-foreground"
                    >
                      <ArrowDownToLine className="h-3.5 w-3.5" aria-hidden="true" />
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
          {questions.length > 0 ? (
            <div className="mt-2">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Pytania klienta z poprzednich rozmów
              </p>
              <ul className="mt-1 list-disc pl-4 text-xs text-foreground">
                {questions.map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {history?.generated_at ? (
            <p className="mt-2 text-[10px] text-muted-foreground">
              Podsumowano {formatDate(history.generated_at)}
              {typeof history.event_count === "number" ? ` · ${history.event_count} zdarzeń` : ""}
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("pl-PL", { day: "numeric", month: "short", year: "numeric" });
}
