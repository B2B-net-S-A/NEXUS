"use client";

/**
 * Okno „Formularz CV klienta” (0522, 26.10.2026): wszystkie pola wzoru,
 * najpierw te do uzupełnienia, każde ze źródłem wartości („z CV”, „ze
 * screeningu i notatek”, „wpisane ręcznie”). Zapis wysyła tylko zmienione
 * pola; pusta wartość = pole do uzupełnienia. Oceny 1–10 i numery
 * certyfikatów zwykle wpisuje rekruter — model ich nie zgaduje.
 *
 * Na górze siatka lat (`ClientFormYearsGrid`, 19.11.2026): lata w
 * kompetencjach liczy serwer z dat stanowisk w CV, rekruter zdejmuje role
 * i wysyła braki do ściągi screeningu.
 *
 * Rekruter weryfikuje, nie przepisuje (23.11.2026): wolne wiersze wzoru
 * (wiersze 2–3 „Wykształcenia” przy jednych studiach) są zwinięte i nie liczą
 * się do braków (`spareFieldIds`), a „TAK/NIE” od modelu pokazuje cytat z CV.
 */

import { useMemo, useState } from "react";
import { Download, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { ClientFormYearsGrid } from "@/components/v2/recruitment/client-form/ClientFormYearsGrid";
import { spareFieldIds } from "@/components/v2/recruitment/client-form/spareRows";
import {
  CLIENT_FORM_SOURCE_LABEL,
  type ClientFormField,
  type ClientFormView,
} from "@/lib/api/clientForms";
import type { ClientFormKind } from "@/lib/api/jobFiles";
import { cn } from "@/lib/utils";

export interface ClientFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  view: ClientFormView;
  /** 0525: tabela punktowa (Excel) — inny tytuł i „Pobierz Excel”. */
  kind?: ClientFormKind;
  candidateName: string;
  readOnly?: boolean;
  saving?: boolean;
  downloading?: boolean;
  onSave: (fields: Record<string, string>) => Promise<void> | void;
  /** Siatka lat: role liczone do pól i braki do ściągi screeningu. */
  onSaveYears?: (payload: { roles?: Record<string, string[]>; ask?: string[] }) => Promise<void> | void;
  onDownload: () => void;
}

const YES_NO = /tak\s*\/\s*nie/i;

interface FieldGroup {
  title: string;
  fields: ClientFormField[];
}

/** Grupy jak we wzorze: nagłówek, potem tabele i ich sekcje, po kolei. */
function groupFields(fields: ClientFormField[]): FieldGroup[] {
  const groups: FieldGroup[] = [];
  for (const field of fields) {
    const title =
      field.kind === "line"
        ? "Dane osoby"
        : [field.table ?? (field.kind === "box" ? field.label : null), field.section]
            .filter(Boolean)
            .join(" · ") || "Formularz";
    const last = groups[groups.length - 1];
    if (last && last.title === title) last.fields.push(field);
    else groups.push({ title, fields: [field] });
  }
  return groups;
}

/** „Wiersz 2” sam nic nie mówi — dokładamy pierwszą wypełnioną komórkę wiersza (np. firmę). */
function rowContext(
  field: ClientFormField,
  fields: ClientFormField[],
  draft: Record<string, string>,
): string | null {
  if (field.kind !== "cell" || !field.row_label?.startsWith("Wiersz ")) return null;
  const row = field.id.slice(0, field.id.lastIndexOf(".c"));
  const sibling = fields.find(
    (other) =>
      other.id !== field.id &&
      other.id.startsWith(`${row}.c`) &&
      (draft[other.id] ?? "").trim() !== "",
  );
  const text = sibling ? (draft[sibling.id] ?? "").trim() : "";
  return text ? (text.length > 48 ? `${text.slice(0, 47)}…` : text) : null;
}

function FieldRow({
  field,
  value,
  context,
  disabled,
  spare = false,
  onChange,
}: {
  field: ClientFormField;
  value: string;
  context: string | null;
  disabled: boolean;
  /** Wolny wiersz wzoru — pusty to nie brak, bez ostrzegawczego koloru. */
  spare?: boolean;
  onChange: (value: string) => void;
}) {
  const empty = value.trim() === "";
  const warn = empty && !spare;
  const long = field.kind === "box" || /opis/i.test(field.label);
  // Propozycja modelu „TAK/NIE” do zatwierdzenia: cytat widać bez najeżdżania.
  const evidence =
    !empty && field.quote && value === (field.value ?? "") && YES_NO.test(field.label)
      ? field.quote
      : null;
  const source =
    !empty && field.source && value === (field.value ?? "")
      ? CLIENT_FORM_SOURCE_LABEL[field.source]
      : !empty
        ? CLIENT_FORM_SOURCE_LABEL.recruiter
        : spare
          ? "wolny wiersz"
          : "do uzupełnienia";
  const id = `client-form-${field.id}`;
  return (
    <div className="grid gap-1 py-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] sm:gap-3">
      <label htmlFor={id} className="min-w-0 text-xs">
        {field.row_label ? (
          <span className="block font-medium text-foreground">
            {context ? `${field.row_label} · ${context}` : field.row_label}
          </span>
        ) : null}
        <span className={cn(field.row_label ? "text-muted-foreground" : "font-medium text-foreground")}>
          {field.label}
        </span>
        <span
          className={cn(
            "block text-[11px]",
            warn ? "font-medium text-warning-muted-foreground" : "text-muted-foreground",
          )}
          title={field.quote ? `Źródło: „${field.quote}”` : undefined}
        >
          {source}
        </span>
        {evidence ? (
          <span className="mt-0.5 block text-[11px] italic text-muted-foreground">
            „{evidence.length > 160 ? `${evidence.slice(0, 159)}…` : evidence}”
          </span>
        ) : null}
      </label>
      <Textarea
        id={id}
        value={value}
        disabled={disabled}
        rows={long ? 3 : 1}
        className={cn("min-h-0 text-sm", warn && "border-warning bg-warning-muted/40")}
        onChange={(event) => onChange(event.target.value)}
      />
    </div>
  );
}

export function ClientFormDialog({
  open,
  onOpenChange,
  view,
  kind = "form",
  candidateName,
  readOnly = false,
  saving = false,
  downloading = false,
  onSave,
  onSaveYears,
  onDownload,
}: ClientFormDialogProps) {
  const initial = useMemo(
    () => Object.fromEntries(view.fields.map((field) => [field.id, field.value ?? ""])),
    [view.fields],
  );
  const [draft, setDraft] = useState<Record<string, string>>(initial);
  const [showFilled, setShowFilled] = useState(false);
  const [showSpare, setShowSpare] = useState(false);
  // Nowe dane z serwera (zapis, ponowne wypełnienie, „Zapisz lata”) zastępują
  // pola, których rekruter nie ruszył; niezapisany wpis w innym polu zostaje —
  // siatka lat ma własny zapis i nie może kasować reszty okna.
  const [seen, setSeen] = useState(initial);
  if (seen !== initial) {
    setSeen(initial);
    setDraft((prev) =>
      Object.fromEntries(
        Object.entries(initial).map(([id, value]) => [
          id,
          id in prev && prev[id] !== (seen[id] ?? "") ? prev[id] : value,
        ]),
      ),
    );
  }

  const changed = Object.fromEntries(
    Object.entries(draft).filter(([id, value]) => value.trim() !== (initial[id] ?? "").trim()),
  );
  // Sekcje liczy stan z serwera, nie szkic: po pierwszej literze pole
  // przeskakiwało do zwiniętych „wypełnionych” i znikało spod kursora
  // (zgłoszenie z CEZ, 23.11.2026). Przenosi się dopiero po zapisie.
  // Wolne wiersze wzoru (23.11.2026) też — nie są brakiem, okno je zwija.
  const spare = spareFieldIds(view.fields, initial);
  const spareFields = view.fields.filter((field) => spare.has(field.id));
  const spareRows = new Set(spareFields.map((field) => field.id.slice(0, field.id.lastIndexOf(".c"))))
    .size;
  const missing = view.fields.filter(
    (field) => (initial[field.id] ?? "").trim() === "" && !spare.has(field.id),
  );
  const filled = view.fields.filter((field) => (initial[field.id] ?? "").trim() !== "");
  const set = (id: string) => (value: string) => setDraft((prev) => ({ ...prev, [id]: value }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="xl" data-testid="client-form-dialog">
        <DialogHeader>
          <DialogTitle>
            {kind === "score" ? "Tabela punktowa" : "Formularz CV klienta"} · {candidateName}
          </DialogTitle>
          <DialogDescription>
            {view.template?.filename ?? "Wzór z Plików rekrutacji"} · układ pliku klienta
            zostaje bez zmian.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="max-h-[65dvh] space-y-5 overflow-y-auto">
          {onSaveYears && view.fields.some((field) => field.years) ? (
            <ClientFormYearsGrid
              fields={view.fields}
              readOnly={readOnly}
              saving={saving}
              onSaveRoles={(roles) => onSaveYears({ roles })}
              onAsk={(ask) => onSaveYears({ ask })}
            />
          ) : null}
          {missing.length > 0 ? (
            <section aria-label="Do uzupełnienia" className="space-y-1">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Do uzupełnienia · {missing.length}
              </h3>
              <p className="text-xs text-muted-foreground">
                Tego nie było w CV ani w notatkach. Oceny w skali i numery certyfikatów
                uzupełnij z kandydatem.
              </p>
              {groupFields(missing).map((group) => (
                <div key={`m-${group.title}`} className="divide-y divide-border">
                  <p className="pt-2 text-xs font-medium text-foreground">{group.title}</p>
                  {group.fields.map((field) => (
                    <FieldRow
                      key={field.id}
                      field={field}
                      value={draft[field.id] ?? ""}
                      context={rowContext(field, view.fields, draft)}
                      disabled={readOnly || saving}
                      onChange={set(field.id)}
                    />
                  ))}
                </div>
              ))}
            </section>
          ) : (
            <p className="rounded-md bg-success-muted px-3 py-2 text-sm text-success-muted-foreground">
              Wszystkie pola formularza są wypełnione.
            </p>
          )}
          {spareRows > 0 ? (
            <section aria-label="Wolne wiersze" className="space-y-1">
              <button
                type="button"
                className="text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground"
                aria-expanded={showSpare}
                onClick={() => setShowSpare((value) => !value)}
              >
                {showSpare ? "Ukryj" : "Pokaż"} wolne wiersze · {spareRows}
              </button>
              {showSpare ? (
                <>
                  <p className="text-xs text-muted-foreground">
                    Zapas we wzorze — wpisz, gdy kandydat ma więcej (np. drugie studia).
                    Puste zostają puste w pliku klienta.
                  </p>
                  {groupFields(spareFields).map((group) => (
                    <div key={`s-${group.title}`} className="divide-y divide-border">
                      <p className="pt-2 text-xs font-medium text-foreground">{group.title}</p>
                      {group.fields.map((field) => (
                        <FieldRow
                          key={field.id}
                          field={field}
                          value={draft[field.id] ?? ""}
                          context={rowContext(field, view.fields, draft)}
                          disabled={readOnly || saving}
                          spare
                          onChange={set(field.id)}
                        />
                      ))}
                    </div>
                  ))}
                </>
              ) : null}
            </section>
          ) : null}
          <section aria-label="Wypełnione" className="space-y-1">
            <button
              type="button"
              className="text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:text-foreground"
              aria-expanded={showFilled}
              onClick={() => setShowFilled((value) => !value)}
            >
              {showFilled ? "Ukryj" : "Pokaż"} wypełnione · {filled.length}
            </button>
            {showFilled
              ? groupFields(filled).map((group) => (
                  <div key={`f-${group.title}`} className="divide-y divide-border">
                    <p className="pt-2 text-xs font-medium text-foreground">{group.title}</p>
                    {group.fields.map((field) => (
                      <FieldRow
                        key={field.id}
                        field={field}
                        value={draft[field.id] ?? ""}
                        context={rowContext(field, view.fields, draft)}
                        disabled={readOnly || saving}
                        onChange={set(field.id)}
                      />
                    ))}
                  </div>
                ))
              : null}
          </section>
        </DialogBody>
        <DialogFooter className="flex-wrap gap-2">
          <p className="mr-auto text-xs text-muted-foreground">
            Model wpisuje tylko to, co jest w CV, screeningu i notatkach.
          </p>
          <Button type="button" variant="outline" disabled={downloading} onClick={onDownload}>
            {downloading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Download className="h-4 w-4" aria-hidden />
            )}
            {kind === "score" ? "Pobierz Excel" : "Pobierz Word"}
          </Button>
          {readOnly ? null : (
            <Button
              type="button"
              loading={saving}
              disabled={saving || Object.keys(changed).length === 0}
              onClick={() => void onSave(changed)}
            >
              Zapisz
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default ClientFormDialog;
