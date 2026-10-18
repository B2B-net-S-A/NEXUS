"use client";

import { Fragment, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiErrorMessage } from "@/lib/api-error";
import {
  M365_KIND_LABELS,
  M365_MODE_LABELS,
  m365Day,
  m365ProfileSyncView,
  m365ReasonLabel,
  m365SecretView,
  m365StatusView,
  useM365Operations,
  useM365Status,
  useRetryM365Operation,
  type M365Mode,
  type M365Operation,
  type M365QueueTab,
  type M365Secret,
  type M365Status,
} from "@/lib/api/hr-m365";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";

import { M365ForwardsPanel } from "./M365ForwardsPanel";

const MODE_TONE: Record<M365Mode, StatusDotTone> = {
  off: "neutral",
  simulate: "info",
  live: "success",
};

const MODE_NOTE: Record<M365Mode, string> = {
  off: "Nic nie wychodzi do Microsoft 365. Operacje czekają w kolejce.",
  simulate:
    "Żądania są zapisywane, ale nie trafiają do skrzynek. Podgląd w zakładce „Zasymulowane”.",
  live: "Autoodpowiedzi, wydarzenia i przekierowania trafiają do skrzynek.",
};

const EMPTY_TEXT: Record<M365QueueTab, string> = {
  pending: "Kolejka jest pusta.",
  failed: "Brak nieudanych operacji.",
  simulated: "Nic jeszcze nie zasymulowano.",
};

const MAX_ATTEMPTS = 6;

function warsawMoment(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("pl-PL", {
    timeZone: "Europe/Warsaw",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function windowLabel(op: M365Operation): string | null {
  const start = m365Day(op.window_start);
  const end = m365Day(op.window_end);
  if (!start) return null;
  return end && end !== start ? `${start} – ${end}` : start;
}

function stateNote(op: M365Operation): string | null {
  const parts: string[] = [];
  const reason = m365ReasonLabel(op.last_error);
  if (reason) parts.push(reason);
  if (op.attempts > 0 && op.status !== "done") {
    parts.push(`próba ${op.attempts} z ${MAX_ATTEMPTS}`);
  }
  if (op.status === "pending") {
    parts.push(`następna ${warsawMoment(op.next_attempt_at)}`);
  }
  return parts.length ? parts.join(" · ") : null;
}

function requestPreview(op: M365Operation): string {
  const requests = op.simulated_request?.requests ?? [];
  return requests
    .map((request) => {
      const head = `${request.method} ${request.path}`;
      const params = request.params ? `\n${JSON.stringify(request.params, null, 2)}` : "";
      const body = request.body === undefined ? "" : `\n${JSON.stringify(request.body, null, 2)}`;
      return `${head}${params}${body}`;
    })
    .join("\n\n");
}

function Facts({ status }: { status: M365Status }) {
  const reconcile = status.last_reconcile;
  const profiles = m365ProfileSyncView(status.last_profile_sync);
  const secret = m365SecretView(status.secret);
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
      <div>
        <dt className="text-xs text-muted-foreground">Aplikacja NEXUSA w Microsoft 365</dt>
        <dd>
          {status.credentials_configured
            ? "Poświadczenia ustawione"
            : "Brak poświadczeń — w trybie „Na żywo” operacje czekają"}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Skrzynki</dt>
        <dd className="break-words">
          {status.allowlist.length
            ? `Tylko lista próbna: ${status.allowlist.join(", ")}`
            : "Wszystkie"}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Uzgadnianie o 7:00</dt>
        <dd>
          {reconcile
            ? `${m365Day(reconcile.day)} · ${reconcile.status === "failed" ? "nie udało się" : reconcile.status === "done" ? "zakończone" : "w trakcie"}`
            : "Jeszcze się nie odbyło"}
        </dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Czekające na termin</dt>
        <dd className="tabular-nums">{status.deferred}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">
          Profile z katalogu (stanowisko, dział, telefon)
        </dt>
        <dd>
          <StatusDot tone={profiles.tone} note={profiles.note}>
            {profiles.label}
          </StatusDot>
        </dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">Sekret aplikacji</dt>
        <dd>
          <StatusDot tone={secret.tone} note={secret.note}>
            {secret.label}
          </StatusDot>
        </dd>
      </div>
    </dl>
  );
}

/** Ostrzeżenie nad kartą, gdy sekret wygasa w 30 dni, wygasł albo nie znamy terminu. */
function SecretWarning({ secret }: { secret: M365Secret }) {
  const day = m365Day(secret.expires_on);
  if (secret.state === "expired") {
    return (
      <p role="alert" className="rounded-md bg-destructive-muted px-3 py-2 text-sm text-destructive-muted-foreground">
        {secret.days_left === 0
          ? `Sekret aplikacji wygasa dziś (${day}).`
          : `Sekret aplikacji wygasł ${day}.`}{" "}
        Autoodpowiedzi, przekierowania i czytnik administracja@ przestają działać — potrzebny
        nowy sekret.
      </p>
    );
  }
  if (secret.state === "expiring") {
    const when = secret.days_left === 1 ? "jutro" : `za ${secret.days_left} dni`;
    return (
      <p role="status" className="rounded-md bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground">
        Sekret aplikacji wygasa {when} ({day}). Po tym terminie staną autoodpowiedzi,
        przekierowania i czytnik administracja@ — admin ustawia nowy sekret i datę przez
        „Coolify set env”.
      </p>
    );
  }
  if (secret.state === "missing") {
    return (
      <p role="status" className="rounded-md bg-warning-muted px-3 py-2 text-sm text-warning-muted-foreground">
        Nie znamy daty wygaśnięcia sekretu aplikacji. Bez niej NEXUS nie ostrzeże przed
        terminem — admin ustawia ją przy rotacji sekretu.
      </p>
    );
  }
  return null;
}

function OperationsTable({ tab }: { tab: M365QueueTab }) {
  const { showToast } = useToast();
  const operations = useM365Operations(tab);
  const retry = useRetryM365Operation();
  const [preview, setPreview] = useState<number | null>(null);
  const items = operations.data?.items ?? [];
  const state = resolveViewState({
    isLoading: operations.isLoading,
    isError: operations.isError,
    error: operations.error,
    isSuccess: operations.isSuccess,
    isEmpty: items.length === 0,
  });

  if (state === "forbidden" || state === "error" || state === "not_found") {
    return <QueryStateNotice state={state} onRetry={() => operations.refetch()} />;
  }
  if (state === "loading") {
    return <p className="text-sm text-muted-foreground">Wczytywanie…</p>;
  }
  if (state === "empty") {
    return <p className="text-sm text-muted-foreground">{EMPTY_TEXT[tab]}</p>;
  }

  const runRetry = (op: M365Operation) =>
    retry.mutate(op.id, {
      onSuccess: () => showToast("Operacja wróciła do kolejki", "success"),
      onError: (err) =>
        showToast(apiErrorMessage(err, "Nie udało się ponowić operacji."), "error"),
    });

  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[520px] text-sm">
        <thead>
          <tr className={CALM_ROW}>
            <th className={`${CALM_HEAD} py-2 pr-3 text-left`}>Osoba</th>
            <th className={`${CALM_HEAD} py-2 pr-3 text-left`}>Operacja</th>
            <th className={`${CALM_HEAD} py-2 pr-3 text-left`}>Stan</th>
            <th className={`${CALM_HEAD} py-2 text-right`}>
              <span className="sr-only">Akcje</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((op) => {
            const view = m365StatusView(op);
            const span = windowLabel(op);
            const canRetry = op.status === "failed" || op.status === "pending";
            const hasPreview = Boolean(op.simulated_request?.requests.length);
            const open = preview === op.id;
            return (
              <Fragment key={op.id}>
                <tr className={CALM_ROW}>
                  <td className="py-2 pr-3 align-top">{op.user_name ?? "—"}</td>
                  <td className="py-2 pr-3 align-top">
                    {M365_KIND_LABELS[op.kind] ?? op.kind}
                    {span ? <span className={CALM_SUBLINE}>{span}</span> : null}
                  </td>
                  <td className="py-2 pr-3 align-top">
                    <StatusDot tone={view.tone} note={stateNote(op)}>
                      {view.label}
                    </StatusDot>
                  </td>
                  <td className="py-2 text-right align-top whitespace-nowrap">
                    {hasPreview ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-expanded={open}
                        onClick={() => setPreview(open ? null : op.id)}
                      >
                        {open ? "Zwiń" : "Podgląd"}
                      </Button>
                    ) : null}
                    {canRetry ? (
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={retry.isPending}
                        onClick={() => runRetry(op)}
                      >
                        Ponów
                      </Button>
                    ) : null}
                  </td>
                </tr>
                {open ? (
                  <tr className={CALM_ROW}>
                    <td colSpan={4} className="pb-3">
                      <p className="mb-1 text-xs text-muted-foreground">
                        Żądania do Microsoft Graph
                        {op.simulated_request?.mailbox
                          ? ` · skrzynka ${op.simulated_request.mailbox}`
                          : ""}
                      </p>
                      <pre
                        aria-label="Podgląd żądań"
                        className="max-h-64 overflow-auto rounded-md bg-muted/60 p-3 text-[11px] leading-4 text-foreground"
                      >
                        {requestPreview(op)}
                      </pre>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      {operations.data && operations.data.total > items.length ? (
        <p className="mt-2 text-xs text-muted-foreground">
          Pokazano {items.length} z {operations.data.total}.
        </p>
      ) : null}
    </div>
  );
}

function MailboxLists({ status }: { status: M365Status }) {
  if (!status.custom_oof_mailboxes.length && !status.mailbox_errors.length) return null;
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {status.custom_oof_mailboxes.length ? (
        <section aria-labelledby="m365-custom-oof">
          <h3 id="m365-custom-oof" className="text-sm font-medium text-foreground">
            Własna autoodpowiedź osoby
          </h3>
          <p className="text-xs text-muted-foreground">
            NEXUS jej nie nadpisał. Z datami — dni bez wniosku trafiają do Akceptacji jako
            wniosek „Z Outlooka”; bez dat — sprawdź z osobą, czy obejmuje nieobecność.
          </p>
          <ul className="mt-1 space-y-0.5 text-sm">
            {status.custom_oof_mailboxes.map((row) => (
              <li key={row.user_id}>{row.name}</li>
            ))}
          </ul>
        </section>
      ) : null}
      {status.mailbox_errors.length ? (
        <section aria-labelledby="m365-mailbox-errors">
          <h3 id="m365-mailbox-errors" className="text-sm font-medium text-foreground">
            Skrzynki z błędem
          </h3>
          <ul className="mt-1 space-y-0.5 text-sm">
            {status.mailbox_errors.map((row) => (
              <li key={row.user_id}>
                {row.name}
                <span className="text-muted-foreground">
                  {" · "}
                  {m365ReasonLabel(row.last_error)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

/** Ustawienia → Kadry: Microsoft 365 dla urlopów (tryb, kolejka, „Ponów”). */
export function M365Card() {
  const status = useM365Status();
  const [tab, setTab] = useState<M365QueueTab>("pending");
  const state = resolveViewState({
    isLoading: status.isLoading,
    isError: status.isError,
    error: status.error,
    isSuccess: status.isSuccess,
  });
  const data = status.data;
  const counts = data?.counts;

  return (
    <Card className="space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-foreground">Microsoft 365 — urlopy</h2>
          <p className="text-sm text-muted-foreground">
            Autoodpowiedź, wydarzenie „Poza biurem” i przekierowanie poczty do zastępcy.
            Uzgadnianie ze skrzynkami codziennie o 7:00.
          </p>
        </div>
        {data ? (
          <StatusDot tone={MODE_TONE[data.mode]} aria-label={`Tryb: ${M365_MODE_LABELS[data.mode]}`}>
            {M365_MODE_LABELS[data.mode]}
          </StatusDot>
        ) : null}
      </div>
      {state === "forbidden" || state === "error" || state === "not_found" ? (
        <QueryStateNotice state={state} onRetry={() => status.refetch()} />
      ) : state === "loading" || !data ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : (
        <>
          <SecretWarning secret={data.secret} />
          <p className="text-sm text-foreground">{MODE_NOTE[data.mode]}</p>
          <Facts status={data} />
          <TabbedNav
            ariaLabel="Kolejka operacji"
            value={tab}
            onValueChange={(value) => setTab(value as M365QueueTab)}
            dense
            tabs={[
              {
                value: "pending",
                label: "Oczekujące",
                count: (counts?.pending ?? 0) + (counts?.running ?? 0),
              },
              { value: "failed", label: "Nieudane", count: counts?.failed ?? 0 },
              { value: "simulated", label: "Zasymulowane", count: counts?.simulated ?? 0 },
            ]}
          />
          <OperationsTable key={tab} tab={tab} />
          <MailboxLists status={data} />
          <M365ForwardsPanel mode={data.mode} />
        </>
      )}
    </Card>
  );
}
