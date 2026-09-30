"use client";

/**
 * Ustawienia → Rekrutacja → Biblioteka ról (admin + Head of Recruitment).
 *
 * Rola to wspólny opis „po ludzku” (co to za praca, przykład z codzienności,
 * czym się zajmuje, o co pyta kandydat, typowe technologie), z którego
 * korzysta blok „Po ludzku” każdej rekrutacji przypiętej do tej roli.
 * Poprawka tutaj zmienia opis we wszystkich takich rekrutacjach i zostaje
 * w historii zmian. Statystyki są bez stawek.
 */

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Library, Loader2 } from "lucide-react";

import { PlainChangeHistory } from "@/components/settings/PlainChangeHistory";
import { SourceLinks, WebOriginChip } from "@/components/champion/plain/PlainBits";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useRoleProfile,
  useRoleProfiles,
  useUpdateRoleProfile,
  type PlainOrigin,
  type RoleProfileDetail,
} from "@/lib/api/plainKnowledge";
import { countPl } from "@/lib/plural-pl";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

export const ROLE_ORIGIN_LABEL: Record<PlainOrigin, string> = {
  // „seed” = baza startowa z researchu w internecie, „ai” = research przy nowej rekrutacji.
  seed: "opis z internetu",
  ai: "dodana automatycznie",
  manual: "poprawiona ręcznie",
};

const lines = (raw: string): string[] =>
  raw
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

interface RoleForm {
  name: string;
  summary: string;
  example: string;
  day_to_day: string;
  candidate_questions: string;
  typical_skills: string;
}

function toForm(role: RoleProfileDetail): RoleForm {
  return {
    name: role.name,
    summary: role.summary ?? "",
    example: role.example ?? "",
    day_to_day: role.day_to_day.join("\n"),
    candidate_questions: role.candidate_questions.join("\n"),
    typical_skills: role.typical_skills.join(", "),
  };
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-foreground">{label}</span>
      {children}
      {hint ? <span className="block text-[11px] text-muted-foreground">{hint}</span> : null}
    </label>
  );
}

function RoleDetail({ id }: { id: number }) {
  const toast = useToast();
  const query = useRoleProfile(id);
  const update = useUpdateRoleProfile(id);
  const [form, setForm] = useState<RoleForm | null>(null);

  useEffect(() => {
    if (query.data) setForm(toForm(query.data));
  }, [query.data]);

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (state === "loading" || (state === "ready" && !form)) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Ładowanie roli…
      </p>
    );
  }
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => void query.refetch()} />;
  }
  if (!query.data || !form) return null;
  const role = query.data;
  const set = (key: keyof RoleForm) => (value: string) => setForm((f) => (f ? { ...f, [key]: value } : f));
  const dirty = JSON.stringify(form) !== JSON.stringify(toForm(role));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!form.name.trim()) return;
    update.mutate(
      {
        name: form.name.trim(),
        summary: form.summary.trim(),
        example: form.example.trim(),
        day_to_day: lines(form.day_to_day),
        candidate_questions: lines(form.candidate_questions),
        typical_skills: form.typical_skills
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      },
      {
        onSuccess: () => toast.showSuccess(`Zapisano rolę „${form.name.trim()}”`),
        onError: (e) => toast.showError(apiErrorMessage(e, "Nie udało się zapisać roli")),
      },
    );
  };

  return (
    <div className="space-y-5" data-testid="role-library-detail">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>{ROLE_ORIGIN_LABEL[role.origin] ?? role.origin}</span>
        {role.origin === "ai" ? <WebOriginChip /> : null}
        {role.status === "researching" ? <span>· szukam opisu…</span> : null}
        {role.status === "failed" ? <span className="text-destructive">· opis nie powstał</span> : null}
      </div>

      <p className="text-xs text-muted-foreground" data-testid="role-library-stats">
        {countPl(role.stats.jobs, "rekrutacja", "rekrutacje", "rekrutacji")} ·{" "}
        {countPl(role.stats.clients, "klient", "klientów", "klientów")} ·{" "}
        {countPl(role.stats.hires, "zatrudniony", "zatrudnionych", "zatrudnionych")}
        {role.stats.hired_titles.length > 0
          ? ` · w CV zatrudnionych najczęściej: ${role.stats.hired_titles.map((t) => t.title).join(", ")}`
          : ""}
      </p>

      <form onSubmit={submit} className="space-y-3">
        <Field label="Nazwa">
          <Input value={form.name} onChange={(e) => set("name")(e.target.value)} />
        </Field>
        <Field label="Po ludzku (jedno–dwa zdania)">
          <Textarea rows={3} value={form.summary} onChange={(e) => set("summary")(e.target.value)} />
        </Field>
        <Field label="Przykład z codzienności">
          <Textarea rows={3} value={form.example} onChange={(e) => set("example")(e.target.value)} />
        </Field>
        <Field label="Czym się zajmuje" hint="Jedna czynność w linii.">
          <Textarea rows={4} value={form.day_to_day} onChange={(e) => set("day_to_day")(e.target.value)} />
        </Field>
        <Field label="O co pyta kandydat" hint="Jedno pytanie w linii.">
          <Textarea
            rows={4}
            value={form.candidate_questions}
            onChange={(e) => set("candidate_questions")(e.target.value)}
          />
        </Field>
        <Field label="Typowe technologie" hint="Po przecinku.">
          <Input value={form.typical_skills} onChange={(e) => set("typical_skills")(e.target.value)} />
        </Field>
        <p className="text-[11px] text-muted-foreground">
          Poprawka zmienia opis we wszystkich rekrutacjach z tą rolą i zostaje w historii zmian.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" size="sm" disabled={!dirty || !form.name.trim() || update.isPending}>
            {update.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
            Zapisz rolę
          </Button>
          {dirty ? (
            <Button type="button" size="sm" variant="ghost" onClick={() => setForm(toForm(role))}>
              Anuluj zmiany
            </Button>
          ) : null}
        </div>
      </form>

      {role.sources.length > 0 ? (
        <section className="space-y-1">
          <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Źródła</h3>
          <SourceLinks sources={role.sources} />
        </section>
      ) : null}

      <section className="space-y-1.5">
        <h3 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          Historia zmian
        </h3>
        <PlainChangeHistory entries={role.history ?? []} />
      </section>
    </div>
  );
}

export function RoleLibraryTab() {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const debounced = useDebouncedValue(search.trim(), 300);
  const query = useRoleProfiles(debounced);
  const items = query.data?.items ?? [];
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: items.length === 0,
    isSuccess: query.isSuccess,
  });
  const active = selected ?? items[0]?.id ?? null;

  return (
    <div className="space-y-5 rounded-2xl border border-border bg-card p-6" data-testid="role-library">
      <div className="flex items-start gap-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10">
          <Library className="h-6 w-6 text-primary" aria-hidden />
        </div>
        <div>
          <h2 className="text-base font-bold text-foreground">Biblioteka ról</h2>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Opisy ról po ludzku. Blok „Po ludzku” w każdej rekrutacji z daną rolą bierze stąd
            przykład z codzienności, typowe zadania i pytania kandydatów.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-2">
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Szukaj roli…"
            aria-label="Szukaj roli"
          />
          {state === "loading" ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Ładowanie ról…
            </p>
          ) : null}
          {state === "error" || state === "forbidden" || state === "not_found" ? (
            <QueryStateNotice
              state={state}
              description={
                state === "forbidden"
                  ? "Bibliotekę ról prowadzi administrator i Head of Recruitment."
                  : undefined
              }
              onRetry={() => void query.refetch()}
            />
          ) : null}
          {state === "empty" ? (
            <p className="text-sm text-muted-foreground">
              {debounced ? "Żadna rola nie pasuje do wyszukiwania." : "Biblioteka jest pusta."}
            </p>
          ) : null}
          {state === "ready" ? (
            <ul className="divide-y divide-border rounded-xl border border-border" aria-label="Role">
              {items.map((role) => (
                <li key={role.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(role.id)}
                    aria-current={role.id === active ? "true" : undefined}
                    className={cn(
                      "w-full px-3 py-2.5 text-left hover:bg-muted/40",
                      role.id === active && "bg-primary/5",
                    )}
                  >
                    <span className="block break-words text-sm font-medium text-foreground">{role.name}</span>
                    <span className="block text-[11px] text-muted-foreground">
                      {countPl(role.jobs, "rekrutacja", "rekrutacje", "rekrutacji")} ·{" "}
                      {ROLE_ORIGIN_LABEL[role.origin] ?? role.origin}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <div className="min-w-0">
          {active != null ? (
            <RoleDetail key={active} id={active} />
          ) : state === "ready" || state === "empty" ? (
            <p className="text-sm text-muted-foreground">Wybierz rolę z listy.</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default RoleLibraryTab;
