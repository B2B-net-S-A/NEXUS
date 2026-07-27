"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { UserX } from "lucide-react";

import api from "@/lib/api";
import { formatDate } from "@/lib/utils";

interface HiringManagerVeto {
  hiring_manager_contact_id: number;
  hiring_manager_name?: string | null;
  source_job_id: number;
  source_job_title?: string | null;
  rejected_at: string;
  rejection_reason_name: string;
  rejection_note?: string | null;
}

interface Props {
  candidateId: number;
  /** Collapse to nothing when the candidate has no vetoes (panel footer use). */
  hideWhenEmpty?: boolean;
}

/**
 * Managers who interviewed this candidate and turned them down.
 *
 * Read-only: vetoes are derived from pipeline history, never entered by hand —
 * so unlike {@link ConflictsWidget} there is no add form. A job-scoped badge can
 * only name one manager; this is the whole picture, with the reasons, so nobody
 * has to open four past recruitments to find out why.
 */
export function HiringManagerVetoesWidget({ candidateId, hideWhenEmpty = false }: Props) {
  const [rows, setRows] = useState<HiringManagerVeto[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<HiringManagerVeto[]>(
          `/api/candidates/${candidateId}/hiring-manager-vetoes`,
        );
        if (!cancelled) setRows(res.data ?? []);
      } catch {
        if (!cancelled) setRows([]);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [candidateId]);

  if (loading) return null;
  // No add action to offer, so an empty state would be pure noise.
  if (rows.length === 0 && hideWhenEmpty) return null;

  if (rows.length === 0) {
    return (
      <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
        <h3 className="font-medium flex items-center gap-2 text-foreground dark:text-foreground">
          <UserX className="w-4 h-4 text-muted-foreground" />
          Odrzucenia przez hiring managerów (0)
        </h3>
        <p className="text-sm text-muted-foreground mt-2">
          Żaden hiring manager nie odrzucił tego kandydata po rozmowie.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
      <h3 className="font-medium flex items-center gap-2 mb-3 text-foreground dark:text-foreground">
        <UserX className="w-4 h-4 text-destructive" />
        Odrzucenia przez hiring managerów ({rows.length})
      </h3>
      <p className="text-xs text-muted-foreground mb-3">
        Nie proponuj tego kandydata ponownie tym osobom — rozmawiały z nim i go
        odrzuciły.
      </p>
      <ul className="space-y-2">
        {rows.map((v) => (
          <li
            key={v.hiring_manager_contact_id}
            className="rounded-md border border-border dark:border-border bg-muted dark:bg-card/40 px-3 py-2 text-sm"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-foreground dark:text-foreground">
                {v.hiring_manager_name ?? "Nieznany hiring manager"}
              </span>
              <span className="text-xs text-muted-foreground shrink-0">
                {formatDate(v.rejected_at)}
              </span>
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              Powód: {v.rejection_reason_name}
            </div>
            {v.rejection_note && (
              <div className="text-xs text-muted-foreground mt-0.5 italic">
                {v.rejection_note}
              </div>
            )}
            <Link
              href={`/jobs/${v.source_job_id}`}
              className="text-xs text-primary hover:underline mt-1 inline-block"
            >
              {v.source_job_title ?? `Rekrutacja #${v.source_job_id}`}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default HiringManagerVetoesWidget;
