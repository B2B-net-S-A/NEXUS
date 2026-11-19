"use client";
// Dwie małe karty Przeglądu kontraktu (przebudowa 19.11.2026, wariant A):
// ostatnie zmiany wprowadzone ręcznie (bez synchronizacji i migracji) i
// najnowsze dokumenty — z przejściem do pełnych zakładek.
import { ArrowRight, FileText } from "lucide-react";
import { fmtDatePl } from "@/lib/contract-happening";
import { humanizeActivity, personFromEmail, type ContractActivity } from "@/lib/contract-history";

const DOC_TYPE: Record<string, string> = { contract: "Umowa", annex: "Aneks", order: "Zamówienie", nda: "NDA", other: "Inny" };

function Card({ title, link, children }: { title: string; link: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card p-4 shadow-xs">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 className="text-[13.5px] font-semibold text-foreground">{title}</h2>
        {link}
      </div>
      {children}
    </section>
  );
}

function MoreLink({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className="inline-flex items-center gap-1 text-[12.5px] font-medium text-primary hover:underline">
      {children} <ArrowRight className="size-3.5" aria-hidden />
    </button>
  );
}

export function ContractRecentActivity({ activities, onOpenHistory }: { activities: ContractActivity[]; onOpenHistory: () => void }) {
  const recent = activities.map(humanizeActivity).filter((e) => !e.automatic).slice(0, 4);
  return (
    <Card title="Ostatnio" link={<MoreLink onClick={onOpenHistory}>Cała historia</MoreLink>}>
      {recent.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">Bez zmian wprowadzonych ręcznie.</p>
      ) : (
        <ol className="space-y-2">
          {recent.map((e) => (
            <li key={e.id} className="grid grid-cols-[78px_minmax(0,1fr)] gap-3 text-[13px] leading-5">
              <span className="tabular-nums text-muted-foreground">{fmtDatePl(e.at)}</span>
              <span className="min-w-0">
                <span className="text-foreground">{e.title}</span>
                <span className="block truncate text-[12px] text-muted-foreground">
                  {[e.detail, e.who].filter(Boolean).join(" · ")}
                </span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

export interface RecentDocument {
  id: number;
  filename: string;
  doc_type?: string | null;
  created_at?: string | null;
  uploaded_by_email?: string | null;
}

export function ContractRecentDocuments({ documents, onOpenDocuments }: { documents: RecentDocument[]; onOpenDocuments: () => void }) {
  const latest = [...documents].sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? "")).slice(0, 4);
  return (
    <Card title="Dokumenty" link={<MoreLink onClick={onOpenDocuments}>Wszystkie ({documents.length})</MoreLink>}>
      {latest.length === 0 ? (
        <p className="text-[13px] text-muted-foreground">Brak dokumentów — dodaj podpisaną umowę.</p>
      ) : (
        <ul className="space-y-2">
          {latest.map((d) => (
            <li key={d.id} className="flex items-start gap-2 text-[13px] leading-5">
              <FileText className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-foreground" title={d.filename}>
                  {d.filename}
                </span>
                <span className="block text-[12px] text-muted-foreground">
                  {[DOC_TYPE[d.doc_type ?? ""] ?? "Dokument", d.created_at ? `dodano ${fmtDatePl(d.created_at)}` : null, personFromEmail(d.uploaded_by_email)]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
