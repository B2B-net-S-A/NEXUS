"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, Inbox, Loader2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FormField } from "@/components/ui/form-field";
import { useToast } from "@/components/Toast";
import { useAuthStore } from "@/store/auth";
import { pipelineApi, type PendingVerificationItem } from "@/lib/api";

const APPROVER_ROLES = new Set([
  "admin",
  "delivery_lead",
  "head_of_recruitment",
]);

const UNIT_LABEL: Record<string, string> = {
  hourly: "/h",
  daily: "/dz.",
  monthly: "/mies.",
};

function formatRate(item: PendingVerificationItem): string {
  if (item.expected_rate_value == null) return "—";
  const value = Number.parseFloat(item.expected_rate_value);
  const formatted = Number.isFinite(value)
    ? value.toLocaleString("pl-PL")
    : item.expected_rate_value;
  const unit = item.expected_rate_unit
    ? UNIT_LABEL[item.expected_rate_unit] ?? `/${item.expected_rate_unit}`
    : "";
  return `${formatted} ${item.expected_rate_currency ?? "PLN"}${unit}`;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("pl-PL", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function PendingVerificationsPage() {
  const userRole = useAuthStore((s) => s.user?.role);
  const isApprover = !!userRole && APPROVER_ROLES.has(userRole);
  const { showSuccess, showError } = useToast();
  const qc = useQueryClient();
  const [rejectTarget, setRejectTarget] = useState<{
    item: PendingVerificationItem;
    note: string;
  } | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["pending-verifications"],
    queryFn: async () => (await pipelineApi.listPendingVerifications()).data,
    enabled: isApprover,
    refetchInterval: 60_000,
  });

  const acceptMutation = useMutation({
    mutationFn: async (id: number) => pipelineApi.acceptVerification(id),
    onSuccess: () => {
      showSuccess("Weryfikacja zaakceptowana.");
      qc.invalidateQueries({ queryKey: ["pending-verifications"] });
    },
    onError: (e) => {
      console.error(e);
      showError("Nie udało się zaakceptować.");
    },
  });

  const rejectMutation = useMutation({
    mutationFn: async ({ id, note }: { id: number; note: string }) =>
      pipelineApi.rejectVerification(id, note),
    onSuccess: () => {
      showSuccess("Odrzucono — kandydat wrócił na poprzedni stage.");
      qc.invalidateQueries({ queryKey: ["pending-verifications"] });
      setRejectTarget(null);
    },
    onError: (e) => {
      console.error(e);
      showError("Nie udało się odrzucić.");
    },
  });

  if (!isApprover) {
    return (
      <div className="p-8 max-w-2xl mx-auto">
        <Card className="!p-6 text-center text-sm text-[hsl(var(--text-muted))]">
          <Inbox className="h-10 w-10 mx-auto mb-3 opacity-40" />
          Tylko delivery lead, head of recruitment lub admin mogą akceptować
          weryfikacje.
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4 max-w-6xl mx-auto">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-[hsl(var(--text-title))]">
            Weryfikacje czekające na akceptację
          </h1>
          <p className="text-sm text-[hsl(var(--text-muted))] mt-1">
            Kandydaci wrzuceni na stage <strong>"Zweryfikowany"</strong> ze
            stawką poza budżetem projektu wymagają Twojej akceptacji.
          </p>
        </div>
        <Badge variant="soft">{data?.length ?? 0}</Badge>
      </div>

      {isLoading && (
        <div className="py-12 text-center text-sm text-[hsl(var(--text-muted))]">
          <Loader2 className="h-6 w-6 mx-auto mb-2 animate-spin" />
          Ładowanie…
        </div>
      )}
      {isError && (
        <Card className="!p-4 text-sm text-rose-700 bg-rose-50 border border-rose-200">
          Nie udało się pobrać listy.
        </Card>
      )}

      {data && data.length === 0 && (
        <Card className="!p-8 text-center text-sm text-[hsl(var(--text-muted))]">
          <CheckCircle2 className="h-10 w-10 mx-auto mb-3 text-emerald-500 opacity-70" />
          Brak oczekujących weryfikacji. Wszyscy kandydaci przeszli przez
          bramkę.
        </Card>
      )}

      {data && data.length > 0 && (
        <div className="overflow-x-auto rounded-v2-m border border-[hsl(var(--border-subtle))]">
          <table className="w-full text-sm">
            <thead className="bg-[hsl(var(--bg-canvas))]/60 text-[hsl(var(--text-muted))]">
              <tr>
                <th className="text-left px-3 py-2 font-medium">Kandydat</th>
                <th className="text-left px-3 py-2 font-medium">Projekt</th>
                <th className="text-left px-3 py-2 font-medium">Stawka</th>
                <th className="text-left px-3 py-2 font-medium">Budżet (max)</th>
                <th className="text-left px-3 py-2 font-medium">Wrzucił</th>
                <th className="text-left px-3 py-2 font-medium">Kiedy</th>
                <th className="text-right px-3 py-2 font-medium">Akcje</th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr
                  key={row.candidate_stage_id}
                  className="border-t border-[hsl(var(--border-subtle))] hover:bg-[hsl(var(--bg-canvas))]/40"
                >
                  <td className="px-3 py-2">
                    <Link
                      href={`/candidates/${row.candidate_id}`}
                      className="font-medium text-[hsl(var(--accent))] hover:underline"
                    >
                      {row.candidate_name}
                    </Link>
                  </td>
                  <td className="px-3 py-2">
                    <Link
                      href={`/jobs/${row.job_id}`}
                      className="hover:underline"
                    >
                      {row.job_title}
                    </Link>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {formatRate(row)}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-[hsl(var(--text-muted))]">
                    {row.budget_max_at_move != null
                      ? `${row.budget_max_at_move.toLocaleString("pl-PL")} PLN`
                      : "—"}
                  </td>
                  <td className="px-3 py-2 text-[hsl(var(--text-muted))]">
                    {row.moved_by_name ?? "?"}
                  </td>
                  <td className="px-3 py-2 text-[hsl(var(--text-muted))] text-xs">
                    <span className="inline-flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {formatDate(row.moved_at)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="inline-flex items-center gap-1.5">
                      <Button
                        size="sm"
                        onClick={() =>
                          acceptMutation.mutate(row.candidate_stage_id)
                        }
                        disabled={acceptMutation.isPending}
                        className="bg-emerald-600 hover:bg-emerald-700"
                      >
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        Akceptuj
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setRejectTarget({ item: row, note: "" })}
                        className="text-rose-700 border-rose-300 hover:bg-rose-50"
                      >
                        <XCircle className="h-3.5 w-3.5" />
                        Odrzuć
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {rejectTarget && (
        <Dialog
          open
          onOpenChange={(v: boolean) => !v && setRejectTarget(null)}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Odrzuć weryfikację</DialogTitle>
              <DialogDescription>
                Kandydat wróci na poprzedni stage z notatką. Recruiter dostanie
                powiadomienie.
              </DialogDescription>
            </DialogHeader>
            <DialogBody>
              <FormField label="Powód odrzucenia">
                <textarea
                  value={rejectTarget.note}
                  onChange={(e) =>
                    setRejectTarget((p) =>
                      p ? { ...p, note: e.target.value } : null
                    )
                  }
                  rows={4}
                  placeholder="np. Stawka za wysoka, max 22000 PLN"
                  className="w-full px-3 py-2 rounded-v2-s border border-[hsl(var(--border-subtle))] bg-[hsl(var(--bg-surface))] focus:outline-none focus:ring-2 focus:ring-[hsl(var(--accent))]"
                  autoFocus
                />
              </FormField>
            </DialogBody>
            <DialogFooter>
              <Button variant="ghost" onClick={() => setRejectTarget(null)}>
                Anuluj
              </Button>
              <Button
                onClick={() =>
                  rejectMutation.mutate({
                    id: rejectTarget.item.candidate_stage_id,
                    note: rejectTarget.note.trim(),
                  })
                }
                disabled={
                  !rejectTarget.note.trim() || rejectMutation.isPending
                }
              >
                Odrzuć i wróć
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
