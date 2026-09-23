"use client";

/**
 * „Do Cpro wysyła: …" — jedna osoba na całą rekrutację Nordei (0353).
 *
 * Decyzja Artura 23.09.2026: nie typujemy osoby przy każdym kandydacie, tylko
 * raz dla procesu. Pasek stoi nad Tablicą, bo tam wysyłający przesuwa karty
 * z „Gotowy do Cpro" na „Wysłane do Cpro" (u Nordei = „CV wysłane"); kolejka
 * na pulpicie prowadzi właśnie tutaj.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";

import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  BOARD_TASKS_QUERY_KEY,
  assigneeLabel,
  setCproSender,
  useCproAssigneeOptions,
} from "@/lib/api/boardTasks";
import { useAuthStore } from "@/store/auth";

interface Props {
  jobId: number;
  senderId: number | null;
  senderName: string | null;
  /** Liczba osób na „Gotowy do Cpro" na tej Tablicy. */
  waiting: number;
  canChange: boolean;
}

export function CproSenderBar({ jobId, senderId, senderName, waiting, canChange }: Props) {
  const me = useAuthStore((s) => s.user);
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const options = useCproAssigneeOptions(canChange);
  const [busy, setBusy] = useState(false);

  const change = async (assigneeId: number) => {
    setBusy(true);
    try {
      const res = await setCproSender(jobId, assigneeId);
      showSuccess(
        `Do Cpro wysyła: ${res.assignee_name ?? "wybrana osoba"}${res.added_to_team ? " (dodana do zespołu rekrutacji)" : ""}.`
      );
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się ustawić osoby. Spróbuj ponownie."));
    } finally {
      setBusy(false);
      void queryClient.invalidateQueries({ queryKey: ["job", String(jobId)] });
      void queryClient.invalidateQueries({ queryKey: BOARD_TASKS_QUERY_KEY });
    }
  };

  const mine = senderId != null && senderId === me?.id;
  return (
    <div
      role="region"
      aria-label="Wysyłka do Cpro"
      className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-lg border border-info/30 bg-info-muted/40 px-3 py-2 text-sm"
    >
      <Send className="h-4 w-4 shrink-0 text-info" aria-hidden />
      <span className="font-medium">Do Cpro wysyła:</span>
      {canChange ? (
        <>
          <label className="sr-only" htmlFor={`cpro-sender-bar-${jobId}`}>
            Osoba, która wysyła kandydatów tej rekrutacji do Cpro
          </label>
          <select
            id={`cpro-sender-bar-${jobId}`}
            className="h-8 min-w-[12rem] rounded-md border border-input bg-background px-2 text-sm"
            value={senderId ?? ""}
            disabled={busy || options.isLoading}
            onChange={(e) => {
              if (e.target.value) void change(Number(e.target.value));
            }}
          >
            {senderId == null && <option value="">Nikt nie ustawiony — wybierz osobę</option>}
            {senderId != null && !(options.data ?? []).some((o) => o.id === senderId) && (
              <option value={senderId}>{senderName ?? "Ustawiona osoba"}</option>
            )}
            {(options.data ?? []).map((o) => (
              <option key={o.id} value={o.id}>
                {assigneeLabel(o)}
                {o.id === me?.id ? " (ja)" : ""}
              </option>
            ))}
          </select>
        </>
      ) : (
        <span>{senderName ?? "nikt nie jest ustawiony"}</span>
      )}
      <span className="text-muted-foreground">
        {waiting > 0
          ? `Gotowych do wysłania: ${waiting}${mine ? " — przesuń ich na „Wysłane do Cpro”." : "."}`
          : "Nikt nie czeka na wysłanie."}
      </span>
    </div>
  );
}
