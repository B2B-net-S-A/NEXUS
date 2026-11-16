"use client";

import { useState } from "react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { useSetVatMarkers, useVatMarkers, type MarkedCounterparty, type VatMarkers } from "@/lib/api/accounting-vat";
import { useCounterparties } from "@/lib/api/finance-ledger";
import { cn } from "@/lib/utils";

import { SectionCard } from "./AccountingShell";
import { markersLabel } from "./vat-model";

const CONTROL = "h-8 rounded-md border border-border bg-background px-2.5 text-sm pointer-coarse:h-10";
const NOTE = "px-3.5 py-2.5 text-[13px] text-muted-foreground";
const RESULTS_SHOWN = 8;

type Editing = Pick<MarkedCounterparty, "counterparty_id" | "name" | "markers">;

/**
 * Znaczniki JPK per kontrahent (K5b-2, decyzja z 15.11.2026): GTU i TP
 * ustawione tutaj trafiają na wszystkie faktury sprzedaży kontrahenta w JPK.
 * Zmienia lista „Księgowi” albo administrator; zmiana po wysłaniu JPK =
 * korekta (lista zamknięcia to pokaże).
 */
export function VatMarkersCard() {
  const markers = useVatMarkers();
  const [editing, setEditing] = useState<Editing | null>(null);
  const [adding, setAdding] = useState(false);
  if (markers.isError) {
    return (
      <SectionCard title="Znaczniki kontrahentów">
        <div className="p-3.5">
          <QueryStateNotice state="error" onRetry={() => markers.refetch()} />
        </div>
      </SectionCard>
    );
  }
  if (!markers.isSuccess) return null;
  const data = markers.data;
  return (
    <SectionCard title="Znaczniki kontrahentów" aside="GTU i TP w JPK">
      {data.items.length ? (
        <ul className="divide-y divide-border/70">
          {data.items.map((item) => (
            <li key={item.counterparty_id} className="flex items-center gap-2 px-3.5 py-1.5 text-[13px]">
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{item.name}</span>
                <span className="block truncate text-[12px] text-muted-foreground">{markersLabel(item.markers)}</span>
              </span>
              {data.can_edit ? (
                <Button size="sm" variant="outline" onClick={() => setEditing(item)}>
                  Zmień
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className={NOTE}>Żaden kontrahent nie ma znaczników — faktury sprzedaży idą do JPK bez GTU i TP.</p>
      )}
      {editing ? (
        <MarkersEditor data={data} item={editing} onDone={() => setEditing(null)} />
      ) : data.can_edit ? (
        adding ? (
          <CounterpartyPicker
            onPick={(party) => {
              setAdding(false);
              setEditing(data.items.find((item) => item.counterparty_id === party.counterparty_id) ?? party);
            }}
            onCancel={() => setAdding(false)}
          />
        ) : (
          <div className="border-t border-border/70 px-3.5 py-2">
            <Button size="sm" variant="outline" onClick={() => setAdding(true)}>
              Dodaj kontrahenta
            </Button>
          </div>
        )
      ) : null}
    </SectionCard>
  );
}

function CounterpartyPicker({ onPick, onCancel }: { onPick: (party: Editing) => void; onCancel: () => void }) {
  const [q, setQ] = useState("");
  const searching = q.trim().length >= 2;
  const results = useCounterparties(searching ? q : "", null, 0);
  const found = searching && results.isSuccess ? results.data.items.slice(0, RESULTS_SHOWN) : [];
  return (
    <div className="space-y-1.5 border-t border-border/70 px-3.5 py-2.5 text-[13px]">
      <div className="flex items-center gap-1.5">
        <input
          className={cn(CONTROL, "w-0 min-w-0 flex-1")}
          aria-label="Szukaj kontrahenta"
          placeholder="Nazwa albo NIP kontrahenta"
          value={q}
          onChange={(event) => setQ(event.target.value)}
        />
        <Button size="sm" variant="outline" onClick={onCancel}>
          Anuluj
        </Button>
      </div>
      {searching && results.isError ? <QueryStateNotice state="error" onRetry={() => results.refetch()} /> : null}
      {searching && results.isSuccess && !found.length ? <p className="text-muted-foreground">Nie ma takiego kontrahenta w kartotece.</p> : null}
      {found.length ? (
        <ul className="space-y-0.5">
          {found.map((party) => (
            <li key={party.id}>
              <button
                type="button"
                className="w-full truncate rounded px-1.5 py-1 text-left hover:bg-muted"
                onClick={() => onPick({ counterparty_id: party.id, name: party.name, markers: [] })}
              >
                <span className="font-medium">{party.name}</span>
                {party.id_value ? <span className="text-muted-foreground"> · {party.id_value}</span> : null}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function MarkersEditor({ data, item, onDone }: { data: VatMarkers; item: Editing; onDone: () => void }) {
  const { showToast } = useToast();
  const save = useSetVatMarkers();
  const [chosen, setChosen] = useState<string[]>(item.markers);
  const toggle = (key: string) => setChosen((prev) => (prev.includes(key) ? prev.filter((value) => value !== key) : [...prev, key]));
  const ordered = data.labels.map((label) => label.key).filter((key) => chosen.includes(key));
  const changed = ordered.join() !== item.markers.join();
  return (
    <form
      className="space-y-2 border-t border-border/70 px-3.5 py-2.5 text-[13px]"
      onSubmit={(event) => {
        event.preventDefault();
        save.mutate(
          { counterpartyId: item.counterparty_id, markers: ordered },
          {
            onSuccess: () => {
              showToast(ordered.length ? `Zapisano znaczniki — ${item.name}` : `Zdjęto znaczniki — ${item.name}`);
              onDone();
            },
            onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zapisać znaczników."), "error"),
          },
        );
      }}
    >
      <p className="font-medium">{item.name}</p>
      <div className="grid gap-x-3 gap-y-1 sm:grid-cols-2 xl:grid-cols-1">
        {data.labels.map((label) => (
          <label key={label.key} className="flex min-w-0 items-start gap-1.5" title={label.label}>
            <input type="checkbox" className="mt-0.5" checked={chosen.includes(label.key)} onChange={() => toggle(label.key)} />
            <span className="min-w-0">
              <span className="font-medium tabular-nums">{label.key}</span>
              <span className="text-muted-foreground"> · {label.label}</span>
            </span>
          </label>
        ))}
      </div>
      <div className="flex gap-1.5">
        <Button size="sm" type="submit" disabled={!changed} loading={save.isPending}>
          Zapisz
        </Button>
        <Button size="sm" type="button" variant="outline" onClick={onDone}>
          Anuluj
        </Button>
      </div>
    </form>
  );
}
