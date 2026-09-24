"use client";

/**
 * „Portale ogłoszeniowe” (Pracuj.pl, JustJoinIT) w oknie zlecenia rekrutacji.
 *
 * Zastępuje symulację `PostingsSection` (losowe `SIM-…`). Renderuje się
 * WYŁĄCZNIE, gdy backend zgłasza co najmniej jeden portal gotowy — dziś oba
 * są wyłączone (brak dokumentacji API), więc sekcja jest niewidoczna. Stan
 * portali, kolejka i powody odmów pochodzą z serwera; front niczego nie zgaduje.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, ExternalLink, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  POSTING_STATUS_LABELS,
  fetchJobPostings,
  fetchPortalConfig,
  isLive,
  jobPortalKeys,
  latestPosting,
  publishToPortal,
  unpublishFromPortal,
  type JobPortal,
  type JobPostingRead,
  type PortalConfigItem,
} from "@/lib/api/jobPortals";
import { formatDate } from "@/lib/utils";

interface Props {
  jobId: number;
  readOnly: boolean;
  /** Harness: sekcja rozwinięta od razu. */
  defaultOpen?: boolean;
  /** Odświeżanie, gdy coś czeka w kolejce; harness podaje `false` (zero zapytań). */
  pollWhilePublishingMs?: number | false;
}

function PortalRow({
  jobId,
  config,
  posting,
  readOnly,
}: {
  jobId: number;
  config: PortalConfigItem;
  posting: JobPostingRead | null;
  readOnly: boolean;
}) {
  const queryClient = useQueryClient();
  const { showError } = useToast();
  const refresh = () => void queryClient.invalidateQueries({ queryKey: jobPortalKeys.postings(jobId) });
  const publish = useMutation({
    mutationFn: (portal: JobPortal) => publishToPortal(jobId, portal),
    onSuccess: refresh,
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się wysłać ogłoszenia.")),
  });
  const unpublish = useMutation({
    mutationFn: (portal: JobPortal) => unpublishFromPortal(jobId, portal),
    onSuccess: refresh,
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się wycofać ogłoszenia.")),
  });
  const live = isLive(posting);
  const pending = publish.isPending || unpublish.isPending;

  return (
    <li className="space-y-1 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{config.label}</span>
        <span className="text-xs text-muted-foreground">
          {config.state !== "ready"
            ? "Portal nie jest skonfigurowany"
            : posting
              ? POSTING_STATUS_LABELS[posting.status]
              : "Nie publikowano"}
          {posting?.published_at ? ` · od ${formatDate(posting.published_at)}` : ""}
        </span>
      </div>
      {posting?.status === "failed" && posting.last_error ? (
        <p role="alert" className="text-xs text-destructive">
          {posting.last_error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {posting?.url ? (
          <a
            href={posting.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            <ExternalLink className="h-3 w-3" aria-hidden /> Zobacz ogłoszenie
          </a>
        ) : null}
        {!readOnly && config.state === "ready" ? (
          live ? (
            <Button size="sm" variant="outline" disabled={pending} onClick={() => unpublish.mutate(config.portal)}>
              {unpublish.isPending ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
              Wycofaj
            </Button>
          ) : (
            <Button size="sm" variant="outline" disabled={pending} onClick={() => publish.mutate(config.portal)}>
              {publish.isPending ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
              {posting?.status === "failed" ? "Wyślij ponownie" : "Opublikuj"}
            </Button>
          )
        ) : null}
      </div>
    </li>
  );
}

export function JobPortalsSection({
  jobId,
  readOnly,
  defaultOpen = false,
  pollWhilePublishingMs = 10_000,
}: Props) {
  const [open, setOpen] = useState(defaultOpen);
  const config = useQuery({
    queryKey: jobPortalKeys.config,
    queryFn: fetchPortalConfig,
    staleTime: 5 * 60_000,
  });
  const ready = config.isSuccess && config.data.any_ready;
  const postings = useQuery({
    queryKey: jobPortalKeys.postings(jobId),
    queryFn: () => fetchJobPostings(jobId),
    enabled: ready && open,
    refetchInterval: (query) =>
      (query.state.data ?? []).some((p) => p.status === "publishing")
        ? pollWhilePublishingMs
        : false,
  });

  // Portale wyłączone (dziś) albo konfiguracja nieznana = brak sekcji. Awaria
  // odczytu konfiguracji nie może wyglądać jak działająca integracja.
  if (!ready) return null;
  const Icon = open ? ChevronDown : ChevronRight;

  return (
    <div className="border-b border-border/70 last:border-b-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 py-2 text-left text-sm font-medium"
      >
        <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
        Portale ogłoszeniowe
      </button>
      {open ? (
        <div className="pb-3 text-sm">
          <p className="text-xs text-muted-foreground">
            Treść ogłoszenia to zatwierdzony opis publiczny rekrutacji, a kandydaci aplikują przez jej link na stronie kariery.
          </p>
          {postings.isError ? (
            <p role="alert" className="mt-2 text-xs text-destructive">
              {apiErrorMessage(postings.error, "Nie udało się wczytać publikacji.")}
            </p>
          ) : postings.isSuccess ? (
            <ul className="divide-y divide-border/70">
              {config.data.portals.map((item) => (
                <PortalRow
                  key={item.portal}
                  jobId={jobId}
                  config={item}
                  posting={latestPosting(postings.data, item.portal)}
                  readOnly={readOnly}
                />
              ))}
            </ul>
          ) : (
            <p className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> Wczytuję publikacje…
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}
