"use client";

/**
 * Słownik umiejętności → „Po ludzku”: słowniczek technologii dla rekruterów.
 *
 * Hasło jest wspólne dla wszystkich rekrutacji — blok „Po ludzku” w Podglądzie
 * Championa czyta je stąd (kolumny „Po ludzku”, „W CV szukaj”, „Nie myl z”).
 * Opis powstaje sam (AI z publicznych źródeł albo zasiew); poprawka ręczna
 * zmienia go wszędzie i zostaje w historii. Zakres: hasła ze słownika
 * umiejętności i spoza niego (np. dziedziny, regulacje z profilu).
 */

import { useState, type FormEvent } from "react";
import { Loader2 } from "lucide-react";

import { SourceLinks, WebOriginChip } from "@/components/champion/plain/PlainBits";
import { PlainChangeHistory } from "@/components/settings/PlainChangeHistory";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  usePlainTermHistory,
  usePlainTerms,
  useUpdatePlainTerm,
  type PlainTerm,
  type PlainTermScope,
} from "@/lib/api/plainKnowledge";
import { countPl } from "@/lib/plural-pl";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn, formatDate } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

const SCOPES: { id: PlainTermScope; label: string }[] = [
  { id: "all", label: "Wszystkie" },
  { id: "dictionary", label: "Ze słownika" },
  { id: "outside", label: "Spoza słownika" },
];

const ORIGIN_LABEL: Record<string, string> = {
  // „seed” = baza startowa z researchu w internecie, „ai” = research przy nowej rekrutacji.
  seed: "opis z internetu",
  ai: "dodane automatycznie",
  manual: "poprawione ręcznie",
};

function TermHistory({ id }: { id: number }) {
  const query = usePlainTermHistory(id);
  if (query.isLoading) return <p className="text-xs text-muted-foreground">Ładowanie historii…</p>;
  if (query.isError) {
    return (
      <p className="text-xs text-muted-foreground" role="alert">
        Nie udało się wczytać historii.{" "}
        <button type="button" className="font-medium text-primary hover:underline" onClick={() => void query.refetch()}>
          Ponów
        </button>
      </p>
    );
  }
  return <PlainChangeHistory entries={query.data ?? []} />;
}

function TermEditor({ term, onDone }: { term: PlainTerm; onDone: () => void }) {
  const toast = useToast();
  const update = useUpdatePlainTerm(term.id);
  const [form, setForm] = useState({
    display_name: term.display_name,
    summary: term.summary ?? "",
    does: term.does ?? "",
    cv_hints: term.cv_hints.join(", "),
    confused_with: term.confused_with ?? "",
  });
  const set = (key: keyof typeof form) => (value: string) => setForm((f) => ({ ...f, [key]: value }));
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!form.display_name.trim()) return;
    update.mutate(
      {
        display_name: form.display_name.trim(),
        summary: form.summary.trim(),
        does: form.does.trim(),
        cv_hints: form.cv_hints
          .split(",")
          .map((h) => h.trim())
          .filter(Boolean),
        confused_with: form.confused_with.trim(),
      },
      {
        onSuccess: () => {
          toast.showSuccess(`Zapisano „${form.display_name.trim()}”`);
          onDone();
        },
        onError: (e) => toast.showError(apiErrorMessage(e, "Nie udało się zapisać hasła")),
      },
    );
  };
  return (
    <form onSubmit={submit} className="mt-2 space-y-2" aria-label={`Edycja: ${term.display_name}`}>
      <Input
        value={form.display_name}
        onChange={(e) => set("display_name")(e.target.value)}
        aria-label="Nazwa"
        className="h-8"
      />
      <Textarea rows={2} value={form.summary} onChange={(e) => set("summary")(e.target.value)} aria-label="Po ludzku" placeholder="Po ludzku — jedno zdanie" />
      <Textarea rows={2} value={form.does} onChange={(e) => set("does")(e.target.value)} aria-label="Do czego służy" placeholder="Do czego służy" />
      <Input
        value={form.cv_hints}
        onChange={(e) => set("cv_hints")(e.target.value)}
        aria-label="W CV szukaj"
        placeholder="W CV szukaj — po przecinku"
        className="h-8"
      />
      <Textarea rows={2} value={form.confused_with} onChange={(e) => set("confused_with")(e.target.value)} aria-label="Nie myl z" placeholder="Nie myl z…" />
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={!form.display_name.trim() || update.isPending}>
          {update.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
          Zapisz
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDone}>
          Anuluj
        </Button>
      </div>
    </form>
  );
}

function TermRow({ term }: { term: PlainTerm }) {
  const [editing, setEditing] = useState(false);
  const [history, setHistory] = useState(false);
  return (
    <li className="px-3 py-2.5" data-testid="plain-term-row">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 font-medium text-foreground">
            {term.display_name}
            {!term.in_dictionary ? (
              <span className="text-xs font-normal text-muted-foreground">spoza słownika</span>
            ) : null}
            {term.origin === "ai" ? <WebOriginChip /> : null}
          </p>
          {term.summary ? (
            <p className="mt-0.5 break-words text-[13px] text-foreground">{term.summary}</p>
          ) : (
            <p className="mt-0.5 text-[13px] italic text-muted-foreground">
              {term.status === "researching" ? "Szukam opisu…" : "Brak opisu"}
            </p>
          )}
          {term.cv_hints.length > 0 ? (
            <p className="mt-0.5 break-words text-xs text-muted-foreground">W CV szukaj: {term.cv_hints.join(", ")}</p>
          ) : null}
          {term.confused_with ? (
            <p className="mt-0.5 break-words text-xs text-muted-foreground">Nie myl z: {term.confused_with}</p>
          ) : null}
          <SourceLinks sources={term.sources} className="mt-1" />
          <p className="mt-1 text-[11px] text-muted-foreground">
            {term.origin ? ORIGIN_LABEL[term.origin] ?? term.origin : "bez opisu"}
            {term.updated_at ? ` · ${formatDate(term.updated_at)}` : ""}
            {term.updated_by_name ? ` · ${term.updated_by_name}` : ""}
          </p>
        </div>
        {!editing ? (
          <div className="flex shrink-0 gap-2">
            <Button type="button" size="sm" variant="ghost" onClick={() => setHistory((v) => !v)}>
              {history ? "Ukryj historię" : "Historia"}
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={() => setEditing(true)}>
              Popraw
            </Button>
          </div>
        ) : null}
      </div>
      {editing ? <TermEditor term={term} onDone={() => setEditing(false)} /> : null}
      {history ? (
        <div className="mt-2">
          <TermHistory id={term.id} />
        </div>
      ) : null}
    </li>
  );
}

export function PlainTermsSection() {
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState<PlainTermScope>("all");
  const debounced = useDebouncedValue(search.trim(), 300);
  const query = usePlainTerms({ q: debounced, scope });
  const items = query.data?.items ?? [];
  const total = query.data?.total ?? items.length;
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: items.length === 0,
    isSuccess: query.isSuccess,
  });

  return (
    <section aria-label="Po ludzku" className="space-y-3 border-t border-border pt-5" data-testid="plain-terms">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Po ludzku</h3>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Słowniczek dla rekruterów: co dana technologia robi, po czym poznać ją w CV i z czym jej
          nie mylić. Poprawka zmienia definicję we wszystkich rekrutacjach i zostaje w historii zmian.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Szukaj hasła…"
          aria-label="Szukaj hasła po ludzku"
          className="max-w-xs"
        />
        <div role="group" aria-label="Zakres" className="inline-flex rounded-lg border border-border p-0.5">
          {SCOPES.map((s) => (
            <button
              key={s.id}
              type="button"
              aria-pressed={scope === s.id}
              onClick={() => setScope(s.id)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium",
                scope === s.id ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
      {state === "loading" ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Ładowanie słowniczka…
        </p>
      ) : null}
      {state === "error" || state === "forbidden" || state === "not_found" ? (
        <QueryStateNotice state={state} onRetry={() => void query.refetch()} />
      ) : null}
      {state === "empty" ? (
        <p className="text-sm text-muted-foreground">
          {debounced ? "Żadne hasło nie pasuje do wyszukiwania." : "Słowniczek jest jeszcze pusty."}
        </p>
      ) : null}
      {state === "ready" ? (
        <>
          <p className="text-sm text-muted-foreground">
            {total > items.length
              ? `Pokazano ${items.length} z ${countPl(total, "hasła", "haseł", "haseł")} — zawęź wyszukiwaniem.`
              : countPl(items.length, "hasło", "hasła", "haseł")}
          </p>
          <ul className="divide-y divide-border rounded-xl border border-border text-sm">
            {items.map((term) => (
              <TermRow key={term.id} term={term} />
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
