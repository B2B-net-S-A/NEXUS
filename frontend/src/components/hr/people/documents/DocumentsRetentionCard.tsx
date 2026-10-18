"use client";

import { useState } from "react";
import Link from "next/link";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  DOCUMENT_KIND_LABELS,
  useDeleteRetentionDue,
  useRetentionDue,
  useSaveRetention,
  type DocumentKind,
  type RetentionEntry,
} from "@/lib/api/hr-documents";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatIsoDatePl } from "@/lib/date-pl";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

/** Zmienione okresy (lata) — serwer dostaje tylko to, co się zmieniło. */
export function retentionChanges(
  entries: RetentionEntry[],
  form: Partial<Record<DocumentKind, string>>,
): { years: Partial<Record<DocumentKind, number>>; error: string | null } {
  const years: Partial<Record<DocumentKind, number>> = {};
  for (const entry of entries) {
    const raw = form[entry.kind];
    if (raw === undefined || raw.trim() === String(entry.years)) continue;
    const value = Number(raw.trim());
    if (!Number.isInteger(value) || value < 1 || value > 50) {
      return { years: {}, error: `Okres dla „${entry.label}”: pełne lata od 1 do 50.` };
    }
    years[entry.kind] = value;
  }
  return { years, error: null };
}

function RetentionYears({ entries }: { entries: RetentionEntry[] }) {
  const { showToast } = useToast();
  const save = useSaveRetention();
  const [form, setForm] = useState<Partial<Record<DocumentKind, string>>>({});
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    const { years, error: invalid } = retentionChanges(entries, form);
    if (invalid) {
      setError(invalid);
      return;
    }
    if (Object.keys(years).length === 0) {
      showToast("Bez zmian", "success");
      return;
    }
    save.mutate(years, {
      onSuccess: () => {
        setForm({});
        showToast("Okresy przechowywania zapisane", "success");
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać okresów.")),
    });
  };

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-foreground">Okres przechowywania po odejściu</h3>
      <ul className="grid gap-x-6 gap-y-1.5 sm:grid-cols-2 lg:grid-cols-3">
        {entries.map((entry) => (
          <li key={entry.kind} className="flex items-center justify-between gap-3 text-sm">
            <label htmlFor={`retention-${entry.kind}`} className="text-foreground">
              {entry.label}
            </label>
            <span className="flex items-center gap-1.5">
              <Input
                id={`retention-${entry.kind}`}
                inputMode="numeric"
                className="h-8 w-16 text-right tabular-nums"
                value={form[entry.kind] ?? String(entry.years)}
                onChange={(event) =>
                  setForm((current) => ({ ...current, [entry.kind]: event.target.value }))
                }
              />
              <span className="text-xs text-muted-foreground">lat</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        Liczone od końca roku, w którym osoba odeszła. Po terminie dokument trafia na listę niżej —
        nic nie znika samo.
      </p>
      <div className="flex flex-wrap items-center justify-end gap-2">
        {error ? (
          <p role="alert" className="mr-auto text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <Button size="sm" onClick={submit} disabled={save.isPending}>
          {save.isPending ? "Zapisywanie…" : "Zapisz okresy"}
        </Button>
      </div>
    </div>
  );
}

/**
 * Ustawienia → Kadry → „Dokumenty po terminie przechowywania” (e-teczka, E4).
 * Lista dokumentów osób, które odeszły, po upływie okresu dla rodzaju. Usuwa
 * człowiek: zaznaczenie + potwierdzenie; serwer sprawdza każdą pozycję jeszcze
 * raz (osoba mogła wrócić). Plik znika, ślad zostaje.
 */
export function DocumentsRetentionCard() {
  const { showToast } = useToast();
  const due = useRetentionDue();
  const remove = useDeleteRetentionDue();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const state = resolveViewState({
    isLoading: due.isLoading,
    isError: due.isError,
    error: due.error,
    isSuccess: due.isSuccess,
    isEmpty: (due.data?.items ?? []).length === 0,
  });
  const items = due.data?.items ?? [];

  const toggle = (id: number, on: boolean) =>
    setPicked((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const deletePicked = async () => {
    const ids = items.filter((item) => picked.has(item.id)).map((item) => item.id);
    if (ids.length === 0) return;
    const ok = await askConfirm({
      title: `Usunąć ${ids.length === 1 ? "dokument" : `dokumenty (${ids.length})`}?`,
      description:
        "Pliki znikną z NEXUSA na stałe. Zostanie ślad: rodzaj, tytuł, kto i kiedy usunął.",
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!ok) return;
    remove.mutate(ids, {
      onSuccess: (result) => {
        setPicked(new Set());
        showToast(
          result.skipped.length
            ? `Usunięto ${result.deleted.length}; ${result.skipped.length} już nie jest po terminie.`
            : `Usunięto ${result.deleted.length}.`,
          "success",
        );
      },
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się usunąć dokumentów."), "error"),
    });
  };

  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className="text-base font-semibold text-foreground">Dokumenty po terminie przechowywania</h2>
        <p className="text-sm text-muted-foreground">
          Dokumenty osób, które odeszły, gdy minął okres przechowywania ich rodzaju.
        </p>
      </div>
      {state === "forbidden" || state === "error" || state === "not_found" ? (
        <QueryStateNotice state={state} onRetry={() => due.refetch()} />
      ) : state === "loading" ? (
        <p className="text-sm text-muted-foreground">Wczytywanie…</p>
      ) : (
        <>
          {state === "empty" ? (
            <p className="text-sm text-muted-foreground">Nic nie czeka na usunięcie.</p>
          ) : (
            <div className="space-y-2">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] table-fixed text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className={cn(CALM_HEAD, "w-8 py-2")}>
                        <span className="sr-only">Zaznacz</span>
                      </th>
                      <th className={cn(CALM_HEAD, "py-2 pr-3 text-left")}>Dokument</th>
                      <th className={cn(CALM_HEAD, "w-[24%] py-2 pr-3 text-left")}>Osoba</th>
                      <th className={cn(CALM_HEAD, "w-[18%] py-2 pr-3 text-left")}>Odeszła</th>
                      <th className={cn(CALM_HEAD, "w-[18%] py-2 text-left")}>Można usunąć od</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr key={item.id} className={CALM_ROW}>
                        <td className="py-2 align-top">
                          <Checkbox
                            aria-label={`Zaznacz: ${item.title}`}
                            checked={picked.has(item.id)}
                            onCheckedChange={(value) => toggle(item.id, value === true)}
                          />
                        </td>
                        <td className="py-2 pr-3 align-top">
                          <span className="block truncate font-medium text-foreground">{item.title}</span>
                          <span className={CALM_SUBLINE}>{DOCUMENT_KIND_LABELS[item.kind]}</span>
                        </td>
                        <td className="py-2 pr-3 align-top">
                          <Link href={`/people/${item.user_id}`} className="hover:underline">
                            {item.person_name}
                          </Link>
                        </td>
                        <td className="py-2 pr-3 align-top tabular-nums">
                          {formatIsoDatePl(item.last_day)}
                        </td>
                        <td className="py-2 align-top tabular-nums">
                          {formatIsoDatePl(item.delete_from)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex justify-end">
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={picked.size === 0 || remove.isPending}
                  onClick={() => void deletePicked()}
                >
                  {remove.isPending ? "Usuwanie…" : `Usuń zaznaczone (${picked.size})`}
                </Button>
              </div>
            </div>
          )}
          {due.data ? <RetentionYears entries={due.data.retention} /> : null}
        </>
      )}
      {confirmDialog}
    </Card>
  );
}
