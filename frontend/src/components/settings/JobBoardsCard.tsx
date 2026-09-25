"use client";

/**
 * Ustawienia → System → „Portale ogłoszeniowe” (admin).
 *
 * Jedno konto firmy u dostawcy RocketJobs / JustJoin.IT (API 1EP, OAuth).
 * „Połącz konto” prowadzi na stronę zgody dostawcy; powrót ląduje tu
 * z `?status=success|error&message=` (callback backendu) — pokazujemy toast
 * i zdejmujemy parametry z adresu. Rozłączenie bez `window.confirm` (natywny
 * dialog zamraża automatyzację przeglądarki) — dwustopniowy przycisk.
 */

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Megaphone, Plug, Trash2 } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  JOB_BOARD_CONNECTION_KEY,
  disconnectJobBoard,
  fetchJobBoardConnection,
  jobBoardAuthorizeUrl,
  jobPortalKeys,
  type JobBoardBalance,
  type JobBoardConnectionBoard,
  type JobBoardConnectionRead,
} from "@/lib/api/jobPortals";
import { cn, formatDate, formatRelativeTime } from "@/lib/utils";

const STATUS_LABEL: Record<JobBoardConnectionRead["status"], string> = {
  not_connected: "Niepołączone",
  active: "Połączone",
  reconnect_required: "Wymaga ponownego połączenia",
};

const STATUS_TONE: Record<JobBoardConnectionRead["status"], string> = {
  not_connected: "bg-muted text-muted-foreground",
  active: "bg-success-muted text-success-muted-foreground",
  reconnect_required: "bg-warning-muted text-warning-muted-foreground",
};

/** Saldo publikacji w jednym zdaniu na pozycję — puste = brak pakietów. */
export function balanceLines(balance: JobBoardBalance): string[] {
  const lines: string[] = [];
  for (const code of balance.codes) {
    lines.push(
      `${code.name}: ${code.remaining} ${code.remaining === 1 ? "ogłoszenie" : "ogłoszeń"}` +
        (code.expires_at ? ` · ważne do ${formatDate(code.expires_at)}` : ""),
    );
  }
  for (const sub of balance.subscriptions) {
    lines.push(
      `Abonament${sub.plan_key ? ` ${sub.plan_key}` : ""}: ${sub.remaining} ${sub.remaining === 1 ? "ogłoszenie" : "ogłoszeń"}` +
        (sub.end_date ? ` · do ${formatDate(sub.end_date)}` : "") +
        (sub.active ? "" : " · nieaktywny"),
    );
  }
  return lines;
}

function BoardRow({ board }: { board: JobBoardConnectionBoard }) {
  const lines = board.balance ? balanceLines(board.balance) : [];
  return (
    <li className="rounded-xl bg-muted p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold text-foreground">{board.label}</span>
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-xs font-medium",
            board.enabled ? "bg-success-muted text-success-muted-foreground" : "bg-card text-muted-foreground",
          )}
        >
          {board.enabled ? "Publikacja włączona" : "Publikacja wyłączona"}
        </span>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        Jednostka organizacyjna: {board.organization_unit_id ?? "nie ustawiono"}
      </p>
      {board.balance_error ? (
        <p role="alert" className="mt-1 text-xs text-destructive">
          Nie udało się odczytać salda: {board.balance_error}
        </p>
      ) : board.balance ? (
        lines.length > 0 ? (
          <ul className="mt-1 space-y-0.5 text-xs text-foreground">
            {lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-xs text-warning-muted-foreground">Brak wykupionych ogłoszeń.</p>
        )
      ) : null}
    </li>
  );
}

export default function JobBoardsCard() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { showSuccess, showError } = useToast();
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);

  const connection = useQuery({
    queryKey: JOB_BOARD_CONNECTION_KEY,
    queryFn: fetchJobBoardConnection,
    staleTime: 30_000,
  });

  // Powrót z OAuth dostawcy: toast raz i czysty adres.
  const returnStatus = searchParams?.get("status") ?? null;
  const returnMessage = searchParams?.get("message") ?? null;
  useEffect(() => {
    if (returnStatus !== "success" && returnStatus !== "error") return;
    if (returnStatus === "success") showSuccess(returnMessage || "Konto portali połączone.");
    else showError(returnMessage || "Nie udało się połączyć konta portali.");
    void queryClient.invalidateQueries({ queryKey: JOB_BOARD_CONNECTION_KEY });
    void queryClient.invalidateQueries({ queryKey: jobPortalKeys.config });
    router.replace("/settings?item=job-boards");
  }, [returnStatus, returnMessage, showSuccess, showError, queryClient, router]);

  const connect = useMutation({
    mutationFn: jobBoardAuthorizeUrl,
    onSuccess: (url) => {
      if (url) window.location.href = url;
    },
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się rozpocząć łączenia konta.")),
  });

  const disconnect = useMutation({
    mutationFn: disconnectJobBoard,
    onSuccess: () => {
      setConfirmDisconnect(false);
      showSuccess("Konto portali rozłączone.");
      void queryClient.invalidateQueries({ queryKey: JOB_BOARD_CONNECTION_KEY });
      void queryClient.invalidateQueries({ queryKey: jobPortalKeys.config });
    },
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się rozłączyć konta.")),
  });

  const data = connection.data;
  const status = data?.status ?? "not_connected";
  const connected = status !== "not_connected";

  return (
    <div className="rounded-2xl border border-border bg-card p-6">
      <div className="mb-5 flex items-start gap-4">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary/10">
          <Megaphone className="h-6 w-6 text-primary" />
        </div>
        <div className="flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-bold text-foreground">RocketJobs i JustJoin.IT</h3>
            {connection.isSuccess ? (
              <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", STATUS_TONE[status])}>
                {STATUS_LABEL[status]}
              </span>
            ) : null}
          </div>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Jedno konto firmy u dostawcy obu portali. Po połączeniu rekrutacje publikuje się z okna zlecenia
            i ze strony „Nowa rekrutacja”.
          </p>
        </div>
      </div>

      {connection.isError ? (
        <Alert
          variant="error"
          title="Nie udało się sprawdzić połączenia"
          description={apiErrorMessage(connection.error, "Spróbuj odświeżyć stronę.")}
        />
      ) : !connection.isSuccess ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Sprawdzam połączenie…
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {!data?.oauth_configured ? (
            <Alert
              variant="warning"
              title="Brak konfiguracji OAuth na serwerze"
              description="Aplikacja nie ma danych klienta OAuth dostawcy (JJIT_OAUTH_CLIENT_ID, JJIT_OAUTH_CLIENT_SECRET, JJIT_OAUTH_REDIRECT_URI). Bez nich nie da się połączyć konta."
            />
          ) : null}
          {status === "reconnect_required" ? (
            <Alert
              variant="warning"
              title="Połącz konto ponownie"
              description="Dostawca odrzucił zapisany dostęp — publikacja i aktualizacje ogłoszeń stoją, dopóki ktoś nie połączy konta jeszcze raz."
            />
          ) : null}
          {data?.last_error ? (
            <p role="alert" className="text-xs text-destructive">
              Ostatni błąd: {data.last_error}
            </p>
          ) : null}

          {connected ? (
            <p className="text-sm text-muted-foreground">
              Połączył(a): <span className="font-medium text-foreground">{data?.connected_by_name ?? "—"}</span>
              {data?.connected_at ? ` · ${formatRelativeTime(data.connected_at)}` : ""}
            </p>
          ) : null}

          {data && data.boards.length > 0 ? (
            <ul className="grid gap-3 sm:grid-cols-2">
              {data.boards.map((board) => (
                <BoardRow key={board.board} board={board} />
              ))}
            </ul>
          ) : null}

          <div className="flex flex-wrap items-center gap-3">
            {status !== "active" ? (
              <Button
                type="button"
                onClick={() => connect.mutate()}
                loading={connect.isPending}
                disabled={!data?.oauth_configured}
              >
                <Plug className="mr-1 h-4 w-4" />
                {status === "reconnect_required" ? "Połącz ponownie" : "Połącz konto"}
              </Button>
            ) : null}
            {connected ? (
              !confirmDisconnect ? (
                <Button type="button" variant="outline" onClick={() => setConfirmDisconnect(true)}>
                  <Trash2 className="mr-1 h-4 w-4" />
                  Rozłącz
                </Button>
              ) : (
                <div className="flex flex-wrap items-center gap-2 rounded-lg border border-destructive/20 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                  <span>Rozłączyć? Publikacje na obu portalach staną.</span>
                  <button
                    type="button"
                    onClick={() => disconnect.mutate()}
                    disabled={disconnect.isPending}
                    className="font-semibold hover:underline disabled:opacity-50"
                  >
                    {disconnect.isPending ? "Rozłączam…" : "Tak, rozłącz"}
                  </button>
                  <span aria-hidden>·</span>
                  <button type="button" onClick={() => setConfirmDisconnect(false)} className="hover:underline">
                    Anuluj
                  </button>
                </div>
              )
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
