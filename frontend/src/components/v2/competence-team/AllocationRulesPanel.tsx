"use client"

/**
 * Ustawienia → Zespół rekrutacji → „Automat przydziału” (29.10.2026, wariant B
 * z makiet https://claude.ai/artifact/LoWjSGVpsx85bp5muLn8CQ).
 *
 * Administrator i Head of Recruitment ustawiają zasady automatu, a obok widzą,
 * co zrobią przy następnym przebiegu: przebieg „na sucho” na dzisiejszych
 * danych (`POST /api/competence-team/rules/preview`). Zasady działają tylko
 * na nowe przydziały — nikt nie traci rekrutacji, którą już ma.
 */

import { useEffect, useState, type ReactNode } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"

import { QueryStateNotice } from "@/components/ds/QueryStateNotice"
import { useToast } from "@/components/Toast"
import { Button } from "@/components/ui/button"
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2"
import {
  MAX_LOAD_OPTIONS,
  MODE_LABEL,
  changedRuleLabels,
  historyLines,
} from "@/lib/allocation-rules"
import { apiErrorMessage } from "@/lib/api-error"
import {
  COMPETENCE_TEAM_QUERY_KEY,
  RULES_HISTORY_QUERY_KEY,
  fetchRulesHistory,
  previewTeamRules,
  putTeamRules,
  useCompetenceTeam,
  type AllocationPreview,
  type AllocationRulesChange,
  type AllocationRunMode,
  type TeamRules,
} from "@/lib/api/requestAllocation"
import { allocationApi } from "@/lib/recruitment-allocation-api"
import { cn } from "@/lib/utils"
import { resolveViewState } from "@/lib/view-state"

const selectCls = "h-9 rounded-md border border-input bg-background px-2 text-sm text-foreground"

function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  label: string
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="inline-flex rounded-md border border-border bg-muted/40 p-0.5"
    >
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "whitespace-nowrap rounded px-3 py-1.5 text-sm",
            value === o.value
              ? "bg-card font-semibold text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Row({
  title,
  hint,
  changed,
  saved,
  children,
}: {
  title: string
  hint: string
  changed: boolean
  saved: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-2 border-t border-border py-3 first-of-type:border-t-0">
      <div className="min-w-0">
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <p className="text-xs text-muted-foreground">{hint}</p>
      </div>
      {children}
      <span
        className={cn(
          "text-xs",
          changed ? "text-warning-muted-foreground" : "text-muted-foreground",
        )}
      >
        {changed ? `zmienione · zapisane: ${saved}` : "tak jest zapisane"}
      </span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-card px-4 py-2">
      <h3 className="pt-2 text-xs font-semibold uppercase tracking-eyebrow text-primary">
        {title}
      </h3>
      {children}
    </section>
  )
}

const MODE_OPTIONS: { value: AllocationRunMode; label: string }[] = [
  { value: "off", label: MODE_LABEL.off },
  { value: "shadow", label: MODE_LABEL.shadow },
  { value: "auto", label: MODE_LABEL.auto },
]

export interface AllocationRulesForm {
  rules: TeamRules
  mode: AllocationRunMode
}

function RulesFields({
  draft,
  saved,
  set,
}: {
  draft: AllocationRulesForm
  saved: AllocationRulesForm
  set: (next: AllocationRulesForm) => void
}) {
  const rules = draft.rules
  const patch = (p: Partial<TeamRules>) => set({ ...draft, rules: { ...rules, ...p } })
  const was = saved.rules
  return (
    <>
      <Section title="Kiedy i dokąd">
        <Row
          title="Tryb"
          hint="Proponuje: przerywana ramka na pulpicie, Head of Recruitment akceptuje. Przydziela sam: osoba dostaje rekrutację od razu."
          changed={draft.mode !== saved.mode}
          saved={MODE_LABEL[saved.mode]}
        >
          <Segmented
            label="Tryb"
            value={draft.mode}
            options={MODE_OPTIONS}
            onChange={(mode) => set({ ...draft, mode })}
          />
        </Row>
        <Row
          title="Do których rekrutacji dobiera ludzi"
          hint="P0 i P1 zawsze. „Przyjmujemy kandydatów” nigdy — tam nikt nie szuka aktywnie."
          changed={rules.include_p2 !== was.include_p2}
          saved={was.include_p2 ? "P0, P1 i P2" : "P0 i P1"}
        >
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={rules.include_p2}
              onChange={(e) => patch({ include_p2: e.target.checked })}
              className="h-4 w-4 accent-primary"
            />
            Także P2
          </label>
        </Row>
        <Row
          title="Codzienny przegląd o"
          hint="Pełny przegląd przydziałów i poranny skrót do zespołu, przed daily."
          changed={rules.review_time !== was.review_time}
          saved={was.review_time}
        >
          <input
            type="time"
            aria-label="Godzina przeglądu"
            value={rules.review_time}
            onChange={(e) => patch({ review_time: e.target.value })}
            className={cn(selectCls, "w-28")}
          />
        </Row>
      </Section>
      <Section title="Ile i komu">
        <Row
          title="Osób na rekrutację P0 i P1"
          hint="Automat dokłada osobę, dopóki rekrutacja ma mniej rekruterów. P2 dostaje jedną."
          changed={rules.people_per_p1 !== was.people_per_p1}
          saved={String(was.people_per_p1)}
        >
          <select
            aria-label="Osób na rekrutację P1"
            className={cn(selectCls, "w-20")}
            value={rules.people_per_p1}
            onChange={(e) => patch({ people_per_p1: Number(e.target.value) })}
          >
            {[1, 2, 3].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </Row>
        <Row
          title="Najwięcej rekrutacji P1 na osobę"
          hint="Kto ma tyle, nie dostaje nowej P1. Rekrutacja bez wolnej osoby czeka na Head of Recruitment."
          changed={rules.max_load !== was.max_load}
          saved={was.max_load === null ? "bez limitu" : String(was.max_load)}
        >
          <select
            aria-label="Limit na osobę"
            className={cn(selectCls, "w-32")}
            value={rules.max_load ?? ""}
            onChange={(e) => patch({ max_load: e.target.value ? Number(e.target.value) : null })}
          >
            <option value="">Bez limitu</option>
            {MAX_LOAD_OPTIONS.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </Row>
        <Row
          title="Kiedy brać kogoś z innej kategorii"
          hint="Gdy najmniej obłożona osoba z kategorii ma o tyle więcej rekrutacji P1 niż najmniej obłożona w zespole."
          changed={rules.overflow !== was.overflow}
          saved={was.overflow === 0 ? "przy każdej różnicy" : `różnica ponad ${was.overflow}`}
        >
          <select
            aria-label="Przelew między kategoriami"
            className={cn(selectCls, "w-52")}
            value={rules.overflow}
            onChange={(e) => patch({ overflow: Number(e.target.value) })}
          >
            <option value={0}>Przy każdej różnicy</option>
            <option value={1}>Różnica ponad 1</option>
            <option value={2}>Różnica ponad 2</option>
            <option value={3}>Różnica ponad 3</option>
          </select>
        </Row>
        <Row
          title="Osoby bez kategorii rekrutacji"
          hint="Gdy w 1. i 2. priorytecie kategorii nie ma nikogo, kto może ją dostać."
          changed={rules.outsiders !== was.outsiders}
          saved={was.outsiders ? "mogą dostać" : "czeka na HoR"}
        >
          <Segmented
            label="Osoby bez kategorii rekrutacji"
            value={rules.outsiders ? "yes" : "no"}
            options={[
              { value: "yes", label: "Mogą dostać" },
              { value: "no", label: "Czeka na HoR" },
            ]}
            onChange={(v) => patch({ outsiders: v === "yes" })}
          />
        </Row>
      </Section>
      <Section title="Kolejność i urlopy">
        <Row
          title="Którą rekrutację obsadzić najpierw"
          hint="Najpierw P0 i P1, w ich obrębie według tej zasady."
          changed={rules.order !== was.order}
          saved={was.order === "deadline_first" ? "najpierw termin" : "najpierw bez wysłanych"}
        >
          <select
            aria-label="Kolejność"
            className={cn(selectCls, "w-72 max-w-full")}
            value={rules.order}
            onChange={(e) => patch({ order: e.target.value as TeamRules["order"] })}
          >
            <option value="sent_first">Najpierw bez wysłanych, potem termin</option>
            <option value="deadline_first">Najpierw najbliższy termin</option>
          </select>
        </Row>
        <Row
          title="Gdy brak świeżych urlopów z Compassa"
          hint="Czekaj: tryb „Przydziela sam” wstrzymuje się, żeby nie dać rekrutacji osobie na urlopie."
          changed={rules.leave_policy !== was.leave_policy}
          saved={was.leave_policy === "ignore" ? "przydziela" : "czeka"}
        >
          <Segmented
            label="Urlopy"
            value={rules.leave_policy}
            options={[
              { value: "wait", label: "Czekaj" },
              { value: "ignore", label: "Przydzielaj" },
            ]}
            onChange={(leave_policy) => patch({ leave_policy })}
          />
        </Row>
      </Section>
    </>
  )
}

function delta(now: number, before: number): string | null {
  if (now === before) return null
  return now > before ? `+${now - before}` : `${now - before}`
}

function ImpactPanel({
  preview,
  previewError,
  previewLoading,
  draft,
  changes,
  saving,
  onSave,
}: {
  preview: AllocationPreview | undefined
  previewError: unknown
  previewLoading: boolean
  draft: AllocationRulesForm
  changes: string[]
  saving: boolean
  onSave: () => void
}) {
  const modeNote: Record<AllocationRunMode, string> = {
    off: "Tryb „Wyłączony”: automat nic nie zrobi, liczby to tylko podgląd.",
    shadow: "Tryb „Proponuje”: nowe osoby pojawią się jako propozycje do akceptacji na pulpicie.",
    auto: "Tryb „Przydziela sam”: osoby dostaną rekrutacje i dzwonek przy następnym przebiegu (do 30 s po zapisie).",
  }
  return (
    <aside
      aria-label="Co się zmieni"
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4 lg:sticky lg:top-4"
    >
      <div>
        <h3 className="text-sm font-semibold text-foreground">Co się zmieni przy następnym przebiegu</h3>
        <p className="text-xs text-muted-foreground">
          Policzone na dzisiejszych rekrutacjach i obłożeniu. Już przydzielonych nikt nie traci —
          zasady działają tylko na nowe przydziały.
        </p>
      </div>
      {previewError ? (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(previewError, "Nie udało się policzyć podglądu.")}
        </p>
      ) : !preview ? (
        <div className="h-32 animate-pulse rounded-md bg-muted" aria-busy="true" />
      ) : (
        <ImpactNumbers preview={preview} draft={draft} loading={previewLoading} />
      )}
      <p className="text-xs text-muted-foreground">{modeNote[draft.mode]}</p>
      {preview?.draft.auto_waits_for_leave && draft.mode === "auto" && (
        <p className="rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground">
          Urlopy z Compassa są nieaktualne, więc „Przydziela sam” czeka. Zasada „Przydzielaj” to
          zmienia.
        </p>
      )}
      <div className="border-t border-border pt-3">
        <p className="text-xs font-semibold text-foreground">
          {changes.length ? `Zmieniasz ${changes.length}:` : "Nic nie zmieniasz."}
        </p>
        <ul className="mt-1 flex flex-col gap-0.5 text-xs text-muted-foreground">
          {changes.map((c) => (
            <li key={c}>· {c}</li>
          ))}
        </ul>
      </div>
      <Button disabled={!changes.length || saving} onClick={onSave}>
        {saving ? "Zapisuję…" : "Zapisz zasady"}
      </Button>
    </aside>
  )
}

function ImpactNumbers({
  preview,
  draft,
  loading,
}: {
  preview: AllocationPreview
  draft: AllocationRulesForm
  loading: boolean
}) {
  const { today, draft: after } = preview
  const lines: { label: string; value: string; note?: string | null; warn?: boolean }[] = [
    {
      label: "Rekrutacji, do których automat dobiera",
      value: String(after.pool),
      note: delta(after.pool, today.pool),
    },
    { label: "Z nich dziś bez nikogo", value: String(after.empty), note: delta(after.empty, today.empty) },
    {
      label: "Nowych przydziałów",
      value: String(after.new_people),
      note: delta(after.new_people, today.new_people),
      warn: after.new_people >= 20,
    },
    {
      label: "Rekrutacji, które poczekają na Head of Recruitment",
      value: String(after.waiting),
      warn: after.waiting > 0,
    },
  ]
  if (draft.rules.max_load !== null) {
    lines.push({
      label: `Osób z ${draft.rules.max_load}+ P1 (nie dostaną nowej P1)`,
      value: `${after.at_limit} z ${after.team}`,
      warn: after.at_limit * 2 > after.team,
    })
  }
  if (after.proposals_dropped > today.proposals_dropped) {
    lines.push({ label: "Propozycji automatu, które znikną", value: String(after.proposals_dropped) })
  }
  return (
    <div className={cn("flex flex-col gap-3", loading && "opacity-60")} aria-busy={loading}>
      <dl className="flex flex-col gap-1.5 text-sm">
        {lines.map((l) => (
          <div key={l.label} className="flex items-baseline justify-between gap-3">
            <dt className="text-muted-foreground">{l.label}</dt>
            <dd
              className={cn(
                "shrink-0 font-semibold tabular-nums",
                l.warn ? "text-warning" : "text-foreground",
              )}
            >
              {l.value}
              {l.note && (
                <span className="ml-1 text-xs font-normal text-warning-muted-foreground">
                  ({l.note})
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>
      {after.people.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-foreground">Kto dostanie najwięcej</p>
          <ul className="mt-1 flex flex-col gap-0.5 text-xs text-muted-foreground">
            {after.people.slice(0, 5).map((p) => (
              <li key={p.user_id} className="flex justify-between gap-2">
                <span className="truncate">{p.name}</span>
                <span className="shrink-0 tabular-nums">
                  +{p.new} · dziś {p.p1_now} P1
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function History({ rows, error }: { rows: AllocationRulesChange[] | undefined; error: unknown }) {
  return (
    <section aria-label="Historia zmian" className="rounded-lg border border-border bg-card p-4">
      <h3 className="text-sm font-semibold text-foreground">Historia zmian</h3>
      {error ? (
        <p role="alert" className="mt-1 text-sm text-destructive">
          {apiErrorMessage(error, "Nie udało się wczytać historii.")}
        </p>
      ) : !rows ? (
        <div className="mt-2 h-10 animate-pulse rounded bg-muted" aria-busy="true" />
      ) : rows.length === 0 ? (
        <p className="mt-1 text-xs text-muted-foreground">Nikt jeszcze nie zmieniał zasad.</p>
      ) : (
        <ul className="mt-2 flex flex-col gap-2 text-sm">
          {rows.map((row) => (
            <li key={`${row.at}-${Object.keys(row.changed).join()}`} className="flex flex-col">
              <span className="text-xs text-muted-foreground">
                {new Date(row.at).toLocaleString("pl-PL", {
                  timeZone: "Europe/Warsaw",
                  dateStyle: "short",
                  timeStyle: "short",
                })}{" "}
                · {row.actor_name ?? "system"}
              </span>
              {historyLines(row.changed).map((line) => (
                <span key={line} className="text-foreground">
                  {line}
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function AllocationRulesView({
  saved,
  preview,
  previewError,
  previewLoading,
  history,
  historyError,
  saving,
  onDraft,
  onSave,
}: {
  saved: AllocationRulesForm
  preview: AllocationPreview | undefined
  previewError: unknown
  previewLoading: boolean
  history: AllocationRulesChange[] | undefined
  historyError: unknown
  saving: boolean
  onDraft: (draft: AllocationRulesForm) => void
  onSave: (draft: AllocationRulesForm) => void
}) {
  const [draft, setDraft] = useState<AllocationRulesForm>(saved)
  const changes = changedRuleLabels(saved.rules, saved.mode, draft.rules, draft.mode)
  const set = (next: AllocationRulesForm) => {
    setDraft(next)
    onDraft(next)
  }
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Zasady, według których automat dobiera rekruterów do rekrutacji. Zmieniają tylko nowe
        przydziały. Zmieniać mogą administrator i Head of Recruitment; każdy zapis trafia do
        historii.
      </p>
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="flex min-w-0 flex-col gap-3">
          <RulesFields draft={draft} saved={saved} set={set} />
          <History rows={history} error={historyError} />
        </div>
        <ImpactPanel
          preview={preview}
          previewError={previewError}
          previewLoading={previewLoading}
          draft={draft}
          changes={changes}
          saving={saving}
          onSave={() => onSave(draft)}
        />
      </div>
    </div>
  )
}

export function AllocationRulesPanel() {
  const team = useCompetenceTeam()
  const queryClient = useQueryClient()
  const { showError, showSuccess } = useToast()
  const { askConfirm, confirmDialog } = useConfirmV2()
  const [draft, setDraft] = useState<AllocationRulesForm | null>(null)
  const [debounced, setDebounced] = useState<AllocationRulesForm | null>(null)
  const [saving, setSaving] = useState(false)

  const saved: AllocationRulesForm | null = team.data
    ? { rules: team.data.rules, mode: team.data.mode }
    : null
  const current = draft ?? saved
  const savedKey = JSON.stringify(saved)
  // Nowe zapisane zasady (także cudzy zapis) zerują formularz, więc i szkic podglądu.
  useEffect(() => setDraft(null), [savedKey])
  useEffect(() => {
    const id = setTimeout(() => setDebounced(current), 350)
    return () => clearTimeout(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(current)])

  const preview = useQuery({
    queryKey: ["competence-team", "rules-preview", debounced?.rules],
    queryFn: () => previewTeamRules(debounced!.rules),
    enabled: !!debounced,
    placeholderData: (previous) => previous,
    staleTime: 30_000,
  })
  const history = useQuery({ queryKey: RULES_HISTORY_QUERY_KEY, queryFn: fetchRulesHistory })

  const state = resolveViewState({
    isLoading: team.isLoading,
    isError: team.isError,
    error: team.error,
    isEmpty: false,
    isSuccess: team.isSuccess,
  })
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => team.refetch()} />
  }
  if (!saved) {
    return <div className="h-64 animate-pulse rounded-lg bg-muted" aria-busy="true" />
  }

  const save = async (next: AllocationRulesForm) => {
    const after = preview.data?.draft
    if (next.mode === "auto" && after && after.new_people >= 20) {
      const ok = await askConfirm({
        title: `Automat da teraz ${after.new_people} nowych przydziałów`,
        description:
          "Tryb „Przydziela sam”: osoby dostaną rekrutacje i dzwonek przy następnym przebiegu. Zapisać zasady?",
        confirmLabel: "Zapisz zasady",
      })
      if (!ok) return
    }
    setSaving(true)
    const rulesChanged = JSON.stringify(next.rules) !== JSON.stringify(saved.rules)
    let rulesSaved = false
    try {
      // Najpierw zasady: „Przydzielaj” przy urlopach pozwala włączyć „Przydziela sam”.
      if (rulesChanged) {
        await putTeamRules(next.rules)
        rulesSaved = true
      }
      if (next.mode !== saved.mode) await allocationApi.mode(next.mode)
      showSuccess("Zasady zapisane. Działają od następnego przebiegu.")
      setDraft(null)
    } catch (error) {
      const message = apiErrorMessage(error, "Nie udało się zapisać zasad.")
      showError(rulesSaved ? `Zasady zapisane, tryb nie: ${message}` : message)
    } finally {
      setSaving(false)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: COMPETENCE_TEAM_QUERY_KEY }),
        queryClient.invalidateQueries({ queryKey: ["request-board"] }),
      ])
    }
  }

  return (
    <>
      <AllocationRulesView
        key={savedKey}
        saved={saved}
        preview={preview.data}
        previewError={preview.isError ? preview.error : null}
        previewLoading={preview.isFetching}
        history={history.data}
        historyError={history.isError ? history.error : null}
        saving={saving}
        onDraft={setDraft}
        onSave={save}
      />
      {confirmDialog}
    </>
  )
}
