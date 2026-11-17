"use client";

/**
 * „Co się zmieniło w Profilu Championa” (pomysł rekruterki 17.11.2026, makiety
 * runda 2: https://claude.ai/artifact/An7dHv22qkmMoX95DfNqx1).
 *
 *  - karta na górze Briefu z ostatnią nieprzeczytaną zmianą i zdaniem DL;
 *    „Przeczytane” (per osoba) zwija ją do jednej linii,
 *  - zakładka „Zmiany” z całą historią — do niej się wraca, gdy karta zniknie,
 *  - okno po zapisie profilu rekrutacji w pracy: autor dopisuje, na co klient
 *    teraz kładzie nacisk (można pominąć).
 *
 * Różnicę liczy serwer (`champion_profile_changes.describe_changes`) przy
 * zapisie; ekran tylko ją pokazuje.
 */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDownUp, Check, History, MessageSquareQuote, Minus, Plus } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Skeleton } from "@/components/ui/skeleton";
import {
  championApi,
  type ChampionChangeItem,
  type ChampionChangesResponse,
  type ChampionProfileRevision,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { formatDateTimePl } from "@/lib/date-pl";
import { resolveViewState } from "@/lib/view-state";

/** Po tylu dniach od ostatniej zmiany przeczytana karta znika z Briefu. */
const SEEN_LINE_DAYS = 14;
const DIALOG_ITEMS = 5;

export const CHAMPION_CHANGE_RECORDED_EVENT = "nexus:champion-change-recorded";

export interface ChampionChangeRecordedDetail {
  jobId: number;
  revision: { id: number; changes: ChampionChangeItem[] };
}

/** Edytor po zapisie: zmiana rekrutacji w pracy zostawiła wersję. */
export function emitChampionChangeRecorded(detail: ChampionChangeRecordedDetail): void {
  window.dispatchEvent(
    new CustomEvent<ChampionChangeRecordedDetail>(CHAMPION_CHANGE_RECORDED_EVENT, { detail }),
  );
}

export function changesQueryKey(jobId: number) {
  return ["champion-profile-changes", jobId] as const;
}

export function useChampionChanges(jobId: number) {
  return useQuery({
    queryKey: changesQueryKey(jobId),
    queryFn: () => championApi.changes(jobId).then((r) => r.data),
    staleTime: 60_000,
  });
}

/** Zmiany innych osób, których czytający jeszcze nie oznaczył jako przeczytane. */
export function unseenRevisions(
  data: ChampionChangesResponse | undefined,
): ChampionProfileRevision[] {
  if (!data) return [];
  const lastSeen = data.last_seen_revision_id ?? 0;
  return data.revisions.filter((r) => r.id > lastSeen && !r.mine);
}

const KIND_ICON = {
  added: Plus,
  removed: Minus,
  moved: ArrowDownUp,
  set: Check,
} as const;

const KIND_TONE: Record<ChampionChangeItem["kind"], string> = {
  added: "bg-success-muted text-success-muted-foreground",
  removed: "bg-destructive-muted text-destructive-muted-foreground",
  moved: "bg-warning-muted text-warning-muted-foreground",
  set: "bg-muted text-muted-foreground",
};

const KIND_LABEL: Record<ChampionChangeItem["kind"], string> = {
  added: "dodane",
  removed: "usunięte",
  moved: "zmieniony poziom",
  set: "zmienione",
};

export function ChangeList({ items }: { items: readonly ChampionChangeItem[] }) {
  return (
    <ul className="grid grid-cols-1 gap-x-6 gap-y-1.5 md:grid-cols-2" data-testid="champion-change-list">
      {items.map((item, index) => {
        const Icon = KIND_ICON[item.kind] ?? Check;
        return (
          <li key={`${index}:${item.kind}:${item.text}`} className="flex min-w-0 items-start gap-2 text-[13px]">
            <span
              className={`mt-px inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${KIND_TONE[item.kind] ?? KIND_TONE.set}`}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden />
              <span className="sr-only">{KIND_LABEL[item.kind]}</span>
            </span>
            <span className="min-w-0 break-words">
              <span
                className={`font-medium text-foreground ${item.kind === "removed" ? "line-through decoration-1" : ""}`}
              >
                {item.text}
              </span>
              {item.detail ? <span className="text-muted-foreground"> — {item.detail}</span> : null}
            </span>
          </li>
        );
      })}
    </ul>
  );
}

function ClientNote({ note }: { note: string }) {
  return (
    <div className="flex gap-2 rounded-lg bg-card px-3 py-2 text-[13px] text-foreground">
      <MessageSquareQuote className="mt-0.5 h-4 w-4 shrink-0 text-info" aria-hidden />
      <p className="min-w-0 break-words">
        <span className="font-semibold">Na co klient kładzie nacisk: </span>
        {note}
      </p>
    </div>
  );
}

function byline(revision: ChampionProfileRevision): string {
  const who = revision.author_name?.trim() || "Ktoś";
  return `${who} · ${formatDateTimePl(revision.created_at)}`;
}

function daysSince(iso: string | null): number {
  if (!iso) return Number.POSITIVE_INFINITY;
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return Number.POSITIVE_INFINITY;
  return (Date.now() - time) / 86_400_000;
}

/** Karta „Co się zmieniło od przekazania” nad Briefem. */
export function ChampionChangesCard({
  jobId,
  onOpenChanges,
}: {
  jobId: number;
  onOpenChanges: () => void;
}) {
  const qc = useQueryClient();
  const query = useChampionChanges(jobId);
  const seen = useMutation({
    mutationFn: (revisionId: number) =>
      championApi.markChangesSeen(jobId, revisionId).then((r) => r.data),
    onSuccess: (body) => {
      qc.setQueryData<ChampionChangesResponse>(changesQueryKey(jobId), (old) =>
        old ? { ...old, last_seen_revision_id: body.last_seen_revision_id ?? old.last_seen_revision_id } : old,
      );
    },
  });
  // Karta jest dodatkiem do Briefu: przy awarii zapytania zostaje zakładka
  // „Zmiany”, która pokazuje błąd zamiast pustej historii.
  if (!query.isSuccess) return null;
  const unseen = unseenRevisions(query.data);
  const latest = query.data.revisions[0];
  if (!latest) return null;

  if (unseen.length === 0) {
    if (daysSince(latest.created_at) > SEEN_LINE_DAYS) return null;
    return (
      <div
        className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-border bg-card px-4 py-2 text-[13px]"
        data-testid="champion-changes-line"
      >
        <History className="h-4 w-4 text-muted-foreground" aria-hidden />
        <span className="text-muted-foreground">
          Profil zmieniony {formatDateTimePl(latest.created_at).slice(0, 5)}
          {latest.mine ? " · Twoja zmiana" : " · przeczytane"}
        </span>
        <button
          type="button"
          onClick={onOpenChanges}
          className="ml-auto font-medium text-primary hover:underline"
        >
          Wszystkie zmiany w zakładce „Zmiany” →
        </button>
      </div>
    );
  }

  const shown = unseen[0];
  const older = unseen.length - 1;
  return (
    <section
      className="space-y-2.5 rounded-xl border border-info/40 bg-info-muted px-4 py-3"
      aria-label="Co się zmieniło od przekazania"
      data-testid="champion-changes-card"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="text-[14px] font-semibold text-info-muted-foreground">
          Co się zmieniło od przekazania
        </h2>
        <span className="text-xs text-muted-foreground">{byline(shown)}</span>
        <span className="ml-auto flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={onOpenChanges}
            className="text-[13px] font-medium text-primary hover:underline"
          >
            {older > 0 ? `Wszystkie zmiany (${unseen.length} nowe)` : "Wszystkie zmiany w zakładce „Zmiany”"}
          </button>
          <button
            type="button"
            onClick={() => seen.mutate(unseen[0].id)}
            disabled={seen.isPending}
            className="rounded-lg border border-border bg-card px-2.5 py-1 text-[13px] font-medium text-foreground hover:bg-accent disabled:opacity-60"
            data-testid="champion-changes-seen"
          >
            Przeczytane
          </button>
        </span>
      </div>
      {shown.note ? <ClientNote note={shown.note} /> : null}
      <ChangeList items={shown.changes} />
      {seen.isError ? (
        <p className="text-[13px] text-destructive" role="alert">
          {apiErrorMessage(seen.error, "Nie udało się oznaczyć zmiany jako przeczytanej.")}
        </p>
      ) : null}
    </section>
  );
}

/** Zakładka „Zmiany”: każda wersja profilu po przekazaniu, najnowsze na górze. */
export function ChampionChangesTimeline({ jobId }: { jobId: number }) {
  const query = useChampionChanges(jobId);
  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: query.isSuccess && query.data.revisions.length === 0,
  });
  if (state === "loading") {
    return <Skeleton className="h-40 w-full max-w-4xl rounded-xl" />;
  }
  if (state === "empty") {
    return (
      <p className="max-w-4xl text-[13px] text-muted-foreground" data-testid="champion-changes-empty">
        Od przekazania do searchu nikt nie zmienił tego profilu.
      </p>
    );
  }
  if (state !== "ready") {
    return <QueryStateNotice state={state} onRetry={() => void query.refetch()} />;
  }
  const revisions = query.data?.revisions ?? [];
  const unseenIds = new Set(unseenRevisions(query.data).map((r) => r.id));
  return (
    <div className="max-w-4xl space-y-3" data-testid="champion-changes-timeline">
      <p className="text-[13px] text-muted-foreground">
        Każdy zapis Profilu Championa po przekazaniu do searchu. Najnowsze na górze.
      </p>
      <ol className="space-y-3">
        {revisions.map((revision) => (
          <li key={revision.id}>
            <section className="space-y-2.5 rounded-xl border border-border bg-card px-4 py-3">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <h3 className="text-[14px] font-semibold text-foreground">
                  {formatDateTimePl(revision.created_at)}
                </h3>
                <span className="text-xs text-muted-foreground">
                  {revision.author_name?.trim() || "Ktoś"}
                </span>
                {unseenIds.has(revision.id) ? (
                  <span className="rounded-full bg-info-muted px-2 py-0.5 text-xs font-semibold text-info-muted-foreground">
                    nowe dla Ciebie
                  </span>
                ) : null}
              </div>
              {revision.note ? <ClientNote note={revision.note} /> : null}
              <ChangeList items={revision.changes} />
            </section>
          </li>
        ))}
      </ol>
    </div>
  );
}

/**
 * Okno po zapisie profilu rekrutacji w pracy. Słucha zdarzenia z edytora,
 * więc działa i po zapisie w szufladzie bloku (szuflada już się zamknęła),
 * i w pełnym formularzu.
 */
export function ChampionChangeNoteHost({ jobId }: { jobId: number }) {
  const qc = useQueryClient();
  const [pending, setPending] = useState<ChampionChangeRecordedDetail["revision"] | null>(null);
  const [note, setNote] = useState("");

  useEffect(() => {
    const onRecorded = (event: Event) => {
      const detail = (event as CustomEvent<ChampionChangeRecordedDetail>).detail;
      if (!detail || detail.jobId !== jobId) return;
      setNote("");
      setPending(detail.revision);
    };
    window.addEventListener(CHAMPION_CHANGE_RECORDED_EVENT, onRecorded);
    return () => window.removeEventListener(CHAMPION_CHANGE_RECORDED_EVENT, onRecorded);
  }, [jobId]);

  const save = useMutation({
    mutationFn: (revisionId: number) =>
      championApi.setChangeNote(jobId, revisionId, note.trim() || null),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: changesQueryKey(jobId) });
      setPending(null);
    },
  });

  if (!pending) return null;
  const items = pending.changes.slice(0, DIALOG_ITEMS);
  const more = pending.changes.length - items.length;
  const close = () => {
    if (!save.isPending) setPending(null);
  };
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) close();
      }}
      title="Ta rekrutacja jest już u rekruterów"
      description="Rekruterzy zobaczą tę zmianę na górze Briefu i w zakładce „Zmiany”."
      size="lg"
      footer={
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button
            type="button"
            onClick={close}
            disabled={save.isPending}
            className="rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-accent disabled:opacity-50"
          >
            Pomiń
          </button>
          <button
            type="button"
            onClick={() => save.mutate(pending.id)}
            disabled={save.isPending || note.trim() === ""}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
            data-testid="champion-change-note-save"
          >
            {save.isPending ? "Zapisuję…" : "Pokaż rekruterom"}
          </button>
        </div>
      }
    >
      <div className="space-y-4" data-testid="champion-change-note-dialog">
        <div className="space-y-2 rounded-xl bg-muted/60 px-4 py-3">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Co się zmieniło
          </p>
          <ChangeList items={items} />
          {more > 0 ? (
            <p className="text-[13px] text-muted-foreground">i {more} więcej w zakładce „Zmiany”</p>
          ) : null}
        </div>
        <div className="space-y-1.5">
          <label htmlFor="champion-change-note" className="block text-[15px] font-semibold text-foreground">
            Na co klient teraz kładzie nacisk?
          </label>
          <p className="text-[13px] text-muted-foreground">
            Jedno, dwa zdania z rozmowy z hiring managerem. Możesz pominąć.
          </p>
          <textarea
            id="champion-change-note"
            rows={3}
            maxLength={600}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="w-full resize-none rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground"
          />
        </div>
        {save.isError ? (
          <p className="text-[13px] text-destructive" role="alert">
            {apiErrorMessage(save.error, "Nie udało się zapisać zdania. Spróbuj jeszcze raz.")}
          </p>
        ) : null}
      </div>
    </AppModal>
  );
}
