"use client";

/**
 * Kafel „Otwarte podobne” w pasku „Kandydaci do dodania” (0614, propozycja
 * Olafa „Podobne requesty P1”, decyzje Artura z 28.10.2026).
 *
 * Tylko otwarte rekrutacje, P1 na górze (Olaf napisał „P1” — przyjęte jako
 * „otwarte, P1 na górze”, nie potwierdzone z nim). Zamknięte zostają
 * w „Podobnych rekrutacjach”, gdzie służą do przepięć. Przy rekrutacji, którą
 * patrzący może połączyć, stoi „⇄ Bliźniak” (okno porównania); przy bliźniaku —
 * „Rozłącz”. Rekruter widzi listę bez przycisków.
 */

import { useState } from "react";
import { ArrowLeftRight } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  budgetLabel,
  type OpenSimilarItem,
  type TwinRuleCheck,
  twinRef,
  useOpenSimilarJobs,
  useUnlinkTwin,
  workModeLabel,
} from "@/lib/job-twins-api";

import { TwinLinkDialog } from "./TwinLinkDialog";

export interface OpenSimilarListProps {
  items: readonly OpenSimilarItem[];
  onTwin: (item: OpenSimilarItem) => void;
  onUnlink: (item: OpenSimilarItem) => void;
}

/** Zasady bliźniaków przy pozycji: ✕ niespełnione wymagane, ⚠ ostrzeżenia. */
export function RuleChips({
  failures = [],
  warnings = [],
}: {
  failures?: readonly TwinRuleCheck[];
  warnings?: readonly TwinRuleCheck[];
}) {
  if (failures.length === 0 && warnings.length === 0) return null;
  return (
    <span className="mt-1 flex flex-wrap gap-1" data-testid="twin-rule-chips">
      {failures.map((c) => (
        <span key={`f-${c.key}`} title={c.detail} className="rounded bg-destructive/10 px-1.5 text-[11px] font-semibold text-destructive">
          ✕ {c.label.toLowerCase()}
        </span>
      ))}
      {warnings.map((c) => (
        <span key={`w-${c.key}`} title={c.detail} className="rounded bg-warning-muted px-1.5 text-[11px] font-semibold text-warning-muted-foreground">
          ⚠ {c.label.toLowerCase()}
        </span>
      ))}
    </span>
  );
}

/** Sam wygląd listy — test i harness bez zapytań. */
export function OpenSimilarList({ items, onTwin, onUnlink }: OpenSimilarListProps) {
  if (items.length === 0) {
    return <p className="px-3 py-2 text-sm text-muted-foreground">Brak otwartych podobnych rekrutacji.</p>;
  }
  return (
    <ul className="divide-y divide-border" data-testid="open-similar-list">
      {items.map((item) => (
        <li key={item.id} className="flex items-center gap-2 px-3 py-2" data-testid={`open-similar-${item.id}`}>
          <div className="min-w-0 flex-1">
            <p className="flex min-w-0 items-center gap-1.5 text-sm font-medium">
              {item.p1 ? (
                <span className="shrink-0 rounded bg-destructive/10 px-1.5 text-[11px] font-bold text-destructive">
                  P1
                </span>
              ) : null}
              <span className="shrink-0 font-mono text-xs">{twinRef(item)}</span>
              <a href={`/jobs/${item.id}`} className="truncate hover:underline">
                {item.title}
              </a>
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {item.client_name ?? "—"}
              {item.delivery_lead_name ? ` · DL ${item.delivery_lead_name}` : ""} · {workModeLabel(item)} ·{" "}
              {budgetLabel(item)}
            </p>
            <RuleChips failures={item.rule_failures} warnings={item.rule_warnings} />
          </div>
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">≈ {item.similarity}%</span>
          {item.twin ? (
            <button
              type="button"
              onClick={() => onUnlink(item)}
              className="shrink-0 rounded-md border border-primary/30 bg-primary/10 px-2 py-0.5 text-xs font-semibold text-primary hover:bg-primary/15"
            >
              ⇄ Bliźniak · Rozłącz
            </button>
          ) : item.can_twin ? (
            <button
              type="button"
              onClick={() => onTwin(item)}
              className="inline-flex shrink-0 items-center gap-1 rounded-md border border-primary/30 px-2 py-0.5 text-xs font-semibold text-primary hover:bg-primary/10"
            >
              <ArrowLeftRight className="h-3 w-3" aria-hidden="true" />
              Bliźniak
            </button>
          ) : item.twin_limit_reached ? (
            <span className="shrink-0 text-xs text-muted-foreground" title="Jedna rozmowa mieści 4 rekrutacje">
              limit bliźniaków
            </span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export function OpenSimilarTile({ jobId, enabled }: { jobId: number; enabled: boolean }) {
  const query = useOpenSimilarJobs(jobId, enabled);
  const [open, setOpen] = useState(false);
  const [linkTo, setLinkTo] = useState<number | null>(null);
  if (!enabled) return null;
  const items = query.data?.items ?? [];
  const count = query.isSuccess ? items.length : null;

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            data-testid="source-tile-open-similar"
            title="Otwarte rekrutacje podobne do tej — P1 na górze. Tu łączysz bliźniaka."
            className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-primary/25 bg-card px-2.5 text-[13px] font-semibold text-foreground transition-colors hover:border-primary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring pointer-coarse:min-h-9"
          >
            Otwarte podobne
            <span className="font-bold tabular-nums">
              {count == null ? <span className="text-muted-foreground">{query.isError ? "—" : "…"}</span> : count}
            </span>
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-[min(560px,calc(100vw-32px))] p-0">
          <div className="border-b border-border px-3 py-2">
            <p className="text-sm font-semibold">Otwarte podobne</p>
            <p className="text-xs text-muted-foreground">Tylko otwarte, P1 na górze. Zamknięte są w „Podobnych rekrutacjach”.</p>
          </div>
          {query.isError ? (
            <p className="px-3 py-2 text-sm text-destructive">Nie udało się pobrać podobnych rekrutacji.</p>
          ) : query.isLoading ? (
            <p className="px-3 py-2 text-sm text-muted-foreground">Szukam…</p>
          ) : (
            <OpenSimilarBody
              jobId={jobId}
              items={items}
              onTwin={(item) => {
                setOpen(false);
                setLinkTo(item.id);
              }}
            />
          )}
        </PopoverContent>
      </Popover>
      {linkTo != null ? (
        <TwinLinkDialog
          jobId={jobId}
          open
          onOpenChange={(next) => {
            if (!next) setLinkTo(null);
          }}
          otherJobId={linkTo}
        />
      ) : null}
    </>
  );
}

/** Treść okienka — komunikaty i potwierdzenie dopiero po otwarciu. */
function OpenSimilarBody({
  jobId,
  items,
  onTwin,
}: {
  jobId: number;
  items: readonly OpenSimilarItem[];
  onTwin: (item: OpenSimilarItem) => void;
}) {
  const { showError, showSuccess } = useToast();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const unlink = useUnlinkTwin(jobId);
  const onUnlink = async (item: OpenSimilarItem) => {
    const ok = await askConfirm({
      title: `Rozłączyć bliźniaka ${twinRef(item)}?`,
      description:
        "Screening przestanie być obowiązkowy pod obie rekrutacje. Nikt nie zniknie z żadnej Tablicy, a rekrutacje zostaną podobne.",
      confirmLabel: "Rozłącz",
    });
    if (!ok) return;
    try {
      await unlink.mutateAsync(item.id);
      showSuccess(`Rozłączono z ${twinRef(item)}.`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się rozłączyć rekrutacji."));
    }
  };
  return (
    <>
      <OpenSimilarList items={items} onTwin={onTwin} onUnlink={(item) => void onUnlink(item)} />
      {confirmDialog}
    </>
  );
}
