"use client";

import { useState } from "react";
import Link from "next/link";

import { AppModal } from "@/components/ds/AppModal";
import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  HIRING_SOURCE_LABELS,
  SOURCE_LABELS,
  useAddStackNote,
  useCareOwners,
  useClientTechMap,
  useSetClientDefaultOwner,
  type ClientTechMap,
  type MapDepartment,
  type TechGap,
  type TechSource,
} from "@/lib/api/care";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn, formatDate } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { sourceSummary, technologiesInArea } from "./care-format";
import { candidatesHref, gapQuestion } from "./tech-gaps";

const SOURCES: { key: TechSource; letter: string }[] = [
  { key: "cards", letter: "T" },
  { key: "jobs", letter: "R" },
  { key: "consultants", letter: "K" },
  { key: "notes", letter: "N" },
];
const DEFAULT_OWNER = "none";

function SourceMarks({ counts }: { counts: Record<TechSource, number> }) {
  return (
    <span className="inline-flex gap-1">
      {SOURCES.map(({ key, letter }) => (
        <span
          key={key}
          title={`${SOURCE_LABELS[key]}: ${counts[key]}`}
          className={cn(
            "inline-flex h-5 min-w-5 items-center justify-center rounded px-1 text-[11px] tabular-nums",
            counts[key] ? "bg-primary/10 text-foreground" : "text-muted-foreground/50",
          )}
        >
          {counts[key] ? counts[key] : "·"}
          <span className="sr-only">{` ${letter}`}</span>
        </span>
      ))}
    </span>
  );
}

function StackNoteDialog({ clientId, onClose }: { clientId: number; onClose: () => void }) {
  const { showToast } = useToast();
  const save = useAddStackNote(clientId);
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const submit = () => {
    setError(null);
    if (!content.trim()) {
      setError("Wpisz notatkę.");
      return;
    }
    save.mutate(content.trim(), {
      onSuccess: () => {
        showToast("Notatka o stacku dodana", "success");
        onClose();
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się dodać notatki.")),
    });
  };
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Notatka o stacku"
      description="Trafia do wiedzy o kliencie (kategoria „Stack technologiczny”). Technologie ze słownika zostaną policzone na mapie."
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={save.isPending}>
            {save.isPending ? "Zapisywanie…" : "Dodaj notatkę"}
          </Button>
        </>
      }
    >
      <FormField label="Notatka" htmlFor="care-stack-note">
        <Textarea
          id="care-stack-note"
          rows={5}
          maxLength={4000}
          value={content}
          placeholder="np. Zespół Data przechodzi z Oracle na PostgreSQL, kolejki na Kafce."
          onChange={(event) => setContent(event.target.value)}
        />
      </FormField>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </AppModal>
  );
}

/** Litery źródeł przy technologii działu („Spark T R K”). */
function SourceLetters({ counts }: { counts: Record<TechSource, number> }) {
  const present = SOURCES.filter(({ key }) => counts[key]);
  return (
    <span className="ml-1 text-[10px] tracking-wide text-muted-foreground">
      {present.map(({ letter }) => letter).join(" ")}
    </span>
  );
}

function DepartmentsTable({ departments }: { departments: MapDepartment[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-card">
      <table className="w-full text-sm" aria-label="Technologie po działach">
        <thead>
          <tr className={CALM_ROW}>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Dział</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Technologie i źródła</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Menedżer</th>
            <th className={cn(CALM_HEAD, "px-3 py-2 text-right")}>Nasi / w bazie</th>
          </tr>
        </thead>
        <tbody>
          {departments.map((dept) => {
            const manager = dept.managers[0];
            const href = candidatesHref(dept.base.skills);
            const more = dept.technologies_total - dept.technologies.length;
            return (
              <tr
                key={dept.area.id}
                className={cn(CALM_ROW, !dept.has_fresh_source && "text-muted-foreground")}
              >
                <td className="px-3 py-1.5 align-top">
                  <span className="font-medium">{dept.area.name}</span>
                  {!dept.has_fresh_source ? (
                    <span className={CALM_SUBLINE}>brak źródła od 18 miesięcy</span>
                  ) : null}
                </td>
                <td className="px-3 py-1.5 align-top">
                  {dept.technologies.length ? (
                    <ul className="flex flex-wrap gap-x-3 gap-y-0.5" aria-label={`Technologie: ${dept.area.name}`}>
                      {dept.technologies.map((tech) => (
                        <li
                          key={tech.skill_id}
                          title={sourceSummary({ ...tech, must_jobs: 0, consultant_months: 0, areas: [], category: null })}
                          className={cn(tech.stale && "text-muted-foreground")}
                        >
                          {tech.name}
                          <SourceLetters counts={tech.counts} />
                        </li>
                      ))}
                      {more > 0 ? <li className="text-muted-foreground">+{more}</li> : null}
                    </ul>
                  ) : (
                    <span className={CALM_EMPTY}>—</span>
                  )}
                </td>
                <td className="px-3 py-1.5 align-top">
                  {manager ? (
                    <>
                      {manager.name}
                      {dept.managers.length > 1 ? (
                        <span className="text-muted-foreground"> +{dept.managers.length - 1}</span>
                      ) : null}
                      {manager.position ? (
                        <span className={CALM_SUBLINE}>{manager.position}</span>
                      ) : null}
                    </>
                  ) : (
                    <span className={CALM_EMPTY}>nie wskazano</span>
                  )}
                </td>
                <td className={cn(CALM_AMOUNT, "px-3 py-1.5 align-top")}>
                  {dept.consultants}
                  {" / "}
                  {href && dept.base.count != null ? (
                    <Link
                      href={href}
                      className="text-primary hover:underline"
                      title={`Osoby w bazie z: ${dept.base.skills.join(" i ")}`}
                    >
                      {dept.base.count}
                    </Link>
                  ) : (
                    <span className={CALM_EMPTY}>—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="border-t border-border/60 px-3 py-2 text-xs text-muted-foreground">
        Działy są te same co w „Strukturze u klienta”. Menedżer — osoba z działu z naszymi
        konsultantami. „W bazie” — osoby z dwiema najmocniejszymi technologiami działu naraz.
      </p>
    </div>
  );
}

function GapsCard({ gaps }: { gaps: TechGap[] }) {
  const questions = gaps.map(gapQuestion);
  return (
    <section className="space-y-2 rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Luki do dopytania</h3>
        <span className="text-sm tabular-nums">{questions.length}</span>
      </div>
      {questions.length ? (
        <ul className="space-y-1.5 text-sm" aria-label="Luki do dopytania">
          {questions.map((item) => (
            <li key={item.key} title={item.question}>
              <span className="font-medium">{item.subject}</span>{" "}
              <span className="text-muted-foreground">{item.detail}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">Nie ma luk do dopytania.</p>
      )}
      <p className="text-xs text-muted-foreground">
        Te pytania pokazują się w oknie rozmowy z konsultantami tego klienta.
      </p>
    </section>
  );
}

function DefaultOwner({ map, clientId }: { map: ClientTechMap; clientId: number }) {
  const { showToast } = useToast();
  const owners = useCareOwners(map.can_edit);
  const save = useSetClientDefaultOwner(clientId);
  if (!map.can_edit) {
    return <span className="text-sm">{map.default_owner?.name ?? "Delivery Lead kontraktu"}</span>;
  }
  return (
    <Select
      value={map.default_owner ? String(map.default_owner.id) : DEFAULT_OWNER}
      disabled={save.isPending}
      onValueChange={(next) =>
        save.mutate(next === DEFAULT_OWNER ? null : Number(next), {
          onSuccess: () => showToast("Domyślny opiekun zapisany", "success"),
          onError: (err) =>
            showToast(apiErrorMessage(err, "Nie udało się zapisać opiekuna."), "error"),
        })
      }
    >
      <SelectTrigger aria-label="Domyślny opiekun konsultantów klienta" className="h-8">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={DEFAULT_OWNER}>Delivery Lead kontraktu</SelectItem>
        {(owners.data ?? []).map((owner) => (
          <SelectItem key={owner.id} value={String(owner.id)}>
            {owner.name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** Zakładka „Technologie” klienta — mapa z czterech źródeł. */
export function ClientTechnologiesTab({ clientId }: { clientId: number }) {
  const query = useClientTechMap(clientId);
  const [area, setArea] = useState<string | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: (query.data?.technologies.length ?? 0) === 0,
  });
  if (state === "loading") {
    return <p className="p-4 text-sm text-muted-foreground">Wczytywanie mapy technologii…</p>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error" || !query.data) {
    return (
      <QueryStateNotice
        state={state === "forbidden" || state === "not_found" ? state : "error"}
        description={
          state === "forbidden" || state === "not_found"
            ? apiErrorMessage(query.error, "Nie możesz zobaczyć mapy tego klienta.")
            : undefined
        }
        onRetry={() => query.refetch()}
      />
    );
  }
  const map = query.data;
  const rows = technologiesInArea(map.technologies, area);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <InlineStats
          id="care-tech-stats"
          stats={[
            { id: "consultants", label: "konsultantów u klienta", value: map.consultants_count },
            { id: "jobs", label: "otwarte rekrutacje", value: map.open_jobs_count },
            { id: "cards", label: "karty technologiczne", value: map.cards_count },
            { id: "notes", label: "notatki o stacku", value: map.notes_count },
          ]}
        />
        <div className="flex flex-wrap gap-2">
          {map.can_edit ? (
            <Button variant="outline" size="sm" onClick={() => setNoteOpen(true)}>
              Dodaj notatkę o stacku
            </Button>
          ) : null}
          <Button size="sm" asChild>
            <Link href={`/jobs/new?client=${clientId}`}>Nowa rekrutacja z tej mapy</Link>
          </Button>
        </div>
      </div>

      {map.departments.length ? (
        <DepartmentsTable departments={map.departments} />
      ) : (
        <p className="text-sm text-muted-foreground">
          Klient nie ma jeszcze działów — zakłada się je w „Strukturze u klienta” albo na karcie
          technologicznej.
        </p>
      )}

      {map.areas.length ? (
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Działy u klienta">
          {[{ id: 0, name: "Wszystkie działy" }, ...map.areas].map((item) => {
            const value = item.id === 0 ? null : item.name;
            const active = area === value;
            return (
              <Button
                key={item.id}
                variant={active ? "secondary" : "ghost"}
                size="sm"
                aria-pressed={active}
                onClick={() => setArea(value)}
              >
                {item.name}
              </Button>
            );
          })}
        </div>
      ) : null}

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="overflow-x-auto rounded-lg border border-border bg-card">
          {state === "empty" ? (
            <p className="p-4 text-sm text-muted-foreground">
              Żadne źródło nie wskazuje jeszcze technologii ze słownika — dodaj kartę
              technologiczną przy kontrakcie albo notatkę o stacku.
            </p>
          ) : (
            <table className="w-full text-sm" aria-label="Wszystkie technologie klienta">
              <thead>
                <tr className={CALM_ROW}>
                  <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Technologia</th>
                  <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Dział</th>
                  <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>
                    Źródła <span className="normal-case tracking-normal">(T · R · K · N)</span>
                  </th>
                  <th className={cn(CALM_HEAD, "px-3 py-2 text-left")}>Ostatnio</th>
                  <th className={cn(CALM_HEAD, "px-3 py-2 text-right")}>Nasi u klienta</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((tech) => (
                  <tr
                    key={tech.skill_id}
                    className={cn(CALM_ROW, tech.stale && "text-muted-foreground")}
                    title={sourceSummary(tech)}
                  >
                    <td className="px-3 py-1.5">
                      <span className="font-medium">{tech.name}</span>
                      {tech.must_jobs ? (
                        <span className={CALM_SUBLINE}>„musi” w {tech.must_jobs} rekrutacjach</span>
                      ) : null}
                    </td>
                    <td className="px-3 py-1.5">
                      {tech.areas.length ? tech.areas.join(", ") : <span className={CALM_EMPTY}>—</span>}
                    </td>
                    <td className="px-3 py-1.5">
                      <SourceMarks counts={tech.counts} />
                    </td>
                    <td className="px-3 py-1.5 tabular-nums">
                      {tech.last_seen ? formatDate(tech.last_seen) : <span className={CALM_EMPTY}>—</span>}
                    </td>
                    <td className={cn(CALM_AMOUNT, "px-3 py-1.5")}>
                      {tech.counts.consultants || <span className={CALM_EMPTY}>—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="border-t border-border/60 px-3 py-2 text-xs text-muted-foreground">
            T — rozmowy (karty technologiczne), R — rekrutacje klienta z 12 miesięcy, K — nasi
            konsultanci u klienta, N — notatki o stacku. Wyszarzone: brak źródła z ostatnich 18
            miesięcy.
          </p>
        </div>

        <div className="grid content-start gap-3">
          <GapsCard gaps={map.gaps} />
          <section className="space-y-2 rounded-lg border border-border bg-card p-4">
            <h3 className="text-sm font-semibold">Klient zatrudnia</h3>
            {map.signals.length ? (
              <ul className="space-y-2 text-sm">
                {map.signals.slice(0, 5).map((signal) => (
                  <li key={`${signal.kind}-${signal.id}`}>
                    <span className="font-medium">
                      {signal.roles.length ? signal.roles.join(", ") : signal.note || "Potrzeba zgłoszona"}
                    </span>
                    <span className={CALM_SUBLINE}>
                      {[
                        formatDate(signal.on),
                        signal.area,
                        signal.source ? HIRING_SOURCE_LABELS[signal.source] : null,
                        signal.sales_status === "converted" ? "sprzedaż: szansa" : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Brak sygnałów z rozmów w ostatnim roku.</p>
            )}
          </section>
          <section className="space-y-2 rounded-lg border border-border bg-card p-4">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-semibold">Do przepięcia</h3>
              <span className="text-sm tabular-nums">{map.redeploy_active}</span>
            </div>
            <Link href="/care?tab=redeploy" className="text-sm text-primary hover:underline">
              Pokaż kolejkę przepięć
            </Link>
          </section>
          <section className="space-y-2 rounded-lg border border-border bg-card p-4">
            <h3 className="text-sm font-semibold">Otwarte rekrutacje</h3>
            {map.open_jobs.length ? (
              <ul className="space-y-1 text-sm">
                {map.open_jobs.map((job) => (
                  <li key={job.id}>
                    <Link href={`/jobs/${job.id}`} className="hover:underline">
                      {job.title}
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Brak otwartych rekrutacji.</p>
            )}
          </section>
          <section className="space-y-2 rounded-lg border border-border bg-card p-4">
            <h3 className="text-sm font-semibold">Dostawcy i opiekun</h3>
            <p className="text-sm">
              {map.vendors.length
                ? map.vendors.map((vendor) => vendor.name).join(", ")
                : <span className="text-muted-foreground">Nikt nie wskazał dostawców.</span>}
            </p>
            <div className="grid gap-1">
              <span className="text-xs text-muted-foreground">Domyślny opiekun konsultantów</span>
              <DefaultOwner map={map} clientId={clientId} />
            </div>
          </section>
          {map.notes.length ? (
            <section className="space-y-2 rounded-lg border border-border bg-card p-4">
              <h3 className="text-sm font-semibold">Notatki o stacku</h3>
              <ul className="space-y-2 text-sm">
                {map.notes.map((note) => (
                  <li key={note.id}>
                    <span className="line-clamp-3 whitespace-pre-line">{note.content}</span>
                    <span className={CALM_SUBLINE}>{formatDate(note.created_on)}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </div>
      </div>
      {noteOpen ? <StackNoteDialog clientId={clientId} onClose={() => setNoteOpen(false)} /> : null}
    </div>
  );
}
