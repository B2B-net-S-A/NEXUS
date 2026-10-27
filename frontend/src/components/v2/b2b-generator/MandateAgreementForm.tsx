"use client";

// Umowa zlecenia w Generatorze Umów (decyzje Artura 26.10.2026). Ten sam
// rejestr co B2B: wiersz „Zlecenie z dnia …” bez numeru z puli B2B, a „Oznacz
// jako podpisaną” zakłada kontrakt typu zlecenie i szkic zamówienia.
// PESEL, dowód i adres idą wyłącznie do pliku.

import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Eye, Lock, Plus, Printer, Trash2 } from "lucide-react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SegmentedRadio } from "@/components/ui/segmented-radio";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/Toast";
import { AgreementAdminDetailsCard } from "@/components/v2/b2b-generator/AgreementAdminDetailsCard";
import {
  adminPayload,
  EMPTY_ADMIN_VALUE,
  isAdminComplete,
  type AgreementAdminValue,
} from "@/lib/agreement-admin-details";
import { b2bGeneratorApi } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { b2bDocumentsApi } from "@/lib/api/b2bDocuments";
import {
  PREVIEW_STYLE,
  instrumentalPl,
  printHtml,
} from "@/lib/b2b-agreement-preview";
import { readDocumentError, SENSITIVE_NOTE } from "@/lib/b2b-documents";
import {
  MANDATE_MAX_TASKS,
  emptyMandateForm,
  mandateErrors,
  mandateLabel,
  mandatePayload,
  type MandateField,
  type MandateFormState,
} from "@/lib/b2b-mandate";
import { downloadBlob, parseDispositionFilename } from "@/lib/cv-generator";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { warsawToday } from "@/lib/warsaw-date";

interface Person {
  candidateId: number | null;
  candidateLabel: string | null;
  jobId: number | null;
  jobLabel: string | null;
}

const NO_PERSON: Person = {
  candidateId: null,
  candidateLabel: null,
  jobId: null,
  jobLabel: null,
};

function FieldError({ id, message }: { id: string; message?: string }) {
  if (!message) return null;
  return (
    <p id={id} className="text-xs text-destructive">
      {message}
    </p>
  );
}

function PersonPicker({
  person,
  onChange,
}: {
  person: Person;
  onChange: (person: Person, email?: string | null) => void;
}) {
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 300).trim();
  const candidates = useQuery({
    queryKey: ["b2b-mandate", "candidates", debounced],
    queryFn: () => b2bDocumentsApi.searchCandidates(debounced),
    enabled: debounced.length >= 2 && person.candidateId === null,
    staleTime: 30_000,
  });
  const recruitments = useQuery({
    queryKey: ["b2b-mandate", "recruitments", person.candidateId ?? 0],
    queryFn: () =>
      b2bDocumentsApi.candidateRecruitments(person.candidateId as number),
    enabled: person.candidateId !== null,
  });

  if (person.candidateId !== null) {
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm">
          <span>
            <span className="font-medium">{person.candidateLabel}</span>
            {person.jobLabel ? (
              <span className="text-muted-foreground"> · {person.jobLabel}</span>
            ) : null}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              setQuery("");
              onChange(NO_PERSON);
            }}
          >
            Zmień
          </Button>
        </div>
        {person.jobId === null ? (
          recruitments.isPending ? (
            <p className="text-sm text-muted-foreground">Wczytuję rekrutacje…</p>
          ) : recruitments.isError ? (
            <Alert
              variant="error"
              title={apiErrorMessage(
                recruitments.error,
                "Nie udało się wczytać rekrutacji.",
              )}
            />
          ) : recruitments.data.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Ten kandydat nie jest w żadnej rekrutacji — umowę wydasz, ale
              podpis wymaga rekrutacji.
            </p>
          ) : (
            <div className="space-y-1">
              <p className="text-sm font-medium">Rekrutacja</p>
              <ul className="max-h-48 divide-y divide-border overflow-y-auto rounded-lg border border-border">
                {recruitments.data.map((r) => (
                  <li key={r.stage_id}>
                    <button
                      type="button"
                      onClick={() =>
                        onChange({ ...person, jobId: r.job_id, jobLabel: r.job_title })
                      }
                      className="w-full px-3 py-2 text-left text-sm hover:bg-muted"
                    >
                      {r.job_title}
                      <span className="block text-xs text-muted-foreground">
                        {r.stage}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )
        ) : null}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <Input
        id="b2b-mandate-candidate"
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
        <ul className="max-h-48 divide-y divide-border overflow-y-auto rounded-lg border border-border empty:hidden">
          {(candidates.data ?? []).map((c) => (
            <li key={c.id}>
              <button
                type="button"
                onClick={() =>
                  onChange(
                    {
                      candidateId: c.id,
                      candidateLabel: c.full_name,
                      jobId: null,
                      jobLabel: null,
                    },
                    c.email,
                  )
                }
                className="w-full px-3 py-2 text-left text-sm hover:bg-muted"
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
  );
}

export function MandateAgreementForm() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [form, setForm] = useState<MandateFormState>(() =>
    emptyMandateForm(warsawToday()),
  );
  const [person, setPerson] = useState<Person>(NO_PERSON);
  const [instrumentalEdited, setInstrumentalEdited] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  // „Szczegóły administracyjne” (0524) — jak w umowie B2B.
  const [admin, setAdmin] = useState<AgreementAdminValue>(EMPTY_ADMIN_VALUE);
  const [showAdminErrors, setShowAdminErrors] = useState(false);
  const [previewHtml, setPreviewHtml] = useState("");
  // „Dodaj czynność” przenosi kursor do nowego pola — bez tego pisanie dalej
  // dopisywało tekst do poprzedniej czynności.
  const [focusTask, setFocusTask] = useState<number | null>(null);
  const taskRefs = useRef<(HTMLInputElement | null)[]>([]);
  useEffect(() => {
    if (focusTask === null) return;
    taskRefs.current[focusTask]?.focus();
    setFocusTask(null);
  }, [focusTask]);

  const errors = useMemo(() => mandateErrors(form), [form]);
  const visible = (key: MandateField) => (showErrors ? errors[key] : undefined);

  const update = (patch: Partial<MandateFormState>) =>
    setForm((prev) => ({ ...prev, ...patch }));

  const setName = (partnerName: string) =>
    update({
      partnerName,
      ...(instrumentalEdited
        ? {}
        : {
            partnerInstrumental: instrumentalPl(
              partnerName,
              form.gender === "f" ? "k" : "m",
            ),
          }),
    });

  const onPerson = (next: Person, email?: string | null) => {
    setPerson(next);
    const patch: Partial<MandateFormState> = {
      candidateId: next.candidateId,
      jobId: next.jobId,
    };
    if (next.candidateId !== null && next.candidateId !== person.candidateId) {
      if (!form.partnerName.trim() && next.candidateLabel) {
        patch.partnerName = next.candidateLabel;
        if (!instrumentalEdited) {
          patch.partnerInstrumental = instrumentalPl(
            next.candidateLabel,
            form.gender === "f" ? "k" : "m",
          );
        }
      }
      if (!form.partnerEmail.trim() && email) patch.partnerEmail = email;
    }
    update(patch);
  };

  const ready = () => {
    setShowErrors(true);
    if (Object.keys(errors).length > 0) {
      toast.showError("Uzupełnij zaznaczone pola.");
      return false;
    }
    return true;
  };

  // Replacement i FTE są obowiązkowe przy umowie z rekrutacją (serwer: 422).
  const adminReady = () => {
    const linked = form.candidateId !== null && form.jobId !== null;
    if (!linked || isAdminComplete(admin)) return true;
    setShowAdminErrors(true);
    toast.showError(
      "Uzupełnij „Szczegóły administracyjne”: replacement i wymiar FTE.",
    );
    return false;
  };

  const previewMut = useMutation({
    mutationFn: () =>
      b2bGeneratorApi.renderMandateHtml({
        ...mandatePayload(form),
        ...adminPayload(admin),
      }),
    onSuccess: (d) => setPreviewHtml(d.html),
    onError: (e) =>
      toast.showError(apiErrorMessage(e, "Nie udało się przygotować podglądu.")),
  });

  const docxMut = useMutation({
    mutationFn: async () => {
      const res = await b2bGeneratorApi.renderMandateDocx({
        ...mandatePayload(form),
        ...adminPayload(admin),
      });
      const filename = parseDispositionFilename(
        res.headers["content-disposition"] || "",
        "Umowa zlecenia.docx",
      );
      downloadBlob(res.data as Blob, filename);
      // Etykieta z daty zawarcia: umowa zlecenia nie ma numeru.
      return { label: mandateLabel(form.signingDate) };
    },
    onSuccess: (result) => {
      toast.showSuccess(
        `${result.label} pobrana (DOCX) i zapisana w rejestrze „Umowy bieżące”.`,
      );
      queryClient.invalidateQueries({ queryKey: ["kanban"] });
      queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
    },
    onError: async (e) => {
      const err = await readDocumentError(e, "Nie udało się wygenerować umowy.");
      toast.showError(err.message);
    },
  });

  const busy = previewMut.isPending || docxMut.isPending;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Kandydat i rekrutacja</CardTitle>
          <p className="text-sm text-muted-foreground">
            Bez kandydata i rekrutacji umowę wydasz, ale „Oznacz jako
            podpisaną” (kontrakt i zamówienie) poprosi o nie przy podpisie.
          </p>
        </CardHeader>
        <CardContent>
          <PersonPicker person={person} onChange={onPerson} />
        </CardContent>
      </Card>

      <AgreementAdminDetailsCard
        candidateId={form.jobId !== null ? form.candidateId : null}
        jobId={form.candidateId !== null ? form.jobId : null}
        value={admin}
        onChange={setAdmin}
        showErrors={showAdminErrors}
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Zleceniobiorca</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-3">
            <div className="space-y-1.5 md:col-span-1">
              <Label htmlFor="b2b-mandate-name">Imię i nazwisko *</Label>
              <Input
                id="b2b-mandate-name"
                value={form.partnerName}
                aria-invalid={Boolean(visible("partnerName"))}
                aria-describedby="b2b-mandate-name-error"
                onChange={(e) => setName(e.target.value)}
              />
              <FieldError id="b2b-mandate-name-error" message={visible("partnerName")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="b2b-mandate-instrumental">W narzędniku (z kim)</Label>
              <Input
                id="b2b-mandate-instrumental"
                value={form.partnerInstrumental}
                placeholder="np. Anną Kowalską"
                onChange={(e) => {
                  setInstrumentalEdited(true);
                  update({ partnerInstrumental: e.target.value });
                }}
              />
            </div>
            <div className="space-y-1.5">
              <Label id="b2b-mandate-gender-label">Płeć (formy w umowie)</Label>
              <SegmentedRadio<"m" | "f">
                labelledBy="b2b-mandate-gender-label"
                value={form.gender}
                onChange={(gender) =>
                  update({
                    gender,
                    ...(!instrumentalEdited && form.partnerName
                      ? {
                          partnerInstrumental: instrumentalPl(
                            form.partnerName,
                            gender === "f" ? "k" : "m",
                          ),
                        }
                      : {}),
                  })
                }
                options={[
                  { value: "m", label: "Mężczyzna" },
                  { value: "f", label: "Kobieta" },
                ]}
              />
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="b2b-mandate-email">E-mail</Label>
              <Input
                id="b2b-mandate-email"
                type="email"
                value={form.partnerEmail}
                onChange={(e) => update({ partnerEmail: e.target.value })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="b2b-mandate-phone">Telefon</Label>
              <Input
                id="b2b-mandate-phone"
                value={form.partnerPhone}
                onChange={(e) => update({ partnerPhone: e.target.value })}
              />
            </div>
          </div>
          <div className="space-y-3 rounded-lg border border-dashed border-border p-3">
            <p className="flex items-center gap-2 text-sm text-muted-foreground">
              <Lock className="h-4 w-4 shrink-0" aria-hidden="true" />
              {SENSITIVE_NOTE}. Puste pole = kropki w pliku do wpisania ręcznie.
            </p>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="space-y-1.5 md:col-span-1">
                <Label htmlFor="b2b-mandate-address">Adres zamieszkania</Label>
                <Input
                  id="b2b-mandate-address"
                  autoComplete="off"
                  value={form.homeAddress}
                  onChange={(e) => update({ homeAddress: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="b2b-mandate-id">Numer dowodu osobistego</Label>
                <Input
                  id="b2b-mandate-id"
                  autoComplete="off"
                  value={form.idDocument}
                  onChange={(e) => update({ idDocument: e.target.value })}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="b2b-mandate-pesel">PESEL</Label>
                <Input
                  id="b2b-mandate-pesel"
                  autoComplete="off"
                  inputMode="numeric"
                  maxLength={11}
                  value={form.pesel}
                  aria-invalid={Boolean(visible("pesel"))}
                  aria-describedby="b2b-mandate-pesel-error"
                  onChange={(e) => update({ pesel: e.target.value.replace(/\D/g, "") })}
                />
                <FieldError id="b2b-mandate-pesel-error" message={visible("pesel")} />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Zlecenie</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-4">
            {(
              [
                ["signingDate", "Data zawarcia *"],
                ["periodFrom", "Zlecenie od *"],
                ["periodTo", "Zlecenie do *"],
              ] as const
            ).map(([key, label]) => (
              <div key={key} className="space-y-1.5">
                <Label htmlFor={`b2b-mandate-${key}`}>{label}</Label>
                <Input
                  id={`b2b-mandate-${key}`}
                  type="date"
                  value={form[key]}
                  aria-invalid={Boolean(visible(key))}
                  aria-describedby={`b2b-mandate-${key}-error`}
                  onChange={(e) => update({ [key]: e.target.value })}
                />
                <FieldError id={`b2b-mandate-${key}-error`} message={visible(key)} />
              </div>
            ))}
            <div className="space-y-1.5">
              <Label htmlFor="b2b-mandate-rate">Stawka brutto, zł/h *</Label>
              <Input
                id="b2b-mandate-rate"
                inputMode="decimal"
                value={form.rate}
                placeholder="np. 45,50"
                aria-invalid={Boolean(visible("rate"))}
                aria-describedby="b2b-mandate-rate-error"
                onChange={(e) => update({ rate: e.target.value })}
              />
              <FieldError id="b2b-mandate-rate-error" message={visible("rate")} />
            </div>
          </div>

          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Czynności (§ 1 ust. 1) *</legend>
            {form.tasks.map((task, index) => (
              <div key={index} className="flex items-start gap-2">
                <span className="mt-2 w-5 shrink-0 text-sm text-muted-foreground">
                  {String.fromCharCode(97 + index)})
                </span>
                <Input
                  ref={(el) => {
                    taskRefs.current[index] = el;
                  }}
                  aria-label={`Czynność ${String.fromCharCode(97 + index)}`}
                  value={task}
                  onChange={(e) =>
                    update({
                      tasks: form.tasks.map((t, i) => (i === index ? e.target.value : t)),
                    })
                  }
                />
                {form.tasks.length > 1 ? (
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    aria-label={`Usuń czynność ${String.fromCharCode(97 + index)}`}
                    onClick={() =>
                      update({ tasks: form.tasks.filter((_, i) => i !== index) })
                    }
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                ) : null}
              </div>
            ))}
            <FieldError id="b2b-mandate-tasks-error" message={visible("tasks")} />
            {form.tasks.length < MANDATE_MAX_TASKS ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => {
                  update({ tasks: [...form.tasks, ""] });
                  setFocusTask(form.tasks.length);
                }}
              >
                <Plus className="mr-2 h-4 w-4" />
                Dodaj czynność
              </Button>
            ) : null}
          </fieldset>

          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Checkbox
                id="b2b-mandate-dpa"
                checked={form.withDpa}
                onCheckedChange={(v) => update({ withDpa: v === true })}
              />
              <Label htmlFor="b2b-mandate-dpa">
                Z umową powierzenia danych (DPA, Załącznik nr 2)
              </Label>
            </div>
            {form.withDpa ? (
              <div className="space-y-1.5">
                <Label htmlFor="b2b-mandate-dpa-purpose">
                  Cel przetwarzania (§ 2 ust. 3 DPA)
                </Label>
                <Textarea
                  id="b2b-mandate-dpa-purpose"
                  rows={3}
                  value={form.dpaPurpose}
                  onChange={(e) => update({ dpaPurpose: e.target.value })}
                />
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Bez DPA umowa nie ma Załącznika nr 2 ani wzmianki o nim w § 7.
              </p>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => ready() && previewMut.mutate()}
            >
              <Eye className="mr-2 h-4 w-4" />
              Podgląd
            </Button>
            <Button
              type="button"
              disabled={busy}
              onClick={() => ready() && adminReady() && docxMut.mutate()}
            >
              <Download className="mr-2 h-4 w-4" />
              Pobierz DOCX i zapisz w rejestrze
            </Button>
          </div>
        </CardContent>
      </Card>

      {previewHtml ? (
        <Card>
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-2 space-y-0">
            <CardTitle className="text-base">Podgląd (nie zapisuje umowy)</CardTitle>
            <Button
              variant="outline"
              size="sm"
              onClick={() => printHtml(previewHtml, "Podgląd umowy zlecenia")}
            >
              <Printer className="mr-2 h-4 w-4" />
              Drukuj podgląd
            </Button>
          </CardHeader>
          <CardContent>
            {/* `sandbox=""`: treść pochodzi z pól formularza. */}
            <iframe
              title="Podgląd umowy zlecenia"
              sandbox=""
              className="h-[60dvh] min-h-[420px] w-full rounded-lg border bg-white"
              srcDoc={`<style>${PREVIEW_STYLE}</style>${previewHtml}`}
            />
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
