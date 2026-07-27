"use client"

import { useState } from "react"
import Link from "next/link"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CheckCircle2, Clock, ShieldAlert, XCircle } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { FormField } from "@/components/ui/form-field"
import { useToast } from "@/components/Toast"
import { pipelineApi, type PendingVerificationItem } from "@/lib/api"

const UNIT_LABEL: Record<string, string> = {
  hourly: "/h",
  daily: "/dz.",
  monthly: "/mies.",
}

function formatRate(item: PendingVerificationItem): string {
  if (item.expected_rate_value == null) return "—"
  const value = Number.parseFloat(item.expected_rate_value)
  const formatted = Number.isFinite(value)
    ? value.toLocaleString("pl-PL")
    : item.expected_rate_value
  const unit = item.expected_rate_unit
    ? UNIT_LABEL[item.expected_rate_unit] ?? `/${item.expected_rate_unit}`
    : ""
  return `${formatted} ${item.expected_rate_currency ?? "PLN"}${unit}`
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("pl-PL", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    })
  } catch {
    return iso
  }
}

const WIDGET_PREVIEW_LIMIT = 3

interface PendingVerificationsWidgetProps {
  /** When true, scope verifications to the logged-in delivery_lead. */
  mine: boolean
}

export function PendingVerificationsWidget({ mine }: PendingVerificationsWidgetProps) {
  const { showSuccess, showError } = useToast()
  const qc = useQueryClient()
  const [rejectTarget, setRejectTarget] = useState<{
    item: PendingVerificationItem
    note: string
  } | null>(null)

  const { data, isLoading, isError } = useQuery({
    queryKey: ["pending-verifications", mine ? "mine" : "all"],
    queryFn: async () =>
      mine
        ? (await pipelineApi.listMyPendingVerifications()).data
        : (await pipelineApi.listPendingVerifications()).data,
    refetchInterval: 60_000,
  })

  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["pending-verifications"] })

  const acceptMutation = useMutation({
    mutationFn: async (id: number) => pipelineApi.acceptVerification(id),
    onSuccess: () => {
      showSuccess("Weryfikacja zaakceptowana.")
      invalidate()
    },
    onError: (e) => {
      console.error(e)
      showError("Nie udało się zaakceptować.")
    },
  })

  const rejectMutation = useMutation({
    mutationFn: async ({ id, note }: { id: number; note: string }) =>
      pipelineApi.rejectVerification(id, note),
    onSuccess: () => {
      showSuccess("Odrzucono — kandydat wrócił na poprzedni stage.")
      invalidate()
      setRejectTarget(null)
    },
    onError: (e) => {
      console.error(e)
      showError("Nie udało się odrzucić.")
    },
  })

  if (isLoading) {
    return (
      <Card className="p-4!">
        <div className="space-y-2">
          <div className="h-4 w-48 bg-muted animate-pulse rounded" />
          <div className="h-3 w-full bg-muted animate-pulse rounded" />
          <div className="h-3 w-3/4 bg-muted animate-pulse rounded" />
        </div>
      </Card>
    )
  }

  if (isError) {
    return (
      <Card className="p-4! text-sm text-rose-700 bg-rose-50 border border-rose-200">
        Nie udało się pobrać weryfikacji.
      </Card>
    )
  }

  const items = data ?? []
  const totalCount = items.length

  if (totalCount === 0) {
    return (
      <Card className="p-3! text-xs text-muted-foreground flex items-center gap-2">
        <CheckCircle2 className="h-4 w-4 text-emerald-500 opacity-70" />
        Wszystkie weryfikacje przejrzane.
      </Card>
    )
  }

  const previewItems = items.slice(0, WIDGET_PREVIEW_LIMIT)
  const overflow = totalCount - previewItems.length

  return (
    <>
      <Card className="p-0! overflow-hidden border-amber-200 bg-amber-50/40">
        <div className="px-4 py-3 border-b border-amber-200 bg-amber-100/60 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-5 w-5 text-amber-700" />
            <div>
              <div className="font-semibold text-sm text-amber-900">
                Weryfikacje wymagające akcji
              </div>
              <div className="text-xs text-amber-800/70">
                Kandydaci ze stawką poza budżetem — czekają na Twoją decyzję.
              </div>
            </div>
          </div>
          <Badge variant="soft" size="sm">
            {totalCount}
          </Badge>
        </div>
        <ul className="divide-y divide-amber-100">
          {previewItems.map((row) => (
            <li
              key={row.candidate_stage_id}
              className="px-4 py-3 flex flex-wrap items-center gap-3 text-sm"
            >
              <div className="min-w-0 flex-1">
                <Link
                  href={`/candidates/${row.candidate_id}`}
                  className="font-medium text-primary hover:underline"
                >
                  {row.candidate_name}
                </Link>
                <span className="text-muted-foreground"> → </span>
                <Link
                  href={`/jobs/${row.job_id}`}
                  className="hover:underline"
                >
                  {row.job_title}
                </Link>
                <div className="text-xs text-muted-foreground mt-0.5 flex flex-wrap gap-2">
                  <span className="font-mono">{formatRate(row)}</span>
                  {row.budget_max_at_move != null && (
                    <span className="opacity-70">
                      budżet: {row.budget_max_at_move.toLocaleString("pl-PL")} PLN
                    </span>
                  )}
                  <span className="inline-flex items-center gap-1">
                    <Clock className="h-3 w-3" />
                    {formatDate(row.moved_at)}
                  </span>
                  {row.moved_by_name && (
                    <span className="opacity-70">· {row.moved_by_name}</span>
                  )}
                </div>
              </div>
              <div className="inline-flex items-center gap-1.5 ml-auto">
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
            </li>
          ))}
        </ul>
        {overflow > 0 && (
          <div className="px-4 py-2 bg-amber-50 border-t border-amber-100 text-right">
            <Link
              href="/pending-verifications"
              className="text-xs font-medium text-amber-900 hover:underline"
            >
              Zobacz wszystkie ({totalCount}) →
            </Link>
          </div>
        )}
      </Card>

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
                      p ? { ...p, note: e.target.value } : null,
                    )
                  }
                  rows={4}
                  placeholder="np. Stawka za wysoka, max 22000 PLN"
                  className="w-full px-3 py-2 rounded-md border border-border bg-card focus:outline-hidden focus:ring-2 focus:ring-primary"
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
    </>
  )
}
