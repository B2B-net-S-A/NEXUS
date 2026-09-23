"use client";

/**
 * „Portale ogłoszeniowe" rekrutacji — lista publikacji i okno „Opublikuj".
 *
 * Wyniesione 1:1 z lokalnych `PostingsSection` + `PublishModal` w
 * `app/jobs/[id]/page.tsx` (widok „jedna tabela", 09.2026): dawna zakładka
 * `?tab=portals` staje się rozwijaną sekcją okna „Zlecenie", a komponent
 * lokalny dla strony nie dał się zaimportować. Zachowanie celowo BEZ zmian (łącznie z notką o symulowanych danych) — to
 * przeniesienie, nie przebudowa. Jedyna różnica: kolory zapisane na sztywno
 * (`green-100`, `amber-50`, `black/40`…) przeszły na tokeny.
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Globe, Plus, Radio } from "lucide-react";

import { DeleteButton } from "@/components/ConfirmDialog";
import { postingsApi } from "@/lib/api";
import { formatDate } from "@/lib/utils";


// ── Types ─────────────────────────────────────────────────────────────────────

type Portal = "pracuj_pl" | "justjoinit" | "linkedin" | "nofluffjobs" | "bulldogjob";
type PostingStatus = "draft" | "published" | "expired" | "removed";

interface JobPosting {
  id: number;
  job_id: number;
  portal: Portal;
  external_id: string | null;
  status: PostingStatus;
  published_at: string | null;
  expires_at: string | null;
  url: string | null;
  views: number;
  applications: number;
}

// ── Portal config ─────────────────────────────────────────────────────────────

// Kropki portali to kolory KATEGORII (rozróżnienie pięciu serii), nie marek —
// stąd tokeny `chart-*`, które przeżywają zmianę palety i tryb ciemny.
const PORTAL_CONFIG: Record<Portal, { label: string; dotColor: string }> = {
  pracuj_pl:   { label: "Pracuj.pl",   dotColor: "bg-chart-1" },
  justjoinit:  { label: "JustJoinIT",  dotColor: "bg-chart-2" },
  linkedin:    { label: "LinkedIn",    dotColor: "bg-chart-3" },
  nofluffjobs: { label: "NoFluffJobs", dotColor: "bg-chart-4" },
  bulldogjob:  { label: "BulldogJob",  dotColor: "bg-chart-5" },
};

const ALL_PORTALS: Portal[] = ["pracuj_pl", "justjoinit", "linkedin", "nofluffjobs", "bulldogjob"];

const STATUS_CONFIG: Record<PostingStatus, { label: string; className: string }> = {
  draft:     { label: "Szkic",       className: "bg-muted text-muted-foreground" },
  published: { label: "Aktywne",     className: "bg-success-muted text-success-muted-foreground" },
  expired:   { label: "Wygasłe",     className: "bg-destructive/15 text-destructive" },
  removed:   { label: "Usunięte",    className: "bg-muted text-muted-foreground" },
};

// ── Publish Modal ─────────────────────────────────────────────────────────────

function PublishModal({
  jobId,
  onClose,
  existingPortals,
}: {
  jobId: number;
  onClose: () => void;
  existingPortals: Portal[];
}) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Portal[]>([]);
  const [expiresDays, setExpiresDays] = useState(30);

  const publishMutation = useMutation({
    mutationFn: (portals: Portal[]) =>
      postingsApi.publishAll(jobId, { portals, expires_days: expiresDays }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["postings", jobId] });
      queryClient.invalidateQueries({ queryKey: ["postings-stats"] });
      onClose();
    },
  });

  const toggle = (p: Portal) =>
    setSelected((prev) => (prev.includes(p) ? prev.filter((x) => x !== p) : [...prev, p]));

  const activePortals = existingPortals;

  return (
    <div className="fixed inset-0 bg-foreground/40 z-50 flex items-center justify-center p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="publish-posting-title"
        className="bg-card rounded-xl shadow-xl w-full max-w-md max-h-[90dvh] overflow-y-auto p-4 sm:p-6"
      >
        <h2 id="publish-posting-title" className="text-lg font-bold mb-1">
          Opublikuj ogłoszenie
        </h2>
        <p className="text-sm text-warning-muted-foreground bg-warning-muted border border-warning/25 rounded-lg px-3 py-2 mb-4">
          ⚠️ Integracja z portalami w przygotowaniu — dane symulowane
        </p>

        <div className="space-y-2 mb-4">
          {ALL_PORTALS.map((p) => {
            const config = PORTAL_CONFIG[p];
            const isActive = activePortals.includes(p);
            const isSelected = selected.includes(p);
            return (
              <label
                key={p}
                className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                  isActive
                    ? "opacity-50 cursor-not-allowed border-border bg-muted"
                    : isSelected
                    ? "border-primary/30 bg-primary/10"
                    : "border-border hover:border-border"
                }`}
              >
                <input
                  type="checkbox"
                  checked={isSelected}
                  disabled={isActive}
                  onChange={() => !isActive && toggle(p)}
                  className="accent-primary"
                />
                <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${config.dotColor}`} />
                <span className="text-sm font-medium">{config.label}</span>
                {isActive && (
                  <span className="ml-auto text-xs text-success font-medium">Już aktywne</span>
                )}
              </label>
            );
          })}
        </div>

        <div className="flex items-center gap-3 mb-5">
          <label className="text-sm text-muted-foreground whitespace-nowrap">Czas trwania:</label>
          <select
            className="text-sm border border-border rounded-lg px-3 py-1.5"
            value={expiresDays}
            onChange={(e) => setExpiresDays(Number(e.target.value))}
          >
            <option value={14}>14 dni</option>
            <option value={30}>30 dni</option>
            <option value={60}>60 dni</option>
            <option value={90}>90 dni</option>
          </select>
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => onClose()}
            className="flex-1 px-4 py-2 text-sm border border-border rounded-lg hover:bg-muted"
          >
            Anuluj
          </button>
          <button
            onClick={() => selected.length > 0 && publishMutation.mutate(selected)}
            disabled={selected.length === 0 || publishMutation.isPending}
            className="flex-1 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {publishMutation.isPending ? "Publikowanie..." : `Publikuj (${selected.length})`}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Postings Section ──────────────────────────────────────────────────────────

export function PostingsSection({
  jobId,
  readOnly = false,
}: {
  jobId: number;
  readOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const [showModal, setShowModal] = useState(false);

  const { data: postings = [], isLoading } = useQuery<JobPosting[]>({
    queryKey: ["postings", jobId],
    queryFn: () => postingsApi.list(jobId).then((r) => r.data),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => postingsApi.delete(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["postings", jobId] });
      queryClient.invalidateQueries({ queryKey: ["postings-stats"] });
    },
  });

  const publishAllMutation = useMutation({
    mutationFn: () =>
      postingsApi.publishAll(jobId, { portals: ALL_PORTALS, expires_days: 30 }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["postings", jobId] });
      queryClient.invalidateQueries({ queryKey: ["postings-stats"] });
    },
  });

  const activePortals = postings
    .filter((p) => p.status === "published")
    .map((p) => p.portal);

  if (isLoading) return <div className="text-muted-foreground text-sm">Ładowanie publikacji...</div>;

  return (
    <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <Globe className="w-5 h-5 text-primary" />
          <h2 className="text-lg font-semibold">Portale ogłoszeniowe</h2>
          <span className="text-xs text-muted-foreground ml-1">({postings.length})</span>
        </div>
        {!readOnly ? <div className="flex gap-2">
          <button
            onClick={() => publishAllMutation.mutate()}
            disabled={publishAllMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-border rounded-lg hover:bg-muted text-muted-foreground disabled:opacity-50"
          >
            <Radio className="w-3.5 h-3.5" />
            Publikuj na wszystkich
          </button>
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-primary text-primary-foreground rounded-lg hover:bg-primary/90"
          >
            <Plus className="w-3.5 h-3.5" />
            Opublikuj ogłoszenie
          </button>
        </div> : null}
      </div>

      {/* Simulation notice */}
      <div className="text-xs text-warning-muted-foreground bg-warning-muted border border-warning/25 rounded-lg px-3 py-2 mb-4">
        ⚠️ Integracja z portalami w przygotowaniu — dane symulowane
      </div>

      {/* Table */}
      {postings.length === 0 ? (
        <div className="text-center py-8 text-muted-foreground">
          <Globe className="w-10 h-10 mx-auto mb-2 opacity-30" />
          <p className="text-sm">
            {readOnly
              ? "Brak publikacji."
              : "Brak publikacji. Opublikuj ogłoszenie na portalach rekrutacyjnych."}
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border dark:border-border">
                <th className="text-left py-2 px-3 text-muted-foreground font-medium">Portal</th>
                <th className="text-left py-2 px-3 text-muted-foreground font-medium">Status</th>
                <th className="text-left py-2 px-3 text-muted-foreground font-medium">Data publ.</th>
                <th className="text-left py-2 px-3 text-muted-foreground font-medium">Wygaśnięcie</th>
                <th className="text-right py-2 px-3 text-muted-foreground font-medium">Wyświetlenia</th>
                <th className="text-right py-2 px-3 text-muted-foreground font-medium">Aplikacje</th>
                <th className="text-center py-2 px-3 text-muted-foreground font-medium">Link</th>
                {!readOnly ? (
                  <th className="text-center py-2 px-3 text-muted-foreground font-medium">Akcje</th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {postings.map((posting) => {
                const portalCfg = PORTAL_CONFIG[posting.portal];
                const statusCfg = STATUS_CONFIG[posting.status];
                return (
                  <tr key={posting.id} className="border-b border-border/50 hover:bg-muted">
                    <td className="py-2.5 px-3">
                      <div className="flex items-center gap-2">
                        <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${portalCfg.dotColor}`} />
                        <span className="font-medium">{portalCfg.label}</span>
                      </div>
                    </td>
                    <td className="py-2.5 px-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${statusCfg.className}`}>
                        {statusCfg.label}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-muted-foreground">
                      {posting.published_at ? formatDate(posting.published_at) : "—"}
                    </td>
                    <td className="py-2.5 px-3 text-muted-foreground">
                      {posting.expires_at ? formatDate(posting.expires_at) : "—"}
                    </td>
                    <td className="py-2.5 px-3 text-right font-medium">
                      {posting.views.toLocaleString()}
                    </td>
                    <td className="py-2.5 px-3 text-right font-medium text-primary">
                      {posting.applications}
                    </td>
                    <td className="py-2.5 px-3 text-center">
                      {posting.url ? (
                        <a
                          href={posting.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={`Otwórz ogłoszenie na ${portalCfg.label} w nowej karcie`}
                          className="text-primary hover:text-primary/80 inline-flex items-center gap-1"
                        >
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    {!readOnly ? (
                      <td className="py-2.5 px-3 text-center">
                        <DeleteButton onConfirm={() => deleteMutation.mutate(posting.id)} />
                      </td>
                    ) : null}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Publish modal */}
      {!readOnly && showModal && (
        <PublishModal
          jobId={jobId}
          existingPortals={activePortals}
          onClose={() => setShowModal(false)}
        />
      )}
    </div>
  );
}
