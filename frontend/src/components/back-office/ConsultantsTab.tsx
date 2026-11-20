"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Plus, Search } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  useBoBoard,
  useBoConsultant,
  useBoConsultants,
  type BoBoard,
  type BoConsultantRow,
} from "@/lib/api/back-office";
import { CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { formatDay } from "./board-model";
import { DueChip } from "./CardTile";
import { NewCaseDialog } from "./NewCaseDialog";

type Quick = "all" | "with_case" | "ending" | "silent";
const QUICK_LABELS: Record<Quick, string> = {
  all: "Wszyscy",
  with_case: "Z otwartą sprawą",
  ending: "Kończą w 60 dni",
  silent: "Bez rozmowy > 90 dni",
};
const TYPE: Record<string, string> = { b2b: "B2B", uop: "UoP", uzlecenie: "UZ" };

function daysBetween(from: string, to: string): number {
  return Math.round((new Date(`${to.slice(0, 10)}T00:00:00`).getTime() - new Date(`${from.slice(0, 10)}T00:00:00`).getTime()) / 86_400_000);
}

export function daysToEnd(row: Pick<BoConsultantRow, "end_date">, today: string): number | null {
  return row.end_date ? daysBetween(today, row.end_date) : null;
}

export function silentFor(row: Pick<BoConsultantRow, "last_conversation">, today: string): number | null {
  return row.last_conversation ? daysBetween(row.last_conversation.on, today) : null;
}

export function matchesQuick(row: BoConsultantRow, quick: Quick, today: string): boolean {
  switch (quick) {
    case "with_case":
      return row.open_cases.length > 0;
    case "ending": {
      const left = daysToEnd(row, today);
      return left != null && left >= 0 && left <= 60;
    }
    case "silent": {
      const silent = silentFor(row, today);
      return silent == null || silent > 90;
    }
    default:
      return true;
  }
}

function labelOf(board: BoBoard | undefined, lane: string, fallback: string): string {
  return board?.labels.find((label) => label.id === lane)?.label ?? fallback;
}

/**
 * Konsultanci (wariant A, 19.11.2026): jedna lista bez „Moi / Mój zakres”
 * i bez opiekuna — każdy z zespołu widzi wszystkich.
 */
export function ConsultantsTab() {
  const query = useBoConsultants();
  const board = useBoBoard();
  const [quick, setQuick] = useState<Quick>("all");
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const today = board.data?.today ?? new Date().toISOString().slice(0, 10);
  const rows = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase("pl");
    return (query.data?.items ?? [])
      .filter((row) => matchesQuick(row, quick, today))
      .filter(
        (row) =>
          !needle ||
          [row.name, row.client_name, row.job_title].some((value) => (value ?? "").toLocaleLowerCase("pl").includes(needle)),
      )
      .sort((a, b) => b.open_cases.length - a.open_cases.length || a.name.localeCompare(b.name, "pl"));
  }, [query.data, quick, search, today]);

  const state = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
  });
  if (!query.isSuccess) {
    if (state === "forbidden" || state === "not_found" || state === "error") {
      return <QueryStateNotice state={state} onRetry={() => query.refetch()} />;
    }
    return <p className="p-4 text-sm text-muted-foreground">Ładowanie konsultantów…</p>;
  }
  const items = query.data.items;
  const count = (id: Quick) => items.filter((row) => matchesQuick(row, id, today)).length;

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filtr konsultantów">
          {(Object.keys(QUICK_LABELS) as Quick[]).map((id) => (
            <button
              key={id}
              type="button"
              aria-pressed={quick === id}
              onClick={() => setQuick(id)}
              className={cn(
                "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-xs",
                quick === id ? "border-primary bg-primary/10 font-medium text-primary" : "border-border bg-card text-muted-foreground",
              )}
            >
              {QUICK_LABELS[id]} <span className="text-[11px] tabular-nums opacity-80">{count(id)}</span>
            </button>
          ))}
        </div>
        <div className="relative">
          <Search aria-hidden className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Szukaj konsultanta"
            className="h-8 w-56 pl-7 text-xs"
            placeholder="Szukaj konsultanta lub klienta…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
      </div>
      {rows.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border bg-card p-3 text-sm text-muted-foreground">
          Nikt nie pasuje do tego filtra.
        </p>
      ) : (
        <div className="max-h-[calc(100dvh-280px)] overflow-y-auto rounded-xl border border-border bg-card">
          <table className="w-full text-sm" aria-label="Konsultanci">
            <thead className="sticky top-0 z-[1] bg-card">
              <tr className={CALM_ROW}>
                {["Konsultant", "Klient", "Koniec współpracy", "Otwarte sprawy", "Ostatnia rozmowa"].map((head) => (
                  <th key={head} className={cn(CALM_HEAD, "px-3 py-2 text-left")}>
                    {head}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 300).map((row) => {
                const left = daysToEnd(row, today);
                const silent = silentFor(row, today);
                return (
                  <tr
                    key={row.contract_id}
                    className={cn(CALM_ROW, "cursor-pointer hover:bg-muted/40")}
                    onClick={() => setOpenId(row.contract_id)}
                  >
                    <td className="px-3 py-1.5">
                      <span className="block text-[13px] font-medium">{row.name}</span>
                      <span className={CALM_SUBLINE}>
                        {TYPE[row.contract_type ?? ""] ?? "—"} · od {row.start_date ? row.start_date.slice(0, 4) : "—"}
                      </span>
                    </td>
                    <td className="px-3 py-1.5 text-[13px]">
                      {row.client_name}
                      {row.job_title ? <span className={CALM_SUBLINE}>{row.job_title}</span> : null}
                    </td>
                    <td className="px-3 py-1.5 text-[13px] tabular-nums">
                      {row.end_date ? formatDay(row.end_date) : <span className={CALM_EMPTY}>—</span>}
                      {row.end_source ? (
                        <span className={CALM_SUBLINE}>
                          {row.end_source === "order" ? "zamówienie" : "umowa"}
                          {left != null && left >= 0 && left <= 60 ? ` · za ${left} dni` : ""}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-1.5">
                      {row.open_cases.length ? (
                        <span className="flex flex-wrap gap-1">
                          {row.open_cases.slice(0, 2).map((item) => (
                            <span
                              key={item.id}
                              className="inline-flex h-5 items-center rounded-full border border-border px-2 text-[11px]"
                            >
                              {labelOf(board.data, item.lane, item.label)}
                            </span>
                          ))}
                          {row.open_cases.length > 2 ? (
                            <span className="text-[11px] text-muted-foreground">+{row.open_cases.length - 2}</span>
                          ) : null}
                        </span>
                      ) : (
                        <span className={CALM_EMPTY}>—</span>
                      )}
                    </td>
                    <td className={cn("px-3 py-1.5 text-[12px]", (silent == null || silent > 90) && "text-warning-muted-foreground")}>
                      {row.last_conversation
                        ? `${formatDay(row.last_conversation.on)} · ${silent} dni temu`
                        : "bez rozmów"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length > 300 ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">Pokazuję 300 z {rows.length} — zawęź szukaniem.</p>
          ) : null}
        </div>
      )}
      <ConsultantPanel contractId={openId} onClose={() => setOpenId(null)} />
    </div>
  );
}

/** Karta konsultanta (wariant A): trzy fakty, sprawy na górze, rozmowy, umowa — bez opiekuna. */
export function ConsultantPanel({ contractId, onClose }: { contractId: number | null; onClose: () => void }) {
  const query = useBoConsultant(contractId);
  const board = useBoBoard();
  const [creating, setCreating] = useState(false);
  const card = query.data;
  const today = board.data?.today ?? new Date().toISOString().slice(0, 10);
  if (contractId == null) return null;
  const silent = card?.last_conversation ? daysBetween(card.last_conversation.on, today) : null;
  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-[560px] max-w-full" aria-label="Konsultant">
        <SheetHeader>
          <SheetTitle className="pr-8">{card?.name ?? "Konsultant"}</SheetTitle>
          <SheetDescription asChild>
            <div className="truncate text-sm">
              {card
                ? [card.client_name, card.job_title, `${TYPE[card.contract_type ?? ""] ?? "—"} od ${formatDay(card.start_date)}.${card.start_date?.slice(0, 4) ?? ""}`]
                    .filter(Boolean)
                    .join(" · ")
                : ""}
            </div>
          </SheetDescription>
        </SheetHeader>
        <SheetBody className="space-y-4">
          {query.isError ? (
            <QueryStateNotice state="error" description="Nie udało się wczytać karty konsultanta." onRetry={() => query.refetch()} />
          ) : null}
          {card ? (
            <>
              <div className="grid grid-cols-3 gap-2">
                {[
                  {
                    label: "Ostatnia rozmowa",
                    value: card.last_conversation ? `${formatDay(card.last_conversation.on)} · ${silent} dni temu` : "bez rozmów",
                    warn: silent == null || silent > 90,
                  },
                  {
                    label: card.end_source === "order" ? "Koniec zamówienia" : "Koniec umowy",
                    value: card.end_date ? `${formatDay(card.end_date)} · za ${card.days_to_end} dni` : "bez daty",
                    warn: card.days_to_end != null && card.days_to_end <= 60,
                  },
                  { label: "Otwarte sprawy", value: String(card.open_count), warn: false },
                ].map((fact) => (
                  <div key={fact.label} className="rounded-lg border border-border px-2.5 py-1.5">
                    <p className="text-[10.5px] uppercase tracking-wide text-muted-foreground">{fact.label}</p>
                    <p className={cn("text-[13px] font-medium", fact.warn && "text-warning-muted-foreground")}>{fact.value}</p>
                  </div>
                ))}
              </div>
              <section>
                <div className="mb-1.5 flex items-center justify-between">
                  <h4 className="text-sm font-semibold">Sprawy</h4>
                  {board.data?.me.cases_handler ? (
                    <Button size="sm" className="h-7 gap-1 px-2.5 text-xs" onClick={() => setCreating(true)}>
                      <Plus aria-hidden className="size-3" /> Nowa sprawa
                    </Button>
                  ) : null}
                </div>
                {card.cases.length === 0 ? (
                  <p className="rounded-lg border border-dashed border-border px-3 py-2 text-sm text-muted-foreground">
                    Brak spraw w ostatnich 120 dniach.
                  </p>
                ) : (
                  <ul className="divide-y rounded-lg border border-border">
                    {card.cases.map((item) => (
                      <li key={item.id} className={cn("flex items-center gap-2 px-3 py-1.5 text-sm", item.state === "done" && "opacity-60")}>
                        <span className="inline-flex h-5 shrink-0 items-center rounded-full border border-border px-2 text-[11px]">
                          {labelOf(board.data, item.lane, item.label)}
                        </span>
                        <Link href={`/back-office?karta=${item.id}`} className="min-w-0 flex-1 truncate hover:underline">
                          {item.title}
                        </Link>
                        {item.state === "done" ? (
                          <span className="shrink-0 text-xs text-muted-foreground">zamknięta</span>
                        ) : (
                          <DueChip due={item.due_on} today={today} />
                        )}
                        <span className="w-[110px] shrink-0 truncate text-right text-xs text-muted-foreground">
                          {item.assignee?.name ?? (item.state === "done" ? "" : "do wzięcia")}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section>
                <h4 className="mb-1.5 text-sm font-semibold">Rozmowy</h4>
                {card.conversations.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    Brak zapisanych rozmów. Rozmowa z konsultantem to sprawa z etykietą „Pomoc” — bierze ją pierwsza wolna osoba.
                  </p>
                ) : (
                  <ul className="space-y-2">
                    {card.conversations.map((talk, index) => (
                      <li key={`${talk.on}-${index}`} className="rounded-lg border border-border px-3 py-2 text-sm">
                        <p className="text-xs text-muted-foreground">
                          {formatDay(talk.on)}.{talk.on.slice(0, 4)}
                          {talk.by ? ` · ${talk.by}` : ""}
                          {talk.satisfaction != null ? ` · ocena ${talk.satisfaction}/5` : ""}
                        </p>
                        {talk.note ? <p className="line-clamp-3">{talk.note}</p> : null}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
              <section>
                <h4 className="mb-1.5 text-sm font-semibold">Umowa i zamówienia</h4>
                <Link
                  href={`/contracts/${card.contract_id}`}
                  className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
                >
                  Kontrakt, zamówienia i dokumenty <ArrowUpRight aria-hidden className="size-3.5" />
                </Link>
              </section>
            </>
          ) : query.isLoading ? (
            <p className="text-sm text-muted-foreground">Ładowanie…</p>
          ) : null}
        </SheetBody>
      </SheetContent>
      {creating && card && board.data ? (
        <NewCaseDialog
          board={board.data}
          onClose={() => setCreating(false)}
          contract={{
            id: card.contract_id,
            candidate_name: card.name,
            client_name: card.client_name,
            start_date: card.start_date,
            end_date: card.end_date,
          }}
        />
      ) : null}
    </Sheet>
  );
}
