"use client";

// Kreator „Nowy dokument”: typ → umowa bazowa (albo kandydat i rekrutacja
// przy umowie przedwstępnej) → formularz z definicji pól → podgląd / DOCX.
// Ten sam komponent obsługuje „Popraw” z listy (ten sam wiersz, `/rerender`).

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
  fieldKeysForLabels,
  findRegisterRowForContract,
  invalidMoneyFields,
  missingRequired,
  readDocumentError,
  typesByFamily,
} from "@/lib/b2b-documents";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { cn } from "@/lib/utils";

import { DocumentFieldsForm, DocumentRefsFields } from "./DocumentFieldsForm";
import { saveDocx } from "./DocumentDialogs";

/** Etykieta braku numerów paragrafów w `missing[]` serwera. */
const REFS_MISSING_LABEL = "Numery paragrafów umowy bazowej";

type Step = "type" | "subject" | "form";

interface Subject {
  parentId: number | null;
  parentLabel: string | null;
  /** Umowa zlecenie bez wiersza w rejestrze — świadomy wybór, nie brak. */
  noParent: boolean;
  candidateId: number | null;
  candidateLabel: string | null;
  jobId: number | null;
  jobLabel: string | null;
}

const EMPTY_SUBJECT: Subject = {
  parentId: null,
  parentLabel: null,
  noParent: false,
  candidateId: null,
  candidateLabel: null,
  jobId: null,
  jobLabel: null,
};

function subjectReady(type: DocumentTypeDef, subject: Subject): boolean {
  if (type.parent === "b2b") return subject.parentId !== null;
  if (type.parent === "mandate") return subject.parentId !== null || subject.noParent;
  return subject.candidateId !== null && subject.jobId !== null;
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
  onClose: () => void;
}

export function DocumentWizard({
  typesData,
  initialType = null,
  initialParentId = null,
  initialContractId = null,
  editDocumentId = null,
  initialValues,
  onClose,
}: DocumentWizardProps) {
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

  // ── Umowa bazowa z kontraktu (`?contract=`) ──────────────────────────────
  const byContract = useQuery({
    queryKey: ["b2b-generated", "by-contract", initialContractId ?? 0],
    queryFn: async () => {
      const id = initialContractId as number;
      const name = await b2bDocumentsApi.contractCandidateName(id);
      if (!name) return null;
      const rows = await b2bGeneratorApi.generated(200, { q: name });
      return findRegisterRowForContract(rows, id);
    },
    enabled: Boolean(initialContractId) && !initialParentId && !editDocumentId,
    staleTime: 30_000,
  });
  useEffect(() => {
    const row = byContract.data;
    if (!row) return;
    setSubject((prev) =>
      prev.parentId ? prev : { ...prev, parentId: row.id, parentLabel: registerRowLabel(row) },
    );
    setStep((prev) => (prev === "subject" && type && type.parent !== "none" ? "form" : prev));
  }, [byContract.data, type]);

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
    setSubject((prev) => ({
      ...prev,
      parentId: form.parent_generated_contract_id,
      parentLabel: form.base?.contract_number ?? prev.parentLabel,
      noParent: form.parent_generated_contract_id === null,
      candidateId: form.candidate_id,
      jobId: form.job_id,
    }));
  }, [savedForm.data]);

  const prefillEnabled =
    step === "form" &&
    type !== null &&
    subjectReady(type, subject) &&
    (!editDocumentId || savedForm.isSuccess);
  const prefill = useQuery({
    queryKey: b2bDocumentsKeys.prefill(
      type?.key ?? "",
      subject.parentId,
      subject.candidateId,
      subject.jobId,
    ),
    queryFn: () =>
      b2bDocumentsApi.prefill({
        documentType: type!.key,
        parentGeneratedContractId: subject.parentId,
        candidateId: subject.candidateId,
        jobId: subject.jobId,
      }),
    enabled: prefillEnabled,
    staleTime: 0,
  });

  // Wartości startowe raz na (typ, podmiot) — kolejny odczyt prefillu nie
  // może nadpisać tego, co użytkownik już wpisał.
  const initKey = `${type?.key}|${subject.parentId}|${subject.candidateId}|${editDocumentId}`;
  useEffect(() => {
    if (!prefill.data || initializedFor === initKey) return;
    const saved = editDocumentId ? savedForm.data : undefined;
    setValues({ ...prefill.data.values, ...(saved?.values ?? {}), ...(initialValues ?? {}) });
    setRefs({ ...prefill.data.ref_defaults, ...(saved?.refs ?? {}) });
    setLanguage(saved?.language ?? prefill.data.default_language);
    setInitializedFor(initKey);
    setErrorKeys(new Set());
    setFormError(null);
    setPreviewHtml(null);
    if (!subject.parentLabel && prefill.data.base.contract_number) {
      setSubject((prev) => ({
        ...prev,
        parentLabel: prefill.data?.base.contract_number ?? prev.parentLabel,
      }));
    }
  }, [prefill.data, initKey, initializedFor, editDocumentId, savedForm.data, initialValues, subject.parentLabel]);

  const needsRefs = prefill.data?.needs_refs ?? false;

  const requestBody = () =>
    buildDocumentRequest({
      type: type!,
      language,
      subject: {
        parentGeneratedContractId: subject.parentId,
        candidateId: type!.parent === "none" ? subject.candidateId : null,
        jobId: type!.parent === "none" ? subject.jobId : null,
      },
      values,
      needsRefs,
      refs,
    });

  const validate = (): boolean => {
    if (!type) return false;
    const missing = missingRequired(type, values);
    const invalid = invalidMoneyFields(type, values);
    const refsMissing =
      needsRefs && !Object.values(refs).some((v) => (v ?? "").trim() !== "");
    setErrorKeys(new Set(fieldKeysForLabels(type, [...missing, ...invalid])));
    setRefsError(refsMissing);
    const problems = [...missing, ...(refsMissing ? [REFS_MISSING_LABEL] : [])];
    if (problems.length || invalid.length) {
      setFormError(
        [
          problems.length ? `Uzupełnij: ${problems.join(", ")}.` : "",
          invalid.length ? `Popraw kwotę: ${invalid.join(", ")}.` : "",
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
      const header = Number((res.headers as Record<string, unknown>)["x-document-id"]);
      return Number.isFinite(header) && header > 0 ? header : savedId;
    },
    onSuccess: (id) => {
      setSavedId(id ?? null);
      queryClient.invalidateQueries({ queryKey: [B2B_DOCUMENTS_KEY, "list"] });
      toast.showSuccess("Dokument zapisany i pobrany.");
    },
    onError: (e) => void handleServerError(e, "Nie udało się wygenerować dokumentu."),
  });

  const setValue = (key: string, value: DocumentValue) => {
    setValues((prev) => ({ ...prev, [key]: value }));
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
  const visibleTypes = presetParent
    ? typesData.types.filter((t) => t.parent !== "none")
    : typesData.types;

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="text-base">
            {editDocumentId ? "Popraw dokument" : "Nowy dokument"}
          </CardTitle>
          <CardDescription>
            {type ? type.label : "Wybierz rodzaj dokumentu."}
            {subject.parentLabel ? ` · umowa ${subject.parentLabel}` : ""}
          </CardDescription>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Zamknij kreator
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

        {step === "subject" && type ? (
          <SubjectStep
            type={type}
            subject={subject}
            onSubject={setSubject}
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
                    description="Plik pobrany, wpis jest na liście dokumentów. Po podpisie oznacz go jako podpisany."
                  >
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Button size="sm" variant="outline" onClick={() => validate() && download.mutate()}>
                        Popraw i pobierz ponownie
                      </Button>
                      <Button size="sm" variant="ghost" onClick={restart}>
                        Nowy dokument
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
                      className="h-[70vh] w-full rounded-lg border border-border bg-card"
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
  onBack,
  onNext,
  contractResolving,
  contractMissing,
}: {
  type: DocumentTypeDef;
  subject: Subject;
  onSubject: (s: Subject) => void;
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
        <CandidateJobPicker subject={subject} onSubject={onSubject} />
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
          Umowa bazowa{optional ? " (opcjonalnie)" : " *"}
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

function CandidateJobPicker({
  subject,
  onSubject,
}: {
  subject: Subject;
  onSubject: (s: Subject) => void;
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
  return (
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
        <p className="text-sm font-medium">Rekrutacja Centrum e-Zdrowia *</p>
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
                  onClick={() => onSubject({ ...subject, jobId: r.job_id, jobLabel: r.job_title })}
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
          Umowa przedwstępna dotyczy wyłącznie rekrutacji Centrum e-Zdrowia —
          inną serwer odrzuci.
        </p>
      </div>
    </div>
  );
}
