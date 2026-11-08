"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { AppModal } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { prepareClientReminder, type ClientReminder } from "@/lib/api/clientWait";

export interface ClientReminderDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  jobId: number;
  /** Puste = wszyscy czekający ponad próg. */
  candidateIds?: number[];
  /** Po przygotowaniu treści (odświeża „Przypomniano”). */
  onPrepared?: () => void;
}

/**
 * Gotowa wiadomość do klienta. Z NEXUSA nic nie wychodzi (D2): Delivery Lead
 * kopiuje treść albo otwiera ją we własnej poczcie.
 */
export function ClientReminderDialog({
  open,
  onOpenChange,
  jobId,
  candidateIds,
  onPrepared,
}: ClientReminderDialogProps) {
  const { showError, showSuccess } = useToast();
  const query = useQuery({
    queryKey: ["client-wait", jobId, "reminder", candidateIds ?? "all"],
    queryFn: () => prepareClientReminder(jobId, candidateIds),
    enabled: open,
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
  });
  const reminder: ClientReminder | undefined = query.data;
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  useEffect(() => {
    if (!reminder) return;
    setSubject(reminder.subject);
    setBody(reminder.body);
    onPrepared?.();
    // Treść wchodzi raz, dalej edytuje Delivery Lead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reminder]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(`${subject}\n\n${body}`);
      showSuccess("Skopiowano wiadomość.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się skopiować. Zaznacz tekst ręcznie."));
    }
  };

  const mailto = reminder
    ? `mailto:${encodeURIComponent(reminder.to_email ?? "")}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
    : undefined;

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Przypomnij klientowi"
      description="NEXUS nie wyśle tej wiadomości. Skopiuj ją albo otwórz we własnej poczcie."
      footer={
        <>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Zamknij
          </Button>
          {mailto ? (
            <Button type="button" variant="outline" asChild>
              <a href={mailto}>Otwórz w poczcie</a>
            </Button>
          ) : null}
          <Button type="button" onClick={() => void copy()} disabled={!reminder}>
            Kopiuj wiadomość
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        {query.isError ? (
          <div role="alert" className="space-y-2 text-sm text-destructive">
            <p>{apiErrorMessage(query.error, "Nie udało się przygotować wiadomości.")}</p>
            <Button type="button" size="sm" variant="outline" onClick={() => void query.refetch()}>
              Spróbuj ponownie
            </Button>
          </div>
        ) : null}
        {query.isLoading ? <p className="text-sm text-muted-foreground">Przygotowuję wiadomość…</p> : null}
        {reminder ? (
          <>
            {reminder.panel_url ? null : (
              <p className="rounded-md border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">
                Panel klienta jest wyłączony, więc wiadomość nie ma linku. Włączysz go w menu rekrutacji,
                jeśli ten klient się na to zgadza.
              </p>
            )}
            <label className="block space-y-1 text-sm">
              <span className="font-medium">Do</span>
              <Input value={reminder.to_email ?? ""} readOnly placeholder="Brak adresu hiring managera" />
            </label>
            <label className="block space-y-1 text-sm">
              <span className="font-medium">Temat</span>
              <Input value={subject} onChange={(e) => setSubject(e.target.value)} />
            </label>
            <label className="block space-y-1 text-sm">
              <span className="font-medium">Treść</span>
              <Textarea rows={10} value={body} onChange={(e) => setBody(e.target.value)} />
            </label>
          </>
        ) : null}
      </div>
    </AppModal>
  );
}
