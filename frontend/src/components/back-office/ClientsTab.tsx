"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Pencil, Search } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useBoClientSheet,
  useBoClients,
  useSaveClientNote,
  type BoClientSheet,
  type BoSheetBlockId,
} from "@/lib/api/back-office";
import { cn } from "@/lib/utils";
import { resolveViewState } from "@/lib/view-state";

import { formatDay } from "./board-model";

/** Sposób rozliczenia ustawiają Finanse (`client_settlement_rules`); tu tylko podpis. */
const SETTLEMENT_LABELS: Record<string, string> = {
  client_report: "Raport od klienta — konsultant nie wysyła raportu",
  report_with_approval: "Raport i akceptacja klienta od konsultanta",
  own_report: "Raport akceptowany przez B2B.net",
};

const BLOCK_HINTS: Record<BoSheetBlockId, string> = {
  settlement: "Skąd raport godzin i do którego dnia, kiedy i gdzie faktura, kto akceptuje po stronie klienta.",
  onboarding: "Sprzęt nasz czy klienta, kto zamawia dostępy, pakiet klienta i mail powitalny.",
  orders: "Ile dni przed końcem przychodzi przedłużenie, zamówienia MD/okresowe, z jakiej skrzynki.",
  contacts: "Do kogo dzwonić po stronie klienta: zakupy, HR, przełożeni zespołów.",
};

function SheetBlock({ sheet, block }: { sheet: BoClientSheet; block: BoClientSheet["blocks"][number] }) {
  const { showToast } = useToast();
  const save = useSaveClientNote(sheet.client_id);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(block.body);
  useEffect(() => setDraft(block.body), [block.body]);
  const facts: string[] = [];
  if (block.id === "settlement" && sheet.settlement_rule) {
    facts.push(SETTLEMENT_LABELS[sheet.settlement_rule.mode] ?? sheet.settlement_rule.mode);
    if (sheet.settlement_rule.instructions) facts.push(sheet.settlement_rule.instructions);
  }
  if (block.id === "contacts" && sheet.delivery_leads.length) {
    facts.push(`Delivery Lead: ${sheet.delivery_leads.join(", ")}`);
  }
  if (block.id === "orders" && sheet.ending_60.length) {
    facts.push(`Kończy się w 60 dni: ${sheet.ending_60.length} (najbliżej ${formatDay(sheet.ending_60[0].end_date)})`);
  }
  return (
    <section className="flex min-w-0 flex-col gap-1.5 rounded-lg border border-border bg-card p-3">
      <header className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold">{block.label}</h4>
        {!editing ? (
          <Button size="sm" variant="ghost" className="h-7 gap-1 px-2 text-xs" onClick={() => setEditing(true)}>
            <Pencil aria-hidden className="size-3" /> {block.body ? "Popraw" : "Uzupełnij"}
          </Button>
        ) : null}
      </header>
      {facts.length ? (
        <ul className="space-y-0.5 text-[12.5px]">
          {facts.map((fact) => (
            <li key={fact} className="text-foreground">
              • {fact}
            </li>
          ))}
        </ul>
      ) : null}
      {editing ? (
        <div className="space-y-1.5">
          <Textarea
            aria-label={block.label}
            rows={5}
            maxLength={4000}
            value={draft}
            placeholder={BLOCK_HINTS[block.id]}
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className="flex justify-end gap-1.5">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setDraft(block.body);
                setEditing(false);
              }}
            >
              Anuluj
            </Button>
            <Button
              size="sm"
              disabled={save.isPending}
              onClick={async () => {
                try {
                  await save.mutateAsync({ block: block.id, body: draft });
                  setEditing(false);
                  showToast("Zapisane", "success");
                } catch (error) {
                  showToast(apiErrorMessage(error, "Nie udało się zapisać ściągi."), "error");
                }
              }}
            >
              Zapisz
            </Button>
          </div>
        </div>
      ) : block.body ? (
        <p className="whitespace-pre-line text-[12.5px] leading-5">{block.body}</p>
      ) : (
        <p className="text-[12.5px] text-muted-foreground">{BLOCK_HINTS[block.id]}</p>
      )}
      {block.updated_by && !editing ? (
        <p className="mt-auto text-[11px] text-muted-foreground">
          {block.updated_by} ·{" "}
          {block.updated_at
            ? new Date(block.updated_at).toLocaleDateString("pl-PL", {
                day: "2-digit",
                month: "2-digit",
                timeZone: "Europe/Warsaw",
              })
            : ""}
        </p>
      ) : null}
    </section>
  );
}

/**
 * Klienci (wariant B, 19.11.2026): ściąga klienta — jak u niego robimy
 * rozliczenia, wejście nowej osoby, zamówienia i kontakty. Liczby i pełny
 * profil zostają w module Klienci.
 */
export function ClientsTab() {
  const query = useBoClients();
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const rows = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase("pl");
    return (query.data?.items ?? []).filter((row) => !needle || row.name.toLocaleLowerCase("pl").includes(needle));
  }, [query.data, search]);
  const selected = openId ?? rows[0]?.client_id ?? null;
  const sheet = useBoClientSheet(selected);

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
    return <p className="p-4 text-sm text-muted-foreground">Ładowanie klientów…</p>;
  }
  if (query.data.items.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border bg-card p-3 text-sm text-muted-foreground">
        Żaden klient nie ma teraz naszych konsultantów.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-[240px_minmax(0,1fr)] gap-3">
      <div className="space-y-2">
        <div className="relative">
          <Search aria-hidden className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Szukaj klienta"
            className="h-8 pl-7 text-xs"
            placeholder="Szukaj klienta…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        <ul className="max-h-[calc(100dvh-300px)] overflow-y-auto rounded-xl border border-border bg-card" aria-label="Klienci">
          {rows.map((row) => (
            <li key={row.client_id}>
              <button
                type="button"
                onClick={() => setOpenId(row.client_id)}
                aria-current={selected === row.client_id ? "true" : undefined}
                className={cn(
                  "flex w-full items-center justify-between gap-2 border-b border-border/60 px-3 py-1.5 text-left text-[13px] last:border-0",
                  selected === row.client_id ? "bg-primary/5 font-medium text-primary" : "hover:bg-muted/50",
                )}
              >
                <span className="min-w-0 truncate">
                  {row.name}
                  {!row.has_sheet ? <span className="ml-1 text-[11px] font-normal text-muted-foreground">· bez ściągi</span> : null}
                </span>
                <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">{row.consultants}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="min-w-0 space-y-3">
        {sheet.isError ? (
          <QueryStateNotice state="error" description="Nie udało się wczytać ściągi klienta." onRetry={() => sheet.refetch()} />
        ) : null}
        {sheet.data ? (
          <>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h3 className="text-lg font-semibold">{sheet.data.name}</h3>
                <p className="text-xs text-muted-foreground">
                  {sheet.data.consultants} konsultantów · otwarte sprawy: {sheet.data.open_cases} · kończą się w 60 dni:{" "}
                  {sheet.data.ending_60.length}
                </p>
              </div>
              <Link
                href={`/clients/${sheet.data.client_id}`}
                className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
              >
                Pełny profil klienta <ArrowUpRight aria-hidden className="size-3" />
              </Link>
            </div>
            <div className="grid grid-cols-2 gap-3">
              {sheet.data.blocks.map((block) => (
                <SheetBlock key={block.id} sheet={sheet.data} block={block} />
              ))}
            </div>
          </>
        ) : sheet.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie ściągi…</p>
        ) : null}
      </div>
    </div>
  );
}
