"use client";

/**
 * „Usuń klienta" — okno z profilu klienta (dowolny status).
 *
 * Otwarcie okna JEST próbą usunięcia: backend ocenia klienta i — gdy są
 * otwarte zamówienia, aktywni kontraktorzy albo kandydaci w otwartych
 * rekrutacjach — odmawia i zapisuje próbę w Historii zdarzeń. Dlatego ocena
 * leci RAZ na otwarcie (mutacja, nie zapytanie z automatycznymi ponowieniami:
 * każde ponowienie byłoby kolejnym wpisem w dzienniku).
 *
 * Potwierdzenie jest takie samo dla klienta pustego i klienta z historią —
 * wpisanie „0". Klient z historią dostaje nad nim zdanie o powiązanych danych.
 */

import { useEffect, useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { AlertTriangle, Ban, Info, Loader2, Trash2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { extractErrorMsg } from "@/lib/api";
import {
  CLIENT_DELETION_CONFIRMATION,
  clientDeletionApi,
  isConfirmationValid,
  type ClientDeletionCheck,
  type ClientDeletionResult,
} from "@/lib/client-deletion";

interface DeleteClientDialogProps {
  clientId: number;
  clientName: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted: (result: ClientDeletionResult) => void;
}

function blockedCheckFrom(error: unknown): ClientDeletionCheck | null {
  if (!(error instanceof AxiosError) || error.response?.status !== 409) return null;
  const check = (error.response.data as { check?: ClientDeletionCheck } | undefined)
    ?.check;
  return check && check.mode === "blocked" ? check : null;
}

export function DeleteClientDialog({
  clientId,
  clientName,
  open,
  onOpenChange,
  onDeleted,
}: DeleteClientDialogProps) {
  const [check, setCheck] = useState<ClientDeletionCheck | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const firedForOpen = useRef(false);

  const checkMutation = useMutation({
    mutationFn: () => clientDeletionApi.check(clientId),
    onSuccess: (data) => setCheck(data),
  });
  const deleteMutation = useMutation({
    mutationFn: () => clientDeletionApi.execute(clientId, confirmation),
    onSuccess: (result) => onDeleted(result),
    onError: (error) => {
      // Między oceną a potwierdzeniem mogło przybyć zamówienie — serwer
      // liczy ocenę od nowa i odsyła ją razem z 409.
      const blocked = blockedCheckFrom(error);
      if (blocked) setCheck(blocked);
    },
  });

  useEffect(() => {
    if (!open) {
      firedForOpen.current = false;
      return;
    }
    if (firedForOpen.current) return;
    firedForOpen.current = true;
    setCheck(null);
    setConfirmation("");
    checkMutation.reset();
    deleteMutation.reset();
    checkMutation.mutate();
    // Mutacje są stabilne w obrębie komponentu; efekt ma odpalić raz na otwarcie.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const blocked = check?.mode === "blocked";
  const canConfirm =
    !!check && check.can_delete && isConfirmationValid(confirmation);
  const deleteError =
    deleteMutation.isError && !blockedCheckFrom(deleteMutation.error)
      ? extractErrorMsg(deleteMutation.error)
      : null;

  const close = () => onOpenChange(false);

  const footer = blocked ? (
    <Button variant="outline" onClick={close}>
      Zamknij
    </Button>
  ) : (
    <>
      <Button variant="outline" onClick={close} disabled={deleteMutation.isPending}>
        Anuluj
      </Button>
      <Button
        variant="destructive"
        onClick={() => deleteMutation.mutate()}
        disabled={!canConfirm || deleteMutation.isPending}
      >
        {deleteMutation.isPending ? (
          <Loader2 className="w-4 h-4 animate-spin mr-1.5" />
        ) : (
          <Trash2 className="w-4 h-4 mr-1.5" />
        )}
        Usuń klienta
      </Button>
    </>
  );

  return (
    <AppModal
      open={open}
      onOpenChange={(next) => {
        if (!deleteMutation.isPending) onOpenChange(next);
      }}
      title={blocked ? "Nie można usunąć klienta" : "Usuń klienta"}
      description={clientName}
      footer={
        check ? (
          footer
        ) : checkMutation.isError ? (
          <Button variant="outline" onClick={close}>
            Zamknij
          </Button>
        ) : undefined
      }
    >
      {checkMutation.isPending && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
          <Loader2 className="w-4 h-4 animate-spin" />
          Sprawdzam, co jest powiązane z klientem…
        </div>
      )}

      {checkMutation.isError && !check && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive"
        >
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{extractErrorMsg(checkMutation.error)}</span>
        </div>
      )}

      {check && blocked && (
        <div className="space-y-3">
          <div
            role="alert"
            className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2.5 text-sm text-destructive"
          >
            <Ban className="w-4 h-4 shrink-0 mt-0.5" />
            <span>
              Klient ma otwarte zamówienia lub aktywnych kandydatów, więc nie może
              zostać usunięty — niezależnie od jego statusu. Próba została
              odnotowana w Historii zdarzeń.
            </span>
          </div>
          <ul className="space-y-2.5">
            {check.blockers.map((blocker) => (
              <li key={blocker.code} className="text-sm">
                <p className="font-medium text-foreground">
                  {blocker.label}: {blocker.count}
                </p>
                {blocker.items.length > 0 && (
                  <ul className="mt-1 ml-4 list-disc text-muted-foreground space-y-0.5">
                    {blocker.items.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {check && !blocked && (
        <div className="space-y-4">
          {check.history_sentence ? (
            <div className="flex items-start gap-2 rounded-lg border border-amber-300/60 bg-amber-50 dark:bg-amber-950/30 px-3 py-2.5 text-sm text-amber-900 dark:text-amber-200">
              <Info className="w-4 h-4 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p>{check.history_sentence}</p>
                <p className="text-xs">
                  Te dane nie zostaną usunięte — pozostaną zachowane w systemie,
                  a klient zniknie z list.
                </p>
              </div>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              Klient nie ma żadnych powiązanych danych — zostanie usunięty trwale.
            </p>
          )}

          <div className="space-y-2">
            <label
              htmlFor="delete-client-confirmation"
              className="block text-sm font-medium text-foreground"
            >
              Czy na pewno chcesz usunąć tego klienta? Wpisz{" "}
              {CLIENT_DELETION_CONFIRMATION}, jak chcesz usunąć.
            </label>
            <Input
              id="delete-client-confirmation"
              inputMode="numeric"
              autoComplete="off"
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && canConfirm && !deleteMutation.isPending) {
                  deleteMutation.mutate();
                }
              }}
              className="max-w-[8rem]"
              autoFocus
            />
          </div>

          {deleteError && (
            <p role="alert" className="text-sm text-destructive">
              {deleteError}
            </p>
          )}
        </div>
      )}
    </AppModal>
  );
}

export default DeleteClientDialog;
