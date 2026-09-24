"use client";

/**
 * Akademia — ustawienia programu: kryteria sortowania Luny, pytania na
 * telefon, pojemność terminów i ogłoszenia-źródła. Zmienia je admin albo
 * Head of Recruitment (`can_manage` z backendu); reszta widzi tylko odczyt.
 */

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { shortDate, toIsoDate } from "@/lib/academy-flow";
import type {
  AcademyProgramDetail,
  JobOption,
  ProgramInput,
} from "@/lib/api/academy";

export function AcademySettingsView({
  program,
  onSave,
  onAddSource,
  onRemoveSource,
  searchJobs,
}: {
  program: AcademyProgramDetail;
  onSave: (patch: Partial<ProgramInput>) => Promise<void>;
  onAddSource: (jobId: number, since: string | null) => Promise<void>;
  onRemoveSource: (jobId: number) => Promise<void>;
  searchJobs: (q: string) => Promise<JobOption[]>;
}) {
  const readOnly = !program.can_manage;
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <ProgramForm program={program} onSave={onSave} readOnly={readOnly} />
      <SourcesPanel
        program={program}
        readOnly={readOnly}
        onAddSource={onAddSource}
        onRemoveSource={onRemoveSource}
        searchJobs={searchJobs}
      />
    </div>
  );
}

function ProgramForm({
  program,
  onSave,
  readOnly,
}: {
  program: AcademyProgramDetail;
  onSave: (patch: Partial<ProgramInput>) => Promise<void>;
  readOnly: boolean;
}) {
  const [name, setName] = React.useState(program.name);
  const [maxYears, setMaxYears] = React.useState(program.max_experience_years);
  const [requirePolish, setRequirePolish] = React.useState(program.require_polish);
  const [luna, setLuna] = React.useState(program.luna_enabled);
  const [conditions, setConditions] = React.useState(program.conditions.join("\n"));
  const [capacity, setCapacity] = React.useState(program.session_capacity);
  const [taskDays, setTaskDays] = React.useState(program.task_due_days);
  const [active, setActive] = React.useState(program.is_active);
  const [busy, setBusy] = React.useState(false);
  const ids = {
    name: React.useId(),
    years: React.useId(),
    cond: React.useId(),
    cap: React.useId(),
    days: React.useId(),
  };
  const field = "rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground disabled:opacity-70";

  return (
    <section className="space-y-4 rounded-xl border border-border bg-card p-5">
      <div>
        <h2 className="text-base font-semibold">Program</h2>
        {readOnly ? (
          <p className="text-xs text-muted-foreground">Ustawienia zmienia admin albo Head of Recruitment.</p>
        ) : null}
      </div>
      <label htmlFor={ids.name} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
        Nazwa
        <input id={ids.name} className={field} value={name} disabled={readOnly} onChange={(e) => setName(e.target.value)} />
      </label>
      <fieldset className="space-y-3 rounded-lg border border-border p-4">
        <legend className="px-1 text-sm font-semibold">Sortowanie Luny</legend>
        <label htmlFor={ids.years} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Doświadczenie najwyżej (lat, liczone od końca studiów; bez studiów — cała praca)
          <input
            id={ids.years}
            type="number"
            min={0}
            max={40}
            className={`${field} w-28`}
            value={maxYears}
            disabled={readOnly}
            onChange={(e) => setMaxYears(Number(e.target.value))}
          />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={requirePolish} disabled={readOnly} onChange={(e) => setRequirePolish(e.target.checked)} />
          Polski na poziomie ojczystym albo biegłym
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={luna} disabled={readOnly} onChange={(e) => setLuna(e.target.checked)} />
          Luna czyta CV, gdy profilowi brakuje dat albo poziomu polskiego
        </label>
        <p className="text-xs text-muted-foreground">
          Luna tylko sortuje. Odkłada osoby niespełniające kryteriów, a wykluczenie zawsze
          zatwierdza człowiek. Sortowanie nie bierze pod uwagę imienia, nazwiska,
          narodowości ani wieku.
        </p>
      </fieldset>
      <label htmlFor={ids.cond} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
        Pytania na telefon (jedno w linii)
        <textarea
          id={ids.cond}
          rows={4}
          className={field}
          value={conditions}
          disabled={readOnly}
          onChange={(e) => setConditions(e.target.value)}
          placeholder={"Umowa zlecenie — pasuje?\nPraca stacjonarna w biurze — pasuje?"}
        />
      </label>
      <div className="flex flex-wrap gap-4">
        <label htmlFor={ids.cap} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Miejsc na spotkaniu
          <input id={ids.cap} type="number" min={1} max={200} className={`${field} w-28`} value={capacity} disabled={readOnly} onChange={(e) => setCapacity(Number(e.target.value))} />
        </label>
        <label htmlFor={ids.days} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
          Dni na zadanie
          <input id={ids.days} type="number" min={1} max={60} className={`${field} w-28`} value={taskDays} disabled={readOnly} onChange={(e) => setTaskDays(Number(e.target.value))} />
        </label>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={active} disabled={readOnly} onChange={(e) => setActive(e.target.checked)} />
        Nabór aktywny (automat pobiera zgłoszenia co 10 minut)
      </label>
      {!readOnly ? (
        <Button
          disabled={busy || name.trim().length < 2}
          onClick={async () => {
            setBusy(true);
            try {
              await onSave({
                name: name.trim(),
                max_experience_years: maxYears,
                require_polish: requirePolish,
                luna_enabled: luna,
                conditions: conditions
                  .split("\n")
                  .map((c) => c.trim())
                  .filter(Boolean),
                session_capacity: capacity,
                task_due_days: taskDays,
                is_active: active,
              });
            } finally {
              setBusy(false);
            }
          }}
        >
          Zapisz ustawienia
        </Button>
      ) : null}
    </section>
  );
}

function SourcesPanel({
  program,
  readOnly,
  onAddSource,
  onRemoveSource,
  searchJobs,
}: {
  program: AcademyProgramDetail;
  readOnly: boolean;
  onAddSource: (jobId: number, since: string | null) => Promise<void>;
  onRemoveSource: (jobId: number) => Promise<void>;
  searchJobs: (q: string) => Promise<JobOption[]>;
}) {
  const [query, setQuery] = React.useState("");
  const [results, setResults] = React.useState<JobOption[]>([]);
  const [searching, setSearching] = React.useState(false);
  const [since, setSince] = React.useState(() => {
    const d = new Date();
    d.setDate(d.getDate() - 30);
    return toIsoDate(d);
  });
  const searchId = React.useId();
  const sinceId = React.useId();
  const known = new Set(program.sources.map((s) => s.job_id));

  React.useEffect(() => {
    if (readOnly || query.trim().length < 2) {
      setResults([]);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const timer = setTimeout(async () => {
      try {
        const items = await searchJobs(query.trim());
        if (!cancelled) setResults(items);
      } finally {
        if (!cancelled) setSearching(false);
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [query, readOnly, searchJobs]);

  return (
    <section className="space-y-4 rounded-xl border border-border bg-card p-5">
      <div>
        <h2 className="text-base font-semibold">Ogłoszenia, z których biorą się ludzie</h2>
        <p className="text-xs text-muted-foreground">
          Każda osoba z tych rekrutacji (także z importu Traffita) trafia sama na etap
          „Z ogłoszeń”. Zgłoszenia sprzed daty „od” są pomijane.
        </p>
      </div>
      {program.sources.length === 0 ? (
        <p className="rounded-md bg-muted px-3 py-3 text-sm">
          Nie podpięto jeszcze żadnego ogłoszenia — bez tego nikt nie wpadnie do naboru.
        </p>
      ) : (
        <ul className="divide-y divide-border rounded-lg border border-border">
          {program.sources.map((source) => (
            <li key={source.job_id} className="flex flex-wrap items-center gap-3 px-3 py-2 text-sm">
              <a className="min-w-0 flex-1 font-medium underline-offset-4 hover:underline" href={`/jobs/${source.job_id}`}>
                {source.title}
              </a>
              <Badge variant="outline">{source.applicants} os.</Badge>
              <span className="text-xs text-muted-foreground">
                {source.since ? `od ${shortDate(source.since)}` : "cała historia"}
              </span>
              {!readOnly ? (
                <Button variant="ghost" size="sm" onClick={() => void onRemoveSource(source.job_id)}>
                  Odepnij
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {!readOnly ? (
        <div className="space-y-3 rounded-lg border border-dashed border-border p-4">
          <div className="flex flex-wrap gap-3">
            <label htmlFor={searchId} className="flex min-w-0 flex-1 flex-col gap-1 text-xs font-medium text-muted-foreground">
              Dodaj ogłoszenie — szukaj rekrutacji po tytule albo ID
              <input
                id={searchId}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="np. Akademia Rekrutera"
                className="rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground"
              />
            </label>
            <label htmlFor={sinceId} className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
              Bierz zgłoszenia od
              <input
                id={sinceId}
                type="date"
                value={since}
                onChange={(e) => setSince(e.target.value)}
                className="rounded-md border border-border bg-card px-3 py-2 text-sm text-foreground"
              />
            </label>
          </div>
          {searching ? <p className="text-xs text-muted-foreground">Szukam…</p> : null}
          {results.length > 0 ? (
            <ul className="divide-y divide-border rounded-md border border-border">
              {results.map((job) => (
                <li key={job.id} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <span className="min-w-0 flex-1 truncate">
                    {job.title} <span className="text-xs text-muted-foreground">#{job.id}</span>
                  </span>
                  <Badge variant="outline">{job.status}</Badge>
                  <Button
                    size="sm"
                    disabled={known.has(job.id)}
                    onClick={async () => {
                      await onAddSource(job.id, since || null);
                      setQuery("");
                    }}
                  >
                    {known.has(job.id) ? "Podpięte" : "Podepnij"}
                  </Button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
