"use client";

// „Jakość QC” (D6, 13.10.2026) — jak często QC CV się myli. Trafność
// sprawdzenia = 1 − pominięte jako „QC się myli” / pokazane w oknie dni z
// serwera. Uwaga z niską trafnością sama staje się informacją; admin może
// ustawić stan ręcznie. Blokad z tego ekranu nie da się wyciszyć (serwer: 422),
// więc nie mają wyboru stanu. Dostęp: admin (middleware `/settings/ai` + 403).

import Link from "next/link";
import { ExternalLink, Loader2 } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Badge } from "@/components/ui/badge";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useQcQuality,
  useSetQcCheckState,
  type QcCheckState,
  type QcQualityCheck,
  type QcQualityReport,
} from "@/lib/api/qcQuality";
import { QC_DISMISS_REASONS } from "@/lib/cv-qc";
import { formatDate } from "@/lib/utils";
import { isForbiddenError } from "@/lib/view-state";

const STATE_LABEL: Record<QcCheckState, string> = {
  active: "Aktywna",
  info: "Informacja",
  off: "Wyłączona",
};

const AUTO = "auto";

const pct = (value: number) => `${Math.round(value * 100)}%`;

function reasonLabel(code: string): string {
  return QC_DISMISS_REASONS.find((r) => r.code === code)?.label ?? code;
}

function Precision({ check, report }: { check: QcQualityCheck; report: QcQualityReport }) {
  if (check.precision == null) return <span className="text-muted-foreground">—</span>;
  const threshold = check.blocking ? report.alert_blocking_below : report.auto_info_below;
  if (check.precision < threshold) {
    return (
      <Badge variant={check.blocking ? "danger" : "warning"} size="md" className="tabular-nums">
        {pct(check.precision)}
      </Badge>
    );
  }
  return <span className="tabular-nums">{pct(check.precision)}</span>;
}

function StateCell({
  check,
  saving,
  onChange,
}: {
  check: QcQualityCheck;
  saving: boolean;
  onChange: (state: QcCheckState | null) => void;
}) {
  if (check.blocking) {
    return <span className="text-xs text-muted-foreground">Zawsze aktywna — blokady nie przechodzą same</span>;
  }
  const automat = check.auto === "info" ? "info" : "active";
  return (
    <div className="space-y-1">
      <select
        aria-label={`Stan: ${check.label}`}
        value={check.manual ?? AUTO}
        disabled={saving}
        onChange={(event) => {
          const value = event.target.value;
          onChange(value === AUTO ? null : (value as QcCheckState));
        }}
        className="w-full min-w-40 rounded-md border border-input bg-background px-2 py-1.5 text-sm text-foreground disabled:opacity-60"
      >
        <option value={AUTO}>Automat ({STATE_LABEL[automat].toLowerCase()})</option>
        <option value="active">{STATE_LABEL.active}</option>
        <option value="info">{STATE_LABEL.info}</option>
        <option value="off">{STATE_LABEL.off}</option>
      </select>
      {check.state !== "active" ? (
        <p className="text-xs text-muted-foreground">
          Teraz: {STATE_LABEL[check.state].toLowerCase()}
          {check.manual == null ? " (automat)" : ""}
        </p>
      ) : null}
    </div>
  );
}

function ChecksTable({ report }: { report: QcQualityReport }) {
  const setState = useSetQcCheckState();
  const { showSuccess, showError } = useToast();
  const savingKey = setState.isPending ? setState.variables?.key : null;
  return (
    <div className="relative overflow-x-auto rounded-xl border border-border bg-card">
      <table className="w-full min-w-[720px] text-sm">
        <caption className="sr-only">Trafność sprawdzeń QC CV</caption>
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th scope="col" className="px-3 py-2 font-medium">
              Sprawdzenie
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Pokazane
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Oznaczone jako nieprawda
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Trafność
            </th>
            <th scope="col" className="px-3 py-2 font-medium">
              Stan
            </th>
          </tr>
        </thead>
        <tbody>
          {report.checks.map((check) => {
            const reasons = Object.entries(check.reasons).filter(([, n]) => n > 0);
            return (
              <tr key={check.key} className="border-b border-border align-top last:border-b-0">
                <th scope="row" className="px-3 py-2 text-left font-normal">
                  <span className="block font-medium text-foreground">{check.label}</span>
                  <Badge variant={check.blocking ? "danger" : "outline"} size="sm" className="mt-1">
                    {check.blocking ? "Blokada" : "Uwaga"}
                  </Badge>
                </th>
                <td className="px-3 py-2 text-right tabular-nums">{check.shown}</td>
                <td className="px-3 py-2">
                  <span className="tabular-nums">{check.dismissed_wrong}</span>
                  {reasons.length > 0 ? (
                    <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                      {reasons.map(([code, n]) => (
                        <li key={code}>
                          {reasonLabel(code)}: <span className="tabular-nums">{n}</span>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-right">
                  <Precision check={check} report={report} />
                </td>
                <td className="px-3 py-2">
                  <StateCell
                    check={check}
                    saving={savingKey === check.key}
                    onChange={(state) =>
                      setState.mutate(
                        { key: check.key, state },
                        {
                          onSuccess: () => showSuccess(`Zapisano stan: ${check.label}.`),
                          onError: (error) =>
                            showError(apiErrorMessage(error, "Nie udało się zapisać stanu. Spróbuj ponownie.")),
                        },
                      )
                    }
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RecentDismissals({ report }: { report: QcQualityReport }) {
  if (report.recent.length === 0) {
    return <p className="text-sm text-muted-foreground">Nikt jeszcze nie oznaczył uwagi QC jako nieprawdy.</p>;
  }
  return (
    <ul className="divide-y divide-border rounded-xl border border-border bg-card">
      {report.recent.map((row) => (
        <li key={row.id} className="flex flex-wrap items-start justify-between gap-2 px-3 py-2 text-sm">
          <div className="min-w-0 flex-1 space-y-0.5">
            <p className="flex flex-wrap items-center gap-1.5">
              <span className="font-medium [overflow-wrap:anywhere]">{row.label}</span>
              <Badge variant="outline" size="sm">
                {row.check_label}
              </Badge>
              {row.restored ? (
                <Badge variant="info" size="sm">
                  przywrócone
                </Badge>
              ) : null}
            </p>
            <p className="text-xs [overflow-wrap:anywhere]">
              {row.reason_label}
              {row.note ? <span className="text-muted-foreground"> — „{row.note}”</span> : null}
            </p>
            <p className="text-xs text-muted-foreground">
              {[row.by_name, formatDate(row.at)].filter(Boolean).join(", ")}
            </p>
          </div>
          <Link
            href={`/jobs/${row.job_id}?candidate=${row.candidate_id}`}
            className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
          >
            Otwórz kandydata w rekrutacji
            <ExternalLink className="size-3" aria-hidden />
          </Link>
        </li>
      ))}
    </ul>
  );
}

export default function QcQualityPage() {
  const query = useQcQuality();
  const wrap = "container max-w-5xl mx-auto md:py-8 md:px-4";

  if (query.isLoading) {
    return (
      <div className={wrap}>
        <p className="flex min-h-[200px] items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-5 animate-spin" aria-hidden />
          Liczę trafność QC…
        </p>
      </div>
    );
  }

  if (query.isError && isForbiddenError(query.error)) {
    return (
      <div className={wrap}>
        <QueryStateNotice state="forbidden" description="„Jakość QC” jest dostępna wyłącznie dla administratora." />
      </div>
    );
  }
  // Pusty raport wolno pokazać tylko po sukcesie — awaria nie jest pustą tabelą.
  if (!query.isSuccess) {
    return (
      <div className={wrap}>
        <QueryStateNotice
          state="error"
          description="Nie udało się policzyć trafności QC."
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  }

  const report = query.data;
  return (
    <div className={wrap}>
      <div className="mb-6 space-y-2">
        <h1 className="text-2xl font-bold text-foreground">Jakość QC</h1>
        <p className="text-sm text-muted-foreground">
          Trafność to część pokazanych uwag, których nikt nie oznaczył jako błąd QC („Jest w CV”, „Pod inną nazwą”,
          „Inna rola albo sekcja”) w ostatnich {report.window_days} dniach. Uwaga z trafnością poniżej{" "}
          {pct(report.auto_info_below)} przy co najmniej {report.auto_min_shown} pokazanych sama staje się informacją
          (widać ją, nie liczy się do uwag); blokady nigdy nie przechodzą same — poniżej{" "}
          {pct(report.alert_blocking_below)} administrator dostaje powiadomienie.
        </p>
      </div>

      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted-foreground">Sprawdzenia</h2>
      <ChecksTable report={report} />

      <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        Ostatnie pominięcia
      </h2>
      <RecentDismissals report={report} />
    </div>
  );
}
