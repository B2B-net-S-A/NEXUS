"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Mail } from "lucide-react";

import EmailCompose from "@/components/emails/EmailCompose";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { microsoft365Api, type M365ConnectionStatus } from "@/lib/api";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  candidateId: number;
  candidateName: string;
  candidateEmail: string;
  requestId?: number;
}

/** Ten sam klucz co karta „Outlook i kalendarz” w Ustawieniach. */
export const M365_CONNECTION_QUERY_KEY = ["m365-connection"] as const;

export function useM365Connection(enabled = true) {
  return useQuery<M365ConnectionStatus>({
    queryKey: M365_CONNECTION_QUERY_KEY,
    queryFn: () => microsoft365Api.getConnection().then((r) => r.data),
    enabled,
    staleTime: 60_000,
    retry: false,
  });
}

/** Skrzynka, z której NIE da się wysłać — wtedy okno mówi to zamiast błędu 412. */
export function mailboxUnavailable(status: M365ConnectionStatus | undefined): boolean {
  if (!status) return false;
  return !status.connected || Boolean(status.requires_reconnect);
}

/**
 * Jedno okno maila (decyzja D5, 04.10.2026): profil, pipeline i historia maili
 * używają kompozytora Microsoft 365. Bez podłączonej skrzynki serwer odmawia
 * (412), więc okno od razu mówi, co zrobić, i daje zapas „program pocztowy”.
 * Awaria odczytu stanu skrzynki nie blokuje — kompozytor pokaże błąd wysyłki.
 */
export function SendEmailV2({
  open,
  onOpenChange,
  candidateId,
  candidateName,
  candidateEmail,
  requestId,
}: Props) {
  const connection = useM365Connection(open);
  if (!open) return null;
  if (connection.isPending) return null;
  if (mailboxUnavailable(connection.data)) {
    return (
      <MailboxMissingDialog
        onOpenChange={onOpenChange}
        candidateEmail={candidateEmail}
        reconnect={Boolean(connection.data?.connected && connection.data?.requires_reconnect)}
      />
    );
  }
  return (
    <EmailCompose
      mode="new"
      candidateId={candidateId}
      candidateName={candidateName}
      defaultTo={candidateEmail}
      requestId={requestId}
      onClose={() => onOpenChange(false)}
    />
  );
}

function MailboxMissingDialog({
  onOpenChange,
  candidateEmail,
  reconnect,
}: {
  onOpenChange: (open: boolean) => void;
  candidateEmail: string;
  reconnect: boolean;
}) {
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent size="md" aria-describedby="mailbox-missing-description">
        <DialogHeader>
          <DialogTitle>
            {reconnect
              ? "Połącz ponownie skrzynkę Microsoft 365"
              : "Twoja skrzynka Microsoft 365 nie jest podłączona"}
          </DialogTitle>
          <DialogDescription id="mailbox-missing-description">
            Mail z NEXUSA wychodzi z Twojej skrzynki i zapisuje się w historii
            kandydata. Podłącz ją raz w Ustawieniach → Moje konto → „Outlook
            i kalendarz”.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-2 text-sm text-muted-foreground">
          {candidateEmail ? (
            <p>
              Możesz też napisać z programu pocztowego na adres{" "}
              <span className="select-all font-medium text-foreground">{candidateEmail}</span> —
              taki mail nie zapisze się w historii kandydata.
            </p>
          ) : (
            <p>Kandydat nie ma adresu e-mail w profilu.</p>
          )}
        </DialogBody>
        <DialogFooter className="flex-wrap gap-2">
          {candidateEmail ? (
            <Button variant="outline" asChild>
              <a href={`mailto:${candidateEmail}`}>
                <Mail className="size-4" />
                Program pocztowy
              </a>
            </Button>
          ) : null}
          <Button variant="primary" asChild>
            <Link href="/settings?area=me&item=outlook" onClick={() => onOpenChange(false)}>
              Podłącz w Ustawieniach
            </Link>
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
