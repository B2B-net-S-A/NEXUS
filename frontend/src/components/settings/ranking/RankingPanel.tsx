"use client";

import { useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import {
  scoringWeightsApi,
  type RankingMeasurement,
  type RankingPanelState,
  type RankingPanelWeights,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { useUrlWriter } from "@/lib/url-selection";

import { HistoryTab } from "./HistoryTab";
import { HowItWorksTab } from "./HowItWorksTab";
import { WeightsTab } from "./WeightsTab";

export const PANEL_KEY = ["scoring-panel"] as const;
const MEASUREMENT_KEY = ["scoring-panel-measurement"] as const;

type Tab = "jak-dziala" | "wagi" | "historia";
const TABS: { value: Tab; label: string }[] = [
  { value: "jak-dziala", label: "Jak to działa" },
  { value: "wagi", label: "Wagi" },
  { value: "historia", label: "Historia zmian" },
];

const isRunning = (m: RankingMeasurement | null | undefined) =>
  m?.status === "queued" || m?.status === "running";

export interface RankingPanelProps {
  /** Zapis w sekcji Insights (bramka sekcji); rola sprawdza serwer (`can_edit`). */
  insightsWrite: boolean;
  isAdmin: boolean;
  /** Harness `/preview` wyłącza odpytywanie — bez sieci przy pomiarze „w toku”. */
  pollMeasurement?: boolean;
}

export function RankingPanel({ insightsWrite, isAdmin, pollMeasurement = true }: RankingPanelProps) {
  const qc = useQueryClient();
  const searchParams = useSearchParams();
  const pathname = usePathname() ?? "/settings/scoring";
  const { replaceUrl } = useUrlWriter();
  const fromUrl = searchParams?.get("zakladka");
  const tab: Tab = TABS.some((t) => t.value === fromUrl) ? (fromUrl as Tab) : "jak-dziala";
  const selectTab = (next: string) => {
    const params = new URLSearchParams(searchParams?.toString() ?? "");
    params.set("zakladka", next);
    replaceUrl(`${pathname}?${params.toString()}`);
  };

  const panel = useQuery({
    queryKey: PANEL_KEY,
    queryFn: () => scoringWeightsApi.panel().then((r) => r.data),
  });
  const state = panel.data;
  const canEdit = Boolean(state?.can_edit) && insightsWrite;

  // Odpytywanie tylko w trakcie pomiaru (co 5 s), potem odświeżenie panelu.
  const running = pollMeasurement && isRunning(state?.measurement);
  const measurement = useQuery({
    queryKey: MEASUREMENT_KEY,
    queryFn: () => scoringWeightsApi.measurement().then((r) => r.data.measurement),
    enabled: running,
    refetchInterval: running ? 5000 : false,
  });
  useEffect(() => {
    const latest = measurement.data;
    if (!latest || !state) return;
    if (!isRunning(latest)) {
      // Koniec pomiaru: raz odśwież panel (wynik, bramka publikacji).
      if (isRunning(state.measurement)) qc.invalidateQueries({ queryKey: PANEL_KEY });
    } else if (latest.progress?.done !== state.measurement?.progress?.done) {
      qc.setQueryData<RankingPanelState>(PANEL_KEY, (old) =>
        old ? { ...old, measurement: latest } : old,
      );
    }
  }, [measurement.data, state, qc]);

  // Suwaki: lokalny szkic; serwerowy szkic albo opublikowane, gdy się zmienią.
  const serverWeights = state ? (state.draft?.weights ?? state.published.weights) : null;
  const serverKey = serverWeights ? JSON.stringify(serverWeights) : "";
  const [local, setLocal] = useState<RankingPanelWeights | null>(null);
  useEffect(() => {
    if (serverWeights) setLocal(serverWeights);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverKey]);

  const [actionError, setActionError] = useState<string | null>(null);
  const onError = (fallback: string) => (error: unknown) =>
    setActionError(apiErrorMessage(error, fallback));
  const store = (next: RankingPanelState) => {
    setActionError(null);
    qc.setQueryData(PANEL_KEY, next);
  };

  const check = useMutation({
    mutationFn: async (draft: RankingPanelWeights) => {
      await scoringWeightsApi.saveDraft(draft);
      await scoringWeightsApi.startMeasurement();
      return (await scoringWeightsApi.panel()).data;
    },
    onSuccess: (next) => {
      store(next);
      selectTab("historia");
    },
    onError: onError("Nie udało się uruchomić pomiaru."),
  });
  const retry = useMutation({
    mutationFn: async () => {
      await scoringWeightsApi.startMeasurement();
      return (await scoringWeightsApi.panel()).data;
    },
    onSuccess: store,
    onError: onError("Nie udało się uruchomić pomiaru."),
  });
  const discard = useMutation({
    mutationFn: async () => {
      await scoringWeightsApi.discardDraft();
      return (await scoringWeightsApi.panel()).data;
    },
    onSuccess: (next) => {
      store(next);
      setLocal(next.published.weights);
    },
    onError: onError("Nie udało się odrzucić szkicu."),
  });
  const publish = useMutation({
    mutationFn: (reason: string | null) => scoringWeightsApi.publish(reason).then((r) => r.data),
    onSuccess: (next) => {
      store(next);
      // „Dop.” na listach liczy się od nowa przy następnym otwarciu.
      qc.invalidateQueries({ queryKey: ["scoring-weights"] });
    },
    onError: onError("Nie udało się opublikować wag."),
  });
  const restore = useMutation({
    mutationFn: (changeId: number) => scoringWeightsApi.restore(changeId).then((r) => r.data),
    onSuccess: (next) => {
      store(next);
      selectTab("wagi");
    },
    onError: onError("Nie udało się przywrócić tych wag."),
  });
  const busy =
    check.isPending || retry.isPending || discard.isPending || publish.isPending || restore.isPending;
  const { askConfirm, confirmDialog } = useConfirmV2();

  return (
    <div className="space-y-5">
      {confirmDialog}
      <TabbedNav tabs={TABS} value={tab} onValueChange={selectTab} ariaLabel="Ranking kandydatów" />
      {panel.isLoading && <p className="text-sm text-muted-foreground">Ładowanie…</p>}
      {panel.isError && (
        <QueryStateNotice
          state="error"
          description={apiErrorMessage(panel.error, "Nie udało się pobrać wag rankingu.")}
          onRetry={() => panel.refetch()}
        />
      )}
      {panel.isSuccess && state && local && (
        <>
          {tab === "jak-dziala" && <HowItWorksTab state={state} />}
          {tab === "wagi" && (
            <WeightsTab
              state={state}
              local={local}
              onChange={setLocal}
              canEdit={canEdit}
              isAdmin={isAdmin}
              busy={busy}
              actionError={actionError}
              onDiscard={() => discard.mutate()}
              onCheck={() => check.mutate(local)}
            />
          )}
          {tab === "historia" && (
            <HistoryTab
              state={state}
              canEdit={canEdit}
              busy={busy}
              actionError={actionError}
              onRetry={() => retry.mutate()}
              onBackToWeights={() => selectTab("wagi")}
              onRestore={(changeId) => restore.mutate(changeId)}
              onPublish={async (reason) => {
                const ok = await askConfirm({
                  title: "Opublikować wagi dla wszystkich rekrutacji?",
                  description:
                    "„Dop.” przeliczy się przy następnym otwarciu listy w każdej rekrutacji, nocne propozycje — od najbliższej nocy. Otwarte przeglądy całej bazy trzeba będzie przeliczyć.",
                  confirmLabel: "Opublikuj",
                });
                if (ok) publish.mutate(reason);
              }}
            />
          )}
        </>
      )}
    </div>
  );
}
