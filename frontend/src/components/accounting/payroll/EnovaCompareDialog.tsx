"use client";

import { useState } from "react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCompareEnova, type EnovaComparison } from "@/lib/api/payroll-k7b";
import type { PayrollList } from "@/lib/api/payroll-lists";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { gr } from "../ledger-model";
import { comparisonSummary, diffLabel } from "./k7b-model";

/**
 * Porównanie listy NEXUSA z listą z Enovy osoba po osobie, do grosza (K7b) —
 * warunek wyłączenia Enovy po 2–3 miesiącach równoległych. Plik nie jest
 * zapisywany; różnice widać od razu, osoby z różnicą na górze.
 */
export function EnovaCompareDialog({
  list,
  open,
  onOpenChange,
}: {
  list: PayrollList;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { showToast } = useToast();
  const compare = useCompareEnova();
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<EnovaComparison | null>(null);

  const run = () => {
    if (!file) return;
    compare.mutate(
      { listId: list.id, file },
      {
        onSuccess: setResult,
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się porównać list."), "error"),
      },
    );
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) {
          setResult(null);
          setFile(null);
        }
        onOpenChange(next);
      }}
    >
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle className="text-lg">Porównanie z Enovą — {list.number}</DialogTitle>
          <DialogDescription>
            Eksport listy płac z Enovy za ten miesiąc (XLSX albo CSV, wiersz na osobę — ten sam plik co do LP). Plik nie
            jest zapisywany.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3 text-[13px]">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="file"
              accept=".xlsx,.csv"
              aria-label="Lista płac z Enovy"
              className="max-w-[260px] text-[12px]"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setResult(null);
              }}
            />
            <Button size="sm" disabled={!file} loading={compare.isPending} onClick={run}>
              Porównaj
            </Button>
          </div>
          {result ? <ComparisonResult result={result} /> : null}
        </DialogBody>
        <DialogFooter>
          <Button size="sm" variant="ghost" onClick={() => onOpenChange(false)}>
            Zamknij
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ComparisonResult({ result }: { result: EnovaComparison }) {
  const messages = [
    ...result.problems.map((text) => `Plik: ${text}`),
    ...result.errors.map((item) => `Wiersz ${item.line}: ${item.message}`),
  ];
  return (
    <div className="space-y-3">
      <p className={cn("rounded-md px-3 py-2 font-medium", result.summary.all_equal ? "bg-success-muted text-success-muted-foreground" : "bg-warning-muted text-warning-muted-foreground")}>
        {comparisonSummary(result)}
      </p>
      {messages.length ? (
        <ul className="space-y-0.5">
          {messages.map((text) => (
            <li key={text} className="flex items-start gap-1.5">
              <span aria-hidden className="mt-[7px] size-1.5 shrink-0 rounded-full bg-destructive" />
              <span className="min-w-0 break-words">{text}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {result.people.length ? (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[640px] table-fixed text-sm">
            <thead>
              <tr className="border-b border-border/70">
                <th className={cn(CALM_HEAD, "w-[30%] py-1.5 text-left")}>Osoba</th>
                <th className={cn(CALM_HEAD, "py-1.5 text-left")}>Różnice (NEXUS − Enova)</th>
              </tr>
            </thead>
            <tbody>
              {result.people.map((person) => {
                const diffs = person.fields.filter((field) => field.diff !== 0);
                return (
                  <tr key={`${person.person}-${person.enova_line}`} className={CALM_ROW}>
                    <td className="truncate py-1.5 align-top font-medium">{person.person}</td>
                    <td className="py-1.5 align-top tabular-nums">
                      {diffs.length ? (
                        <ul className="space-y-0.5">
                          {diffs.map((field) => (
                            <li key={field.key}>
                              {field.label}: <span className="font-medium">{diffLabel(field.diff)}</span>{" "}
                              <span className="text-muted-foreground">
                                (NEXUS {gr(field.nexus)}, Enova {gr(field.enova)})
                              </span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <span className="text-success-muted-foreground">zgodne do grosza</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      {result.only_nexus.length || result.only_enova.length ? (
        <div className="grid gap-2 sm:grid-cols-2">
          {result.only_nexus.length ? (
            <div>
              <h3 className="text-[12px] font-semibold">Tylko na liście NEXUSA</h3>
              <ul className="text-muted-foreground">
                {result.only_nexus.map((item) => (
                  <li key={item.person}>{item.person}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {result.only_enova.length ? (
            <div>
              <h3 className="text-[12px] font-semibold">Tylko w pliku z Enovy</h3>
              <ul className="text-muted-foreground">
                {result.only_enova.map((item) => (
                  <li key={item.line}>
                    {item.person || "bez nazwiska"} (wiersz {item.line}
                    {item.reason === "two_rows" ? ", dwa wiersze tej osoby" : ""})
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
