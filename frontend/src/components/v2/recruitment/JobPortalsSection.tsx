"use client";

/**
 * „Portale ogłoszeniowe” (RocketJobs, JustJoin.IT, Pracuj.pl) w oknie zlecenia.
 *
 * Renderuje się WYŁĄCZNIE, gdy backend zgłasza co najmniej jeden portal gotowy
 * — na produkcji flagi są wyłączone, więc sekcja jest niewidoczna. Stan
 * portali, kolejka i powody odmów pochodzą z serwera; front niczego nie
 * zgaduje. „Opublikuj” i „Edytuj ogłoszenie” otwierają okno z parametrami
 * ogłoszenia (kategoria, miasto, widełki…) wstępnie wypełnionymi z rekrutacji.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, ExternalLink, Loader2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  POSTING_STATUS_LABELS,
  fetchJobPostings,
  fetchListingDefaults,
  fetchPortalConfig,
  isLive,
  jobPortalKeys,
  latestPosting,
  listingProblemsFromError,
  pendingActionLabel,
  publishToPortal,
  unpublishFromPortal,
  updatePostingOptions,
  validateListingOptions,
  type JobPortal,
  type JobPostingRead,
  type PortalConfigItem,
  type PortalListingOptions,
} from "@/lib/api/jobPortals";
import { formatDate } from "@/lib/utils";
import { hasRole, useAuthStore } from "@/store/auth";
import { PortalListingForm } from "./PortalListingForm";

interface Props {
  jobId: number;
  readOnly: boolean;
  /** Harness: sekcja rozwinięta od razu. */
  defaultOpen?: boolean;
  /**
   * Wejście z linku `?tab=portals` (np. `/jobs/new` po nieudanej publikacji):
   * sekcja rozwinięta i przewinięta do widoku, gdy tylko się pojawi.
   */
  focusOnReady?: boolean;
  /** Odświeżanie, gdy coś czeka w kolejce; harness podaje `false` (zero zapytań). */
  pollWhilePublishingMs?: number | false;
  /** Harness: okno publikacji otwarte od razu dla tego portalu. */
  defaultDialogPortal?: JobPortal;
}

type DialogState = { portal: PortalConfigItem; mode: "publish" | "edit"; posting: JobPostingRead | null };

/** Etykieta stanu portalu w wierszu. */
export function portalRowStatus(config: PortalConfigItem, posting: JobPostingRead | null): string {
  if (config.state === "not_connected") return "Konto portalu niepołączone";
  if (config.state !== "ready") return "Portal nie jest skonfigurowany";
  if (!posting) return "Nie publikowano";
  return pendingActionLabel(posting.pending_action) ?? POSTING_STATUS_LABELS[posting.status];
}

function PortalRow({
  config,
  posting,
  readOnly,
  isAdmin,
  pending,
  onPublish,
  onEdit,
  onUnpublish,
}: {
  config: PortalConfigItem;
  posting: JobPostingRead | null;
  readOnly: boolean;
  isAdmin: boolean;
  pending: boolean;
  onPublish: () => void;
  onEdit: () => void;
  onUnpublish: () => void;
}) {
  const live = isLive(posting);
  const closing = posting?.pending_action === "close";

  return (
    <li className="space-y-1 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{config.label}</span>
        <span className="text-xs text-muted-foreground">
          {portalRowStatus(config, posting)}
          {config.state === "ready" && posting?.published_at ? ` · od ${formatDate(posting.published_at)}` : ""}
        </span>
      </div>
      {config.state === "not_connected" ? (
        <p className="text-xs text-muted-foreground">
          Konto portalu niepołączone —{" "}
          {isAdmin ? (
            <Link href="/settings?item=job-boards" className="font-medium text-primary hover:underline">
              Ustawienia → Portale ogłoszeniowe
            </Link>
          ) : (
            "Ustawienia → Portale ogłoszeniowe"
          )}
        </p>
      ) : null}
      {posting?.last_error ? (
        // Nieudana publikacja = błąd; przy żywym ogłoszeniu (nieudana
        // aktualizacja, zamknięcie czekające na ponowne połączenie konta,
        // niezmieniony tytuł) to uwaga — ogłoszenie dalej wisi na portalu.
        <p
          role={posting.status === "failed" ? "alert" : "status"}
          className={posting.status === "failed" ? "text-xs text-destructive" : "text-xs text-warning"}
        >
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
            <>
              <Button size="sm" variant="outline" disabled={pending || closing} onClick={onEdit}>
                Edytuj ogłoszenie
              </Button>
              <Button size="sm" variant="outline" disabled={pending || closing} onClick={onUnpublish}>
                {pending ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                Wycofaj
              </Button>
            </>
          ) : (
            <Button size="sm" variant="outline" disabled={pending} onClick={onPublish}>
              {posting?.status === "failed" ? "Wyślij ponownie" : "Opublikuj"}
            </Button>
          )
        ) : null}
      </div>
    </li>
  );
}

function ListingDialog({
  jobId,
  state,
  onClose,
}: {
  jobId: number;
  state: DialogState;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const saved = state.posting?.options ?? null;
  const defaults = useQuery({
    queryKey: jobPortalKeys.listingDefaults(jobId),
    queryFn: () => fetchListingDefaults(jobId),
    enabled: saved == null,
    staleTime: 60_000,
  });
  const initial = saved ?? defaults.data ?? null;

  return (
    <AppModal
      open
      onOpenChange={(open) => (!open ? onClose() : undefined)}
      size="lg"
      title={
        state.mode === "edit"
          ? `Edytuj ogłoszenie — ${state.portal.label}`
          : `Opublikuj na ${state.portal.label}`
      }
      description="Treść ogłoszenia to zatwierdzony opis publiczny rekrutacji. Tu ustawiasz parametry, po których kandydaci je znajdą."
    >
      {initial ? (
        <ListingDialogForm
          key={state.portal.portal}
          jobId={jobId}
          state={state}
          initial={initial}
          onDone={(message) => {
            void queryClient.invalidateQueries({ queryKey: jobPortalKeys.postings(jobId) });
            showSuccess(message);
            onClose();
          }}
          onError={(err) =>
            showError(apiErrorMessage(err, "Nie udało się wysłać ogłoszenia."))
          }
          onCancel={onClose}
        />
      ) : defaults.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {apiErrorMessage(defaults.error, "Nie udało się wczytać danych rekrutacji do ogłoszenia.")}
        </p>
      ) : (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Wczytuję dane rekrutacji…
        </p>
      )}
    </AppModal>
  );
}

function ListingDialogForm({
  jobId,
  state,
  initial,
  onDone,
  onError,
  onCancel,
}: {
  jobId: number;
  state: DialogState;
  initial: PortalListingOptions;
  onDone: (message: string) => void;
  onError: (err: unknown) => void;
  onCancel: () => void;
}) {
  const [options, setOptions] = useState<PortalListingOptions>(initial);
  const [serverProblems, setServerProblems] = useState<string[] | null>(null);
  const [touched, setTouched] = useState(false);
  const portal = state.portal.portal;
  const problems = useMemo(() => validateListingOptions(options, { board: portal }), [options, portal]);
  const save = useMutation({
    mutationFn: () =>
      state.mode === "edit"
        ? updatePostingOptions(jobId, portal, options)
        : publishToPortal(jobId, portal, options),
    onSuccess: () =>
      onDone(state.mode === "edit" ? "Zmiany ogłoszenia czekają w kolejce." : "Ogłoszenie trafiło do kolejki."),
    onError: (err) => {
      const listing = listingProblemsFromError(err);
      if (listing) setServerProblems(listing);
      else onError(err);
    },
  });
  const shown = serverProblems ?? (touched ? problems : []);

  return (
    <div className="flex flex-col gap-4">
      <PortalListingForm
        value={options}
        onChange={(next) => {
          setOptions(next);
          setServerProblems(null);
        }}
        selected={[portal]}
        problems={shown}
        disabled={save.isPending}
      />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel} disabled={save.isPending}>
          Anuluj
        </Button>
        <Button
          type="button"
          loading={save.isPending}
          onClick={() => {
            setTouched(true);
            if (problems.length === 0) save.mutate();
          }}
        >
          {state.mode === "edit" ? "Zapisz zmiany" : "Opublikuj"}
        </Button>
      </div>
    </div>
  );
}

export function JobPortalsSection({
  jobId,
  readOnly,
  defaultOpen = false,
  focusOnReady = false,
  pollWhilePublishingMs = 10_000,
  defaultDialogPortal,
}: Props) {
  const [open, setOpen] = useState(defaultOpen || focusOnReady);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const focused = useRef(false);
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [dialogSeeded, setDialogSeeded] = useState(false);
  const user = useAuthStore((s) => s.user);
  const isAdmin = hasRole(user, "admin");
  const queryClient = useQueryClient();
  const { showError } = useToast();
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
      (query.state.data ?? []).some((p) => p.status === "publishing" || p.pending_action != null)
        ? pollWhilePublishingMs
        : false,
  });
  const unpublish = useMutation({
    mutationFn: (portal: JobPortal) => unpublishFromPortal(jobId, portal),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: jobPortalKeys.postings(jobId) }),
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się wycofać ogłoszenia.")),
  });

  // Sekcji nie ma w DOM do wczytania konfiguracji — przewijamy raz, po niej.
  useEffect(() => {
    if (!focusOnReady || !ready || focused.current) return;
    focused.current = true;
    rootRef.current?.scrollIntoView?.({ block: "start" });
  }, [focusOnReady, ready]);

  // Harness: otwarte okno od pierwszego renderu z danymi.
  if (defaultDialogPortal && !dialogSeeded && ready && postings.isSuccess) {
    const item = config.data.portals.find((p) => p.portal === defaultDialogPortal);
    setDialogSeeded(true);
    if (item) {
      const posting = latestPosting(postings.data, item.portal);
      setDialog({ portal: item, mode: isLive(posting) ? "edit" : "publish", posting });
    }
  }

  // Portale wyłączone (dziś) albo konfiguracja nieznana = brak sekcji. Awaria
  // odczytu konfiguracji nie może wyglądać jak działająca integracja.
  if (!ready) return null;
  const Icon = open ? ChevronDown : ChevronRight;

  return (
    <div ref={rootRef} className="border-b border-border/70 last:border-b-0">
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
              {config.data.portals.map((item) => {
                const posting = latestPosting(postings.data, item.portal);
                return (
                  <PortalRow
                    key={item.portal}
                    config={item}
                    posting={posting}
                    readOnly={readOnly}
                    isAdmin={isAdmin}
                    pending={unpublish.isPending && unpublish.variables === item.portal}
                    onPublish={() => setDialog({ portal: item, mode: "publish", posting })}
                    onEdit={() => setDialog({ portal: item, mode: "edit", posting })}
                    onUnpublish={() => unpublish.mutate(item.portal)}
                  />
                );
              })}
            </ul>
          ) : (
            <p className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" /> Wczytuję publikacje…
            </p>
          )}
        </div>
      ) : null}
      {dialog ? <ListingDialog jobId={jobId} state={dialog} onClose={() => setDialog(null)} /> : null}
    </div>
  );
}
