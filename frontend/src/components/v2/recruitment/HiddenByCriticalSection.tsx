"use client";

/**
 * „Ukryci przez »musi mieć«, choć w CV jest coś bliskiego · N” — sekcja pod
 * „Propozycjami z bazy” (28.10.2026, makieta A:
 * https://claude.ai/artifact/TBHtexa3vvyK76HW2vkSMS). Osoby, które ostatni
 * nocny przegląd ukrył brakiem krytycznej, a które mają w CV, profilu albo
 * notatce jej człon („SailPoint” przy „SailPoint IIQ”). Reguła po stronie
 * serwera: `services/hidden_by_critical.py`.
 *
 * Wiersz jest taki sam jak w propozycjach (`PickList`: zaznaczenie,
 * „+ Dodaj”, „Pomiń”, podgląd) — wynik „?”, bo bramka nie dopuściła osoby do
 * oceny. Dodanie idzie tą samą drogą co propozycje (`proposals/bulk`,
 * źródło `proposal_inbox`). Przycisk „„SailPoint” = SailPoint IIQ” dopisuje
 * wariant do wiersza krytycznej zwykłym zapisem Championa
 * (`lib/critical-variant.ts`); nocny przegląd liczy go od następnej nocy.
 * Przy więcej niż `COLLAPSED_ROWS` osobach sekcja startuje zwinięta.
 */

import { useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { api, type ChampionProfileResponse } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { invalidateChampionDependents } from "@/lib/champion-cache";
import { rowsWithVariant } from "@/lib/critical-variant";
import {
  jobProposalsApi,
  jobProposalsKeys,
  type HiddenByCriticalItem,
  type HiddenByCriticalResponse,
  type HiddenByCriticalVariant,
} from "@/lib/job-proposals-api";
import { cn } from "@/lib/utils";

import { PickList, type PickListProps, type PickRow } from "./pick-list";

/** Tyle osób widać, zanim ktoś kliknie „Pokaż wszystkich N”. */
export const COLLAPSED_ROWS = 3;

const SOURCE_LABEL: Record<string, string> = {
  cv: "w CV",
  profile: "w profilu",
  note: "w notatce",
};

/** Nazwa krytycznej do pokazania: wiersz Championa (pisownia DL-a), inaczej etykieta bramki. */
export function criticalName(item: { critical: string; row: string | null }): string {
  return item.row ?? item.critical;
}

/** Plakietka „≈ SailPoint IIQ · w CV: „…Sailpoint IdentityIQ…”” pod nazwiskiem. */
export function HiddenTraceBadge({ item }: { item: HiddenByCriticalItem }) {
  const where = SOURCE_LABEL[item.source] ?? "w CV";
  return (
    <p className="mt-1" data-testid="hidden-trace">
      <span
        className="inline-block max-w-full truncate rounded bg-warning-muted px-1.5 py-px align-top text-[10.5px] font-semibold text-warning-muted-foreground"
        title={`Bramka szukała „${criticalName(item)}” — ${where} jest „${item.word}”: ${item.snippet}`}
      >
        ≈ {criticalName(item)} · {where}: „{item.snippet}”
      </span>
    </p>
  );
}

export function useHiddenByCritical(jobId: number, enabled: boolean) {
  return useQuery<HiddenByCriticalResponse>({
    queryKey: jobProposalsKeys.hiddenByCritical(jobId),
    queryFn: ({ signal }) => jobProposalsApi.hiddenByCritical(jobId, signal),
    enabled,
    staleTime: 60_000,
    retry: false,
  });
}

function variantKey(v: Pick<HiddenByCriticalVariant, "critical" | "word">): string {
  return `${v.critical}\u0000${v.word}`;
}

/**
 * „„X” = krytyczna”: wczytuje profil (bez oznaczania powiadomień jako
 * przeczytanych), dopisuje słowo do wiersza i zapisuje cały `stack` z odciskiem
 * — ten sam zapis co edytor wymagań; zmiana w międzyczasie = 409 z komunikatem.
 */
function useAddCriticalVariant(jobId: number) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  return useMutation({
    mutationFn: async (variant: HiddenByCriticalVariant) => {
      const { data } = await api.get<ChampionProfileResponse>(
        `/api/jobs/${jobId}/champion-profile`,
        { params: { mark_read: false } },
      );
      const stack = "stack" in data.champion_profile ? data.champion_profile.stack : null;
      const result = rowsWithVariant(stack?.rows ?? null, criticalName(variant), variant.word);
      if (!result.ok) throw new Error(result.reason);
      await api.put(`/api/jobs/${jobId}/champion-profile`, {
        stack: { ...stack, rows: result.rows },
        ...(data.profile_hash ? { expected_profile_hash: data.profile_hash } : {}),
      });
    },
    onSuccess: (_data, variant) => {
      invalidateChampionDependents(queryClient, jobId);
      void queryClient.invalidateQueries({ queryKey: jobProposalsKeys.hiddenByCritical(jobId) });
      showSuccess(
        `„${variant.word}” liczy się teraz jako ${criticalName(variant)}. Nocny przegląd uwzględni to od następnej nocy.`,
      );
    },
    onError: (error) =>
      showError(
        error instanceof Error && !("response" in error)
          ? error.message
          : apiErrorMessage(error, "Nie udało się dopisać wariantu do Profilu Championa."),
      ),
  });
}

export interface HiddenByCriticalSectionProps
  extends Pick<
    PickListProps,
    | "selected"
    | "onToggle"
    | "onPreview"
    | "onClosePreview"
    | "activeId"
    | "onDismiss"
    | "onAdd"
    | "onUndo"
  > {
  jobId: number;
  query: ReturnType<typeof useHiddenByCritical>;
  /** Wiersze w kolejności serwera, z dodanymi w tym oknie (`withKeptRows`). */
  rows: PickRow[];
  readOnly: boolean;
}

function searchedLine(data: HiddenByCriticalResponse): ReactNode {
  const criticals = data.searched.map((s) => `„${criticalName(s)}”`).join(", ");
  const words = [...new Set(data.variants.map((v) => `„${v.word}”`))].join(", ");
  return (
    <>
      Bramka szukała {criticals}. Te osoby mają w CV {words || "coś bliskiego"} — sprawdź sam albo powiedz
      NEXUSOWI, że to to samo.
    </>
  );
}

export function HiddenByCriticalSection({
  jobId,
  query,
  rows,
  readOnly,
  ...listProps
}: HiddenByCriticalSectionProps) {
  const [expanded, setExpanded] = useState(false);
  const addVariant = useAddCriticalVariant(jobId);
  const { askConfirm, confirmDialog } = useConfirmV2();

  if (query.isPending) {
    return (
      <p role="status" className="text-xs text-muted-foreground">
        Sprawdzam, kogo ukryło „musi mieć”…
      </p>
    );
  }
  if (query.isError) {
    return (
      <p role="alert" className="text-xs text-destructive" data-testid="hidden-by-critical-error">
        {apiErrorMessage(query.error, "Nie sprawdziliśmy, kogo ukryło „musi mieć”.")}{" "}
        <button type="button" className="font-medium underline" onClick={() => void query.refetch()}>
          Ponów
        </button>
      </p>
    );
  }
  const data = query.data;
  if (!data || rows.length === 0) return null;

  const visible = expanded || rows.length <= COLLAPSED_ROWS ? rows : rows.slice(0, COLLAPSED_ROWS);
  const variants = data.can_add_variant && !readOnly ? data.variants.filter((v) => v.row) : [];
  const confirmVariant = async (variant: HiddenByCriticalVariant) => {
    const ok = await askConfirm({
      title: `„${variant.word}” = ${criticalName(variant)}?`,
      description: `Dopiszemy „${variant.word}” do wiersza „${criticalName(variant)}” w Profilu Championa, jak „+ lub”. Od następnej nocy przegląd bazy uzna to słowo za tę umiejętność krytyczną — dotyczy ${variant.people} os. z tej listy.`,
      confirmLabel: "Dopisz wariant",
    });
    if (ok) addVariant.mutate(variant);
  };

  return (
    <section
      aria-labelledby="hidden-by-critical-title"
      className="space-y-2 rounded-md border border-warning/40"
      data-testid="hidden-by-critical"
    >
      <div className="flex flex-wrap items-start justify-between gap-2 rounded-t-md bg-warning-muted/60 px-3 py-2">
        <div className="min-w-0 flex-1 space-y-0.5">
          <h3 id="hidden-by-critical-title" className="text-sm font-semibold text-warning-muted-foreground">
            Ukryci przez „musi mieć”, choć w CV jest coś bliskiego · {data.total}
          </h3>
          <p className="text-xs text-warning-muted-foreground">{searchedLine(data)}</p>
          {data.truncated ? (
            <p className="text-xs text-muted-foreground">
              Pokazujemy pierwszych {data.total} — może ich być więcej.
            </p>
          ) : null}
        </div>
        {variants.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {variants.map((variant) => {
              const busy = addVariant.isPending && addVariant.variables && variantKey(addVariant.variables) === variantKey(variant);
              return variant.in_row ? (
                <span
                  key={variantKey(variant)}
                  className="inline-flex h-7 items-center gap-1 rounded-md bg-card px-2 text-xs font-medium text-success-muted-foreground"
                  data-testid="hidden-variant-done"
                  title="Wariant jest już w Profilu Championa — przegląd bazy uwzględni go od następnej nocy."
                >
                  <Check className="h-3.5 w-3.5" aria-hidden="true" />„{variant.word}” = {criticalName(variant)} · od następnej nocy
                </span>
              ) : (
                <Button
                  key={variantKey(variant)}
                  size="sm"
                  variant="outline"
                  className={cn("h-7 bg-card px-2 text-xs")}
                  loading={Boolean(busy)}
                  disabled={addVariant.isPending}
                  onClick={() => void confirmVariant(variant)}
                  title={`Uznaj „${variant.word}” za ${criticalName(variant)} — ${variant.people} os. z tej listy`}
                  data-testid="hidden-variant-add"
                >
                  „{variant.word}” = {criticalName(variant)}
                </Button>
              );
            })}
          </div>
        ) : null}
      </div>
      <div className="px-2 pb-2">
        <PickList
          label="Ukryci przez „musi mieć”"
          rows={visible}
          readOnly={readOnly}
          emptyText=""
          renderScore={() => (
            <span
              className="shrink-0 cursor-help text-xs font-bold text-muted-foreground"
              title="Bramka „musi mieć” ukryła tę osobę przed oceną — procentu nie liczyliśmy"
            >
              ?
            </span>
          )}
          {...listProps}
        />
        {visible.length < rows.length ? (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="mt-2 text-xs font-semibold text-primary hover:underline"
            data-testid="hidden-show-all"
          >
            Pokaż wszystkich {rows.length}
          </button>
        ) : null}
      </div>
      {confirmDialog}
    </section>
  );
}
