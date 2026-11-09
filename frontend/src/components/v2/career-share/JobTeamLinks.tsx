"use client";

/**
 * Kto z zespołu ma link do tej rekrutacji i co przyniósł (makieta C,
 * https://claude.ai/artifact/BcevDUToiG7AGHfgY86T5P). Trasa stoi za rolami
 * admin, Head of Recruitment i Delivery Lead — rekruter widzi tylko swoje wyniki.
 */

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { type JobTeamLink, useJobTeamLinks } from "@/lib/api/careerLinks";
import { hasRole, useAuthStore } from "@/store/auth";

const STATE_LABEL: Partial<Record<JobTeamLink["state"], string>> = {
  expired: "wygasł",
  revoked: "wycofany",
};

function originLabel(label: string | null): string {
  return label || "Własny link";
}

export function JobTeamLinks({ enabled, jobId }: { enabled: boolean; jobId: number | null }) {
  const me = useAuthStore((s) => s.user);
  const canSee = hasRole(me, "admin", "head_of_recruitment", "delivery_lead");
  const query = useJobTeamLinks(enabled && canSee, jobId);

  if (!canSee || jobId == null) return null;
  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się wczytać linków zespołu do tej rekrutacji."
        onRetry={() => query.refetch()}
      />
    );
  }
  const rows = query.data ?? [];
  if (rows.length === 0) return null;
  const visits = rows.reduce((sum, row) => sum + row.visits, 0);
  const applications = rows.reduce((sum, row) => sum + row.applications, 0);

  return (
    <section className="space-y-2" aria-labelledby="job-team-links-heading" data-testid="job-team-links">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 id="job-team-links-heading" className="text-sm font-semibold text-foreground">
          Linki do tej rekrutacji w zespole
        </h3>
        <span className="text-xs text-muted-foreground tabular-nums">
          {visits} wejść · {applications} zgłoszeń
        </span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Czyj link</th>
              <th className="px-3 py-2 text-left font-medium">Skąd się wziął</th>
              <th className="px-3 py-2 text-right font-medium">Wejścia</th>
              <th className="px-3 py-2 text-right font-medium">Zgłoszenia</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.slug ?? `${row.owner_id}-${row.created_at}`} className="border-t border-border">
                <td className="px-3 py-2 font-medium text-foreground">
                  {row.owner_name}
                  {row.owner_id === me?.id ? (
                    <span className="ml-1 text-xs font-normal text-muted-foreground">(Ty)</span>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-muted-foreground">
                  {originLabel(row.label)}
                  {STATE_LABEL[row.state] ? (
                    <Badge size="sm" variant="neutral" className="ml-1.5">
                      {STATE_LABEL[row.state]}
                    </Badge>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{row.visits}</td>
                <td className="px-3 py-2 text-right tabular-nums">{row.applications}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
