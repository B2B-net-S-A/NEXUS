"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Phone } from "lucide-react";

import { useToast } from "@/components/Toast";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiErrorMessage } from "@/lib/api-error";
import { ownHiringApi, ownHiringKeys, type QueueItem } from "@/lib/api/ownHiring";
import { cn } from "@/lib/utils";

import { formatDay, formatTime, formatWhen } from "./format";
import { SlotPicker } from "./SlotPicker";

function attemptLabel(item: QueueItem): string {
  if (item.callback_at) return `Telefon ${formatWhen(item.callback_at)}`;
  return item.call_attempts === 0 ? "Pierwszy telefon" : `Próba ${item.call_attempts + 1} z ${item.max_attempts}`;
}

export function CallQueue() {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const queue = useQuery({ queryKey: ["own-hiring", "queue"], queryFn: ownHiringApi.queue, refetchInterval: 60_000 });
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [slot, setSlot] = useState<string | null>(null);
  const [callback, setCallback] = useState("");
  const items = queue.data ?? [];
  const current = items.find((item) => item.id === currentId) ?? items[0] ?? null;
  useEffect(() => {
    setSlot(null);
    setCallback("");
  }, [current?.id]);
  const done = (message: string) => {
    showSuccess(message);
    void queryClient.invalidateQueries({ queryKey: ownHiringKeys.all });
  };
  const fail = (error: unknown) => {
    showError(apiErrorMessage(error, "Nie udało się zapisać. Spróbuj ponownie."));
    void queryClient.invalidateQueries({ queryKey: ["own-hiring", "slots"] });
  };
  const book = useMutation({
    mutationFn: ({ id, start }: { id: number; start: string }) => ownHiringApi.queueBook(id, start),
    onSuccess: () => done("Rozmowa umówiona, zaproszenie wysłane"),
    onError: fail,
  });
  const result = useMutation({
    mutationFn: (input: { id: number; result: "no_answer" | "callback" | "withdrawn"; callback_at: string | null }) =>
      ownHiringApi.queueResult(input.id, { result: input.result, callback_at: input.callback_at }),
    onSuccess: () => done("Zapisano"),
    onError: fail,
  });
  const busy = book.isPending || result.isPending;
  if (queue.isError) return <QueryStateNotice state="error" />;
  return (
    <div className="flex h-[calc(100dvh-7rem)] min-h-0 flex-col">
      <header className="border-b border-border px-5 py-3">
        <h1 className="text-base font-semibold">Telefony do umówienia</h1>
        <p className="mt-0.5 text-xs text-muted-foreground">Widzisz tylko osoby przekazane do zadzwonienia.</p>
      </header>
      {queue.isPending && <p className="p-6 text-sm text-muted-foreground">Wczytuję…</p>}
      {queue.isSuccess && items.length === 0 && (
        <p className="p-6 text-sm text-muted-foreground">Nie ma teraz nikogo do zadzwonienia.</p>
      )}
      {queue.isSuccess && current && (
        <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[minmax(0,1fr)_400px]">
          <ul className="overflow-auto">
            {items.map((item) => (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => setCurrentId(item.id)}
                  className={cn(
                    "flex w-full items-center gap-3 border-b border-border px-5 py-3 text-left",
                    item.id === current.id && "bg-primary/5",
                  )}
                >
                  <Phone className="size-4 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium">{item.name}</span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {item.invited_at ? `Zaproszenie ${formatDay(item.invited_at)}, bez odpowiedzi` : item.ad_title}
                    </span>
                  </span>
                  <Badge variant={item.callback_at ? "info" : "outline"} size="sm" className="font-normal">
                    {attemptLabel(item)}
                  </Badge>
                  <ChevronRight className="size-4 text-muted-foreground" />
                </button>
              </li>
            ))}
          </ul>
          <aside className="overflow-auto border-t border-border p-4 md:border-l md:border-t-0">
            <h2 className="text-sm font-semibold">{current.name}</h2>
            <p className="mt-1 text-lg font-medium tabular-nums">{current.phone ?? "Brak numeru"}</p>
            <p className="mt-1 text-xs text-muted-foreground">{current.ad_title}</p>
            <p className="mb-1.5 mt-4 text-xs font-medium text-muted-foreground">Umów rozmowę na Teams</p>
            <SlotPicker kind="teams" value={slot} onChange={setSlot} />
            <Button
              size="sm"
              className="mt-3 w-full"
              disabled={!slot || busy}
              onClick={() => slot && book.mutate({ id: current.id, start: slot })}
            >
              {slot ? `Umów: ${formatTime(slot)} i wyślij zaproszenie` : "Wybierz termin"}
            </Button>
            <p className="mb-1.5 mt-4 text-xs font-medium text-muted-foreground">Albo wynik telefonu</p>
            <div className="grid grid-cols-2 gap-1.5">
              <Button size="sm" variant="outline" disabled={busy} onClick={() => result.mutate({ id: current.id, result: "no_answer", callback_at: null })}>
                Nie odbiera
              </Button>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => result.mutate({ id: current.id, result: "withdrawn", callback_at: null })}>
                Rezygnuje
              </Button>
            </div>
            <label htmlFor="oh-callback" className="mt-3 block text-xs text-muted-foreground">Oddzwonić</label>
            <div className="mt-1 flex gap-1.5">
              <Input id="oh-callback" type="datetime-local" value={callback} onChange={(e) => setCallback(e.target.value)} />
              <Button
                size="sm"
                variant="outline"
                disabled={!callback || busy}
                onClick={() => result.mutate({ id: current.id, result: "callback", callback_at: new Date(callback).toISOString() })}
              >
                Zapisz
              </Button>
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
