"use client";

// Kreator „Nowy dokument”: typ → umowa bazowa (albo kandydat i rekrutacja
// przy umowie przedwstępnej) → formularz z definicji pól → podgląd / DOCX.
// Umowę przedwstępną wybiera klient rekrutacji (`/preliminary-options`):
// Centrum e-Zdrowia — własny wzór, inni klienci — umowa o udziale w procesie
// rekrutacyjnym (kandydat z działalnością albo osoba fizyczna, 21.10.2026).
// Ten sam komponent obsługuje „Popraw” z listy (ten sam wiersz, `/rerender`)
// i zakładkę „Generator aneksów” (`mode="annexes"`: tylko aneksy). Podmiot
// aneksu wybiera jedno wyszukiwanie osoby (`AnnexSubjectPicker`): umowa
// z rejestru albo kontrakt bez umowy w rejestrze — każdy aneks jest
// zapisywany i ma kontrakt (13.10.2026).

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  Eye,
  FileText,
  Loader2,
  Search,
} from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/Toast";
import { b2bGeneratorApi, type B2BGeneratedContractRow } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  B2B_DOCUMENTS_KEY,
  b2bDocumentsApi,
  b2bDocumentsKeys,
  type DocumentTypeDef,
  type DocumentTypesResponse,
  type DocumentValue,
  type DocumentValues,
} from "@/lib/api/b2bDocuments";
import {
  LANGUAGE_LABELS,
  buildDocumentRequest,
  createdInAnnexGenerator,
  fieldKeysForLabels,
  invalidListFields,
  invalidMoneyFields,
  missingRequired,
  paragraphAfterVariantChange,
  readDocumentError,
  typesByFamily,
  type PartnerVariant,
} from "@/lib/b2b-documents";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";

import {
  AnnexSubjectPicker,
  EMPTY_ANNEX_CHOICE,
  annexChoiceReady,
  choiceFromSubject,
  type AnnexSubjectChoice,
} from "./AnnexSubjectPicker";
import { DocumentFieldsForm, DocumentRefsFields } from "./DocumentFieldsForm";
import { MandateFormsSection } from "./MandateFormsSection";
import { saveDocx } from "./DocumentDialogs";

/** Etykieta braku numerów paragrafów w `missing[]` serwera. */
const REFS_MISSING_LABEL = "Numery paragrafów umowy bazowej";

type Step = "type" | "subject" | "form";

/** Podmiot dokumentu: umowa z rejestru, kontrakt aneksu albo kandydat. */
interface Subject extends AnnexSubjectChoice {
  /** Umowa zlecenie bez wiersza w rejestrze — świadomy wybór, nie brak. */
  noParent: boolean;
  candidateId: number | null;
  candidateLabel: string | null;
  jobId: number | null;
  jobLabel: string | null;
  /** Umowy przedwstępne dozwolone w wybranej rekrutacji; `null` = jeszcze nie wiadomo. */
  allowedTypes: string[] | null;
}

const EMPTY_SUBJECT: Subject = {
  ...EMPTY_ANNEX_CHOICE,
  noParent: false,
  candidateId: null,
  candidateLabel: null,
  jobId: null,
  jobLabel: null,
  allowedTypes: null,
};

/** Aneks do umowy albo kontraktu — podmiot wybiera wyszukiwanie osoby. */
function usesAnnexPicker(type: DocumentTypeDef): boolean {
  return type.family === "annex" && type.parent !== "none";
}

function subjectReady(type: DocumentTypeDef, subject: Subject): boolean {
  if (usesAnnexPicker(type)) return annexChoiceReady(type, subject);
  if (type.parent === "b2b") return subject.parentId !== null;
  if (type.parent === "mandate") return subject.parentId !== null || subject.noParent;
  return (
    subject.candidateId !== null &&
    subject.jobId !== null &&
    (subject.allowedTypes?.includes(type.key) ?? false)
  );
}

function registerRowLabel(row: B2BGeneratedContractRow): string {
  const who = row.partner_name || row.candidate_name || row.partner_display_name;
  return who ? `${row.contract_number} — ${who}` : row.contract_number;
}

export interface DocumentWizardProps {
  typesData: DocumentTypesResponse;
  initialType?: string | null;
  initialParentId?: number | null;
  initialContractId?: number | null;
  /** „Popraw” z listy — wczytuje zapisany formularz dokumentu. */
  editDocumentId?: number | null;
  /** Nadpisanie wartości startowych (harness). */
  initialValues?: DocumentValues;
  /** `annexes` = zakładka „Generator aneksów” (tylko aneksy). */
  mode?: "documents" | "annexes";
  onClose: () => void;
}

export function DocumentWizard({
  typesData,
  initialType = null,
  initialParentId = null,
  initialContractId = null,
  editDocumentId = null,
  initialValues,
  mode = "documents",
  onClose,
}: DocumentWizardProps) {
  const annexMode = mode === "annexes";
  const toast = useToast();
  const queryClient = useQueryClient();
  const typesByKey = useMemo(
    () => new Map(typesData.types.map((t) => [t.key, t])),
    [typesData],
  );
  const startType = initialType ? (typesByKey.get(initialType) ?? null) : null;
  const [typeKey, setTypeKey] = useState<string | null>(startType?.key ?? null);
  const type = typeKey ? (typesByKey.get(typeKey) ?? null) : null;
  const [subject, setSubject] = useState<Subject>({
    ...EMPTY_SUBJECT,
    parentId: initialParentId,
  });
  const [step, setStep] = useState<Step>(() => {
    if (editDocumentId) return "form";
    if (!startType) return "type";
    return initialParentId && startType.parent !== "none" ? "form" : "subject";
  });

  const [values, setValues] = useState<DocumentValues>({});
  const [refs, setRefs] = useState<Record<string, string>>({});
  const [language, setLanguage] = useState("pl");
  const [initializedFor, setInitializedFor] = useState<string | null>(null);
  const [errorKeys, setErrorKeys] = useState<Set<string>>(new Set());
  const [refsError, setRefsError] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [previewMissing, setPreviewMissing] = useState<string[]>([]);
  const [savedId, setSavedId] = useState<number | null>(editDocumentId);

  // ── Podmiot z kontraktu (`?contract=`, wejście z modułu Kontrakty) ───────
  // Umowa tego kontraktu w rejestrze albo — dla aneksu — sam kontrakt, gdy
  // umowy w rejestrze nie ma. Pyta trasę generatora (do 13.10.2026 kreator
  // czytał kontrakt z modułu Kontrakty i bez wglądu w Delivery dostawał 403).
  const byContract = useQuery({
    queryKey: b2bDocumentsKeys.subjects(type?.key ?? "", "", initialContractId),
    queryFn: async () => {
      const subjects = await b2bDocumentsApi.subjects({
        documentType: type!.key,
        contractId: initialContractId,
      });
      return subjects[0] ?? null;
    },
    enabled:
      Boolean(initialContractId) &&
      type !== null &&
      type.parent !== "none" &&
      !initialParentId &&
      !editDocumentId,
    staleTime: 30_000,
  });
  useEffect(() => {
    const found = byContract.data;
    if (!found) return;
    const choice = choiceFromSubject(found);
    setSubject((prev) =>
      prev.parentId || prev.contractId ? prev : { ...prev, ...choice },
    );
    // Kilka kontraktów do wyboru zostawia człowieka w kroku wyboru.
    if (!choice.needsContractPick) {
      setStep((prev) => (prev === "subject" ? "form" : prev));
    }
  }, [byContract.data]);

  // ── Zapisany dokument („Popraw”) ─────────────────────────────────────────
  const savedForm = useQuery({
    queryKey: [B2B_DOCUMENTS_KEY, "form", editDocumentId ?? 0],
    queryFn: () => b2bDocumentsApi.form(editDocumentId as number),
    enabled: Boolean(editDocumentId),
    staleTime: 0,
  });
  useEffect(() => {
    const form = savedForm.data;
    if (!form) return;
    setTypeKey(form.document_type);
    const withoutParent = form.parent_generated_contract_id === null;
    setSubject((prev) => ({
      ...prev,
      parentId: form.parent_generated_contract_id,
      parentLabel: form.base?.contract_number ?? prev.parentLabel,
      noParent: withoutParent,
      // Aneks bez umowy w rejestrze: kontrakt i klient zostają te z zapisu —
      // „Popraw” zmienia treść, nie podmiot.
      contractId: withoutParent ? (form.contract_id ?? null) : null,
      contractLabel:
        withoutParent && form.contract_id ? `Kontrakt #${form.contract_id}` : null,
      needsContractPick: false,
      withoutContract: withoutParent && !form.contract_id,
      clientId: form.client_id ?? null,
      clientName: form.client_name ?? null,
      candidateId: form.candidate_id,
      jobId: form.job_id,
      // „Popraw” nie zmienia rodzaju dokumentu — serwer sprawdził go przy wydaniu.
      allowedTypes: [form.document_type],
    }));
  }, [savedForm.data]);

  const prefillEnabled =
    step === "form" &&
    type !== null &&
    subjectReady(type, subject) &&
    (!editDocumentId || savedForm.isSuccess);
  // Dane Partnera z kontraktu tylko dla aneksu bez umowy w rejestrze — umowa
  // z rejestru niesie własne.
  const prefillContractId =
    type && usesAnnexPicker(type) && subject.parentId === null
      ? subject.contractId
      : null;
  const prefill = useQuery({
    queryKey: b2bDocumentsKeys.prefill(
      type?.key ?? "",
      subject.parentId,
      subject.candidateId,
      subject.jobId,
      prefillContractId,
    ),
    queryFn: () =>
      b2bDocumentsApi.prefill({
        documentType: type!.key,
        parentGeneratedContractId: subject.parentId,
        candidateId: subject.candidateId,
        jobId: subject.jobId,
        contractId: prefillContractId,
      }),
    enabled: prefillEnabled,
    staleTime: 0,
  });

  // Wartości startowe raz na (typ, podmiot) — kolejny odczyt prefillu nie
  // może nadpisać tego, co użytkownik już wpisał.
  const initKey = `${type?.key}|${subject.parentId}|${prefillContractId}|${subject.withoutContract}|${subject.candidateId}|${editDocumentId}`;
  useEffect(() => {
    // Tylko w kroku formularza: wartość z cache (inny wybór umowy) nie może
    // zainicjować formularza, zanim człowiek wybierze umowę.
    if (!prefillEnabled || !prefill.data || initializedFor === initKey) return;
    const saved = editDocumentId ? savedForm.data : undefined;
    setValues({ ...prefill.data.values, ...(saved?.values ?? {}), ...(initialValues ?? {}) });
    setRefs({ ...prefill.data.ref_defaults, ...(saved?.refs ?? {}) });
    setLanguage(saved?.language ?? prefill.data.default_language);
    setInitializedFor(initKey);
    setErrorKeys(new Set());
    setFormError(null);
    setPreviewHtml(null);
    if (subject.parentId && !subject.parentLabel && prefill.data.base.contract_number) {
      setSubject((prev) => ({
        ...prev,
        parentLabel: prefill.data?.base.contract_number ?? prev.parentLabel,
      }));
    }
  }, [prefill.data, prefillEnabled, initKey, initializedFor, editDocumentId, savedForm.data, initialValues, subject.parentId, subject.parentLabel]);

  const needsRefs = prefill.data?.needs_refs ?? false;

  const requestBody = () =>
    buildDocumentRequest({
      type: type!,
      language,
      subject: {
        parentGeneratedContractId: subject.parentId,
        candidateId: type!.parent === "none" ? subject.candidateId : null,
        jobId: type!.parent === "none" ? subject.jobId : null,
        ...(usesAnnexPicker(type!)
          ? { contractId: subject.contractId, clientId: subject.clientId }
          : {}),
      },
      values,
      needsRefs,
      refs,
    });

  const validate = (): boolean => {
    if (!type) return false;
    const missing = missingRequired(type, values);
    const invalid = invalidMoneyFields(type, values);
    const listProblems = invalidListFields(type, values);
    const refsMissing =
      needsRefs && !Object.values(refs).some((v) => (v ?? "").trim() !== "");
    setErrorKeys(new Set(fieldKeysForLabels(type, [...missing, ...invalid])));
    setRefsError(refsMissing);
    const problems = [...missing, ...(refsMissing ? [REFS_MISSING_LABEL] : [])];
    if (listProblems.length) {
      setErrorKeys((prev) => {
        const next = new Set(prev);
        type.fields.filter((f) => f.kind === "rate_items").forEach((f) => next.add(f.key));
        return next;
      });
    }
    if (problems.length || invalid.length || listProblems.length) {
      setFormError(
        [
          problems.length ? `Uzupełnij: ${problems.join(", ")}.` : "",
          invalid.length ? `Popraw kwotę: ${invalid.join(", ")}.` : "",
          ...listProblems,
        ]
          .filter(Boolean)
          .join(" "),
      );
      return false;
    }
    setFormError(null);
    return true;
  };

  const handleServerError = async (error: unknown, fallback: string) => {
    const parsed = await readDocumentError(error, fallback);
    setFormError(parsed.message);
    if (type && parsed.missing.length) {
      setErrorKeys(new Set(fieldKeysForLabels(type, parsed.missing)));
      setRefsError(parsed.missing.includes(REFS_MISSING_LABEL));
    }
  };

  const preview = useMutation({
    mutationFn: () => b2bDocumentsApi.preview(requestBody()),
    onSuccess: (data) => {
      setPreviewHtml(data.html);
      setPreviewMissing(data.missing ?? []);
    },
    onError: (e) => void handleServerError(e, "Nie udało się przygotować podglądu."),
  });

  const download = useMutation({
    mutationFn: async () => {
      const body = requestBody();
      const res = savedId
        ? await b2bDocumentsApi.rerender(savedId, body)
        : await b2bDocumentsApi.create(body);
      saveDocx(res as { data: unknown; headers: Record<string, unknown> }, `${type!.label}.docx`);
      const headers = res.headers as Record<string, unknown>;
      const header = Number(headers["x-document-id"]);
      return Number.isFinite(header) && header > 0 ? header : savedId;
    },
    onSuccess: (id) => {
      setSavedId(id ?? null);
      queryClient.invalidateQueries({ queryKey: [B2B_DOCUMENTS_KEY, "list"] });
      const annex = type ? usesAnnexPicker(type) : false;
      if (annex) {
        // Aneks widać w kontrakcie od wygenerowania („czeka na podpis”).
        queryClient.invalidateQueries({ queryKey: ["contract-annex-documents"] });
      }
      if (subject.parentId && annex) {
        // Wiersz „Umów bieżących” zmienia się już przy wygenerowaniu aneksu.
        queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
      }
      toast.showSuccess(
        !annex
          ? "Dokument zapisany i pobrany."
          : subject.parentId
            ? "Aneks zapisany i pobrany. Jest w rejestrze aneksów, a rejestr umów już pokazuje zmianę."
            : "Aneks zapisany i pobrany. Jest w rejestrze aneksów.",
      );
    },
    onError: (e) => void handleServerError(e, "Nie udało się wygenerować dokumentu."),
  });

  const setValue = (key: string, value: DocumentValue) => {
    setValues((prev) => {
      const next = { ...prev, [key]: value };
      if (key === "partner_variant" && (value === "sole_trader" || value === "company")) {
        // Paragraf daty startu zależy od wariantu (spółka ma § 12 „Osoby
        // skierowane…”); ręcznie wpisany numer zostaje.
        const paragraph = paragraphAfterVariantChange(
          prev,
          (prev.partner_variant as PartnerVariant | undefined) ?? null,
          value,
          prefill.data?.paragraph_defaults,
        );
        if (paragraph) Object.assign(next, paragraph);
      }
      return next;
    });
    setErrorKeys((prev) => {
      if (!prev.has(key)) return prev;
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  };

  const chooseType = (next: DocumentTypeDef) => {
    setTypeKey(next.key);
    setInitializedFor(null);
    setSavedId(null);
    const keepParent = subject.parentId !== null && next.parent !== "none";
    if (!keepParent) setSubject({ ...EMPTY_SUBJECT });
    setStep(keepParent ? "form" : "subject");
  };

  // Wybór umowy przedwstępnej w kroku rekrutacji — podmiot (kandydat,
  // rekrutacja) zostaje, zmienia się tylko rodzaj dokumentu.
  const switchType = (key: string) => {
    setTypeKey(key);
    setInitializedFor(null);
    setSavedId(null);
  };

  const restart = () => {
    setTypeKey(null);
    setSubject({ ...EMPTY_SUBJECT });
    setSavedId(null);
    setInitializedFor(null);
    setValues({});
    setPreviewHtml(null);
    setFormError(null);
    setStep("type");
  };

  const presetParent = Boolean(initialParentId || initialContractId);
  // Aneksy powstają wyłącznie w „Generatorze aneksów” (ticket 29.09.2026);
  // zakładka „Dokumenty” tworzy rozwiązania i umowę przedwstępną.
  const modeTypes = typesData.types.filter((t) =>
    annexMode ? createdInAnnexGenerator(t) : !createdInAnnexGenerator(t),
  );
  const visibleTypes = presetParent
    ? modeTypes.filter((t) => t.parent !== "none")
    : modeTypes;

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="text-base">
            {editDocumentId
              ? "Popraw dokument"
              : annexMode
                ? "Nowy aneks"
                : "Nowy dokument"}
          </CardTitle>
          <CardDescription>
            {type ? type.label : annexMode ? "Wybierz typ aneksu." : "Wybierz rodzaj dokumentu."}
            {subject.parentLabel ? ` · umowa ${subject.parentLabel}` : ""}
            {!subject.parentId && subject.contractLabel
              ? ` · ${subject.contractLabel}`
              : ""}
            {subject.withoutContract
              ? ` · bez kontraktu${subject.clientName ? `, ${subject.clientName}` : ""}`
              : ""}
          </CardDescription>
        </div>
        <Button variant="ghost" size="sm" onClick={annexMode ? restart : onClose}>
          {annexMode ? "Zacznij od nowa" : "Zamknij kreator"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-6">
        {step === "type" ? (
          <TypeStep
            types={visibleTypes}
            selected={typeKey}
            onChoose={chooseType}
            contractResolving={byContract.isFetching}
            contractMissing={byContract.isSuccess && !byContract.data}
            contractError={byContract.isError ? byContract.error : null}
          />
        ) : null}
        {step === "type" && !annexMode ? (
          <MandateFormsSection forms={typesData.mandate_forms ?? []} />
        ) : null}

        {step === "subject" && type ? (
          <SubjectStep
            type={type}
            subject={subject}
            onSubject={setSubject}
            onType={switchType}
            onBack={() => setStep("type")}
            onNext={() => setStep("form")}
            contractResolving={byContract.isFetching}
            contractMissing={Boolean(initialContractId) && byContract.isSuccess && !byContract.data}
          />
        ) : null}

        {step === "form" && type ? (
          <div className="space-y-6">
            <div className="flex flex-wrap items-center gap-2">
              {!editDocumentId ? (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    // Umowa z wiersza rejestru jest już wybrana — wstecz znaczy
                    // „inny rodzaj dokumentu”, nie „inna umowa”.
                    setStep(presetParent && type.parent !== "none" ? "type" : "subject")
                  }
                >
                  <ArrowLeft className="mr-1 h-4 w-4" aria-hidden="true" />
                  Wstecz
                </Button>
              ) : null}
              {type.parent === "none" && subject.candidateLabel ? (
                <Badge variant="outline">
                  {subject.candidateLabel}
                  {subject.jobLabel ? ` · ${subject.jobLabel}` : ""}
                </Badge>
              ) : null}
            </div>

            {prefill.isPending && prefillEnabled ? (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Wczytuję dane z umowy bazowej…
              </p>
            ) : prefill.isError || savedForm.isError ? (
              <Alert
                variant="error"
                title="Nie udało się wczytać formularza"
                description={apiErrorMessage(
                  prefill.error ?? savedForm.error,
                  "Spróbuj ponownie za chwilę.",
                )}
              >
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-2"
                  onClick={() => {
                    void prefill.refetch();
                    if (editDocumentId) void savedForm.refetch();
                  }}
                >
                  Ponów
                </Button>
              </Alert>
            ) : initializedFor === initKey ? (
              <>
                {savedId && download.isSuccess ? (
                  <Alert
                    variant="success"
                    icon={CheckCircle2}
                    title="Dokument zapisany"
                    description={
                      !usesAnnexPicker(type)
                        ? "Plik pobrany, wpis jest na liście dokumentów. Po podpisie oznacz go jako podpisany."
                        : subject.withoutContract
                          ? "Plik pobrany. Aneks jest w rejestrze aneksów z oznaczeniem „Bez kontraktu” — powiąż go z kontraktem, żeby dało się go oznaczyć jako podpisany."
                          : "Plik pobrany. Aneks jest w rejestrze aneksów poniżej — tam pobierzesz go ponownie i oznaczysz jako podpisany. Kontrakt zmieni się po podpisie."
                    }
                  >
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Button size="sm" variant="outline" onClick={() => validate() && download.mutate()}>
                        Popraw i pobierz ponownie
                      </Button>
                      <Button size="sm" variant="ghost" onClick={restart}>
                        {annexMode ? "Nowy aneks" : "Nowy dokument"}
                      </Button>
                    </div>
                  </Alert>
                ) : null}

                {type.languages.length > 1 ? (
                  <div className="space-y-1">
                    <Label htmlFor="b2b-doc-language">Język dokumentu</Label>
                    <select
                      id="b2b-doc-language"
                      value={language}
                      onChange={(e) => setLanguage(e.target.value)}
                      className="flex h-9 w-full max-w-xs rounded-md border border-border bg-card px-3 text-sm text-foreground"
                    >
                      {type.languages.map((lang) => (
                        <option key={lang} value={lang}>
                          {LANGUAGE_LABELS[lang] ?? lang.toUpperCase()}
                        </option>
                      ))}
                    </select>
                  </div>
                ) : null}

                <DocumentFieldsForm
                  type={type}
                  values={values}
                  onChange={setValue}
                  errorKeys={errorKeys}
                />

                {needsRefs ? (
                  <div className={cn(refsError && "rounded-lg ring-2 ring-destructive")}>
                    <DocumentRefsFields
                      labels={typesData.ref_labels}
                      refs={refs}
                      onChange={(key, value) => {
                        setRefs((prev) => ({ ...prev, [key]: value }));
                        setRefsError(false);
                      }}
                    />
                  </div>
                ) : null}

                {formError ? <Alert variant="error" title={formError} /> : null}

                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    onClick={() => preview.mutate()}
                    loading={preview.isPending}
                    disabled={preview.isPending}
                  >
                    <Eye className="mr-1 h-4 w-4" aria-hidden="true" />
                    Podgląd
                  </Button>
                  <Button
                    onClick={() => validate() && download.mutate()}
                    loading={download.isPending}
                    disabled={download.isPending}
                  >
                    <Download className="mr-1 h-4 w-4" aria-hidden="true" />
                    {savedId ? "Popraw i pobierz DOCX" : "Pobierz DOCX"}
                  </Button>
                </div>

                {previewHtml !== null ? (
                  <div className="space-y-2">
                    {previewMissing.length ? (
                      <Alert
                        variant="warning"
                        title={`W podglądzie brakuje: ${previewMissing.join(", ")}.`}
                      />
                    ) : null}
                    {/* sandbox="" — podgląd bez skryptów, formularzy i nawigacji. */}
                    <iframe
                      title="Podgląd dokumentu"
                      sandbox=""
                      srcDoc={previewHtml}
                      className="h-[70dvh] w-full rounded-lg border border-border bg-card"
                    />
                  </div>
                ) : null}
              </>
            ) : null}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

// ── Krok 1: typ ─────────────────────────────────────────────────────────────

function TypeStep({
  types,
  selected,
  onChoose,
  contractResolving,
  contractMissing,
  contractError,
}: {
  types: DocumentTypeDef[];
  selected: string | null;
  onChoose: (type: DocumentTypeDef) => void;
  contractResolving: boolean;
  contractMissing: boolean;
  contractError: unknown;
}) {
  return (
    <div className="space-y-5">
      {contractResolving ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Szukam umowy tej osoby w rejestrze…
        </p>
      ) : null}
      {contractMissing ? (
        <Alert
          variant="warning"
          title="Ta osoba nie ma umowy w rejestrze"
          description="Umowę bazową wybierzesz ręcznie w następnym kroku."
        />
      ) : null}
      {contractError ? (
        <Alert
          variant="error"
          title="Nie udało się znaleźć umowy tej osoby"
          description={apiErrorMessage(contractError, "Wybierz umowę ręcznie.")}
        />
      ) : null}
      {typesByFamily(types).map((group) => (
        <section key={group.family} className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground">{group.label}</h3>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {group.types.map((t) => (
              <button
                key={t.key}
                type="button"
                aria-pressed={selected === t.key}
                onClick={() => onChoose(t)}
                className={cn(
                  "flex h-full flex-col items-start gap-1 rounded-lg border p-3 text-left transition-colors hover:bg-muted",
                  selected === t.key ? "border-primary bg-primary/5" : "border-border bg-card",
                )}
              >
                <span className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <FileText className="h-4 w-4 text-primary" aria-hidden="true" />
                  {t.label}
                </span>
                {t.description ? (
                  <span className="text-xs text-muted-foreground">{t.description}</span>
                ) : null}
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

// ── Krok 2: umowa bazowa / kandydat ─────────────────────────────────────────

function SubjectStep({
  type,
  subject,
  onSubject,
  onType,
  onBack,
  onNext,
  contractResolving,
  contractMissing,
}: {
  type: DocumentTypeDef;
  subject: Subject;
  onSubject: (s: Subject) => void;
  onType: (key: string) => void;
  onBack: () => void;
  onNext: () => void;
  contractResolving: boolean;
  contractMissing: boolean;
}) {
  return (
    <div className="space-y-4">
      <Button variant="ghost" size="sm" onClick={onBack}>
        <ArrowLeft className="mr-1 h-4 w-4" aria-hidden="true" />
        Zmień rodzaj dokumentu
      </Button>
      {contractResolving ? (
        <p className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          Szukam umowy tej osoby w rejestrze…
        </p>
      ) : null}
      {contractMissing ? (
        <Alert
          variant="warning"
          title="Ta osoba nie ma umowy w rejestrze"
          description="Wyszukaj umowę po numerze albo nazwisku Partnera."
        />
      ) : null}
      {type.parent === "none" ? (
        <CandidateJobPicker
          type={type}
          subject={subject}
          onSubject={onSubject}
          onType={onType}
        />
      ) : usesAnnexPicker(type) ? (
        <AnnexSubjectPicker
          type={type}
          choice={subject}
          onChoice={(choice) => onSubject({ ...subject, ...choice })}
        />
      ) : (
        <RegisterPicker
          optional={type.parent === "mandate"}
          subject={subject}
          onSubject={onSubject}
        />
      )}
      <div className="flex justify-end">
        <Button onClick={onNext} disabled={!subjectReady(type, subject)}>
          Dalej
        </Button>
      </div>
    </div>
  );
}

/** Umowa bazowa rozwiązania albo wypowiedzenia — wybór z rejestru umów. */
function RegisterPicker({
  optional,
  subject,
  onSubject,
}: {
  optional: boolean;
  subject: Subject;
  onSubject: (s: Subject) => void;
}) {
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 300);
  const rows = useQuery({
    queryKey: ["b2b-generated", "documents-picker", debounced.trim()],
    queryFn: () => b2bGeneratorApi.generated(20, { q: debounced }),
    staleTime: 10_000,
  });
  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <Label htmlFor="b2b-doc-parent-search">
          {`Umowa bazowa${optional ? " (opcjonalnie)" : " *"}`}
        </Label>
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden="true" />
          <Input
            id="b2b-doc-parent-search"
            className="pl-8"
            placeholder="Numer umowy, Partner albo nazwa firmy"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>
      {optional ? (
        <Button
          variant={subject.noParent ? "primary" : "outline"}
          size="sm"
          aria-pressed={subject.noParent}
          onClick={() =>
            onSubject({ ...subject, parentId: null, parentLabel: null, noParent: true })
          }
        >
          Umowy nie ma w rejestrze
        </Button>
      ) : null}
      {rows.isPending ? (
        <p className="text-sm text-muted-foreground">Szukam…</p>
      ) : rows.isError ? (
        <Alert
          variant="error"
          title="Nie udało się przeszukać rejestru"
          description={apiErrorMessage(rows.error, "Spróbuj ponownie.")}
        >
          <Button variant="outline" size="sm" className="mt-2" onClick={() => void rows.refetch()}>
            Ponów
          </Button>
        </Alert>
      ) : rows.isSuccess && rows.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Brak umów pasujących do wyszukiwania.
        </p>
      ) : (
        <ul className="max-h-72 divide-y divide-border overflow-y-auto rounded-lg border border-border">
          {(rows.data ?? []).map((row) => {
            const chosen = subject.parentId === row.id;
            return (
              <li key={row.id}>
                <button
                  type="button"
                  aria-pressed={chosen}
                  onClick={() =>
                    onSubject({
                      ...subject,
                      parentId: row.id,
                      parentLabel: registerRowLabel(row),
                      noParent: false,
                    })
                  }
                  className={cn(
                    "flex w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-muted",
                    chosen && "bg-primary/5",
                  )}
                >
                  <span className="font-medium text-foreground">{registerRowLabel(row)}</span>
                  <span className="text-xs text-muted-foreground">
                    {row.client_name || "—"}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function sameKeys(a: string[] | null, b: string[]): boolean {
  return a !== null && a.length === b.length && a.every((k, i) => k === b[i]);
}

function CandidateJobPicker({
  type,
  subject,
  onSubject,
  onType,
}: {
  type: DocumentTypeDef;
  subject: Subject;
  onSubject: (s: Subject) => void;
  onType: (key: string) => void;
}) {
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 300).trim();
  const candidates = useQuery({
    queryKey: [B2B_DOCUMENTS_KEY, "candidates", debounced],
    queryFn: () => b2bDocumentsApi.searchCandidates(debounced),
    enabled: debounced.length >= 2,
    staleTime: 30_000,
  });
  const recruitments = useQuery({
    queryKey: [B2B_DOCUMENTS_KEY, "recruitments", subject.candidateId ?? 0],
    queryFn: () => b2bDocumentsApi.candidateRecruitments(subject.candidateId as number),
    enabled: subject.candidateId !== null,
  });
  const options = useQuery({
    queryKey: b2bDocumentsKeys.preliminaryOptions(
      subject.candidateId ?? 0,
      subject.jobId ?? 0,
    ),
    queryFn: () =>
      b2bDocumentsApi.preliminaryOptions(
        subject.candidateId as number,
        subject.jobId as number,
      ),
    enabled: subject.candidateId !== null && subject.jobId !== null,
    staleTime: 60_000,
  });
  useEffect(() => {
    const data = options.data;
    if (!data || subject.jobId === null) return;
    const keys = data.types.map((t) => t.key);
    if (sameKeys(subject.allowedTypes, keys)) return;
    onSubject({ ...subject, allowedTypes: keys });
    // Jedyny dozwolony wzór (Centrum e-Zdrowia) wybiera się sam.
    if (keys.length === 1 && keys[0] !== type.key) onType(keys[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [options.data, subject.jobId, subject.candidateId]);
  const allowed = options.data?.types ?? [];
  const typeAllowed = allowed.some((t) => t.key === type.key);
  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="b2b-doc-candidate-search">Kandydat *</Label>
          <Input
            id="b2b-doc-candidate-search"
            placeholder="Imię i nazwisko (min. 2 znaki)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {candidates.isError ? (
            <Alert
              variant="error"
              title={apiErrorMessage(candidates.error, "Nie udało się wyszukać kandydatów.")}
            />
          ) : candidates.isSuccess && candidates.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">Brak kandydatów o tym nazwisku.</p>
          ) : (
            <ul className="max-h-60 divide-y divide-border overflow-y-auto rounded-lg border border-border empty:hidden">
              {(candidates.data ?? []).map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    aria-pressed={subject.candidateId === c.id}
                    onClick={() =>
                      onSubject({
                        ...subject,
                        candidateId: c.id,
                        candidateLabel: c.full_name,
                        jobId: null,
                        jobLabel: null,
                        allowedTypes: null,
                      })
                    }
                    className={cn(
                      "w-full px-3 py-2 text-left text-sm hover:bg-muted",
                      subject.candidateId === c.id && "bg-primary/5",
                    )}
                  >
                    {c.full_name}
                    {c.email ? (
                      <span className="block text-xs text-muted-foreground">{c.email}</span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="space-y-2">
          <p className="text-sm font-medium">Rekrutacja *</p>
          {subject.candidateId === null ? (
            <p className="text-sm text-muted-foreground">Najpierw wybierz kandydata.</p>
          ) : recruitments.isPending ? (
            <p className="text-sm text-muted-foreground">Wczytuję rekrutacje…</p>
          ) : recruitments.isError ? (
            <Alert
              variant="error"
              title={apiErrorMessage(recruitments.error, "Nie udało się wczytać rekrutacji.")}
            />
          ) : recruitments.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Ten kandydat nie jest w żadnej rekrutacji.
            </p>
          ) : (
            <ul className="max-h-60 divide-y divide-border overflow-y-auto rounded-lg border border-border">
              {recruitments.data.map((r) => (
                <li key={r.stage_id}>
                  <button
                    type="button"
                    aria-pressed={subject.jobId === r.job_id}
                    onClick={() =>
                      onSubject({
                        ...subject,
                        jobId: r.job_id,
                        jobLabel: r.job_title,
                        allowedTypes: null,
                      })
                    }
                    className={cn(
                      "w-full px-3 py-2 text-left text-sm hover:bg-muted",
                      subject.jobId === r.job_id && "bg-primary/5",
                    )}
                  >
                    {r.job_title}
                    <span className="block text-xs text-muted-foreground">{r.stage}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="text-xs text-muted-foreground">
            Rodzaj umowy podpowiadamy po kliencie rekrutacji.
          </p>
        </div>
      </div>
      {subject.jobId !== null ? (
        <div className="space-y-2">
          <p className="text-sm font-medium">Rodzaj umowy *</p>
          {options.isPending ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              Sprawdzam, która umowa pasuje do tej rekrutacji…
            </p>
          ) : options.isError ? (
            <Alert
              variant="error"
              title={apiErrorMessage(
                options.error,
                "Nie udało się sprawdzić, którą umowę wystawić w tej rekrutacji.",
              )}
            >
              <Button
                variant="outline"
                size="sm"
                className="mt-2"
                onClick={() => void options.refetch()}
              >
                Ponów
              </Button>
            </Alert>
          ) : (
            <>
              <div className="grid gap-2 sm:grid-cols-2" role="group" aria-label="Rodzaj umowy">
                {allowed.map((t) => (
                  <button
                    key={t.key}
                    type="button"
                    aria-pressed={type.key === t.key}
                    onClick={() => onType(t.key)}
                    className={cn(
                      "rounded-lg border px-3 py-2 text-left text-sm transition-colors hover:bg-muted",
                      type.key === t.key ? "border-primary bg-primary/5" : "border-border bg-card",
                    )}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
              {!typeAllowed && allowed.length > 1 ? (
                <p className="text-xs text-muted-foreground">
                  W tej rekrutacji wybierz jedną z powyższych umów.
                </p>
              ) : null}
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
