"use client";

// Finanse → Rozliczenia → lista miesiąca: potwierdzenie usług dla klienta,
// jeden dokument na projekt (roadmapa E6.2, reguła `cl.client_document`).
// PDF bez nazwisk składa NEXUS z Time Sheet osób; przy estymacji z planu.
import { Download } from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadBlob } from "@/lib/authenticated-files";
import { fetchClientDocument, useClientDocuments, type ClientDocumentProject } from "@/lib/api/client-settlements";

import { mdText, monthLabel } from "./format";

function peopleText(p: ClientDocumentProject): string {
  const people = p.people === 1 ? "1 osoba" : p.people < 5 ? `${p.people} osoby` : `${p.people} osób`;
  return `${people}, przyjęte ${p.accepted} z ${p.people}`;
}

export function ClientDocumentsPanel({ clientId, month }: { clientId: number; month: string }) {
  const query = useClientDocuments(clientId, month);
  const { showError } = useToast();

  if (query.isError) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(query.error, "Nie udało się pobrać dokumentów dla klienta.")}
        onRetry={() => query.refetch()}
      />
    );
  }
  if (!query.isSuccess || !query.data.enabled) return null;
  const data = query.data;

  async function onDownload(project: string) {
    try {
      const blob = await fetchClientDocument(clientId, month, project);
      downloadBlob(blob, `SDC_${project.replace(/[^A-Za-z0-9.-]+/g, "_")}_${month}.pdf`);
    } catch (error) {
      showError(apiErrorMessage(error, "Nie udało się pobrać dokumentu."));
    }
  }

  return (
    <section aria-label={data.kind} className="rounded-xl border bg-card px-3 py-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold">
          {data.kind} za {monthLabel(month)}
          {data.stage === "FORECAST" ? <span className="ml-1.5 font-normal text-muted-foreground">z planu (estymacja)</span> : null}
        </h2>
        <p className="text-xs text-muted-foreground">Jeden PDF na projekt, bez nazwisk. Godziny z Time Sheet, MD = godziny / 8.</p>
      </div>
      {data.projects.length === 0 ? (
        <p className="mt-2 text-xs text-muted-foreground">Nikt jeszcze nie przysłał Time Sheet w Excelu za ten miesiąc.</p>
      ) : (
        <ul className="mt-1 grid gap-x-6 sm:grid-cols-2">
          {data.projects.map((p) => (
            <li key={p.project} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 border-t py-1 text-[13px]">
              <span className="min-w-20 font-medium">{p.project}</span>
              <span className="text-xs text-muted-foreground">{peopleText(p)}</span>
              <span className="tabular-nums">
                {mdText(p.hours)} h · {mdText(p.md)} MD
              </span>
              <button
                type="button"
                onClick={() => onDownload(p.project)}
                title={p.order_numbers.join(", ") || "bez numeru zamówienia"}
                className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline pointer-coarse:min-h-9"
                aria-label={`Pobierz PDF: ${p.project}`}
              >
                <Download aria-hidden className="size-3.5" /> PDF
              </button>
            </li>
          ))}
        </ul>
      )}
      {data.skipped.length > 0 ? (
        <p className="mt-1.5 text-xs text-warning-muted-foreground">
          Poza dokumentem: {data.skipped.map((s) => `${s.person} (${s.reason.toLowerCase()})`).join(", ")}.
        </p>
      ) : null}
    </section>
  );
}
