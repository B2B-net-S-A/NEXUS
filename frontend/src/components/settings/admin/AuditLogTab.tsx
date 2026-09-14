"use client";

/**
 * Ustawienia → Administracja → Log aktywności.
 *
 * Do 09.2026 (B16, audyt Codexa) zakładka pobierała RANKING tygodnia
 * (endpoint `leaderboard`) i z liczników syntetyzowała wiersze
 * z losowym identyfikatorem obiektu i losową datą z ostatnich 7 dni —
 * bez oznaczenia, że to przykład. Admin czytał zmyślony dziennik.
 *
 * Teraz zakładka czyta PRAWDZIWY feed (`GET /api/activities/feed`): scope
 * (`apply_activity_feed_scope`) i redakcję finansów robi backend; front
 * renderuje autora, opis i znacznik czasu DOKŁADNIE z odpowiedzi. Feed nie
 * ma `offset` — „Pokaż więcej" podnosi `limit` do sufitu endpointu (100).
 */

import { useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Activity, Clock, ExternalLink, Loader2 } from "lucide-react";
import Link from "next/link";

import api from "@/lib/api";
import { formatDateTimePl } from "@/lib/date-pl";
import { resolveViewState } from "@/lib/view-state";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { activityActionLabel } from "@/components/v2/pages/candidate-timeline-labels";

/** Sufit `limit` w `GET /api/activities/feed` (`Query(50, ge=1, le=100)`). */
const FEED_INITIAL_LIMIT = 50;
const FEED_MAX_LIMIT = 100;

export interface ActivityFeedEntry {
  id: number;
  user: string;
  user_id: number | null;
  action: string;
  entity_type: string;
  entity_id: number | null;
  entity_name: string;
  description: string;
  timestamp: string | null;
  link: string | null;
}

const ENTITY_TYPE_LABELS: Record<string, string> = {
  candidate: "Kandydat",
  job: "Rekrutacja",
  client: "Klient",
  contract: "Kontrakt",
  note: "Notatka",
  pipeline: "Pipeline",
  user: "Użytkownik",
};

/**
 * Etykiety akcji obiektów INNYCH niż kandydat. Słownik osi czasu kandydata
 * (`activityActionLabel`) tłumaczy `created` jako „Utworzono profil kandydata",
 * co dla rekrutacji czy klienta byłoby fałszem — stąd osobna, ogólna mapa.
 */
const GENERIC_ACTION_LABELS: Record<string, string> = {
  created: "Utworzono",
  updated: "Zaktualizowano",
  deleted: "Usunięto",
  closed: "Zamknięto",
  published: "Opublikowano",
  merged: "Scalono",
  status_updated: "Zmieniono status",
  stage_changed: "Zmieniono etap",
  hired: "Zatrudniono",
  terminated: "Zakończono współpracę",
  bulk_marked_ended: "Zakończono zbiorczo",
  note_added: "Dodano notatkę",
  document_uploaded: "Dodano plik",
  document_deleted: "Usunięto plik",
  handed_off_to_search: "Przekazano do searchu",
  claimed: "Przejęto",
  owner_assigned: "Przypisano opiekuna",
  owner_released: "Zwolniono opiekuna",
  collaborator_added: "Dodano współpracownika",
  champion_profile_updated: "Zaktualizowano profil Championa",
  champion_verification_updated: "Zaktualizowano weryfikację Championa",
};

const SLUG_RE = /^[a-z0-9_]+$/;

/** Etykieta akcji z feedu; nieznany slug nigdy nie wraca dosłownie. */
export function feedActionLabel(action: string, entityType: string): string {
  if (entityType === "candidate") return activityActionLabel(action);
  const known = GENERIC_ACTION_LABELS[action];
  if (known) return known;
  return SLUG_RE.test(action) ? "Zdarzenie systemowe" : action;
}

export function AuditLogTab() {
  const [limit, setLimit] = useState(FEED_INITIAL_LIMIT);

  const query = useQuery({
    queryKey: ["activities", "feed", "audit-log", limit],
    queryFn: () =>
      api
        .get<ActivityFeedEntry[]>("/api/activities/feed", { params: { limit } })
        .then((r) => r.data),
    placeholderData: keepPreviousData,
    staleTime: 15 * 1000,
  });

  const entries = query.data ?? [];
  const viewState = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isEmpty: entries.length === 0,
    isSuccess: query.isSuccess,
  });
  const canShowMore = limit < FEED_MAX_LIMIT && entries.length >= limit;

  if (viewState === "loading") {
    return (
      <div className="flex items-center justify-center gap-2 rounded-xl border border-border bg-card py-10 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
        Ładowanie logu aktywności…
      </div>
    );
  }

  if (viewState === "error" || viewState === "forbidden" || viewState === "not_found") {
    return (
      <QueryStateNotice
        state={viewState}
        description={
          viewState === "error"
            ? "Nie udało się pobrać logu aktywności. Zdarzenia istnieją — spróbuj ponownie."
            : undefined
        }
        onRetry={() => void query.refetch()}
      />
    );
  }

  if (viewState === "empty") {
    return (
      <div className="rounded-xl border border-border bg-card p-8 text-center text-muted-foreground">
        <Activity className="mx-auto mb-3 h-10 w-10 opacity-30" aria-hidden="true" />
        <p>Brak zdarzeń w logu aktywności</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-xs">
      <div className="flex items-center gap-2 border-b border-border px-6 py-4">
        <Activity className="h-4 w-4 text-primary" aria-hidden="true" />
        <h3 className="font-semibold text-foreground">Ostatnia aktywność użytkowników</h3>
        <span className="ml-auto text-xs text-muted-foreground">
          Ostatnie {entries.length} zdarzeń
        </span>
      </div>
      <ul className="divide-y divide-border">
        {entries.map((entry) => (
          <li
            key={entry.id}
            className="flex items-center gap-4 px-6 py-3 transition-colors hover:bg-muted"
          >
            <div
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-bold text-primary-foreground"
              aria-hidden="true"
            >
              {entry.user.charAt(0)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-foreground">{entry.user}</span>
                <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-foreground">
                  {feedActionLabel(entry.action, entry.entity_type)}
                </span>
                <span className="text-xs text-muted-foreground">
                  {ENTITY_TYPE_LABELS[entry.entity_type] ?? entry.entity_type}
                  {entry.entity_id != null ? ` #${entry.entity_id}` : ""}
                </span>
              </div>
              <p className="mt-0.5 truncate text-sm text-muted-foreground">{entry.description}</p>
            </div>
            {entry.link ? (
              <Link
                href={entry.link}
                className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-primary hover:underline"
              >
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
                Otwórz
              </Link>
            ) : null}
            <div className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground">
              <Clock className="h-3 w-3" aria-hidden="true" />
              <time dateTime={entry.timestamp ?? undefined}>{formatDateTimePl(entry.timestamp)}</time>
            </div>
          </li>
        ))}
      </ul>
      {canShowMore ? (
        <div className="border-t border-border px-6 py-3 text-center">
          <button
            type="button"
            onClick={() => setLimit(FEED_MAX_LIMIT)}
            disabled={query.isFetching}
            className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-60"
          >
            {query.isFetching ? "Ładowanie…" : "Pokaż więcej"}
          </button>
        </div>
      ) : null}
    </div>
  );
}

export default AuditLogTab;
