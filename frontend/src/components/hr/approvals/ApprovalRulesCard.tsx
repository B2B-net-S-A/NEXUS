"use client";

import { useEffect, useState } from "react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useMentionableUsers } from "@/hooks/useMentionableUsers";
import { apiErrorMessage } from "@/lib/api-error";
import { useApprovalRules, useSaveApprovalRules, type ApprovalKind } from "@/lib/api/hr-approvals";
import { resolveViewState } from "@/lib/view-state";

import { KIND_OPTIONS } from "./approvals-format";

const NEVER = "never";
const ADMINS = "admins";

/** Próg z pola: puste albo „nigdy” = `null`; liczba całkowita ≥ 0. */
export function parseLimit(text: string): number | null | undefined {
  const value = text.replace(/\s/g, "");
  if (value === "" || value === NEVER) return null;
  if (!/^\d+$/.test(value)) return undefined;
  const number = Number(value);
  return number <= 1_000_000 ? number : undefined;
}

/**
 * Ustawienia → Kadry → Moduły: zasady zgód (0483). Do jakiej kwoty brutto
 * przełożony autora zatwierdza sam (puste = nigdy — zawsze zatwierdzający)
 * i kto zatwierdza resztę (puste = aktywni admini). Tylko admin.
 */
export function ApprovalRulesCard() {
  const rules = useApprovalRules(true);
  const save = useSaveApprovalRules();
  const users = useMentionableUsers({ kind: "global" });
  const { showToast } = useToast();
  const [limits, setLimits] = useState<Record<ApprovalKind, string> | null>(null);
  const [approver, setApprover] = useState<string>(ADMINS);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!rules.data) return;
    setLimits(
      Object.fromEntries(
        KIND_OPTIONS.map(({ value }) => [
          value,
          rules.data.supervisor_limits[value]?.toString() ?? "",
        ]),
      ) as Record<ApprovalKind, string>,
    );
    setApprover(
      rules.data.final_approver_user_id ? String(rules.data.final_approver_user_id) : ADMINS,
    );
  }, [rules.data]);

  const state = resolveViewState({
    isLoading: rules.isLoading,
    isError: rules.isError,
    error: rules.error,
    isSuccess: rules.isSuccess,
    isEmpty: false,
  });
  if (state === "loading" || !limits) {
    return <Card className="p-5 text-sm text-muted-foreground">Wczytywanie zasad zgód…</Card>;
  }
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <QueryStateNotice state={state} onRetry={() => rules.refetch()} />;
  }

  const submit = () => {
    const parsed: Partial<Record<ApprovalKind, number | null>> = {};
    for (const { value, label } of KIND_OPTIONS) {
      const limit = parseLimit(limits[value]);
      if (limit === undefined) {
        setError(
          `${label}: kwota w złotych (liczba całkowita) albo puste pole = zawsze zatwierdzający.`,
        );
        return;
      }
      parsed[value] = limit;
    }
    setError(null);
    save.mutate(
      {
        final_approver_user_id: approver === ADMINS ? null : Number(approver),
        supervisor_limits: parsed as Record<ApprovalKind, number | null>,
      },
      {
        onSuccess: () => showToast("Zasady zgód zapisane", "success"),
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać zasad zgód.")),
      },
    );
  };

  return (
    <Card className="space-y-4 p-5">
      <div>
        <h2 className="text-base font-semibold text-foreground">Zgody — kto zatwierdza</h2>
        <p className="text-sm text-muted-foreground">
          Do progu wydatek zatwierdza przełożony autora sam. Powyżej — i zawsze przy pustym polu —
          decyduje zatwierdzający. Kwoty brutto w złotych; subskrypcja co miesiąc liczy się rocznie.
        </p>
      </div>

      <div className="space-y-1.5">
        <label htmlFor="approval-final" className="text-sm font-medium text-foreground">
          Zatwierdzający
        </label>
        <Select value={approver} onValueChange={setApprover}>
          <SelectTrigger id="approval-final" className="max-w-sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ADMINS}>Wszyscy admini</SelectItem>
            {(users.data ?? []).map((user) => (
              <SelectItem key={user.id} value={String(user.id)}>
                {user.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          Dziś zatwierdza: {rules.data?.effective_final_approver_names.join(", ") || "—"}
        </p>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] text-sm">
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="py-1.5 pr-3 font-medium">Rodzaj</th>
              <th className="py-1.5 font-medium">Przełożony zatwierdza sam do (zł)</th>
            </tr>
          </thead>
          <tbody>
            {KIND_OPTIONS.map(({ value, label }) => (
              <tr key={value} className="border-t border-border/60">
                <td className="py-2 pr-3 font-medium text-foreground">{label}</td>
                <td className="py-2">
                  <Input
                    aria-label={`${label} — próg przełożonego`}
                    inputMode="numeric"
                    placeholder="nigdy — zawsze zatwierdzający"
                    className="max-w-[260px]"
                    value={limits[value]}
                    onChange={(event) =>
                      setLimits((prev) => (prev ? { ...prev, [value]: event.target.value } : prev))
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      <Button onClick={submit} disabled={save.isPending}>
        {save.isPending ? "Zapisywanie…" : "Zapisz zasady"}
      </Button>
    </Card>
  );
}
