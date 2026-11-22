"use client";

/**
 * „Na Pracuj.pl bez rekrutacji w NEXUSIE” (23.11.2026) — ogłoszenia ze strefy
 * Pracuj.pl, których aplikacje nie trafiają do żadnej rekrutacji. Delivery Lead
 * przypisuje je do rekrutacji z podpowiedzi albo oznacza jako rekrutację
 * wewnętrzną. Tytuł tylko podpowiada: ten sam tytuł miewa kilka ogłoszeń
 * i kilka rekrutacji. `GET /api/job-ads/pracuj-unpaired`.
 */

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/Toast";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import { jobAdApi, missingAdsQueryKey, pracujUnpairedQueryKey } from "@/lib/api/jobAd";
import { formatDate } from "@/lib/utils";

import { applicationsText, pairedMessage } from "./PracujAdPairing";

export type PracujUnpairedApi = Pick<
  typeof jobAdApi,
  "pracujUnpaired" | "pairPracujAd" | "markPracujInternal"
>;

export function PracujUnpairedAds({ api = jobAdApi }: { api?: PracujUnpairedApi }) {
  const queryClient = useQueryClient();
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const query = useQuery({ queryKey: pracujUnpairedQueryKey, queryFn: () => api.pracujUnpaired() });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: pracujUnpairedQueryKey });
    void queryClient.invalidateQueries({ queryKey: missingAdsQueryKey });
  };

  const pair = useMutation({
    mutationFn: (input: { jobId: number; strefaId: string }) =>
      api.pairPracujAd(input.jobId, input.strefaId),
    onSuccess: (result) => {
      showSuccess(pairedMessage(result));
      refresh();
    },
    onError: (err) =>
      showError(apiErrorMessage(err, "Nie udało się przypisać ogłoszenia. Spróbuj ponownie.")),
  });

  const internal = useMutation({
    mutationFn: (strefaId: string) => api.markPracujInternal(strefaId),
    onSuccess: refresh,
    onError: (err) => showError(apiErrorMessage(err, "Nie udało się zapisać. Spróbuj ponownie.")),
  });

  if (query.isError) {
    return (
      <Alert
        variant="error"
        title="Nie udało się wczytać ogłoszeń z Pracuj.pl bez rekrutacji"
        description={apiErrorMessage(query.error, "Spróbuj ponownie za chwilę.")}
      />
    );
  }
  // Pusta albo jeszcze niewczytana lista: sekcja nie ma czego pokazać.
  if (!query.isSuccess || query.data.length === 0) return null;

  const items = query.data;
  const total = items.reduce(
    (sum, item) => sum + Math.max(item.logged_applications, item.applications),
    0,
  );
  const busy = pair.isPending || internal.isPending;

  const confirmInternal = async (strefaId: string, title: string) => {
    const confirmed = await askConfirm({
      title: `„${title}” to rekrutacja wewnętrzna?`,
      description:
        "Ogłoszenie zniknie z tej listy, a aplikacje z niego nie trafią do żadnej rekrutacji w NEXUSIE. Pomyłkę cofniesz, wskazując to ogłoszenie w karcie Pracuj.pl okna „Ogłoszenie” rekrutacji.",
      confirmLabel: "Rekrutacja wewnętrzna",
    });
    if (confirmed) internal.mutate(strefaId);
  };

  return (
    <section
      aria-label="Ogłoszenia na Pracuj.pl bez rekrutacji"
      className="flex flex-col gap-2 rounded-lg border border-warning/40 bg-card px-4 py-3"
      data-testid="pracuj-unpaired"
    >
      <h2 className="text-sm font-semibold text-foreground">
        Na Pracuj.pl bez rekrutacji w NEXUSIE · {items.length} ·{" "}
        {applicationsText(total)}
      </h2>
      <p className="text-xs text-muted-foreground">
        Aplikacje z tych ogłoszeń nie trafiają do żadnej rekrutacji. Przypisz ogłoszenie albo
        otwórz rekrutację i wskaż je w karcie Pracuj.pl okna „Ogłoszenie”.
      </p>
      <ul className="flex flex-col divide-y divide-border">
        {items.map((item) => (
          <li
            key={item.strefa_id}
            className="grid grid-cols-1 gap-2 py-2 text-[13px] md:grid-cols-[minmax(0,1.2fr)_minmax(0,1.5fr)_auto] md:items-center"
          >
            <span className="flex min-w-0 flex-col">
              <span className="text-foreground">{item.title}</span>
              <span className="text-xs text-muted-foreground">
                nr {item.strefa_id} · od {formatDate(item.first_seen_at)} ·{" "}
                {applicationsText(Math.max(item.logged_applications, item.applications))}
              </span>
            </span>
            <span className="flex min-w-0 flex-wrap items-center gap-1.5">
              {item.suggestions.length > 1 ? (
                <span className="w-full text-xs text-warning-muted-foreground">
                  Kilka rekrutacji o tym tytule — wybierz właściwą.
                </span>
              ) : null}
              {item.suggestions.map((s) => (
                <Button
                  key={s.job_id}
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-auto min-h-7 max-w-full whitespace-normal px-2.5 py-1 text-left"
                  disabled={busy}
                  title={s.delivery_lead_name ? `DL: ${s.delivery_lead_name}` : undefined}
                  onClick={() => pair.mutate({ jobId: s.job_id, strefaId: item.strefa_id })}
                >
                  Przypisz do: {s.title}
                  {s.delivery_lead_name ? ` · ${s.delivery_lead_name}` : ""}
                </Button>
              ))}
              {item.more_suggestions ? (
                <span className="text-xs text-muted-foreground">
                  i {item.more_suggestions} innych — wskaż w rekrutacji
                </span>
              ) : null}
              {item.suggestions.length === 0 ? (
                <span className="text-xs text-muted-foreground">
                  Brak rekrutacji o podobnym tytule.{" "}
                  <Link href="/jobs" className="text-primary underline-offset-2 hover:underline">
                    Otwórz rekrutację
                  </Link>{" "}
                  i wskaż ogłoszenie w karcie Pracuj.pl.
                </span>
              ) : null}
            </span>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="h-7 justify-self-start px-2 md:justify-self-end"
              disabled={busy}
              onClick={() => void confirmInternal(item.strefa_id, item.title)}
            >
              Rekrutacja wewnętrzna
            </Button>
          </li>
        ))}
      </ul>
      {confirmDialog}
    </section>
  );
}
