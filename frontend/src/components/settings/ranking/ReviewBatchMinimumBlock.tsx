"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import api from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { REVIEW_BATCH_QUERY_KEY } from "@/lib/api/reviewBatch";

import { ReviewBatchTeamPanel } from "./ReviewBatchTeamPanel";

interface BatchRecruiter {
  id: number;
  name: string;
}

interface BatchSettings {
  minimum: number;
  block_enabled: boolean;
  pilot_user_ids: number[];
  batch_size: number;
  min_score: number;
  max_age_days: number;
  enabled: boolean;
  /** Tylko dla HoR i admina — lista do wyboru pilota. */
  recruiters?: BatchRecruiter[];
}

type SettingsPayload = Pick<BatchSettings, "minimum" | "block_enabled" | "pilot_user_ids" | "min_score">;

const SETTINGS_KEY = [...REVIEW_BATCH_QUERY_KEY, "settings"] as const;

/**
 * Porcja dnia przed ręcznym wyszukiwaniem (decyzje Artura z 07.11 i 08.11.2026):
 * minimum decyzji (domyślnie 10), wyłącznik samej blokady i lista pilotażowa.
 * Ustawia Head of Recruitment i admin; działa od razu, bez wdrożenia.
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
  const [scoreDraft, setScoreDraft] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: async ({ payload }: { payload: SettingsPayload; done: string }) =>
      (await api.put("/api/review-batch/settings", payload)).data,
    onSuccess: (_data, { done }) => {
      setDraft(null);
      setScoreDraft(null);
      void queryClient.invalidateQueries({ queryKey: REVIEW_BATCH_QUERY_KEY });
      setNotice({ ok: true, text: done });
    },
    onError: (error) =>
      setNotice({ ok: false, text: apiErrorMessage(error, "Nie udało się zapisać ustawień porcji.") }),
  });

  if (query.isError) {
    return (
      <p className="border-t border-border pt-3.5 text-xs text-destructive" role="alert">
        {apiErrorMessage(query.error, "Nie udało się wczytać ustawień porcji dnia.")}
      </p>
    );
  }
  if (!query.isSuccess) return null;
  const data = query.data;
  const current: SettingsPayload = {
    minimum: data.minimum,
    block_enabled: data.block_enabled ?? true,
    pilot_user_ids: data.pilot_user_ids ?? [],
    min_score: data.min_score,
  };
  const value = draft ?? String(current.minimum);
  const parsed = Number(value);
  const valid = Number.isInteger(parsed) && parsed >= 1 && parsed <= 300;
  const scoreValue = scoreDraft ?? String(current.min_score);
  const parsedScore = Number(scoreValue);
  const scoreValid = Number.isFinite(parsedScore) && parsedScore >= 50 && parsedScore <= 95;
  const pilot = new Set(current.pilot_user_ids);
  const togglePilot = (id: number, on: boolean) => {
    const next = new Set(pilot);
    if (on) next.add(id);
    else next.delete(id);
    save.mutate({
      payload: { ...current, pilot_user_ids: [...next].sort((a, b) => a - b) },
      done: next.size ? `Blokada dotyczy ${next.size} os. z pilota.` : "Blokada dotyczy wszystkich rekruterów.",
    });
  };
  return (
    <div data-testid="ranking-review-batch" className="flex flex-col gap-2 border-t border-border pt-3.5">
      <div>
        <h3 className="text-sm font-semibold text-foreground">Porcja dnia od Nexusa</h3>
        <p className="text-xs text-muted-foreground">
          Codziennie rano każda rekrutacja z rekruterem dostaje do {data.batch_size} osób
          od {data.min_score}%, dzielonych po równo w zespole. W porcji są tylko karty
          nie starsze niż {data.max_age_days ?? 7} dni. Rekruter szuka ręcznie dopiero po
          tylu decyzjach (screening albo odrzucenie z powodem), w dni robocze od 7:00.
          {data.enabled ? "" : " Porcja jest teraz wyłączona."}
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
        {canEdit && draft !== null && draft !== String(current.minimum) ? (
          <Button
            size="sm"
            disabled={!valid || save.isPending}
            onClick={() =>
              save.mutate({ payload: { ...current, minimum: parsed }, done: "Zapisano minimum porcji dnia." })
            }
          >
            Zapisz minimum
          </Button>
        ) : null}
      </div>
      {!valid ? <p className="text-xs text-destructive">Podaj liczbę od 1 do 300.</p> : null}
      <div className="flex flex-wrap items-end gap-2">
        <label htmlFor="review-batch-min-score" className="text-sm font-semibold text-foreground">
          Próg wyniku porcji (%)
        </label>
        <Input
          id="review-batch-min-score"
          type="number"
          min={50}
          max={95}
          className="w-24"
          value={scoreValue}
          disabled={!canEdit || save.isPending}
          onChange={(e) => setScoreDraft(e.target.value)}
        />
        {canEdit && scoreDraft !== null && scoreDraft !== String(current.min_score) ? (
          <Button
            size="sm"
            disabled={!scoreValid || save.isPending}
            onClick={() =>
              save.mutate({ payload: { ...current, min_score: parsedScore }, done: "Zapisano próg wyniku porcji." })
            }
          >
            Zapisz próg
          </Button>
        ) : null}
      </div>
      {!scoreValid ? <p className="text-xs text-destructive">Podaj liczbę od 50 do 95.</p> : null}
      <div className="flex items-center gap-2">
        <Switch
          id="review-batch-block"
          checked={current.block_enabled}
          disabled={!canEdit || save.isPending}
          onCheckedChange={(on) =>
            save.mutate({
              payload: { ...current, block_enabled: on },
              done: on
                ? "Blokada wyszukiwania włączona."
                : "Blokada wyszukiwania wyłączona — porcja zostaje, wyszukiwanie działa.",
            })
          }
        />
        <label htmlFor="review-batch-block" className="text-sm text-foreground">
          Blokada ręcznego wyszukiwania przed minimum
        </label>
      </div>
      {canEdit && data.recruiters?.length ? (
        <fieldset className="flex flex-col gap-1.5">
          <legend className="text-sm font-semibold text-foreground">Pilot</legend>
          <p className="text-xs text-muted-foreground">
            Zaznaczone osoby mają blokadę. Nikt nie zaznaczony = blokada dla wszystkich rekruterów.
          </p>
          <div className="grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
            {data.recruiters.map((person) => (
              <label key={person.id} className="flex items-center gap-2 text-sm text-foreground">
                <Checkbox
                  checked={pilot.has(person.id)}
                  disabled={save.isPending || !current.block_enabled}
                  onCheckedChange={(on) => togglePilot(person.id, on === true)}
                  aria-label={`Pilot: ${person.name}`}
                />
                <span className="truncate">{person.name}</span>
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}
      {canEdit ? <ReviewBatchTeamPanel /> : null}
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
