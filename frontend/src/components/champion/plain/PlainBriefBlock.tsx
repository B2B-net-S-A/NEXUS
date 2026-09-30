"use client";

/**
 * „Po ludzku” — blok na górze Podglądu Championa (makieta v7, 29.09.2026).
 *
 * Rekruter bez zaplecza technicznego dostaje tu: jedno zdanie, o co chodzi
 * w tej rekrutacji, przykład z codzienności, kim jest klient, czym osoba
 * będzie się zajmować, słowniczek technologii i pytania screeningowe z profilu
 * przetłumaczone na zwykły język. Wszystko to pomoc AI bez zatwierdzania —
 * warunki i tak ustala DL w profilu, a każdy tekst mówi, skąd pochodzi.
 *
 * Dane: `GET /api/jobs/{id}/plain-brief` (nic nie zapisuje). Otwarta
 * rekrutacja z nieaktualnym wyjaśnieniem odświeża się sama raz na
 * zamontowanie (`shouldAutoRefresh`); zamknięta dostaje przycisk.
 */

import { useState, type ReactNode } from "react";
import { Loader2, RefreshCw } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { apiErrorMessage } from "@/lib/api-error";
import {
  briefHasContent,
  useAutoRefreshPlainBrief,
  usePlainBrief,
  useRefreshPlainBrief,
  useRoleProfiles,
  useSetJobRoleProfile,
  type BriefRole,
  type PlainBrief,
} from "@/lib/api/plainKnowledge";
import { countPl } from "@/lib/plural-pl";
import { cn, formatRelativeTime } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import {
  PlainEyebrow,
  ProvenanceMark,
  SourceLinks,
  WebOriginChip,
} from "./PlainBits";
import { PlainGlossaryTable } from "./PlainGlossaryTable";
import { PlainScreeningCards } from "./PlainScreeningCards";

/** Długi opis klienta (ręczne karty mają do ~1600 znaków) zwijamy do kilku linii. */
const CLIENT_ABOUT_CLAMP = 420;

export function ClientAbout({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > CLIENT_ABOUT_CLAMP;
  return (
    <div>
      <p
        className={cn(
          "whitespace-pre-line text-[13px] leading-relaxed text-foreground",
          long && !open && "line-clamp-4",
        )}
        data-testid="plain-client-about"
      >
        {text}
      </p>
      {long ? (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="mt-1 text-xs font-medium text-primary hover:underline"
        >
          {open ? "Pokaż mniej" : "Pokaż więcej"}
        </button>
      ) : null}
    </div>
  );
}

/** Makieta 6: czego NEXUS szuka teraz w internecie dla tej rekrutacji. */
export function ResearchProgress({ brief, refreshing }: { brief: PlainBrief; refreshing: boolean }) {
  const searching = brief.glossary.filter((t) => t.status === "researching");
  const roleSearching = refreshing && !brief.role;
  if (!refreshing && searching.length === 0) return null;
  return (
    <ul className="space-y-1 rounded-md bg-muted/40 px-3 py-2 text-xs text-muted-foreground" role="status" data-testid="plain-research-progress">
      {roleSearching ? (
        <li className="flex items-center gap-1.5">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          Rola: szukam opisu w internecie i zapisuję ją w bibliotece
        </li>
      ) : null}
      {searching.length > 0 ? (
        <li className="flex items-center gap-1.5">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          Słowniczek: szukam opisu w internecie —{" "}
          {searching.slice(0, 4).map((t) => t.display_name).join(", ")}
          {searching.length > 4 ? ` i ${searching.length - 4} więcej` : ""}
        </li>
      ) : null}
      {refreshing ? (
        <li className="flex items-center gap-1.5">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          Teksty dla tej rekrutacji: w toku — to może potrwać do minuty
        </li>
      ) : null}
    </ul>
  );
}

const FAILED_DEFAULT = "Nie udało się przygotować wyjaśnienia — spróbuj „Odśwież”.";

/** „N podobnych rekrutacji · N zatrudnionych · w CV zatrudnionych najczęściej: …” — bez stawek. */
export function RoleHistoryStrip({ role }: { role: BriefRole }) {
  const { stats } = role;
  if (!stats || stats.jobs <= 0) return null;
  if (stats.jobs <= 1 && stats.hires === 0) {
    // Makieta 6: pierwsza rekrutacja na tę rolę — zamiast zer mówimy, czemu ich brak.
    return (
      <p className="text-xs text-muted-foreground" data-testid="role-history-first">
        Pierwsza taka rekrutacja. Statystyki tej roli pojawią się po pierwszych zatrudnieniach.
      </p>
    );
  }
  const titles = stats.hired_titles.filter((t) => t.title.trim()).slice(0, 3);
  return (
    <p
      className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground"
      data-testid="role-history-strip"
    >
      <span>{countPl(stats.jobs, "podobna rekrutacja", "podobne rekrutacje", "podobnych rekrutacji")}</span>
      <span aria-hidden="true">·</span>
      <span>{countPl(stats.hires, "zatrudniony", "zatrudnionych", "zatrudnionych")}</span>
      {titles.length > 0 ? (
        <>
          <span aria-hidden="true">·</span>
          <span>
            w CV zatrudnionych najczęściej: {titles.map((t) => t.title).join(", ")}
          </span>
        </>
      ) : null}
    </p>
  );
}

function RoleChip({ jobId, brief }: { jobId: number; brief: PlainBrief }) {
  const roles = useRoleProfiles("", { enabled: brief.can_change_role });
  const setRole = useSetJobRoleProfile(jobId);
  const role = brief.role;
  if (!brief.can_change_role) {
    if (!role) return null;
    return (
      <span
        className="inline-flex h-6 max-w-full items-center truncate rounded-full bg-primary/10 px-2.5 text-xs font-medium text-primary"
        data-testid="plain-role-chip"
        title={role.assignment === "manual" ? "Rolę wybrał człowiek" : "Rola dobrana automatycznie"}
      >
        {role.name}
      </span>
    );
  }
  const items = roles.data?.items ?? [];
  const options = role && !items.some((r) => r.id === role.id) ? [{ id: role.id, name: role.name }, ...items] : items;
  return (
    <label className="inline-flex max-w-full items-center gap-1.5 text-xs text-muted-foreground">
      <span className="sr-only">Rola w bibliotece</span>
      <select
        value={role?.id ?? ""}
        onChange={(e) => setRole.mutate(e.target.value ? Number(e.target.value) : null)}
        disabled={setRole.isPending}
        className="h-7 max-w-[16rem] rounded-full border border-primary/30 bg-primary/5 px-2.5 text-xs font-medium text-primary focus:outline-none focus:ring-2 focus:ring-ring"
        data-testid="plain-role-select"
        aria-label="Rola w bibliotece"
      >
        <option value="">Bez roli z biblioteki</option>
        {options.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name}
          </option>
        ))}
      </select>
      {setRole.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : null}
      {setRole.isError ? (
        <span className="text-destructive">{apiErrorMessage(setRole.error, "Nie zapisano roli")}</span>
      ) : null}
    </label>
  );
}

function BriefBody({ brief }: { brief: PlainBrief }) {
  const client = brief.client;
  const dayToDay = brief.day_to_day.filter((l) => l.trim()).slice(0, 3);
  return (
    <div className="space-y-4">
      {brief.one_liner ? (
        <div className="space-y-1">
          <p className="text-[17px] font-medium leading-snug text-foreground" data-testid="plain-one-liner">
            {brief.one_liner}
          </p>
          <ProvenanceMark kind="job" />
        </div>
      ) : null}

      {brief.example ? (
        <div className="rounded-lg border border-dashed border-border bg-muted/30 px-3.5 py-3">
          <p className="text-[13px] font-semibold text-foreground">Przykład z codzienności:</p>
          <p className="mt-1 text-[13px] leading-relaxed text-foreground">{brief.example}</p>
          {/* Przykład pisze model z profilu TEJ rekrutacji (job_plain_briefs). */}
          <ProvenanceMark kind="job" className="mt-1.5" />
        </div>
      ) : null}

      {client?.about?.trim() || dayToDay.length > 0 ? (
        <div className="grid grid-cols-1 gap-3 @2xl:grid-cols-2">
          {client?.about?.trim() ? (
            <div className="space-y-1.5 rounded-lg border border-border bg-muted/20 px-3.5 py-3" data-testid="plain-client">
              <div className="flex flex-wrap items-center gap-2">
                <PlainEyebrow>O kliencie{client.name ? ` · ${client.name}` : ""}</PlainEyebrow>
                {client.origin === "web" ? <WebOriginChip /> : null}
              </div>
              <ClientAbout text={client.about} />
              {client.origin === "web" ? <SourceLinks sources={client.sources} /> : null}
              <ProvenanceMark kind="client" />
            </div>
          ) : null}
          {dayToDay.length > 0 ? (
            <div className="space-y-1.5 rounded-lg border border-border px-3.5 py-3">
              <PlainEyebrow>Czym będzie się zajmować</PlainEyebrow>
              <ol className="list-decimal space-y-1 pl-5 text-[13px] leading-snug text-foreground">
                {dayToDay.map((line, i) => (
                  <li key={`${i}-${line}`}>{line}</li>
                ))}
              </ol>
              <ProvenanceMark kind="job" />
            </div>
          ) : null}
        </div>
      ) : null}

      {brief.glossary.length > 0 ? (
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <PlainEyebrow>Słowniczek</PlainEyebrow>
            <ProvenanceMark kind="glossary" />
          </div>
          <PlainGlossaryTable terms={brief.glossary} />
        </div>
      ) : null}

      <PlainScreeningCards items={brief.screening_plain} />
    </div>
  );
}

export function PlainBriefBlock({ jobId }: { jobId: number }) {
  const query = usePlainBrief(jobId);
  const refresh = useRefreshPlainBrief(jobId);
  useAutoRefreshPlainBrief(jobId, query.data, refresh);

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  const brief = query.data;
  const refreshing = refresh.isPending;

  const shell = (children: ReactNode) => (
    <section
      className="@container space-y-4 rounded-xl border border-primary/30 bg-card px-5 py-4"
      aria-label="Po ludzku"
      data-testid="champion-plain-brief"
    >
      {children}
    </section>
  );

  if (state === "loading") {
    return shell(
      <div className="space-y-3" aria-busy="true">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>,
    );
  }
  if (state !== "ready" || !brief) {
    return shell(
      <div role="alert" className="flex flex-wrap items-center justify-between gap-2 text-[13px]">
        <p className="text-muted-foreground">
          {state === "forbidden"
            ? "Nie masz dostępu do wyjaśnienia tej rekrutacji."
            : "Nie udało się wczytać wyjaśnienia „po ludzku”."}
        </p>
        {state === "error" ? (
          <button
            type="button"
            onClick={() => void query.refetch()}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs font-medium hover:bg-muted"
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Ponów
          </button>
        ) : null}
      </div>,
    );
  }

  const hasContent = briefHasContent(brief);
  const refreshButton = brief.can_refresh ? (
    <button
      type="button"
      onClick={() => refresh.mutate()}
      disabled={refreshing}
      className="inline-flex items-center gap-1 rounded-md border border-border px-2.5 py-1 text-xs font-medium text-foreground hover:bg-muted disabled:opacity-60"
    >
      {refreshing ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
      ) : (
        <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      {brief.status === "none" ? "Przygotuj wyjaśnienie" : "Odśwież"}
    </button>
  ) : null;

  return shell(
    <>
      <header className="space-y-1.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-[15px] font-semibold text-foreground">Po ludzku</h2>
          <RoleChip jobId={jobId} brief={brief} />
        </div>
        {brief.role ? <RoleHistoryStrip role={brief.role} /> : null}
      </header>

      <ResearchProgress brief={brief} refreshing={refreshing} />
      {refresh.isError ? (
        <p className="text-xs text-destructive" role="alert">
          {apiErrorMessage(refresh.error, "Nie udało się odświeżyć wyjaśnienia.")}
        </p>
      ) : null}
      {brief.status === "failed" ? (
        <p className="rounded-md bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground" role="alert">
          {brief.message || FAILED_DEFAULT}
        </p>
      ) : null}

      {hasContent ? (
        <BriefBody brief={brief} />
      ) : refreshing ? (
        <div className="space-y-3" aria-busy="true">
          <Skeleton className="h-6 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : brief.status === "none" ? (
        <p className="text-[13px] text-muted-foreground">
          {brief.can_refresh
            ? "Wyjaśnienie tej rekrutacji nie jest jeszcze przygotowane."
            : "Wyjaśnienie tej rekrutacji nie jest jeszcze przygotowane — przygotuje się przy najbliższym otwarciu przez zespół."}
        </p>
      ) : (
        <p className="text-[13px] text-muted-foreground">Profil nie ma jeszcze treści do wyjaśnienia.</p>
      )}

      <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3 text-xs text-muted-foreground">
        <span>
          Pomoc AI, bez zatwierdzania
          {brief.generated_at ? ` · odświeżone ${formatRelativeTime(brief.generated_at)}` : ""}
          {brief.stale && brief.status !== "none" ? " · profil zmienił się od tego czasu" : ""}
        </span>
        {refreshButton}
      </footer>
    </>,
  );
}
