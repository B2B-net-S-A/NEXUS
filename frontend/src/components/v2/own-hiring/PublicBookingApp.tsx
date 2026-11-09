"use client";

import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Calendar, Check, Clock, Video } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import { publicBookingApi, type PublicBookingView } from "@/lib/api/publicBooking";
import { cn } from "@/lib/utils";

import { formatTime, formatWhen } from "./format";

function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-dvh bg-muted/40 px-4 py-6 sm:py-10">
      <div className="mx-auto max-w-lg">
        <p className="mb-4 text-sm font-semibold">B2B Network</p>
        <div className="rounded-lg border border-border bg-card p-5 sm:p-6">{children}</div>
        <p className="mt-3 text-center text-xs text-muted-foreground">
          Dane przetwarzamy na potrzeby tej rekrutacji.
        </p>
      </div>
    </div>
  );
}

function statusOf(error: unknown): number | undefined {
  return (error as { response?: { status?: number } } | null)?.response?.status;
}

function SlotList({
  view,
  value,
  onChange,
}: {
  view: PublicBookingView;
  value: string | null;
  onChange: (slot: string) => void;
}) {
  if (!view.calendar_available) {
    return <p className="mt-4 text-sm">Chwilowo nie możemy pokazać terminów. Spróbuj za kilka minut.</p>;
  }
  if (view.days.length === 0) {
    return <p className="mt-4 text-sm">Nie ma teraz wolnych terminów. Daj znać, że żaden nie pasuje, a odezwiemy się.</p>;
  }
  return (
    <div className="mt-4 space-y-3">
      {view.days.map((day) => (
        <div key={day.date}>
          <p className="text-sm font-medium">{day.label}</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {day.slots.map((slot) => (
              <button
                key={slot}
                type="button"
                aria-pressed={value === slot}
                onClick={() => onChange(slot)}
                className={cn(
                  "min-h-10 min-w-16 rounded-md border px-3 py-2 text-center text-sm tabular-nums",
                  value === slot ? "border-primary bg-primary text-primary-foreground" : "border-border hover:bg-muted",
                )}
              >
                {formatTime(slot)}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function PublicBookingApp({ token }: { token: string }) {
  const queryClient = useQueryClient();
  const key = ["public-booking", token];
  const view = useQuery({
    queryKey: key,
    queryFn: () => publicBookingApi.view(token),
    retry: false,
    refetchOnWindowFocus: true,
  });
  const [slot, setSlot] = useState<string | null>(null);
  const [changing, setChanging] = useState(false);
  const [noFitOpen, setNoFitOpen] = useState(false);
  const [note, setNote] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const apply = (next: PublicBookingView) => {
    queryClient.setQueryData(key, next);
    setSlot(null);
    setChanging(false);
    setNoFitOpen(false);
    setError(null);
  };
  const onError = (failure: unknown) => {
    setError(apiErrorMessage(failure, "Nie udało się zapisać. Spróbuj ponownie."));
    setSlot(null);
    void queryClient.invalidateQueries({ queryKey: key });
  };
  const book = useMutation({ mutationFn: (start: string) => publicBookingApi.book(token, start), onSuccess: apply, onError });
  const cancel = useMutation({ mutationFn: () => publicBookingApi.cancel(token), onSuccess: apply, onError });
  const noFit = useMutation({
    mutationFn: () => publicBookingApi.noFit(token, note),
    onSuccess: (next) => {
      apply(next);
      setMessage("Dziękujemy. Odezwiemy się w sprawie innego terminu.");
    },
    onError,
  });
  const withdraw = useMutation({ mutationFn: () => publicBookingApi.withdraw(token), onSuccess: apply, onError });
  const busy = book.isPending || cancel.isPending || noFit.isPending || withdraw.isPending;

  if (view.isPending) return <Frame><p className="text-sm text-muted-foreground">Wczytuję terminy…</p></Frame>;
  if (view.isError) {
    const status = statusOf(view.error);
    const text = status === 404 || status === 410 ? "Ten link jest nieaktualny." : "Nie udało się wczytać strony. Spróbuj ponownie za chwilę.";
    return <Frame><p className="text-sm">{text}</p></Frame>;
  }
  const data = view.data;
  if (data.state === "closed") return <Frame><h1 className="text-lg font-semibold">Ta rekrutacja jest zamknięta</h1></Frame>;
  if (data.state === "finished") {
    return <Frame><h1 className="text-lg font-semibold">Termin został już ustalony</h1><p className="mt-1 text-sm text-muted-foreground">Szczegóły są w zaproszeniu w kalendarzu.</p></Frame>;
  }
  if (data.state === "booked" && !changing && data.booking) {
    return (
      <Frame>
        <div className="flex size-10 items-center justify-center rounded-full bg-success-muted text-success-muted-foreground"><Check className="size-5" /></div>
        <h1 className="mt-3 text-lg font-semibold">Termin zapisany</h1>
        <p className="mt-3 flex items-center gap-2 text-sm"><Calendar className="size-4 text-muted-foreground" /> {formatWhen(data.booking.start)}</p>
        <p className="mt-1 flex items-center gap-2 text-sm"><Video className="size-4 text-muted-foreground" /> Link do Teams jest w zaproszeniu w kalendarzu</p>
        {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
        <div className="mt-4 flex gap-2">
          <Button variant="outline" size="sm" disabled={busy} onClick={() => setChanging(true)}>Zmień termin</Button>
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => cancel.mutate()}>Odwołaj</Button>
        </div>
      </Frame>
    );
  }
  return (
    <Frame>
      <h1 className="text-lg font-semibold">Wybierz termin rozmowy</h1>
      <p className="mt-1 text-sm text-muted-foreground">Prowadzi: {data.owner_name}. Stanowisko: {data.role_title}.</p>
      <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="flex items-center gap-1"><Video className="size-3.5" /> Teams</span>
        <span className="flex items-center gap-1"><Clock className="size-3.5" /> {data.minutes} minut</span>
      </p>
      {message && <p className="mt-3 text-sm">{message}</p>}
      {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
      <SlotList view={data} value={slot} onChange={setSlot} />
      <Button className="mt-5 w-full" size="lg" disabled={!slot || busy} onClick={() => slot && book.mutate(slot)}>
        {slot ? `Potwierdź: ${formatWhen(slot)}` : "Wybierz godzinę"}
      </Button>
      {noFitOpen ? (
        <div className="mt-3 space-y-2">
          <label htmlFor="oh-public-note" className="text-xs text-muted-foreground">Kiedy możesz? (nieobowiązkowe)</label>
          <Textarea id="oh-public-note" value={note} maxLength={500} rows={2} onChange={(e) => setNote(e.target.value)} />
          <Button variant="outline" size="sm" disabled={busy} onClick={() => noFit.mutate()}>Wyślij</Button>
        </div>
      ) : (
        <div className="mt-3 flex justify-between text-xs">
          <button type="button" className="text-primary" onClick={() => setNoFitOpen(true)}>Żaden termin mi nie pasuje</button>
          <button type="button" className="text-muted-foreground" disabled={busy} onClick={() => withdraw.mutate()}>Rezygnuję z rekrutacji</button>
        </div>
      )}
    </Frame>
  );
}
