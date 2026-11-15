"use client";

// Cennik umowy ramowej klienta i dopłaty za technologie (F1, 15.11.2026).
// Czyta DL swojego klienta i Finanse; import z załącznika robią Finanse,
// „Przelicz kategorie z COA” — DL (kategoria i limit z zapisanych zamówień).
import { useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileUp, RefreshCw } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import {
  frameworkKeys,
  importFrameworkTerms,
  recomputeFrameworkCategories,
  useFrameworkTerms,
  type FrameworkImportResult,
  type FrameworkRecomputeRow,
} from "@/lib/api/framework-rates";
import { plnPerHour } from "@/lib/framework-category";
import { RECOMPUTE_OUTCOME_LABEL, summarizeRecompute } from "@/lib/framework-terms";
import { resolveViewState } from "@/lib/view-state";

interface Props {
  clientId: number;
  canImport: boolean;
  canRecompute: boolean;
}

export function FrameworkTermsPanel({ clientId, canImport, canRecompute }: Props) {
  const query = useFrameworkTerms(clientId, true);
  const queryClient = useQueryClient();
  const { showSuccess } = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [validFrom, setValidFrom] = useState("");
  const [preview, setPreview] = useState<FrameworkImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recompute, setRecompute] = useState<FrameworkRecomputeRow[] | null>(null);

  const runImport = async (apply: boolean) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const result = await importFrameworkTerms(clientId, file, apply, validFrom || null);
      setPreview(apply ? null : result);
      if (apply) {
        await queryClient.invalidateQueries({ queryKey: frameworkKeys.terms(clientId) });
        showSuccess("Zapisano cennik umowy ramowej");
        setFile(null);
      }
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się odczytać załącznika."));
    } finally {
      setBusy(false);
    }
  };

  const runRecompute = async () => {
    setBusy(true);
    setError(null);
    setRecompute([]);
    const rows: FrameworkRecomputeRow[] = [];
    try {
      let after: number | null = 0;
      while (after !== null) {
        const page = await recomputeFrameworkCategories(clientId, after, true);
        rows.push(...page.rows);
        setRecompute([...rows]);
        after = page.next_after_id;
      }
      showSuccess("Przeliczono kategorie z COA");
    } catch (err) {
      setError(apiErrorMessage(err, "Nie udało się przeliczyć kategorii z COA."));
    } finally {
      setBusy(false);
    }
  };

  if (query.isPending) return <p className="text-sm text-muted-foreground">Wczytywanie cennika…</p>;
  if (!query.isSuccess) {
    const state = resolveViewState({ isLoading: false, isError: true, error: query.error, isEmpty: false });
    return (
      <QueryStateNotice
        state={state === "forbidden" ? "forbidden" : "error"}
        onRetry={() => void query.refetch()}
      />
    );
  }
  const { cards, adders } = query.data;
  const summary = recompute ? summarizeRecompute(recompute) : null;

  return (
    <div className="space-y-4 text-sm" data-testid="framework-terms-panel">
      {canImport && (
        <div className="flex flex-wrap items-end gap-2 rounded-lg border border-border p-3">
          <div className="space-y-1">
            <div className="text-xs font-medium text-muted-foreground">Załącznik ze stawkami (.docx)</div>
            <input
              ref={fileRef}
              type="file"
              accept=".docx"
              className="sr-only"
              onChange={(e) => {
                setFile(e.target.files?.[0] ?? null);
                setPreview(null);
              }}
            />
            <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()}>
              <FileUp className="mr-1 h-3.5 w-3.5" />
              {file ? file.name : "Wybierz plik"}
            </Button>
          </div>
          <div className="space-y-1">
            <label htmlFor="fa-valid-from" className="text-xs font-medium text-muted-foreground">
              Obowiązuje od
            </label>
            <Input id="fa-valid-from" type="date" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
          </div>
          <Button size="sm" disabled={!file || busy} onClick={() => void runImport(false)}>
            Pokaż, co się zmieni
          </Button>
          {preview && (
            <Button size="sm" disabled={busy} onClick={() => void runImport(true)}>
              Zapisz cennik
            </Button>
          )}
        </div>
      )}
      {preview && (
        <div className="rounded-lg border border-border p-3">
          <div className="font-medium text-foreground">
            Podgląd: {preview.rates.length} stawek, {preview.adders.length} dopłat
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            Nowe: {preview.rates.filter((r) => r.action === "create").length} stawek,{" "}
            {preview.adders.filter((a) => a.action === "create").length} dopłat · zmienione:{" "}
            {preview.rates.filter((r) => r.action === "update").length + preview.adders.filter((a) => a.action === "update").length}
          </div>
          {preview.warnings.map((w) => (
            <p key={w} className="mt-1 text-xs text-warning">
              {w}
            </p>
          ))}
        </div>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}

      {cards.length === 0 ? (
        <p className="text-muted-foreground">
          Cennik umowy ramowej jest pusty. {canImport ? "Wgraj załącznik ze stawkami." : "Wgrywają go Finanse."}
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <div className="max-h-[50dvh] overflow-auto rounded-lg border border-border">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-card text-left text-muted-foreground">
                <tr>
                  <th className="px-3 py-1.5 font-medium">Kategoria</th>
                  <th className="px-3 py-1.5 text-right font-medium">Maks.</th>
                  <th className="px-3 py-1.5 font-medium">Dopłaty</th>
                </tr>
              </thead>
              <tbody>
                {cards.map((card) => (
                  <tr key={card.id} className="border-t border-border">
                    <td className="px-3 py-1.5 text-foreground">{card.label}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{plnPerHour(card.rate_max)}</td>
                    <td className="px-3 py-1.5 text-muted-foreground">{card.addons.length ? "tak" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">Dopłaty za technologie ({adders.length})</div>
            <div className="flex flex-wrap gap-1">
              {adders.map((a) => (
                <Badge key={a.id} variant={Number(a.percent) >= 20 ? "soft" : "outline"} size="md">
                  {a.technology} {Number(a.percent)}%
                </Badge>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              Dopłata nie zmienia zamówienia ani stawki przychodowej. Podnosi limit, gdy klient potwierdzi technologię.
            </p>
          </div>
        </div>
      )}

      {canRecompute && cards.length > 0 && (
        <div className="space-y-2 rounded-lg border border-border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              Kategoria i poziom z ostatniego zapisanego COA każdej osoby ustawiają limit z cennika.
            </p>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => void runRecompute()}>
              <RefreshCw className={`mr-1 h-3.5 w-3.5${busy && recompute ? " animate-spin" : ""}`} />
              {busy && recompute ? `Przeliczam… ${recompute.length} umów` : "Przelicz kategorie z COA"}
            </Button>
          </div>
          {summary && (
            <div className="flex flex-wrap gap-1">
              {summary.map(([outcome, count]) => (
                <Badge key={outcome} variant="outline" size="md">
                  {RECOMPUTE_OUTCOME_LABEL[outcome] ?? outcome}: {count}
                </Badge>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
