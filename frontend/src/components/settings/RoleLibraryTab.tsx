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
import { Loader2, PencilLine } from "lucide-react";

import { TabbedNav } from "@/components/ds/TabbedNav";

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

function ReadBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-1">
      <h4 className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</h4>
      {children}
    </section>
  );
}

/**
 * Opis roli do czytania — tymi samymi słowami trafia do bloku „Po ludzku”
 * rekrutacji z tą rolą. Puste pole = „—”, żeby brak był widać.
 */
function RoleReadView({ role }: { role: RoleProfileDetail }) {
  const empty = <p className="text-sm text-muted-foreground">—</p>;
  return (
    <div className="space-y-4" data-testid="role-library-read">
      <ReadBlock title="Po ludzku">
        {role.summary ? <p className="text-sm text-foreground">{role.summary}</p> : empty}
      </ReadBlock>
      <ReadBlock title="Przykład z codzienności">
        {role.example ? <p className="text-sm text-foreground">{role.example}</p> : empty}
      </ReadBlock>
      <ReadBlock title="Czym się zajmuje">
        {role.day_to_day.length > 0 ? (
          <ul className="list-disc space-y-0.5 pl-5 text-sm text-foreground">
            {role.day_to_day.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : (
          empty
        )}
      </ReadBlock>
      <ReadBlock title="O co pyta kandydat">
        {role.candidate_questions.length > 0 ? (
          <ol className="list-decimal space-y-0.5 pl-5 text-sm text-foreground">
            {role.candidate_questions.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ol>
        ) : (
          empty
        )}
      </ReadBlock>
      <ReadBlock title="Typowe technologie">
        {role.typical_skills.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {role.typical_skills.map((skill) => (
              <span key={skill} className="rounded-full bg-muted px-2 py-0.5 text-xs text-foreground">
                {skill}
              </span>
            ))}
          </div>
        ) : (
          empty
        )}
      </ReadBlock>
      <p className="text-[11px] text-muted-foreground">
        Tak opis widzi rekruter w bloku „Po ludzku” każdej rekrutacji z tą rolą.
      </p>
    </div>
  );
}

function RoleDetail({ id }: { id: number }) {
  const toast = useToast();
  const query = useRoleProfile(id);
  const update = useUpdateRoleProfile(id);
  const [form, setForm] = useState<RoleForm | null>(null);
  // Runda 2 (21.10.2026): najpierw opis do czytania, edycja pod „Edytuj” — dotąd
  // rola od razu otwierała się jako formularz z pięcioma długimi polami.
  const [editing, setEditing] = useState(false);
  const [tab, setTab] = useState<"opis" | "zrodla" | "historia">("opis");

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
        onSuccess: () => {
          toast.showSuccess(`Zapisano rolę „${form.name.trim()}”`);
          setEditing(false);
        },
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

      <div className="flex flex-wrap items-start gap-3">
        <h3 className="min-w-0 flex-1 text-base font-semibold text-foreground">{role.name}</h3>
        {!editing ? (
          <Button type="button" size="sm" onClick={() => setEditing(true)}>
            <PencilLine className="mr-1.5 h-4 w-4" aria-hidden />
            Edytuj
          </Button>
        ) : null}
      </div>

      <TabbedNav
        tabs={[
          { value: "opis", label: "Opis" },
          { value: "zrodla", label: `Źródła (${role.sources.length})` },
          { value: "historia", label: "Historia zmian" },
        ]}
        value={tab}
        onValueChange={(value) => setTab(value as typeof tab)}
        ariaLabel="Rola"
      />

      {tab === "opis" && editing ? (
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
              Cofnij zmiany
            </Button>
          ) : null}
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => {
              setForm(toForm(role));
              setEditing(false);
            }}
          >
            Zamknij edycję
          </Button>
        </div>
      </form>
      ) : null}

      {tab === "opis" && !editing ? (
        <RoleReadView role={role} />
      ) : null}

      {tab === "zrodla" ? (
        role.sources.length > 0 ? (
          <SourceLinks sources={role.sources} />
        ) : (
          <p className="text-sm text-muted-foreground">Opis bez źródeł z internetu.</p>
        )
      ) : null}

      {tab === "historia" ? <PlainChangeHistory entries={role.history ?? []} /> : null}
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
      {/* Tytuł ekranu rysuje strona Ustawień — tu tylko opis (20.10.2026). */}
      <p className="text-sm text-muted-foreground">
        Opisy ról po ludzku. Blok „Po ludzku” w każdej rekrutacji z daną rolą bierze stąd
        przykład z codzienności, typowe zadania i pytania kandydatów.
      </p>

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
