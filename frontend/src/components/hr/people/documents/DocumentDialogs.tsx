"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { FileDropZone } from "@/components/ds/FileDropZone";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage } from "@/lib/api-error";
import {
  DEFAULT_AUDIENCE,
  DOCUMENT_KINDS,
  DOCUMENT_KIND_LABELS,
  profileSyncMessage,
  useRemoveDocument,
  useUpdateDocument,
  useUploadDocument,
  type DocumentAudience,
  type DocumentKind,
  type PersonDocument,
} from "@/lib/api/hr-documents";

const MAX_DOCUMENT_BYTES = 20 * 1024 * 1024;
const ACCEPT = ".pdf,.docx,.jpg,.jpeg,.png";

function ErrorLine({ error }: { error: string | null }) {
  return error ? (
    <p role="alert" className="text-sm text-destructive">
      {error}
    </p>
  ) : null;
}

/** Krąg widzących poza Kadrami: osoba, Płace, recepcja. */
export function AudienceFields({
  value,
  onChange,
  personLocked = false,
}: {
  value: DocumentAudience;
  onChange: (next: DocumentAudience) => void;
  /** Umowa z generatora zostaje widoczna dla osoby. */
  personLocked?: boolean;
}) {
  const row = (key: keyof DocumentAudience, label: string, disabled = false) => (
    <label className="flex items-center gap-2 text-sm text-foreground">
      <Checkbox
        checked={value[key]}
        disabled={disabled}
        onCheckedChange={(next) => onChange({ ...value, [key]: next === true })}
      />
      {label}
    </label>
  );
  return (
    <fieldset className="space-y-1.5">
      <legend className="mb-1 text-sm font-medium text-foreground">Kto widzi</legend>
      <div className="flex flex-wrap gap-x-5 gap-y-1.5">
        {row("person", "osoba", personLocked)}
        {row("payroll", "Płace")}
        {row("equipment", "recepcja")}
      </div>
      <p className="text-xs text-muted-foreground">
        Kadry widzą zawsze. Przełożony nie widzi dokumentów osoby.
      </p>
    </fieldset>
  );
}

/** Kadry: wgranie dokumentu do e-teczki osoby. */
export function UploadDocumentDialog({
  userId,
  name,
  open,
  onOpenChange,
}: {
  userId: number;
  name: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { showToast } = useToast();
  const upload = useUploadDocument(userId);
  const [file, setFile] = useState<File | null>(null);
  const [kind, setKind] = useState<DocumentKind>("contract");
  const [title, setTitle] = useState("");
  const [validUntil, setValidUntil] = useState("");
  const [student, setStudent] = useState(false);
  const [audience, setAudience] = useState<DocumentAudience>(DEFAULT_AUDIENCE.contract);
  const [error, setError] = useState<string | null>(null);

  const pickKind = (next: DocumentKind) => {
    setKind(next);
    setAudience(DEFAULT_AUDIENCE[next]);
    if (next !== "statement") setStudent(false);
  };

  const submit = () => {
    setError(null);
    if (!file) {
      setError("Wybierz plik dokumentu.");
      return;
    }
    if (!title.trim()) {
      setError("Podaj tytuł dokumentu.");
      return;
    }
    if (student && !validUntil) {
      setError("Podaj „ważny do” oświadczenia — od tej daty Płace naliczą składki.");
      return;
    }
    upload.mutate(
      {
        file,
        kind,
        title: title.trim(),
        valid_until: validUntil || null,
        purpose: student ? "student_status" : null,
        audience,
      },
      {
        onSuccess: (saved) => {
          showToast("Dokument zapisany", "success");
          const note = profileSyncMessage(saved.profile_sync);
          if (note) showToast(note, "info");
          onOpenChange(false);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się wgrać dokumentu.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title={`Wgraj dokument · ${name}`}
      description="PDF, plik Word (DOCX) albo skan JPG/PNG, do 20 MB. Plik trafia do dokumentów osoby."
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={upload.isPending}>
            {upload.isPending ? "Wgrywanie…" : "Wgraj dokument"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <FileDropZone
            inputId="hr-document-file"
            file={file}
            onPick={(picked) => {
              setFile(picked);
              setError(null);
            }}
            accept={ACCEPT}
            maxBytes={MAX_DOCUMENT_BYTES}
            label="Plik dokumentu"
            hint="PDF, DOCX, JPG albo PNG do 20 MB"
            onError={setError}
          />
        </div>
        <FormField label="Rodzaj" htmlFor="hr-document-kind">
          <Select value={kind} onValueChange={(value) => pickKind(value as DocumentKind)}>
            <SelectTrigger id="hr-document-kind">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DOCUMENT_KINDS.map((key) => (
                <SelectItem key={key} value={key}>
                  {DOCUMENT_KIND_LABELS[key]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField
          label="Ważny do"
          htmlFor="hr-document-valid"
          description={kind === "contract" ? "Puste = bezterminowo." : "Puste = bez daty."}
        >
          <Input
            id="hr-document-valid"
            type="date"
            value={validUntil}
            onChange={(event) => setValidUntil(event.target.value)}
          />
        </FormField>
        <FormField label="Tytuł" htmlFor="hr-document-title" className="sm:col-span-2">
          <Input
            id="hr-document-title"
            value={title}
            maxLength={300}
            placeholder="np. Oświadczenie studenta"
            onChange={(event) => setTitle(event.target.value)}
          />
        </FormField>
        {kind === "statement" ? (
          <label className="flex items-start gap-2 text-sm text-foreground sm:col-span-2">
            <Checkbox
              checked={student}
              onCheckedChange={(value) => setStudent(value === true)}
              className="mt-0.5"
            />
            <span>
              Oświadczenie o statusie ucznia lub studenta.{" "}
              <span className="text-muted-foreground">
                Na zleceniu „ważny do” wpisze się w kartotece jako koniec zwolnienia ze składek,
                a Płace dostaną przypomnienie 30 dni wcześniej.
              </span>
            </span>
          </label>
        ) : null}
        <div className="sm:col-span-2">
          <AudienceFields value={audience} onChange={setAudience} />
        </div>
      </div>
      <div className="mt-3">
        <ErrorLine error={error} />
      </div>
    </AppModal>
  );
}

/** Kadry: tytuł, „ważny do” i krąg widzących (rodzaju i pliku się nie zmienia). */
export function EditDocumentDialog({
  document,
  open,
  onOpenChange,
}: {
  document: PersonDocument;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { showToast } = useToast();
  const update = useUpdateDocument(document.user_id);
  const [title, setTitle] = useState(document.title);
  const [validUntil, setValidUntil] = useState(document.valid_until ?? "");
  const [audience, setAudience] = useState<DocumentAudience>(document.audience);
  const [error, setError] = useState<string | null>(null);
  const generated = document.source !== "upload";

  const submit = () => {
    setError(null);
    if (!title.trim()) {
      setError("Podaj tytuł dokumentu.");
      return;
    }
    update.mutate(
      {
        id: document.id,
        patch: { title: title.trim(), valid_until: validUntil || null, audience },
      },
      {
        onSuccess: (saved) => {
          showToast("Dokument zapisany", "success");
          const note = profileSyncMessage(saved.profile_sync);
          if (note) showToast(note, "info");
          onOpenChange(false);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się zapisać zmian.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Zmień dokument"
      description={`${DOCUMENT_KIND_LABELS[document.kind]} · plik zostaje ten sam`}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button onClick={submit} disabled={update.isPending}>
            {update.isPending ? "Zapisywanie…" : "Zapisz"}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label="Tytuł" htmlFor="hr-document-edit-title" className="sm:col-span-2">
          <Input
            id="hr-document-edit-title"
            value={title}
            maxLength={300}
            onChange={(event) => setTitle(event.target.value)}
          />
        </FormField>
        <FormField label="Ważny do" htmlFor="hr-document-edit-valid">
          <Input
            id="hr-document-edit-valid"
            type="date"
            value={validUntil}
            onChange={(event) => setValidUntil(event.target.value)}
          />
        </FormField>
        <div className="sm:col-span-2">
          <AudienceFields value={audience} onChange={setAudience} personLocked={generated} />
        </div>
      </div>
      <div className="mt-3">
        <ErrorLine error={error} />
      </div>
    </AppModal>
  );
}

/** Kadry: usunięcie pomyłkowo wgranego dokumentu — z powodem, plik znika, ślad zostaje. */
export function RemoveDocumentDialog({
  document,
  open,
  onOpenChange,
}: {
  document: PersonDocument;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { showToast } = useToast();
  const remove = useRemoveDocument(document.user_id);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    if (!note.trim()) {
      setError("Napisz, dlaczego usuwasz dokument.");
      return;
    }
    remove.mutate(
      { id: document.id, note: note.trim() },
      {
        onSuccess: () => {
          showToast("Dokument usunięty", "success");
          onOpenChange(false);
        },
        onError: (err) => setError(apiErrorMessage(err, "Nie udało się usunąć dokumentu.")),
      },
    );
  };

  return (
    <AppModal
      open={open}
      onOpenChange={onOpenChange}
      title="Usunąć dokument?"
      description={`„${document.title}” — plik zniknie z NEXUSA, a w dokumentach zostanie ślad: kto, kiedy i dlaczego.`}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Anuluj
          </Button>
          <Button variant="destructive" onClick={submit} disabled={remove.isPending}>
            {remove.isPending ? "Usuwanie…" : "Usuń dokument"}
          </Button>
        </>
      }
    >
      <FormField label="Powód" htmlFor="hr-document-remove-note">
        <Textarea
          id="hr-document-remove-note"
          value={note}
          maxLength={500}
          rows={3}
          placeholder="np. wgrany do złej osoby"
          onChange={(event) => setNote(event.target.value)}
        />
      </FormField>
      <div className="mt-3">
        <ErrorLine error={error} />
      </div>
    </AppModal>
  );
}
