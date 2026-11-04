"use client";

// „Oświadczenia i deklaracje” do umowy zlecenie (21.10.2026): puste wzory
// z SharePointa Administracji do wysłania zleceniobiorcy razem z umową.
// Wypełnia je zleceniobiorca (PESEL, konto, dowód), więc NEXUS ich nie
// generuje ani nie zapisuje — tylko wydaje plik
// (`backend/app/services/b2b_documents/mandate_forms.py`).

import { useMutation } from "@tanstack/react-query";
import { Download, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { useToast } from "@/components/Toast";
import { b2bDocumentsApi, type MandateFormDef } from "@/lib/api/b2bDocuments";
import { readDocumentError } from "@/lib/b2b-documents";

import { saveDocx } from "./DocumentDialogs";

export function MandateFormsSection({ forms }: { forms: MandateFormDef[] }) {
  const toast = useToast();
  const download = useMutation({
    mutationFn: async (form: MandateFormDef) => {
      const res = await b2bDocumentsApi.mandateForm(form.key);
      saveDocx(
        res as { data: unknown; headers: Record<string, unknown> },
        form.download_name,
      );
    },
    onError: async (e) => {
      const parsed = await readDocumentError(e, "Nie udało się pobrać wzoru.");
      toast.showError(parsed.message);
    },
  });

  if (!forms.length) return null;
  return (
    <section className="space-y-2" aria-labelledby="mandate-forms-heading">
      <div>
        <h3 id="mandate-forms-heading" className="text-sm font-semibold text-foreground">
          Oświadczenia i deklaracje — umowa zlecenie
        </h3>
        <p className="text-xs text-muted-foreground">
          Puste wzory do wysłania zleceniobiorcy razem z umową. Wypełnia je
          zleceniobiorca — NEXUS ich nie zapisuje.
        </p>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {forms.map((form) => {
          const pending = download.isPending && download.variables?.key === form.key;
          return (
            <button
              key={form.key}
              type="button"
              disabled={pending}
              onClick={() => download.mutate(form)}
              aria-label={`Pobierz: ${form.label} (${form.format})`}
              className="flex h-full flex-col items-start gap-1 rounded-lg border border-border bg-card p-3 text-left transition-colors hover:bg-muted disabled:opacity-60"
            >
              <span className="flex w-full items-center gap-2 text-sm font-medium text-foreground">
                {pending ? (
                  <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" aria-hidden="true" />
                ) : (
                  <Download className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                )}
                <span className="min-w-0 flex-1">{form.label}</span>
                <Badge variant="neutral" size="sm" className="shrink-0">
                  {form.format}
                </Badge>
              </span>
              <span className="text-xs text-muted-foreground">{form.description}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}
