"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { REVIEW_BATCH_QUERY_KEY } from "@/lib/api/reviewBatch";

interface BatchSettings {
  minimum: number;
  batch_size: number;
  min_score: number;
  enabled: boolean;
}

const SETTINGS_KEY = [...REVIEW_BATCH_QUERY_KEY, "settings"] as const;

/**
 * Minimum decyzji z porcji dnia przed ręcznym wyszukiwaniem (decyzja Artura
 * z 07.11.2026, domyślnie 50). Ustawia Head of Recruitment i admin; działa od
 * razu, bez szkicu i pomiaru panelu.
 */
export function ReviewBatchMinimumBlock({ canEdit }: { canEdit: boolean }) {
  const queryClient = useQueryClient();
  // Komunikat w bloku, nie powiadomienie: panel bywa renderowany bez
  // dostawcy powiadomień (harness, testy strony).
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const query = useQuery<BatchSettings>({
    queryKey: SETTINGS_KEY,
    queryFn: async () => (await api.get<BatchSettings>("/api/review-batch/settings")).data,
    retry: false,
  });
  const [draft, setDraft] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: async (minimum: number) =>
      (await api.put("/api/review-batch/settings", { minimum })).data,
    onSuccess: () => {
      setDraft(null);
      void queryClient.invalidateQueries({ queryKey: REVIEW_BATCH_QUERY_KEY });
      setNotice({ ok: true, text: "Zapisano minimum porcji dnia." });
    },
    onError: (error) =>
      setNotice({ ok: false, text: apiErrorMessage(error, "Nie udało się zapisać minimum.") }),
  });

  if (query.isError) {
    return (
      <p className="border-t border-border pt-3.5 text-xs text-destructive" role="alert">
        {apiErrorMessage(query.error, "Nie udało się wczytać ustawień porcji dnia.")}
      </p>
    );
  }
  if (!query.isSuccess) return null;
  const value = draft ?? String(query.data.minimum);
  const parsed = Number(value);
  const valid = Number.isInteger(parsed) && parsed >= 1 && parsed <= 300;
  return (
    <div data-testid="ranking-review-batch" className="flex flex-col gap-2 border-t border-border pt-3.5">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Porcja dnia od Nexusa</h3>
        <p className="text-xs text-muted-foreground">
          Codziennie rano każda rekrutacja z rekruterem dostaje do {query.data.batch_size} osób
          od {query.data.min_score}%, dzielonych po równo w zespole. Rekruter szuka ręcznie
          dopiero po tylu decyzjach (screening albo odrzucenie z powodem).
          {query.data.enabled ? "" : " Porcja jest teraz wyłączona."}
        </p>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <label htmlFor="review-batch-minimum" className="text-sm font-semibold text-foreground">
          Minimum decyzji dziennie
        </label>
        <Input
          id="review-batch-minimum"
          type="number"
          min={1}
          max={300}
          className="w-24"
          value={value}
          disabled={!canEdit || save.isPending}
          onChange={(e) => setDraft(e.target.value)}
        />
        {canEdit && draft !== null && draft !== String(query.data.minimum) ? (
          <Button size="sm" disabled={!valid || save.isPending} onClick={() => save.mutate(parsed)}>
            Zapisz minimum
          </Button>
        ) : null}
      </div>
      {!valid ? <p className="text-xs text-destructive">Podaj liczbę od 1 do 300.</p> : null}
      {notice ? (
        <p
          role={notice.ok ? "status" : "alert"}
          className={notice.ok ? "text-xs text-success" : "text-xs text-destructive"}
        >
          {notice.text}
        </p>
      ) : null}
    </div>
  );
}
