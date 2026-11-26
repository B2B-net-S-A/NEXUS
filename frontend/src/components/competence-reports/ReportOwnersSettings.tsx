"use client";

import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { apiErrorMessage } from "@/lib/api-error";
import { useOwnerPool, useSaveOwnerPool, type PoolMember } from "@/lib/competence-reports/api";
import { formatWhen } from "@/lib/competence-reports/logic";
import { resolveViewState } from "@/lib/view-state";

type Row = Pick<PoolMember, "user_id" | "name" | "active" | "account_active" | "last_assigned_at">;

/**
 * Ustawienia → Zespół i dostęp → „Opiekunowie raportów” (decyzja Artura
 * 25.11.2026): raporty ze strony idą po kolei do osób z tej listy — do tej,
 * która najdawniej dostała raport, przy remisie według kolejności. Wyłączona
 * osoba (urlop) jest pomijana; pusta lista = raport bez opiekuna, przejmuje go
 * każdy z kolejki. Zapis tylko admin (`PUT /api/competence-reports/owners`).
 */
export function ReportOwnersSettings() {
  const query = useOwnerPool(true);
  const save = useSaveOwnerPool();
  const { showSuccess, showError } = useToast();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [adding, setAdding] = useState("");

  useEffect(() => {
    if (query.data && rows === null) setRows(query.data.members);
  }, [query.data, rows]);

  const viewState = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (viewState === "forbidden" || viewState === "not_found" || viewState === "error") {
    return (
      <QueryStateNotice
        state={viewState}
        description={apiErrorMessage(query.error, "Nie udało się wczytać listy opiekunów.")}
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (!query.data || rows === null) {
    return <p className="text-sm text-muted-foreground">Ładowanie…</p>;
  }

  const listed = new Set(rows.map((r) => r.user_id));
  const addable = query.data.eligible.filter((p) => !listed.has(p.id));
  const saved = query.data.members;
  const dirty =
    rows.length !== saved.length ||
    rows.some((r, i) => r.user_id !== saved[i]?.user_id || r.active !== saved[i]?.active);

  const move = (index: number, delta: number) =>
    setRows((prev) => {
      if (!prev) return prev;
      const next = [...prev];
      const [row] = next.splice(index, 1);
      next.splice(index + delta, 0, row);
      return next;
    });

  async function persist() {
    try {
      const pool = await save.mutateAsync(
        (rows ?? []).map((r) => ({ user_id: r.user_id, active: r.active })),
      );
      setRows(pool.members);
      showSuccess("Lista opiekunów zapisana.");
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się zapisać listy opiekunów."));
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-foreground">Opiekunowie raportów</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Raporty kompetencji ze strony idą po kolei do osób z tej listy. Wyłącz osobę na czas urlopu —
          kolejne raporty ją ominą. Pusta lista oznacza raporty bez opiekuna.
        </p>
      </div>

      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-4 py-6 text-sm text-muted-foreground">
          Lista jest pusta — raporty trafiają do kolejki bez opiekuna.
        </p>
      ) : (
        <ol className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-card">
          {rows.map((row, index) => (
            <li key={row.user_id} className="flex items-center gap-3 px-4 py-3">
              <span className="w-6 text-sm tabular-nums text-muted-foreground">{index + 1}.</span>
              <span className="min-w-0 flex-1">
                <span className="block font-medium text-foreground">{row.name}</span>
                <span className="block text-xs text-muted-foreground">
                  {!row.account_active
                    ? "Konto wyłączone — pomijane"
                    : row.last_assigned_at
                      ? `Ostatni raport: ${formatWhen(row.last_assigned_at)}`
                      : "Jeszcze bez raportu"}
                </span>
              </span>
              <label className="flex items-center gap-2 text-sm text-muted-foreground">
                <Switch
                  checked={row.active}
                  onCheckedChange={(checked) =>
                    setRows((prev) =>
                      prev?.map((r) => (r.user_id === row.user_id ? { ...r, active: checked } : r)) ?? prev,
                    )
                  }
                  aria-label={`${row.name} dostaje raporty`}
                />
                {row.active ? "Dostaje" : "Pominięty"}
              </label>
              <Button
                size="icon"
                variant="ghost"
                aria-label={`Wyżej: ${row.name}`}
                disabled={index === 0}
                onClick={() => move(index, -1)}
              >
                <ArrowUp className="h-4 w-4" />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                aria-label={`Niżej: ${row.name}`}
                disabled={index === rows.length - 1}
                onClick={() => move(index, 1)}
              >
                <ArrowDown className="h-4 w-4" />
              </Button>
              <Button
                size="icon"
                variant="quiet"
                aria-label={`Zdejmij z listy: ${row.name}`}
                onClick={() => setRows((prev) => prev?.filter((r) => r.user_id !== row.user_id) ?? prev)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ol>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Select value={adding} onValueChange={setAdding} disabled={addable.length === 0}>
          <SelectTrigger className="h-9 w-64" aria-label="Dodaj osobę">
            <SelectValue placeholder={addable.length === 0 ? "Wszyscy są już na liście" : "Dodaj osobę…"} />
          </SelectTrigger>
          <SelectContent>
            {addable.map((person) => (
              <SelectItem key={person.id} value={String(person.id)}>
                {person.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {adding ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => {
              const person = addable.find((p) => String(p.id) === adding);
              if (person) {
                setRows((prev) => [
                  ...(prev ?? []),
                  {
                    user_id: person.id,
                    name: person.name,
                    active: true,
                    account_active: true,
                    last_assigned_at: null,
                  },
                ]);
              }
              setAdding("");
            }}
          >
            Dodaj
          </Button>
        ) : null}
        <span className="flex-1" />
        <Button size="sm" onClick={() => void persist()} loading={save.isPending} disabled={!dirty}>
          Zapisz listę
        </Button>
      </div>
    </div>
  );
}
