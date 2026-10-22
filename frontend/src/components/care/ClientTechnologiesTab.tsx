"use client";

import { useState } from "react";
import Link from "next/link";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form-field";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  HIRING_SOURCE_LABELS,
  useAddStackNote,
  useClientTechMap,
  type ClientTechMap,
  type TechGap,
} from "@/lib/api/care";
import { CALM_SUBLINE } from "@/lib/calm-table";
import { countPl } from "@/lib/plural-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";
import { formatIsoDatePl } from "@/lib/date-pl";
import { hasCapability } from "@/lib/capabilities";
import { useAuthStore } from "@/store/auth";

import { gapQuestion } from "./tech-gaps";
import { TechHeatmap } from "./TechHeatmap";
import { UnlinkedCardsPanel } from "./UnlinkedCardsPanel";

export function StackNoteDialog({ clientId, onClose }: { clientId: number; onClose: () => void }) {
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

export function GapsCard({
  gaps,
  clientId,
  onAddNote,
}: {
  gaps: TechGap[];
  clientId: number;
  onAddNote: (() => void) | null;
}) {
  return (
    <section className="space-y-2 rounded-lg border border-border bg-card p-4" data-help="client.people.gaps">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">
          Luki do dopytania <span className="tabular-nums text-muted-foreground">· {gaps.length}</span>
        </h3>
      </div>
      {gaps.length ? (
        <ul className="text-sm" aria-label="Luki do dopytania">
          {gaps.map((gap, index) => {
            const item = gapQuestion(gap);
            return (
              <li
                key={item.key}
                title={item.question}
                className={cn("flex flex-col gap-0.5 py-2", index > 0 && "border-t border-border/60")}
              >
                <span>
                  <span className="font-semibold">{item.subject}</span>
                  <span className="text-muted-foreground"> — {item.detail}</span>
                  <span className="text-xs text-muted-foreground"> · pytanie w najbliższej rozmowie</span>
                </span>
                {gap.kind === "manager_unplaced" ? (
                  <Link
                    href={`/clients/${clientId}?tab=ludzie&view=drzewo`}
                    className="text-xs text-primary hover:underline"
                  >
                    Ustaw w „Drzewie osób”
                  </Link>
                ) : onAddNote ? (
                  <button
                    type="button"
                    className="self-start text-xs text-primary hover:underline"
                    onClick={onAddNote}
                  >
                    Dopisz notatkę o stacku
                  </button>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">Nie ma luk do dopytania.</p>
      )}
      <p className="border-t border-border/60 pt-2 text-xs text-muted-foreground">
        Każda luka trafia jako pytanie do okna „Rozmowa” konsultanta tego klienta — przy najbliższej
        rozmowie.
      </p>
    </section>
  );
}

/** Zakładka „Technologie” klienta — mapa cieplna z czterech źródeł (19.10.2026). */
export function ClientTechnologiesTab({ clientId }: { clientId: number }) {
  const query = useClientTechMap(clientId);
  const [noteOpen, setNoteOpen] = useState(false);
  // `/jobs/new` odsyła na listę każdego bez `job.create` (np. TCM) — bez
  // takiego uprawnienia przycisku nie ma.
  const canCreateJob = useAuthStore((s) => !!s.user && hasCapability(s.user, "job.create"));
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
  const heat = map.heatmap ?? null;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3">
        <p className="text-sm text-muted-foreground">
          {[
            countPl(map.consultants_count, "konsultant", "konsultantów", "konsultantów"),
            countPl(map.open_jobs_count, "otwarta rekrutacja", "otwarte rekrutacje", "otwartych rekrutacji"),
            countPl(map.cards_count, "karta technologiczna", "karty technologiczne", "kart technologicznych"),
            countPl(map.notes_count, "notatka o stacku", "notatki o stacku", "notatek o stacku"),
          ].join(" · ")}
        </p>
        <div className="flex flex-wrap gap-2">
          {map.can_edit ? (
            <Button variant="outline" size="sm" onClick={() => setNoteOpen(true)}>
              Dodaj notatkę o stacku
            </Button>
          ) : null}
          {canCreateJob ? (
            <Button size="sm" asChild>
              <Link href={`/jobs/new?client=${clientId}`}>Nowa rekrutacja z tej mapy</Link>
            </Button>
          ) : null}
        </div>
      </div>

      <UnlinkedCardsPanel clientId={clientId} />

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_300px]">
        <div className="min-w-0 space-y-2">
          {state === "empty" || !heat ? (
            <p className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
              {state === "empty"
                ? "Żadne źródło nie wskazuje jeszcze technologii ze słownika — dodaj kartę technologiczną przy kontrakcie albo notatkę o stacku."
                : "Mapa się przelicza — odśwież za chwilę."}
            </p>
          ) : (
            <TechHeatmap departments={map.departments} rows={heat.rows} rowsTotal={heat.rows_total} />
          )}
          {!map.departments.length ? (
            <p className="text-xs text-muted-foreground">
              Klient nie ma jeszcze działów — zakłada się je w „Strukturze u klienta” albo na karcie
              technologicznej. Do tego czasu wszystko stoi w kolumnie „bez działu”.
            </p>
          ) : null}
        </div>

        <div className="grid content-start gap-3">
          <GapsCard
            gaps={map.gaps}
            clientId={clientId}
            onAddNote={map.can_edit ? () => setNoteOpen(true) : null}
          />
          <section className="space-y-2 rounded-lg border border-border bg-card p-4">
            <h3 className="text-sm font-semibold">Otwarte rekrutacje</h3>
            {map.open_jobs.length ? (
              <ul className="space-y-1.5 text-sm">
                {map.open_jobs.map((job) => (
                  <li key={job.id} className="flex items-center justify-between gap-2">
                    <Link href={`/jobs/${job.id}`} className="min-w-0 truncate hover:underline">
                      {job.title}
                    </Link>
                    {job.area ? (
                      <Badge variant="neutral" className="shrink-0">
                        {job.area}
                      </Badge>
                    ) : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Brak otwartych rekrutacji.</p>
            )}
          </section>
          <section className="space-y-2 rounded-lg border border-border bg-card p-4">
            <h3 className="text-sm font-semibold">Klient zatrudnia</h3>
            {map.signals.length ? (
              <ul className="space-y-2 text-sm">
                {map.signals.slice(0, 5).map((signal) => (
                  <li key={`${signal.kind}-${signal.id}`}>
                    {signal.roles.length ? (
                      <span className="flex flex-wrap gap-1">
                        {signal.roles.map((role) => (
                          <Badge key={role} variant="info">
                            {role}
                          </Badge>
                        ))}
                      </span>
                    ) : (
                      <span className="font-medium">{signal.note || "Potrzeba zgłoszona"}</span>
                    )}
                    <span className={CALM_SUBLINE}>
                      {[
                        formatIsoDatePl(signal.on),
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
            <div className="flex items-center justify-between border-t border-border/60 pt-2 text-sm">
              <span>
                Do przepięcia <span className="font-semibold tabular-nums">{map.redeploy_active}</span>
              </span>
              <Link href="/care?tab=redeploy" className="text-primary hover:underline">
                Kolejka przepięć →
              </Link>
            </div>
          </section>
          <section className="space-y-2 rounded-lg border border-border bg-card p-4">
            <h3 className="text-sm font-semibold">Dostawcy u klienta</h3>
            <p className="text-sm">
              {map.vendors.length
                ? map.vendors.map((vendor) => vendor.name).join(", ")
                : <span className="text-muted-foreground">Nikt nie wskazał dostawców.</span>}
            </p>
          </section>
          {map.notes.length ? (
            <section className="space-y-2 rounded-lg border border-border bg-card p-4">
              <h3 className="text-sm font-semibold">Notatki o stacku</h3>
              <ul className="space-y-2 text-sm">
                {map.notes.map((note) => (
                  <li key={note.id}>
                    <span className="line-clamp-3 whitespace-pre-line">{note.content}</span>
                    <span className={CALM_SUBLINE}>{formatIsoDatePl(note.created_on)}</span>
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
