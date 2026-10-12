"use client";

/**
 * „Kontrola przed skopiowaniem”: znaleziska blokujące (nazwa klienta, kwota,
 * kontakt, nazwisko) i doradcze. Blokujące wyłączają kopiowanie w całym oknie.
 */

import { AlertTriangle, Ban } from "lucide-react";

import { Button } from "@/components/ui/button";
import { advisoryFindings, blockingFindings, type AdFinding } from "@/lib/api/jobAd";
import { cn } from "@/lib/utils";

import { isEditKey } from "./job-ad-edit";

interface AdChecksPanelProps {
  findings: AdFinding[];
  busy: boolean;
  /** Przewija do pola ogłoszenia, którego dotyczy znalezisko. */
  onShow: (field: string) => void;
  onRemove: (finding: AdFinding) => void;
}

function FindingRow({
  finding,
  busy,
  onShow,
  onRemove,
}: {
  finding: AdFinding;
  busy: boolean;
  onShow: (field: string) => void;
  onRemove: (finding: AdFinding) => void;
}) {
  const blocking = finding.severity === "block";
  const inAd = isEditKey(finding.field);
  return (
    <li
      role={blocking ? "alert" : undefined}
      className={cn(
        "flex flex-col gap-1.5 rounded-md border px-2.5 py-2 text-[13px] leading-snug",
        blocking
          ? "border-destructive/20 bg-destructive-muted text-destructive-muted-foreground"
          : "border-warning/25 bg-warning-muted text-warning-muted-foreground",
      )}
    >
      <span>{finding.message}</span>
      {inAd ? (
        <span className="flex flex-wrap gap-x-3">
          <Button
            type="button"
            size="sm"
            variant="tertiary"
            className="h-auto p-0"
            onClick={() => onShow(finding.field as string)}
          >
            Pokaż
          </Button>
          {finding.excerpt ? (
            <Button
              type="button"
              size="sm"
              variant="tertiary"
              className="h-auto p-0"
              disabled={busy}
              onClick={() => onRemove(finding)}
            >
              Usuń fragment
            </Button>
          ) : null}
        </span>
      ) : null}
    </li>
  );
}

export function AdChecksPanel({ findings, busy, onShow, onRemove }: AdChecksPanelProps) {
  const blocking = blockingFindings(findings);
  const advisory = advisoryFindings(findings);
  return (
    <aside
      aria-label="Kontrola przed skopiowaniem"
      className="flex w-[320px] flex-none flex-col gap-3 overflow-y-auto border-l border-border bg-card px-4 py-3"
    >
      <h2 className="text-sm font-semibold text-foreground">Kontrola przed skopiowaniem</h2>
      {blocking.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-destructive">
            <Ban className="h-3.5 w-3.5" aria-hidden="true" />
            Do usunięcia — {blocking.length}
          </p>
          <ul className="flex flex-col gap-2" data-testid="job-ad-blocking">
            {blocking.map((finding, index) => (
              <FindingRow
                key={`${finding.code}-${index}`}
                finding={finding}
                busy={busy}
                onShow={onShow}
                onRemove={onRemove}
              />
            ))}
          </ul>
        </div>
      ) : null}
      {advisory.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-warning-muted-foreground">
            <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
            Warto poprawić — {advisory.length}
          </p>
          <ul className="flex flex-col gap-2" data-testid="job-ad-advisory">
            {advisory.map((finding, index) => (
              <FindingRow
                key={`${finding.code}-${index}`}
                finding={finding}
                busy={busy}
                onShow={onShow}
                onRemove={onRemove}
              />
            ))}
          </ul>
        </div>
      ) : null}
    </aside>
  );
}
