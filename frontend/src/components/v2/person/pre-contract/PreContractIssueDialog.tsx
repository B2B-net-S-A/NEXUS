"use client";

/**
 * „Wystaw umowę” z panelu osoby (0504) — ten sam formularz i ten sam wiersz
 * co Generator dokumentów (rodzina „preliminary”), z ustaloną parą
 * (kandydat + rekrutacja). Po zapisie DOCX pobiera się, a dokument od razu
 * podpina się do prośby. Wzór dobiera serwer po kliencie rekrutacji
 * (`/documents/preliminary-options`); bez tej trasy — wszystkie wzory
 * przedwstępnej, a niepasujący serwer odrzuci z czytelnym zdaniem.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";

import { AppModal } from "@/components/ds/AppModal";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { DocumentFieldsForm } from "@/components/v2/b2b-generator/documents/DocumentFieldsForm";
import { saveDocx } from "@/components/v2/b2b-generator/documents/DocumentDialogs";
import api from "@/lib/api";
import {
  b2bDocumentsApi,
  useDocumentTypes,
  type DocumentTypeDef,
  type DocumentValue,
  type DocumentValues,
} from "@/lib/api/b2bDocuments";
import { preContractsApi, type PreContractRequest } from "@/lib/api/preContracts";
import { buildDocumentRequest, missingRequired, readDocumentError } from "@/lib/b2b-documents";

interface PreliminaryOptions {
  types: string[];
}

async function loadOptions(candidateId: number, jobId: number): Promise<string[] | null> {
  try {
    const res = await api.get<PreliminaryOptions | { types: { key: string }[] }>(
      "/api/b2b-generator/documents/preliminary-options",
      { params: { candidate_id: candidateId, job_id: jobId } },
    );
    const types = (res.data as { types?: unknown }).types;
    if (!Array.isArray(types)) return null;
    return types
      .map((t) => (typeof t === "string" ? t : (t as { key?: string })?.key))
      .filter((k): k is string => typeof k === "string");
  } catch {
    // Trasa przychodzi z PR-em wzorów — do tego czasu pokazujemy wszystkie.
    return null;
  }
}

export function PreContractIssueDialog({
  open,
  onOpenChange,
  request,
  onDone,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  request: PreContractRequest;
  onDone: (request: PreContractRequest) => void;
}) {
  const { showError, showSuccess } = useToast();
  const types = useDocumentTypes();
  const options = useQuery({
    queryKey: ["pre-contract", "options", request.candidate_id, request.job_id],
    queryFn: () => loadOptions(request.candidate_id, request.job_id),
    enabled: open,
    staleTime: 5 * 60_000,
  });
  const preliminary = useMemo<DocumentTypeDef[]>(() => {
    const all = (types.data?.types ?? []).filter((t) => t.family === "preliminary");
    const allowed = options.data;
    return allowed ? all.filter((t) => allowed.includes(t.key)) : all;
  }, [types.data, options.data]);
  const [typeKey, setTypeKey] = useState<string | null>(null);
  const type = preliminary.find((t) => t.key === typeKey) ?? preliminary[0] ?? null;

  const prefill = useQuery({
    queryKey: ["pre-contract", "prefill", type?.key, request.candidate_id, request.job_id],
    queryFn: () =>
      b2bDocumentsApi.prefill({
        documentType: (type as DocumentTypeDef).key,
        candidateId: request.candidate_id,
        jobId: request.job_id,
      }),
    enabled: open && type != null,
  });
  const [values, setValues] = useState<DocumentValues>({});
  const [errors, setErrors] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (prefill.data) setValues({ ...prefill.data.values });
  }, [prefill.data]);

  const onChange = (key: string, value: DocumentValue) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => {
      if (!prev.has(key)) return prev;
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  };

  const submit = async () => {
    if (!type) return;
    const missing = missingRequired(type, values);
    if (missing.length) {
      const keys = new Set(type.fields.filter((f) => missing.includes(f.label)).map((f) => f.key));
      setErrors(keys);
      showError(`Uzupełnij: ${missing.join(", ")}.`);
      return;
    }
    setBusy(true);
    try {
      const body = buildDocumentRequest({
        type,
        language: prefill.data?.default_language ?? "pl",
        subject: { candidateId: request.candidate_id, jobId: request.job_id },
        values,
        needsRefs: false,
      });
      const res = await b2bDocumentsApi.create(body);
      saveDocx(res as { data: unknown; headers: Record<string, unknown> }, `${type.label}.docx`);
      const docId = Number((res.headers as Record<string, unknown>)["x-document-id"]);
      if (Number.isFinite(docId) && docId > 0) {
        const linked = await preContractsApi.linkDocument(request.id, docId);
        onDone(linked);
      }
      showSuccess("Umowa wystawiona i pobrana. Wyślij ją kandydatowi i oznacz jako wysłaną.");
      onOpenChange(false);
    } catch (e) {
      const err = await readDocumentError(e, "Nie udało się wystawić umowy.");
      showError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const loading = types.isLoading || options.isLoading || (type != null && prefill.isLoading);

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      size="lg"
      title="Wystaw umowę przedwstępną"
      description={`${request.candidate_name} · ${request.job_title}${
        request.requested_by ? ` · prośba: ${request.requested_by.name}, ${request.needed_before_label}` : ""
      }`}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={() => void submit()} disabled={busy || loading || !type} data-testid="pre-contract-issue-save">
            {busy ? <Loader2 className="mr-1 h-4 w-4 animate-spin" aria-hidden /> : null}
            Wystaw i pobierz DOCX
          </Button>
        </>
      }
    >
      {loading ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          Wczytuję wzór umowy…
        </p>
      ) : types.isError || prefill.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Nie udało się wczytać wzoru umowy.{" "}
          <button type="button" className="font-medium underline" onClick={() => void (types.isError ? types.refetch() : prefill.refetch())}>
            Ponów
          </button>
        </p>
      ) : !type ? (
        <p className="text-sm text-muted-foreground">Dla tego klienta nie ma wzoru umowy przedwstępnej.</p>
      ) : (
        <div className="space-y-4">
          {preliminary.length > 1 ? (
            <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="Wzór umowy">
              {preliminary.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  role="radio"
                  aria-checked={t.key === type.key}
                  onClick={() => setTypeKey(t.key)}
                  className={
                    t.key === type.key
                      ? "rounded-md border border-primary bg-primary/10 px-3 py-1.5 text-sm font-medium text-primary"
                      : "rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
                  }
                >
                  {t.label}
                </button>
              ))}
            </div>
          ) : (
            <p className="text-sm font-medium">{type.label}</p>
          )}
          <p className="rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground">
            Dane wrażliwe (PESEL, dowód, adres) trafiają tylko do pliku — NEXUS ich nie zapisuje.
            Kandydat może podpisać, jak mu wygodnie: profilem zaufanym, podpisem osobistym,
            kwalifikowanym albo odręcznie (skan).
          </p>
          <DocumentFieldsForm type={type} values={values} onChange={onChange} errorKeys={errors} idPrefix="pre-contract" />
        </div>
      )}
    </AppModal>
  );
}
