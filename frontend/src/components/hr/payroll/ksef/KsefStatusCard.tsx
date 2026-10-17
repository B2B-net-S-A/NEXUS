"use client";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { formatNip } from "@/components/hr/me/settlement-format";
import { Card } from "@/components/ui/card";
import { useKsefStatus, type KsefStatus } from "@/lib/api/hr-ksef";
import { formatMomentPl } from "@/lib/date-pl";
import { resolveViewState } from "@/lib/view-state";

import { HEALTH_TONE, RUN_KIND_LABELS, WHITE_LIST_MODE_LABELS } from "./ksef-format";

/**
 * Ustawienia → Płace: stan integracji z KSeF i białą listą VAT — tylko odczyt.
 * Tryb, NIP spółki i token ustawia się w zmiennych środowiska (workflow
 * „Coolify set env”), nie na ekranie.
 */
export function KsefStatusCard() {
  const status = useKsefStatus();
  const state = resolveViewState({
    isLoading: status.isLoading,
    error: status.error,
    isSuccess: status.isSuccess,
  });
  const data = status.data;

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-foreground">KSeF — faktury od zespołu</h2>
          <p className="text-sm text-muted-foreground">
            Faktury, w których spółka jest nabywcą, pobierane co godzinę — tylko od NIP-ów
            z danych do rozliczeń. Ustawienia są w zmiennych środowiska serwera.
          </p>
        </div>
        {data ? <StatusDot tone={HEALTH_TONE[data.health]}>{data.mode_label}</StatusDot> : null}
      </div>
      {state === "forbidden" || state === "error" || state === "not_found" ? (
        <QueryStateNotice state={state} onRetry={() => status.refetch()} />
      ) : !data ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : (
        <>
          {data.disabled_text ? <p className="text-sm text-foreground">{data.disabled_text}</p> : null}
          {data.last_error_text ? (
            <p role="status" className="text-sm text-destructive">
              Ostatnie pobranie ({formatMomentPl(data.last_error_at)}) się nie udało.{" "}
              {data.last_error_text}
            </p>
          ) : null}
          <Facts status={data} />
          {data.problems.length > 0 ? <Problems status={data} /> : null}
        </>
      )}
    </Card>
  );
}

function Facts({ status }: { status: KsefStatus }) {
  const counts = status.last_counts;
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
      <div>
        <dt className="text-xs text-muted-foreground">NIP spółki (kontekst logowania)</dt>
        <dd>{status.context_nip ? formatNip(status.context_nip) : "—"}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Token KSeF</dt>
        <dd>{status.token_configured ? "Ustawiony" : "Brak"}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Ostatnie pobranie</dt>
        <dd>
          {status.last_run_at
            ? `${formatMomentPl(status.last_run_at)}${status.last_run_kind ? ` · ${RUN_KIND_LABELS[status.last_run_kind]}` : ""}`
            : "Jeszcze nie pobierano"}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Ostatnie udane</dt>
        <dd>{formatMomentPl(status.last_success_at)}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">W ostatnim pobraniu</dt>
        <dd className="tabular-nums">
          od zespołu: {counts.saved ?? 0} · dostawców pominiętych: {counts.skipped ?? 0}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Czeka na ponowne pobranie</dt>
        <dd className="tabular-nums">{status.pending}</dd>
      </div>
      {status.blocked_until ? (
        <div>
          <dt className="text-xs text-muted-foreground">Limit zapytań KSeF</dt>
          <dd>Przerwa do {formatMomentPl(status.blocked_until)}</dd>
        </div>
      ) : null}
      <div>
        <dt className="text-xs text-muted-foreground">Biała lista VAT</dt>
        <dd>
          {WHITE_LIST_MODE_LABELS[status.white_list.mode]}
          {status.white_list.mode !== "off" ? (
            <span className="tabular-nums">
              {" "}
              · dziś: {status.white_list.used.search}/{status.white_list.limits.search} wyszukań,{" "}
              {status.white_list.used.check}/{status.white_list.limits.check} sprawdzeń rachunku
            </span>
          ) : null}
        </dd>
      </div>
    </dl>
  );
}

function Problems({ status }: { status: KsefStatus }) {
  return (
    <section aria-label="Faktury, których nie udało się zapisać" className="space-y-1">
      <h3 className="text-sm font-medium text-foreground">Faktury, których nie udało się zapisać</h3>
      <ul className="space-y-1 text-sm">
        {status.problems.map((problem) => (
          <li key={problem.ksef_number} className="flex flex-wrap gap-x-2">
            <span className="font-mono text-xs">{problem.ksef_number}</span>
            <span className="text-muted-foreground">{problem.text}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
