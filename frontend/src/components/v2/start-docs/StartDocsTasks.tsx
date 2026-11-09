"use client";

/**
 * „Dokumenty do startu” na pulpicie („Czeka na Ciebie”) i w ikonie „Umowy”
 * w pasku. Pasek jest sygnałem stałym: czerwona liczba znika dopiero przy
 * komplecie, kliknięcie jej nie gasi (decyzja Artura 05.11.2026).
 */

import Link from "next/link";
import { useState } from "react";
import { FileUp } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  startDocsApi,
  useMineStartDocs,
  type MineStartDocRow,
} from "@/lib/api/start-documents";
import { hasSectionAccess } from "@/lib/section-access";
import { startLine } from "@/lib/start-docs-format";
import { hasRole, useAuthStore, type User } from "@/store/auth";

const ROWS = 6;
export const REMIND_NOT_SENT = "Dziś rekruter już dostał przypomnienie, drugiego nie wysyłam.";

function personHref(row: MineStartDocRow): string {
  return `/jobs/${row.job_id}?candidate=${row.candidate_id}`;
}

function missingText(row: MineStartDocRow): string {
  return row.missing.length ? `Brakuje: ${row.missing.join(", ")}` : "Komplet";
}

/** Awaria nie może wyglądać jak „nic do zrobienia”. 403 to konto spoza rekrutacji. */
function ListFailure({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const status = (error as { response?: { status?: number } })?.response?.status;
  if (status === 403) return null;
  return (
    <p role="alert" className="px-3 py-2 text-xs text-destructive">
      Nie udało się sprawdzić dokumentów do startu.{" "}
      <button type="button" className="font-medium underline" onClick={onRetry}>
        Ponów
      </button>
    </p>
  );
}

/** Lustro `require_start_documents_access`: bez tego każdy ekran kont spoza rekrutacji dokłada 403. */
function canSeeMineStartDocs(user: User | null): boolean {
  return (
    !hasRole(user, "user") &&
    hasRole(
      user,
      "admin",
      "head_of_recruitment",
      "delivery_lead",
      "talent_community_manager",
      "recruiter",
    ) &&
    hasSectionAccess(user, "pipeline", "read")
  );
}

function useMyStartDocs() {
  return useMineStartDocs(useAuthStore((state) => canSeeMineStartDocs(state.user)));
}

export function useStartDocsCount(): number {
  return useMyStartDocs().data?.items.length ?? 0;
}

function RemindButton({ row }: { row: MineStartDocRow }) {
  const { showError, showSuccess } = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="sm"
      variant="outline"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          const { sent } = await startDocsApi.remind(row.candidate_id, row.job_id);
          showSuccess(sent ? "Rekruter dostał przypomnienie." : REMIND_NOT_SENT);
        } catch (error) {
          showError(apiErrorMessage(error, "Nie udało się wysłać przypomnienia."));
        } finally {
          setBusy(false);
        }
      }}
    >
      Przypomnij rekruterowi
    </Button>
  );
}

export function StartDocsTasksSection() {
  const query = useMyStartDocs();
  const [all, setAll] = useState(false);
  const rows = query.data?.items ?? [];
  if (query.isError) {
    return (
      <div className="min-w-0 lg:col-span-3">
        <ListFailure error={query.error} onRetry={() => void query.refetch()} />
      </div>
    );
  }
  if (!rows.length) return null;
  const asDl = query.data?.role === "delivery_lead";
  const shown = all ? rows : rows.slice(0, ROWS);
  return (
    <section
      aria-label="Dokumenty do startu"
      data-testid="start-docs-tasks"
      className="min-w-0 lg:col-span-3"
    >
      <header className="mb-2 flex items-baseline gap-2">
        <h3 className="text-sm font-semibold">Dokumenty do startu</h3>
        <span className="rounded-full bg-warning-muted px-1.5 text-xs font-semibold tabular-nums text-warning-muted-foreground">
          {rows.length}
        </span>
      </header>
      <p className="mb-2 text-xs text-muted-foreground">
        {asDl
          ? "Rekruter zbiera, Ty sprawdzasz pliki i przepisujesz dane do klienta. Znika przy komplecie."
          : "Klient wpuści osobę dopiero z kompletem. Znika, gdy dodasz ostatni dokument."}
      </p>
      <ul className="divide-y divide-border rounded-lg border border-border">
        {shown.map((row) => (
          <li
            key={`${row.candidate_id}-${row.job_id}`}
            className="flex flex-wrap items-center gap-x-2 gap-y-1.5 px-3 py-2"
          >
            <div className="min-w-[12rem] flex-1">
              <Link
                href={personHref(row)}
                title={row.candidate_name}
                className="block max-w-full truncate text-sm font-medium hover:underline"
              >
                {row.candidate_name}
                {/* Sam KRK w terminie po starcie to nie alarm: osoba pracuje zgodnie z planem. */}
                {row.working && row.tone !== "calm" ? (
                  <Badge variant="danger" className="ml-2 align-middle">
                    Już pracuje
                  </Badge>
                ) : null}
              </Link>
              <p className="truncate text-xs text-muted-foreground">
                {row.agreement_number ? `Umowa ${row.agreement_number} · ` : ""}
                {row.job_title} · {row.client_name}
              </p>
              <p className="text-xs text-muted-foreground">
                {missingText(row)}
                {asDl && row.to_check.length ? ` · do sprawdzenia: ${row.to_check.join(", ")}` : ""}
                {" · "}
                {startLine(row.start_date, row.deadline, row.tone)}
                {asDl && row.recruiter_name ? ` · rekruter: ${row.recruiter_name}` : ""}
              </p>
            </div>
            {asDl ? (
              <>
                <Button size="sm" variant="ghost" asChild>
                  <Link href={personHref(row)}>Otwórz</Link>
                </Button>
                <RemindButton row={row} />
              </>
            ) : (
              <Button size="sm" variant="outline" asChild>
                <Link href={personHref(row)}>
                  <FileUp className="h-3.5 w-3.5" aria-hidden />
                  Uzupełnij
                </Link>
              </Button>
            )}
          </li>
        ))}
      </ul>
      {rows.length > ROWS ? (
        <button
          type="button"
          onClick={() => setAll((value) => !value)}
          aria-expanded={all}
          className="mt-1.5 text-xs font-medium text-primary hover:underline"
        >
          {all ? "Zwiń" : `Pokaż wszystkie (${rows.length})`}
        </button>
      ) : null}
    </section>
  );
}

/** Góra okienka „Umowy”. */
export function StartDocsTopbarBlock({ onNavigate }: { onNavigate?: () => void }) {
  const query = useMyStartDocs();
  const rows = query.data?.items ?? [];
  if (query.isError) {
    return <ListFailure error={query.error} onRetry={() => void query.refetch()} />;
  }
  if (!rows.length) return null;
  const asDl = query.data?.role === "delivery_lead";
  return (
    <div className="border-b border-border bg-warning-muted/60 p-3" data-testid="start-docs-topbar">
      <p className="text-xs font-semibold text-warning-muted-foreground">
        Dokumenty do startu · {rows.length}
      </p>
      <ul className="mt-1.5 max-h-48 space-y-1.5 overflow-y-auto">
        {rows.map((row) => (
          <li key={`${row.candidate_id}-${row.job_id}`} className="text-xs">
            <Link
              href={personHref(row)}
              onClick={onNavigate}
              className="font-medium text-foreground hover:underline"
            >
              {row.candidate_name}
            </Link>
            <span className="block text-muted-foreground">
              {missingText(row)} · {startLine(row.start_date, row.deadline, row.tone)}
              {asDl && row.recruiter_name ? ` · ${row.recruiter_name}` : ""}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
