"use client";

import { useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { ForwardOffDialog, type ForwardOffTarget } from "@/components/hr/leave/ForwardOffDialog";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  M365_FORWARD_HEALTH,
  canCloseRule,
  forwardStillAhead,
  m365Day,
  m365ReasonLabel,
  reconcileSummary,
  useCheckM365Mailboxes,
  useCloseM365Rule,
  useM365Forwards,
  useReconcileM365Now,
  type M365ForwardHealth,
  type M365MailboxCheck,
  type M365Mode,
} from "@/lib/api/hr-m365";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { resolveViewState } from "@/lib/view-state";

function span(start: string | null, end: string | null): string {
  const a = m365Day(start);
  const b = m365Day(end);
  if (!a) return "—";
  return b && b !== a ? `${a} – ${b}` : a;
}

function Health({ health, reason }: { health: M365ForwardHealth; reason: string | null }) {
  const view = M365_FORWARD_HEALTH[health];
  return (
    <StatusDot tone={view.tone} note={reason ?? undefined}>
      {view.label}
    </StatusDot>
  );
}

interface CloseTarget {
  user_id: number;
  leave_request_id: string;
  user_name: string | null;
}

/**
 * Karta Microsoft 365 → przekierowania poczty (Compass `AdminForwardRules`):
 * lista zapisanych w NEXUSIE, „Sprawdź skrzynki” (odczyt na żywo, bez zapisu),
 * „Uzgodnij teraz” i „Zamknij regułę” przez kolejkę. Tylko Kadry i admin.
 */
export function M365ForwardsPanel({ mode }: { mode: M365Mode }) {
  const { showToast } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const forwards = useM365Forwards();
  const check = useCheckM365Mailboxes();
  const close = useCloseM365Rule();
  const reconcile = useReconcileM365Now();
  const [forwardOff, setForwardOff] = useState<ForwardOffTarget | null>(null);
  const items = forwards.data?.items ?? [];
  const state = resolveViewState({
    isLoading: forwards.isLoading,
    isError: forwards.isError,
    error: forwards.error,
    isSuccess: forwards.isSuccess,
    isEmpty: items.length === 0,
  });

  const closeRule = async (target: CloseTarget) => {
    const ok = await askConfirm({
      title: "Zamknąć regułę przekierowania?",
      description: `${target.user_name ?? "Osoba"} — reguła zastępstwa zostanie usunięta ze skrzynki przez kolejkę Microsoft 365. Poczta przestanie trafiać do zastępcy.`,
      confirmLabel: "Zamknij regułę",
      cancelLabel: "Zostaw",
      variant: "destructive",
    });
    if (!ok) return;
    close.mutate(
      { user_id: target.user_id, leave_request_id: target.leave_request_id },
      {
        onSuccess: () => {
          showToast("Zamknięcie reguły czeka w kolejce", "success");
          // Wynik sprawdzenia jest sprzed zamknięcia — sprawdź jeszcze raz po wykonaniu.
          check.reset();
        },
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się zamknąć reguły."), "error"),
      },
    );
  };

  const runReconcile = () =>
    reconcile.mutate(undefined, {
      onSuccess: (result) =>
        showToast(`Uzgadnianie zakończone — ${reconcileSummary(result.counts)}`, "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Uzgadnianie się nie udało."), "error"),
    });

  const runCheck = () =>
    check.mutate(undefined, {
      onError: (err) =>
        showToast(apiErrorMessage(err, "Nie udało się sprawdzić skrzynek."), "error"),
    });

  return (
    <section aria-labelledby="m365-forwards" className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 id="m365-forwards" className="text-sm font-medium text-foreground">
            Przekierowania poczty do zastępców
          </h3>
          <p className="text-xs text-muted-foreground">
            Reguła w skrzynce nie wygasa sama — zamyka ją kolejka po ostatnim dniu i uzgadnianie
            o 7:00.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={runCheck}
            disabled={check.isPending}
          >
            {check.isPending ? "Sprawdzanie…" : "Sprawdź skrzynki"}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={runReconcile}
            disabled={reconcile.isPending || mode === "off"}
            title={mode === "off" ? "Microsoft 365 jest wyłączony — nie ma czego uzgadniać." : undefined}
          >
            {reconcile.isPending ? "Uzgadnianie…" : "Uzgodnij teraz"}
          </Button>
        </div>
      </div>

      {state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie przekierowań…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => forwards.refetch()} />
      ) : state === "empty" ? (
        <p className="text-sm text-muted-foreground">
          Nikt nie ma teraz ani w najbliższym czasie przekierowania poczty.
        </p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <caption className="sr-only">Przekierowania zapisane w NEXUSIE</caption>
            <thead>
              <tr className={CALM_ROW}>
                <th className={`${CALM_HEAD} py-2 pr-3 text-left`}>Osoba</th>
                <th className={`${CALM_HEAD} py-2 pr-3 text-left`}>Zastępca</th>
                <th className={`${CALM_HEAD} py-2 pr-3 text-left`}>Stan</th>
                <th className={`${CALM_HEAD} py-2 text-right`}>
                  <span className="sr-only">Akcje</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.leave_request_id} className={CALM_ROW}>
                  <td className="py-2 pr-3 align-top">
                    {row.user_name ?? "—"}
                    <span className={CALM_SUBLINE}>{span(row.start_date, row.end_date)}</span>
                  </td>
                  <td className="py-2 pr-3 align-top">{row.substitute_name ?? "—"}</td>
                  <td className="py-2 pr-3 align-top">
                    <Health health={row.health} reason={row.reason} />
                    {row.last_operation?.status === "failed" ? (
                      <span className={CALM_SUBLINE}>
                        ostatnia operacja: {m365ReasonLabel(row.last_operation.last_error)}
                      </span>
                    ) : null}
                  </td>
                  <td className="py-2 text-right align-top whitespace-nowrap">
                    {row.consent && row.status === "approved" && forwardStillAhead(row.end_date) ? (
                      <Button
                        size="sm"
                        variant="quiet"
                        onClick={() =>
                          setForwardOff({
                            id: row.leave_request_id,
                            user_name: row.user_name,
                            start_date: row.start_date,
                            end_date: row.end_date,
                            substitute_name: row.substitute_name,
                          })
                        }
                      >
                        Wyłącz przekierowanie
                      </Button>
                    ) : canCloseRule(row) ? (
                      <Button
                        size="sm"
                        variant="quiet"
                        disabled={close.isPending}
                        onClick={() => void closeRule(row)}
                      >
                        Zamknij regułę
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {check.data ? (
        <MailboxCheckResult
          result={check.data}
          closing={close.isPending}
          onClose={(target) => void closeRule(target)}
        />
      ) : null}

      <ForwardOffDialog
        target={forwardOff}
        onClose={(done) => {
          setForwardOff(null);
          if (done) showToast("Przekierowanie wyłączone — reguła zostanie zamknięta", "success");
        }}
      />
      {confirmDialog}
    </section>
  );
}

function MailboxCheckResult({
  result,
  closing,
  onClose,
}: {
  result: M365MailboxCheck;
  closing: boolean;
  onClose: (target: CloseTarget) => void;
}) {
  if (!result.available) {
    return (
      <p role="status" className="rounded-md bg-muted px-3 py-2 text-sm text-foreground">
        {result.message}
      </p>
    );
  }
  const problems = result.items.filter((item) => item.health !== "ok");
  return (
    <div className="space-y-2 rounded-md border border-border p-3" aria-live="polite">
      <p className="text-sm text-foreground">
        Sprawdzono skrzynek: {result.scanned ?? 0}.{" "}
        {problems.length
          ? `Do wyjaśnienia: ${problems.length}.`
          : "Reguły zgadzają się z NEXUSEM."}
      </p>
      {result.unreadable && result.unreadable.length > 0 ? (
        <p className="text-xs text-muted-foreground">
          Nie udało się odczytać:{" "}
          {result.unreadable
            .map((row) => `${row.name} (${m365ReasonLabel(row.error)})`)
            .join(", ")}
          {" — ich stan jest nieznany."}
        </p>
      ) : null}
      {result.items.length > 0 ? (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <caption className="sr-only">Reguły zastępstw w skrzynkach</caption>
            <thead>
              <tr className={CALM_ROW}>
                <th className={`${CALM_HEAD} py-2 pr-3 text-left`}>Skrzynka</th>
                <th className={`${CALM_HEAD} py-2 pr-3 text-left`}>Reguła</th>
                <th className={`${CALM_HEAD} py-2 pr-3 text-left`}>Stan</th>
                <th className={`${CALM_HEAD} py-2 text-right`}>
                  <span className="sr-only">Akcje</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {result.items.map((item) => (
                <tr key={`${item.user_id}-${item.rule_id ?? item.leave_request_id}`} className={CALM_ROW}>
                  <td className="py-2 pr-3 align-top">
                    {item.user_name ?? "—"}
                    <span className={CALM_SUBLINE}>{span(item.start_date, item.end_date)}</span>
                  </td>
                  <td className="py-2 pr-3 align-top">
                    {item.rule_id
                      ? item.owner === "compass"
                        ? "Compass"
                        : "NEXUS"
                      : "—"}
                    {item.substitute_name ? (
                      <span className={CALM_SUBLINE}>do {item.substitute_name}</span>
                    ) : null}
                  </td>
                  <td className="py-2 pr-3 align-top">
                    <Health health={item.health} reason={item.reason} />
                  </td>
                  <td className="py-2 text-right align-top">
                    {item.rule_id && canCloseRule(item) ? (
                      <Button
                        size="sm"
                        variant="quiet"
                        disabled={closing}
                        onClick={() =>
                          onClose({
                            user_id: item.user_id,
                            leave_request_id: item.leave_request_id,
                            user_name: item.user_name,
                          })
                        }
                      >
                        Zamknij regułę
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
