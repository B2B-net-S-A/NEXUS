"use client";

/**
 * Fakt nagłówka rekrutacji „Przedwstępna” obok „Procesu u klienta” (0762,
 * decyzje Artura 23.11.2026): ustawienie „każda osoba podpisuje umowę
 * przedwstępną przed <etap>” i „Zatrzymaj kartę do podpisu”. Edycja w okienku
 * jak proces; przy tworzeniu — `/jobs/new`. Przy 1280 px sama ikona (linia
 * faktów się nie mieści), napis od szerokości nagłówka 86rem.
 * Reguła: `docs/claude/rekrutacja-tablica/stop-do-podpisu-przedwstepnej.md`.
 */

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileSignature, Loader2, Lock } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { PreContractRuleEditor, type PreContractRuleDraft } from "@/components/v2/jobs/PreContractRuleEditor";
import { apiErrorMessage } from "@/lib/api-error";
import { invalidatePreContract, preContractsApi, type PreContractJobRule } from "@/lib/api/preContracts";
import { canSetPreContractStop, ruleStageLabel, ruleStageShort } from "@/lib/pre-contract-stop";
import { cn, formatDate } from "@/lib/utils";
import { useAuthStore } from "@/store/auth";

interface JobPreContractRuleFactProps {
  jobId: number;
  rule: PreContractJobRule | null;
  onSaved: () => void;
}

export function JobPreContractRuleFact({ jobId, rule, onSaved }: JobPreContractRuleFactProps) {
  const canEdit = canSetPreContractStop(useAuthStore((st) => st.user));
  const queryClient = useQueryClient();
  const { showSuccess, showError } = useToast();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<PreContractRuleDraft | null | undefined>(undefined);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (draft === undefined) return;
    setSaving(true);
    try {
      const res = await preContractsApi.setJobRule(jobId, draft);
      invalidatePreContract(queryClient, jobId);
      onSaved();
      setDraft(undefined);
      setOpen(false);
      showSuccess(
        res.requests_created > 0
          ? `Zapisano. Prośby o przedwstępną dla ${res.requests_created} os. trafiły do rekruterów.`
          : "Zapisano.",
      );
    } catch (e) {
      showError(apiErrorMessage(e, "Nie udało się zapisać ustawienia przedwstępnej."));
    } finally {
      setSaving(false);
    }
  };

  const title = rule
    ? `Umowa przedwstępna od każdej osoby: ${ruleStageLabel(rule.needed_before).replace("Przed", "przed")}${
        rule.stop ? ", karta stoi do podpisu" : ""
      }`
    : "Umowa przedwstępna: nie wymagana od wszystkich";

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) setDraft(undefined);
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "flex h-7 shrink-0 items-center gap-1.5 rounded-md border px-2 focus-visible:outline-2 focus-visible:outline-primary @min-[86rem]/job-header:px-2.5",
            rule?.stop
              ? "border-destructive/40 bg-destructive/10 hover:bg-destructive/15"
              : rule
                ? "border-primary/20 bg-primary/5 hover:bg-primary/10"
                : "border-dashed border-border hover:bg-muted",
          )}
          data-testid="job-header-fact-pre-contract"
          data-tour="job.header.pre-contract"
          title={title}
        >
          {rule?.stop ? (
            <Lock className="h-3.5 w-3.5 shrink-0 text-destructive" aria-hidden="true" />
          ) : (
            <FileSignature className="h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
          )}
          <span className="sr-only">{title}</span>
          <span
            aria-hidden="true"
            className={cn(
              "hidden whitespace-nowrap text-[13px] leading-tight @min-[86rem]/job-header:inline",
              rule ? "font-semibold text-foreground" : "text-muted-foreground",
            )}
          >
            {rule ? `Przedwstępna · ${ruleStageShort(rule.needed_before)}` : "przedwstępna"}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[480px] max-w-[calc(100vw-2rem)] p-0" data-testid="pre-contract-rule-popover">
        <div className="flex flex-col">
          <div className="border-b border-border px-4 py-3">
            <p className="text-sm font-semibold">Umowa przedwstępna w tej rekrutacji</p>
            <p className="text-xs text-muted-foreground">
              {rule
                ? `Ustawił(a) ${rule.set_by_name ?? "—"}${rule.set_at ? `, ${formatDate(rule.set_at)}` : ""}`
                : "Nie wymagana od wszystkich — o umowę można prosić przy pojedynczej osobie."}
            </p>
          </div>
          <div className="px-4 py-3">
            {draft !== undefined ? (
              <PreContractRuleEditor value={draft} onChange={setDraft} idPrefix="job-pre-contract" disabled={saving} />
            ) : rule ? (
              <ul className="space-y-1 text-sm">
                <li>
                  Każda osoba podpisuje: <b>{ruleStageLabel(rule.needed_before)}</b>
                </li>
                <li>
                  {rule.stop ? (
                    <span className="font-medium text-destructive">Karta stoi do podpisu obu stron</span>
                  ) : (
                    "Brak umowy tylko ostrzega"
                  )}
                </li>
                <li className="text-xs text-muted-foreground">
                  Prośby zakładają się same od „Zweryfikowanego”. Wyjątek dla jednej osoby: panel osoby › Umowa.
                </li>
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Brak ustawienia.</p>
            )}
          </div>
          {canEdit ? (
            <div className="flex justify-end gap-2 border-t border-border px-4 py-2">
              {draft !== undefined ? (
                <>
                  <Button size="sm" variant="ghost" onClick={() => setDraft(undefined)} disabled={saving}>
                    Anuluj
                  </Button>
                  <Button size="sm" onClick={() => void save()} disabled={saving} data-testid="pre-contract-rule-save" data-tour="job.pre-contract.save">
                    {saving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden /> : null}
                    Zapisz
                  </Button>
                </>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  data-testid="pre-contract-rule-edit"
                  data-tour="job.pre-contract.edit"
                  onClick={() =>
                    setDraft(rule ? { needed_before: rule.needed_before, stop: rule.stop } : { needed_before: "cv_sent", stop: true })
                  }
                >
                  {rule ? "Zmień" : "Ustaw dla wszystkich"}
                </Button>
              )}
            </div>
          ) : (
            <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
              Zmienia Delivery Lead klienta albo Head of Recruitment.
            </p>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
