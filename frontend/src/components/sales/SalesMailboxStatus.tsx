"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Loader2, Mail, Plug } from "lucide-react";
import { usePathname } from "next/navigation";

import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { microsoft365Api, type M365ConnectionStatus } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { rememberM365Return } from "@/lib/m365-return";
import { formatRelativeTime } from "@/lib/utils";

export type MailboxNotice = "connect" | "reconnect" | "error" | "connected" | "hidden";

/**
 * Co pokazać handlowcowi o jego skrzynce. `hidden` — konto, którego poczta
 * nie trafia do Sprzedaży (backend o tym decyduje, `mail_to_sales`).
 */
export function mailboxNotice(status: M365ConnectionStatus | undefined): MailboxNotice {
  if (!status?.mail_to_sales) return "hidden";
  if (status.requires_reconnect) return "reconnect";
  if (!status.connected) return "connect";
  if (status.last_error) return "error";
  return "connected";
}

/**
 * „Twoja skrzynka Outlook” w Sprzedaży (decyzja Artura 28.10.2026, jak
 * w Atlasie): maile i spotkania handlowca z kontaktami firm trafiają na oś
 * firmy i kartę szansy, widoczne dla zespołu Sprzedaży.
 */
export function SalesMailboxStatus() {
  const pathname = usePathname() ?? "/sales";
  const { showError } = useToast();
  const query = useQuery({
    queryKey: ["m365-connection"],
    queryFn: () => microsoft365Api.getConnection().then((r) => r.data),
    staleTime: 60_000,
  });
  const connect = useMutation({
    mutationFn: () => microsoft365Api.getAuthorizeUrl().then((r) => r.data),
    onSuccess: (data) => {
      if (!data?.authorize_url) return;
      rememberM365Return(pathname);
      window.location.href = data.authorize_url;
    },
    onError: (error) =>
      showError(apiErrorMessage(error, "Nie udało się rozpocząć podłączania skrzynki.")),
  });

  if (query.isPending) return null;
  if (query.isError) {
    return (
      <p className="text-xs text-destructive">
        Nie udało się sprawdzić, czy Twoja skrzynka Outlook jest podłączona.
      </p>
    );
  }
  const status = query.data;
  const notice = mailboxNotice(status);
  if (notice === "hidden") return null;

  const connectButton = (label: string) => (
    <Button
      size="sm"
      className="mt-2"
      onClick={() => connect.mutate()}
      disabled={connect.isPending}
    >
      {connect.isPending ? <Loader2 className="animate-spin" /> : <Plug />}
      {label}
    </Button>
  );

  if (notice === "connect") {
    return (
      <Alert
        variant="info"
        title="Podłącz swoją skrzynkę Outlook"
        description="Maile i spotkania z kontaktami firm trafią na oś firmy i kartę szansy — jak w Atlasie, widoczne dla zespołu Sprzedaży. Poza Sprzedażą zostają maile z kategorią Outlooka „ATS:ignore” i spotkania oznaczone jako prywatne."
      >
        {connectButton("Podłącz Outlooka")}
      </Alert>
    );
  }
  if (notice === "reconnect") {
    return (
      <Alert
        variant="warning"
        title="Skrzynka Outlook wymaga ponownego podłączenia"
        description="Do tego czasu nowe maile i spotkania nie trafiają do Sprzedaży."
      >
        {connectButton("Połącz ponownie")}
      </Alert>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <Mail className="size-3.5" aria-hidden />
      <StatusDot tone={notice === "error" ? "warning" : "success"}>
        {notice === "error" ? "Outlook: błąd synchronizacji" : "Outlook podłączony"}
      </StatusDot>
      <span className="truncate">{status?.mailbox_upn}</span>
      {status?.last_sync_at ? (
        <span>ostatnia synchronizacja {formatRelativeTime(status.last_sync_at)}</span>
      ) : null}
    </div>
  );
}
