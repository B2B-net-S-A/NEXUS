"use client";

/**
 * Ustawienia → Rekrutacja → Słownik umiejętności (admin + Head of Recruitment).
 *
 * Jedyna część Cortexa, która przeżyła jego usunięcie (23.09.2026): dodanie
 * umiejętności, aliasy i mapowanie nieznanych terminów. Każdy zapis odświeża
 * aliasy scoringu po stronie serwera, więc wyszukiwarka i dopasowanie widzą
 * zmianę od razu. Backend: `/api/skills-admin` (bramka HoR+ i zapis Sourcing).
 */

import { useState, type FormEvent } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Loader2, Plus } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  skillsAdminApi,
  type SkillDictionaryItem,
  type UnmatchedSkillTerm,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { pluralPl } from "@/lib/plural-pl";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { resolveViewState } from "@/lib/view-state";

const PAGE_SIZE = 50;

export const skillDictionaryQueryKey = ["skills-admin", "skills"] as const;
export const unmatchedTermsQueryKey = ["skills-admin", "unmatched-terms"] as const;

function parseAliases(raw: string): string[] {
  return raw
    .split(",")
    .map((alias) => alias.trim())
    .filter(Boolean);
}

function AliasForm({ skill, onDone }: { skill: SkillDictionaryItem; onDone: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [alias, setAlias] = useState("");
  const mutation = useMutation({
    mutationFn: () => skillsAdminApi.addAlias(skill.id, alias.trim()),
    onSuccess: (result) => {
      toast.showSuccess(
        result.inserted
          ? `Dodano alias „${result.alias}” do ${skill.name}`
          : `Alias „${result.alias}” już jest w słowniku`,
      );
      void queryClient.invalidateQueries({ queryKey: skillDictionaryQueryKey });
      onDone();
    },
    onError: (e) => toast.showError(apiErrorMessage(e, "Nie udało się dodać aliasu")),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (alias.trim()) mutation.mutate();
  };
  return (
    <form onSubmit={submit} className="mt-2 flex items-center gap-2">
      <Input
        value={alias}
        onChange={(e) => setAlias(e.target.value)}
        placeholder="Nowy alias, np. reactjs"
        aria-label={`Nowy alias dla ${skill.name}`}
        className="h-8 max-w-xs"
        autoFocus
      />
      <Button type="submit" size="sm" disabled={!alias.trim() || mutation.isPending}>
        Dodaj
      </Button>
      <Button type="button" size="sm" variant="ghost" onClick={onDone}>
        Anuluj
      </Button>
    </form>
  );
}

function SkillRow({ skill }: { skill: SkillDictionaryItem }) {
  const [adding, setAdding] = useState(false);
  return (
    <li className="px-3 py-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-foreground">
            {skill.name}
            {skill.category ? (
              <span className="ml-2 text-xs font-normal text-muted-foreground">{skill.category}</span>
            ) : null}
          </p>
          {skill.aliases.length > 0 ? (
            <ul className="mt-1 flex flex-wrap gap-1" aria-label={`Aliasy: ${skill.name}`}>
              {skill.aliases.map((alias) => (
                <li
                  key={alias}
                  className="inline-flex h-6 items-center rounded-full bg-muted px-2 text-xs text-muted-foreground"
                >
                  {alias}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-xs text-muted-foreground">Bez aliasów</p>
          )}
        </div>
        {!adding ? (
          <Button type="button" size="sm" variant="outline" onClick={() => setAdding(true)}>
            Dodaj alias
          </Button>
        ) : null}
      </div>
      {adding ? <AliasForm skill={skill} onDone={() => setAdding(false)} /> : null}
    </li>
  );
}

function CreateSkillForm() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [aliases, setAliases] = useState("");
  const mutation = useMutation({
    mutationFn: () =>
      skillsAdminApi.create({ canonical_name: name.trim(), aliases: parseAliases(aliases) }),
    onSuccess: (created) => {
      toast.showSuccess(`Dodano umiejętność „${created.canonical_name}”`);
      setName("");
      setAliases("");
      void queryClient.invalidateQueries({ queryKey: skillDictionaryQueryKey });
    },
    onError: (e) => toast.showError(apiErrorMessage(e, "Nie udało się dodać umiejętności")),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (name.trim()) mutation.mutate();
  };
  return (
    <form
      onSubmit={submit}
      className="grid gap-2 rounded-xl border border-border p-4 sm:grid-cols-[1fr_1fr_auto]"
      aria-label="Nowa umiejętność"
    >
      <Input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Nazwa, np. Apache Kafka"
        aria-label="Nazwa umiejętności"
      />
      <Input
        value={aliases}
        onChange={(e) => setAliases(e.target.value)}
        placeholder="Aliasy po przecinku (opcjonalnie)"
        aria-label="Aliasy nowej umiejętności"
      />
      <Button type="submit" disabled={!name.trim() || mutation.isPending}>
        <Plus className="mr-1 h-4 w-4" aria-hidden />
        Dodaj umiejętność
      </Button>
    </form>
  );
}

function MapTermPicker({ term, onDone }: { term: UnmatchedSkillTerm; onDone: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const debounced = useDebouncedValue(q.trim(), 300);
  const matches = useQuery({
    queryKey: [...skillDictionaryQueryKey, "picker", debounced],
    queryFn: () => skillsAdminApi.list({ q: debounced, limit: 8 }),
    enabled: debounced.length > 0,
  });
  const mutation = useMutation({
    mutationFn: (skill: SkillDictionaryItem) => skillsAdminApi.mapTerm(term.id, skill.id),
    onSuccess: (_data, skill) => {
      toast.showSuccess(`„${term.term}” to teraz alias ${skill.name}`);
      void queryClient.invalidateQueries({ queryKey: ["skills-admin"] });
      onDone();
    },
    onError: (e) => toast.showError(apiErrorMessage(e, "Nie udało się zmapować terminu")),
  });
  return (
    <div className="mt-2 space-y-2">
      <Input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Szukaj umiejętności…"
        aria-label={`Umiejętność dla terminu ${term.term}`}
        className="h-8 max-w-xs"
        autoFocus
      />
      {matches.isSuccess && matches.data.items.length === 0 ? (
        <p className="text-xs text-muted-foreground">Nic nie pasuje — dodaj ją jako nową umiejętność.</p>
      ) : null}
      {matches.isError ? (
        <p className="text-xs text-destructive">Nie udało się wyszukać umiejętności.</p>
      ) : null}
      {matches.isSuccess && matches.data.items.length > 0 ? (
        <ul className="flex flex-wrap gap-1.5">
          {matches.data.items.map((skill) => (
            <li key={skill.id}>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={mutation.isPending}
                onClick={() => mutation.mutate(skill)}
              >
                {skill.name}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      <Button type="button" size="sm" variant="ghost" onClick={onDone}>
        Anuluj
      </Button>
    </div>
  );
}

function UnmatchedTermRow({ term }: { term: UnmatchedSkillTerm }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [mapping, setMapping] = useState(false);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["skills-admin"] });
  const createMutation = useMutation({
    mutationFn: () => skillsAdminApi.create({ canonical_name: term.term, from_term_id: term.id }),
    onSuccess: () => {
      toast.showSuccess(`Dodano umiejętność „${term.term}”`);
      refresh();
    },
    onError: (e) => toast.showError(apiErrorMessage(e, "Nie udało się dodać umiejętności")),
  });
  const ignoreMutation = useMutation({
    mutationFn: () => skillsAdminApi.ignoreTerm(term.id),
    onSuccess: () => {
      toast.showSuccess(`„${term.term}” oznaczony jako ignorowany`);
      refresh();
    },
    onError: (e) => toast.showError(apiErrorMessage(e, "Nie udało się zignorować terminu")),
  });
  const busy = createMutation.isPending || ignoreMutation.isPending;
  return (
    <li className="px-3 py-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-foreground">
          <span className="font-medium">{term.term}</span>
          <span className="ml-2 text-xs text-muted-foreground">
            {term.occurrences} {pluralPl(term.occurrences, "wystąpienie", "wystąpienia", "wystąpień")}
          </span>
        </p>
        {!mapping ? (
          <div className="flex flex-wrap gap-1.5">
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => setMapping(true)}>
              Zmapuj na umiejętność
            </Button>
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => createMutation.mutate()}>
              Nowa umiejętność
            </Button>
            <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => ignoreMutation.mutate()}>
              Ignoruj
            </Button>
          </div>
        ) : null}
      </div>
      {mapping ? <MapTermPicker term={term} onDone={() => setMapping(false)} /> : null}
    </li>
  );
}

function UnmatchedTermsSection() {
  const query = useQuery({
    queryKey: [...unmatchedTermsQueryKey, "new"],
    queryFn: () => skillsAdminApi.unmatchedTerms("new", 50),
  });
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: (query.data?.length ?? 0) === 0,
    isSuccess: query.isSuccess,
  });
  return (
    <section aria-label="Nieznane terminy" className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Nieznane terminy</h3>
        <p className="text-xs text-muted-foreground">
          Najczęstsze technologie z CV i Traffita, których słownik nie zna. Lista nie
          rośnie od 23.09.2026 — zawiera to, co zebrała dawna ekstrakcja Cortexa.
        </p>
      </div>
      {viewState === "loading" ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Ładowanie terminów…
        </p>
      ) : null}
      {viewState === "error" || viewState === "forbidden" ? (
        <QueryStateNotice state={viewState} onRetry={() => void query.refetch()} />
      ) : null}
      {viewState === "empty" ? (
        <p className="text-sm text-muted-foreground">Nie ma nieznanych terminów do przejrzenia.</p>
      ) : null}
      {viewState === "ready" && query.data ? (
        <ul className="divide-y divide-border rounded-xl border border-border text-sm">
          {query.data.map((term) => (
            <UnmatchedTermRow key={term.id} term={term} />
          ))}
        </ul>
      ) : null}
    </section>
  );
}

export function SkillDictionaryTab() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const debounced = useDebouncedValue(search.trim(), 300);
  const query = useQuery({
    queryKey: [...skillDictionaryQueryKey, debounced, page],
    queryFn: () =>
      skillsAdminApi.list({ q: debounced, limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const data = query.data;
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: (data?.items.length ?? 0) === 0,
    isSuccess: query.isSuccess,
  });
  const total = data?.total ?? 0;
  const lastPage = Math.max(0, Math.ceil(total / PAGE_SIZE) - 1);

  return (
    <div className="space-y-6 rounded-2xl border border-border bg-card p-6">
      <div className="flex items-start gap-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10">
          <BookOpen className="h-6 w-6 text-primary" aria-hidden />
        </div>
        <div>
          <h2 className="text-base font-bold text-foreground">Słownik umiejętności</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Nazwy technologii i ich aliasy, po których wyszukiwarka i dopasowanie
            rozpoznają umiejętności kandydatów. Nowy alias działa od razu.
          </p>
        </div>
      </div>

      <CreateSkillForm />

      <section aria-label="Umiejętności" className="space-y-3">
        <Input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(0);
          }}
          placeholder="Szukaj po nazwie albo aliasie…"
          aria-label="Szukaj umiejętności"
          className="max-w-sm"
        />
        {viewState === "loading" ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Ładowanie słownika…
          </p>
        ) : null}
        {viewState === "error" || viewState === "forbidden" ? (
          <QueryStateNotice
            state={viewState}
            description={
              viewState === "forbidden"
                ? "Słownik umiejętności prowadzi administrator i Head of Recruitment."
                : undefined
            }
            onRetry={() => void query.refetch()}
          />
        ) : null}
        {viewState === "empty" ? (
          <p className="text-sm text-muted-foreground">
            {debounced ? "Żadna umiejętność nie pasuje do wyszukiwania." : "Słownik jest pusty."}
          </p>
        ) : null}
        {viewState === "ready" && data ? (
          <>
            <p className="text-sm text-muted-foreground">
              {total} {pluralPl(total, "umiejętność", "umiejętności", "umiejętności")}
            </p>
            <ul className="divide-y divide-border rounded-xl border border-border text-sm">
              {data.items.map((skill) => (
                <SkillRow key={skill.id} skill={skill} />
              ))}
            </ul>
            {lastPage > 0 ? (
              <div className="flex items-center justify-between text-sm">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                >
                  Poprzednia
                </Button>
                <span className="text-muted-foreground">
                  Strona {page + 1} z {lastPage + 1}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={page >= lastPage}
                  onClick={() => setPage((p) => Math.min(lastPage, p + 1))}
                >
                  Następna
                </Button>
              </div>
            ) : null}
          </>
        ) : null}
      </section>

      <UnmatchedTermsSection />
    </div>
  );
}

export default SkillDictionaryTab;
