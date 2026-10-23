"use client";

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Copy } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { interviewCycleApi } from "@/lib/api/interviewCycle";
import { clientReplyText } from "@/lib/client-reply";
import {
  candidateLabel,
  formatSlot,
  pairContext,
  type PairInfo,
  slotConfirmedMessage,
  type SlotRequest,
} from "@/lib/interview-cycle";
import { hhmm, interviewStart, slotPassed, windowBounds, windowEarliest } from "@/lib/interview-pick";
import { useAuthStore } from "@/store/auth";
import { cn } from "@/lib/utils";

const INPUT =
  "w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-hidden focus-visible:ring-2 focus-visible:ring-ring";

/**
 * „Odpisz klientowi” (0487, decyzja Artura 20.10.2026). Rekruter wybrał
 * termin z kandydatem i rozmowa jest już w kalendarzu — Delivery Lead kopiuje
 * gotową odpowiedź, wysyła ją klientowi swoim mailem i odhacza „Wysłane”.
 * Gdy klient woli inny z zaproponowanych terminów: „Klient wybrał inny
 * termin” przestawia rozmowę (stara jest odwoływana jak przy przełożeniu).
 */
export function ClientReplyDialog({
  open,
  onOpenChange,
  pair,
  request,
  onInvalidate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pair: PairInfo | null;
  request: SlotRequest | null;
  onInvalidate: () => void;
}) {
  const toast = useToast();
  const signature = useAuthStore((st) => st.user?.name ?? null);
  const [text, setText] = useState("");
  const [changing, setChanging] = useState(false);
  const [other, setOther] = useState<number | null>(null);
  const [windowTime, setWindowTime] = useState("");
  const [error, setError] = useState<string | null>(null);

  const chosen = request && request.chosen_index != null ? request.slots[request.chosen_index] : null;

  useEffect(() => {
    if (!open || !pair || !request || !chosen) return;
    setText(
      clientReplyText({
        candidateName: candidateLabel(pair),
        start: chosen.start,
        durationMinutes: request.duration_minutes,
        signature,
      }),
    );
    setChanging(false);
    setOther(null);
    setWindowTime("");
    setError(null);
    // Tekst składamy przy otwarciu — poprawki DL-a nie mogą znikać przy odświeżeniu przeglądu.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, request?.id]);

  const replied = useMutation({
    mutationFn: () => interviewCycleApi.clientReplied(request!.id),
    onSuccess: () => {
      onInvalidate();
      toast.showSuccess("Odnotowane — klient ma potwierdzenie.");
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać.")),
  });

  const otherSlot = request && other != null ? request.slots[other] : null;
  const otherStart = otherSlot ? interviewStart(otherSlot, windowTime, request!.duration_minutes) : null;
  const change = useMutation({
    mutationFn: () =>
      interviewCycleApi.changeSlot(request!.id, {
        index: other as number,
        start: otherSlot && windowBounds(otherSlot, request!.duration_minutes) ? otherStart : null,
      }),
    onSuccess: (res) => {
      onInvalidate();
      // Ten sam komunikat co potwierdzenie z przełożeniem — mówi prawdę o blokadzie w Outlooku.
      const { tone, message } = slotConfirmedMessage(res);
      const text = `${message} Rekruter dostał powiadomienie — sprawdź godziny prepów.`;
      if (tone === "error") toast.showError(text);
      else toast.showSuccess(text);
      onOpenChange(false);
    },
    onError: (err) => setError(apiErrorMessage(err, "Nie udało się zmienić terminu.")),
  });

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast.showSuccess("Skopiowane — wklej w odpowiedzi do klienta.");
    } catch {
      setError("Przeglądarka nie pozwoliła skopiować — zaznacz tekst i skopiuj ręcznie.");
    }
  };

  const busy = replied.isPending || change.isPending;
  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Odpisz klientowi"
      description="Rozmowa jest już w kalendarzu. Potwierdź klientowi termin i odhacz wysłanie."
      footer={
        <>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="h-9 px-4 text-sm text-muted-foreground hover:text-foreground"
          >
            Zamknij
          </button>
          {changing ? (
            <button
              type="button"
              disabled={busy || other == null || otherStart == null}
              onClick={() => {
                setError(null);
                change.mutate();
              }}
              className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              Przestaw rozmowę
            </button>
          ) : (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setError(null);
                replied.mutate();
              }}
              className="h-9 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              Wysłane klientowi
            </button>
          )}
        </>
      }
    >
      {pair && request && chosen ? (
        <div className="space-y-4">
          <div className="rounded-lg bg-muted/50 px-3 py-2 text-sm">
            <div className="font-semibold">{candidateLabel(pair)}</div>
            <div className="text-xs text-muted-foreground">{pairContext(pair)}</div>
            <div className="mt-1 text-sm">
              W kalendarzu: <span className="font-semibold">{formatSlot(chosen)}</span>
            </div>
          </div>

          {!changing ? (
            <div className="space-y-2">
              <label htmlFor="client-reply-text" className="text-xs font-semibold text-muted-foreground">
                Odpowiedź do klienta
              </label>
              <textarea
                id="client-reply-text"
                rows={6}
                value={text}
                onChange={(e) => setText(e.target.value)}
                className={cn(INPUT, "resize-y")}
              />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={copy}
                  className="inline-flex h-9 items-center gap-1.5 rounded-md border border-border bg-card px-3 text-sm font-semibold hover:bg-muted"
                >
                  <Copy className="h-4 w-4" aria-hidden="true" /> Kopiuj odpowiedź
                </button>
                {request.slots.length > 1 ? (
                  <button
                    type="button"
                    onClick={() => setChanging(true)}
                    className="text-sm font-semibold text-primary hover:underline"
                  >
                    Klient wybrał inny termin…
                  </button>
                ) : null}
              </div>
            </div>
          ) : (
            <fieldset className="space-y-2">
              <legend className="mb-1 text-xs font-semibold text-muted-foreground">
                Który termin wybrał klient?
              </legend>
              {request.slots.map((s, i) => {
                if (i === request.chosen_index) return null;
                const bounds = windowBounds(s, request.duration_minutes);
                // Okno, które już trwa: od teraz, nie od minionego początku (F36).
                const earliest = windowEarliest(s, request.duration_minutes);
                // Minionego terminu serwer nie przyjmie (422, audyt 21.10.2026).
                const passed = slotPassed(s, request.duration_minutes);
                return (
                  <div
                    key={`${s.start}-${i}`}
                    className={cn("rounded-md border border-border px-3 py-2 text-sm", passed && "opacity-60")}
                  >
                    <label className={cn("flex items-center gap-2", passed ? "cursor-not-allowed" : "cursor-pointer")}>
                      <input
                        type="radio"
                        name="client-other-slot"
                        checked={other === i}
                        disabled={passed}
                        onChange={() => {
                          setOther(i);
                          setWindowTime(earliest ?? "");
                        }}
                        className="h-4 w-4"
                      />
                      <span className="font-semibold">
                        {bounds
                          ? `${formatSlot({ start: s.start, end: null })} · okno ${bounds.from}–${hhmm(s.window_end as string)}`
                          : formatSlot(s)}
                      </span>
                      {passed ? <span className="text-xs text-muted-foreground">· termin minął</span> : null}
                    </label>
                    {bounds && other === i ? (
                      <label className="mt-2 flex items-center gap-2 pl-6 text-xs text-muted-foreground">
                        Godzina
                        <input
                          type="time"
                          value={windowTime}
                          min={earliest ?? bounds.from}
                          max={bounds.to}
                          step={900}
                          onChange={(e) => setWindowTime(e.target.value)}
                          className="h-9 rounded-md border border-border bg-card px-2 text-sm"
                        />
                      </label>
                    ) : null}
                  </div>
                );
              })}
              <p className="text-xs text-muted-foreground">
                Obecna rozmowa zostanie odwołana, a nowa trafi do kalendarza rekrutera. Prepy zostają — jeśli
                wypadną po rozmowie, ekran poprosi o ich przełożenie.
              </p>
              <button
                type="button"
                onClick={() => setChanging(false)}
                className="text-sm text-muted-foreground hover:text-foreground"
              >
                ← Wróć do odpowiedzi
              </button>
            </fieldset>
          )}

          {error ? (
            <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
    </AppModal>
  );
}
