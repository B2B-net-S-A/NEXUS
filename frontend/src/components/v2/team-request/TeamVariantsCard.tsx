"use client";

/**
 * Gotowe składy dla klienta (Z3, decyzja Artura 15.11.2026): automat proponuje
 * trzy składy, Delivery Lead podmienia osoby, poprawia nazwę i „dlaczego”,
 * a klient widzi wyłącznie zatwierdzone. Nic nie idzie do klienta przed
 * „Zatwierdź i pokaż klientowi”.
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { formatPanelDate } from "@/components/v2/client-panel/panel-logic";
import { apiErrorMessage } from "@/lib/api-error";
import {
  jobTeamKeys,
  proposeVariants,
  saveVariants,
  type TeamDetail,
  type TeamVariantInput,
} from "@/lib/api/jobTeams";
import { cn } from "@/lib/utils";

import { formatHourly, formatThousands, hourlyValue } from "./team-logic";

const CARD = "rounded-xl border border-border bg-card";
const NAME_MAX = 60;
const WHY_MAX = 240;

/** Zapisane składy w kształcie do edycji. */
export function draftsFromSaved(team: TeamDetail): TeamVariantInput[] {
  return team.variants.map((v) => ({
    key: v.key,
    name: v.name,
    why: v.why,
    picks: v.picks.map((p) => ({ job_id: p.job_id, candidate_ids: p.candidates.map((c) => c.candidate_id) })),
  }));
}

/** Suma stawek do klienta składu (zł/h) i liczba osób bez stawki. */
export function draftHourly(team: TeamDetail, draft: TeamVariantInput): { total: number; unpriced: number } {
  let total = 0;
  let unpriced = 0;
  for (const pick of draft.picks) {
    const position = team.positions.find((p) => p.job_id === pick.job_id);
    for (const id of pick.candidate_ids) {
      const rate = hourlyValue(position?.candidates.find((c) => c.candidate_id === id)?.client_rate);
      if (rate == null) unpriced += 1;
      else total += rate;
    }
  }
  return { total, unpriced };
}

/** Ten sam skład co wcześniejszy na liście (te same osoby na tych samych stanowiskach)? */
export function duplicateOf(drafts: readonly TeamVariantInput[], index: number): TeamVariantInput | null {
  const signature = (d: TeamVariantInput) =>
    d.picks
      .filter((p) => p.candidate_ids.length > 0)
      .map((p) => `${p.job_id}:${[...p.candidate_ids].sort((a, b) => a - b).join(",")}`)
      .sort()
      .join("|");
  const own = signature(drafts[index]);
  return drafts.slice(0, index).find((d) => signature(d) === own) ?? null;
}

/** Zmiana osoby na miejscu `seat` stanowiska `jobId`; `null` = puste miejsce. */
export function setSeat(
  draft: TeamVariantInput,
  jobId: number,
  seat: number,
  candidateId: number | null,
): TeamVariantInput {
  const existing = draft.picks.find((p) => p.job_id === jobId)?.candidate_ids ?? [];
  const next = [...existing];
  if (candidateId == null) next.splice(seat, 1);
  else next[seat] = candidateId;
  const ids = next.filter((id, index) => id != null && next.indexOf(id) === index);
  const others = draft.picks.filter((p) => p.job_id !== jobId);
  return { ...draft, picks: [...others, { job_id: jobId, candidate_ids: ids }] };
}

function DraftEditor({
  team,
  draft,
  onChange,
}: {
  team: TeamDetail;
  draft: TeamVariantInput;
  onChange: (next: TeamVariantInput) => void;
}) {
  const hours = team.hours_per_month;
  const { total, unpriced } = draftHourly(team, draft);
  return (
    <div className="grid min-w-0 gap-2 rounded-lg border border-border px-3 py-2" data-testid={`draft-${draft.key}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Input
          aria-label="Nazwa składu"
          value={draft.name}
          maxLength={NAME_MAX}
          className="h-8 max-w-[220px] font-semibold"
          onChange={(e) => onChange({ ...draft, name: e.target.value })}
        />
        <span className="text-sm font-semibold tabular-nums">
          {formatThousands(total * hours)} / mies.
          <span className="ml-1 text-xs font-normal text-muted-foreground">{formatHourly(total)}</span>
        </span>
      </div>
      <Input
        aria-label="Dlaczego ten skład (widzi klient)"
        value={draft.why}
        maxLength={WHY_MAX}
        className="h-8 text-xs"
        placeholder="Jedno zdanie dla klienta, np. wszyscy dostępni od zaraz"
        onChange={(e) => onChange({ ...draft, why: e.target.value })}
      />
      <div className="grid gap-1">
        {team.positions
          .filter((p) => !p.closed)
          .flatMap((position) => {
            const chosen = draft.picks.find((p) => p.job_id === position.job_id)?.candidate_ids ?? [];
            return Array.from({ length: Math.max(1, position.headcount) }, (_, seat) => (
              <label
                key={`${position.job_id}-${seat}`}
                className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] items-center gap-2 text-xs"
              >
                <span className="truncate text-muted-foreground">{position.title}</span>
                <select
                  className="h-8 min-w-0 rounded-md border border-input bg-background px-2 text-sm text-foreground"
                  value={chosen[seat] ?? ""}
                  onChange={(e) =>
                    onChange(setSeat(draft, position.job_id, seat, e.target.value ? Number(e.target.value) : null))
                  }
                >
                  <option value="">— nikt —</option>
                  {position.candidates.map((c) => {
                    const rate = hourlyValue(c.client_rate);
                    return (
                      <option key={c.candidate_id} value={c.candidate_id}>
                        {c.name}
                        {rate != null ? ` · ${formatHourly(rate)}` : " · bez stawki"}
                        {c.available_from ? ` · od ${formatPanelDate(c.available_from)}` : ""}
                      </option>
                    );
                  })}
                </select>
              </label>
            ));
          })}
      </div>
      {unpriced > 0 ? (
        <p className="text-xs text-warning-muted-foreground">
          Bez stawki do klienta: {unpriced}. Cena składu ich nie liczy.
        </p>
      ) : null}
    </div>
  );
}

export function TeamVariantsCard({ team }: { team: TeamDetail }) {
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [drafts, setDrafts] = useState<TeamVariantInput[] | null>(null);
  const onSaved = (next: TeamDetail, message: string) => {
    queryClient.setQueryData(jobTeamKeys.detail(team.id), next);
    setDrafts(null);
    showSuccess(message);
  };
  const propose = useMutation({
    mutationFn: () => proposeVariants(team.id),
    onSuccess: ({ variants }) =>
      setDrafts(variants.map(({ key, name, why, picks }) => ({ key, name, why, picks }))),
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się ułożyć propozycji składów.")),
  });
  const save = useMutation({
    mutationFn: (variants: TeamVariantInput[]) => saveVariants(team.id, variants),
    onSuccess: (next, variants) =>
      onSaved(next, variants.length ? "Składy zatwierdzone, klient je widzi" : "Składy wycofane z panelu klienta"),
    onError: (error) => showError(apiErrorMessage(error, "Nie udało się zapisać składów.")),
  });

  const withdraw = async () => {
    const yes = await askConfirm({
      title: "Wycofać gotowe składy?",
      description: "Klient przestanie je widzieć w panelu zespołu. Skład, który sam ułożył, zostaje u niego.",
      confirmLabel: "Wycofaj",
      variant: "destructive",
    });
    if (yes) save.mutate([]);
  };
  const approve = () => {
    const all = drafts ?? [];
    const ready = all.filter(
      (d, index) =>
        d.name.trim() && d.picks.some((p) => p.candidate_ids.length > 0) && duplicateOf(all, index) == null,
    );
    save.mutate(ready.map((d) => ({ ...d, name: d.name.trim(), why: d.why.trim() })));
  };

  return (
    <div className={cn(CARD, "grid min-w-0 gap-2 px-3.5 py-3")} data-testid="team-variants-card">
      {confirmDialog}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-display text-sm font-semibold">Gotowe składy dla klienta</h2>
        {drafts == null ? (
          <Button
            size="sm"
            variant="outline"
            data-tour="jobs.team.variants"
            disabled={propose.isPending}
            onClick={() => propose.mutate()}
          >
            <Sparkles className="h-3.5 w-3.5" />
            {team.variants.length ? "Ułóż od nowa" : "Zaproponuj składy"}
          </Button>
        ) : null}
      </div>

      {drafts != null ? (
        <>
          <p className="text-xs text-muted-foreground">
            Propozycja automatu. Podmień osoby, popraw nazwę i zdanie dla klienta. Klient zobaczy składy dopiero po
            zatwierdzeniu.
          </p>
          {drafts.map((draft, index) => {
            const same = duplicateOf(drafts, index);
            return (
              <div key={draft.key} className="grid gap-1">
                <DraftEditor
                  team={team}
                  draft={draft}
                  onChange={(next) => setDrafts(drafts.map((d, i) => (i === index ? next : d)))}
                />
                {same ? (
                  <p className="text-xs text-warning-muted-foreground">
                    Taki sam jak „{same.name}”: klient go nie zobaczy, chyba że zmienisz osoby.
                  </p>
                ) : null}
              </div>
            );
          })}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={save.isPending} onClick={approve} data-tour="jobs.team.variants-approve">
              Zatwierdź i pokaż klientowi
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setDrafts(null)}>
              Anuluj
            </Button>
          </div>
        </>
      ) : team.variants.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Klient nie widzi gotowych składów. „Zaproponuj składy” ułoży trzy: najszybszy start, najniższa cena i
          najwięcej wymagań w CV.
        </p>
      ) : (
        <>
          {team.variants.map((variant) => {
            const { total } = draftHourly(team, draftsFromSaved({ ...team, variants: [variant] })[0]);
            return (
              <div key={variant.key} className="grid gap-0.5 rounded-lg border border-border px-3 py-2 text-sm">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-semibold">{variant.name}</span>
                  <span className="font-semibold tabular-nums">{formatThousands(total * team.hours_per_month)}</span>
                </div>
                {variant.why ? <p className="text-xs text-muted-foreground">{variant.why}</p> : null}
                <p className="truncate text-xs">
                  {variant.picks.flatMap((p) => p.candidates.map((c) => c.name)).join(", ")}
                </p>
              </div>
            );
          })}
          <p className="text-xs text-muted-foreground">
            Klient widzi te składy
            {team.variants_approved_at ? ` od ${formatPanelDate(team.variants_approved_at)}` : ""}.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => setDrafts(draftsFromSaved(team))}>
              Zmień
            </Button>
            <Button size="sm" variant="ghost" disabled={save.isPending} onClick={() => void withdraw()}>
              Wycofaj
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
