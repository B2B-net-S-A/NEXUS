"use client";

/**
 * Formularz karty klienta — JEDEN komponent w dwóch miejscach (D4):
 * zakładka „Karta klienta" w edytorze reguł CV (`CvRulePlaybookTab`) i edycja
 * w miejscu w profilu klienta (`ClientPlaybookTab`). Samowystarczalny:
 * własny odczyt, zapis i historia — komponent osadzający nie dubluje ani
 * walidacji, ani zapisu.
 *
 * Niezależny od reguły CV: „Zapisz kartę" zapisuje tylko kartę i nie wymaga
 * zatwierdzenia (zapis = obowiązuje, D2). Off-limit jest TYLKO DO ODCZYTU —
 * pochodzi z warunków umowy ramowej (zakładka Umowy), nie z karty.
 *
 * Awaria odczytu ma własną gałąź — nie może udawać „klient nie ma karty",
 * bo to zaprasza do wpisania karty, która już istnieje. Delivery Lead spoza
 * zespołu klienta widzi formularz (capability po roli), a zapis dostaje 403
 * z grafu klienta — komunikat ląduje inline, jak w regułach CV po #1351.
 * Nie „naprawiaj" tego bramką po portfelu po stronie frontu.
 */

import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "@/components/ui/button";
import { extractErrorMsg } from "@/lib/api";
import {
  CLIENT_PLAYBOOKS_OVERVIEW_KEY,
  clientPlaybooksApi,
  formatOffLimits,
  playbookFormToPayload,
  playbookToForm,
  useClientPlaybookHistory,
  PLAYBOOK_EVENT_LABELS,
  PLAYBOOK_FIELD_LABELS,
  PLAYBOOK_LIMITS,
  type ClientPlaybook,
  type PlaybookEvent,
  type PlaybookForm,
} from "@/lib/client-playbooks";

export interface ClientPlaybookFormProps {
  clientId: number;
  /** Po udanym zapisie (profil klienta wraca z formularza do karty). */
  onSaved?: (playbook: ClientPlaybook) => void;
}

const FIELD_CLASS = "w-full rounded-md border px-3 py-2 text-sm";

export function ClientPlaybookForm({ clientId, onSaved }: ClientPlaybookFormProps) {
  const queryClient = useQueryClient();
  const [playbook, setPlaybook] = useState<ClientPlaybook | null>(null);
  const [form, setForm] = useState<PlaybookForm | null>(null);
  const [savedForm, setSavedForm] = useState<PlaybookForm | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);
  const history = useClientPlaybookHistory(clientId);

  // Odczyt INLINE w efekcie — bez eslint-disable na exhaustive-deps.
  useEffect(() => {
    let cancelled = false;
    setForm(null);
    setSavedForm(null);
    setPlaybook(null);
    setError("");
    setInfo("");
    setLoadFailed(false);
    clientPlaybooksApi
      .get(clientId)
      .then((res) => {
        if (cancelled) return;
        setPlaybook(res);
        const f = playbookToForm(res);
        setForm(f);
        setSavedForm(f);
      })
      .catch(() => {
        // Awaria ≠ „brak karty".
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [clientId]);

  const set = <K extends keyof PlaybookForm>(key: K, value: PlaybookForm[K]) =>
    setForm((f) => (f ? { ...f, [key]: value } : f));

  const dirty = useMemo(
    () => JSON.stringify(form) !== JSON.stringify(savedForm),
    [form, savedForm],
  );

  const save = async () => {
    if (!form) return;
    setBusy(true);
    setError("");
    setInfo("");
    try {
      const res = await clientPlaybooksApi.save(clientId, playbookFormToPayload(form));
      setPlaybook(res);
      const f = playbookToForm(res);
      setForm(f);
      setSavedForm(f);
      setInfo(`Zapisano kartę (wersja ${res.version}).`);
      void queryClient.invalidateQueries({ queryKey: ["client-playbook", clientId] });
      void queryClient.invalidateQueries({ queryKey: CLIENT_PLAYBOOKS_OVERVIEW_KEY });
      void queryClient.invalidateQueries({
        queryKey: ["client-playbook-history", clientId],
      });
      onSaved?.(res);
    } catch (err) {
      setError(extractErrorMsg(err) || "Nie udało się zapisać karty klienta.");
    } finally {
      setBusy(false);
    }
  };

  if (loadFailed) {
    return (
      <p className="text-sm text-destructive">Nie udało się wczytać karty klienta.</p>
    );
  }
  if (!form) {
    return <p className="text-sm text-muted-foreground">Ładowanie karty klienta…</p>;
  }

  const updateDocument = (index: number, patch: Partial<PlaybookForm["documents"][number]>) =>
    set(
      "documents",
      form.documents.map((doc, i) => (i === index ? { ...doc, ...patch } : doc)),
    );

  return (
    <div className="space-y-4" data-testid="client-playbook-form">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold">
          {`Karta klienta${playbook?.exists ? ` · wersja ${playbook.version}` : ""}`}
        </h4>
        {playbook?.exists ? (
          <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-700 dark:text-emerald-400">
            Założona
          </span>
        ) : (
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            Brak karty
          </span>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        Karta jest niezależna od reguły CV: „Zapisz kartę" zapisuje tylko tę
        zakładkę i nie wymaga zatwierdzenia.
      </p>

      <fieldset className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <legend className="mb-1 text-xs font-medium">Liczby</legend>
        <NumberField
          id="playbook-sla-days"
          label={PLAYBOOK_FIELD_LABELS.sla_business_days}
          value={form.sla_business_days}
          onChange={(v) => set("sla_business_days", v)}
        />
        <NumberField
          id="playbook-sla-min"
          label={PLAYBOOK_FIELD_LABELS.sla_min_candidates}
          value={form.sla_min_candidates}
          onChange={(v) => set("sla_min_candidates", v)}
        />
        <NumberField
          id="playbook-cv-limit"
          label={PLAYBOOK_FIELD_LABELS.cv_limit_per_process}
          value={form.cv_limit_per_process}
          onChange={(v) => set("cv_limit_per_process", v)}
        />
        <NumberField
          id="playbook-hold-hours"
          label={PLAYBOOK_FIELD_LABELS.hold_hours}
          value={form.hold_hours}
          onChange={(v) => set("hold_hours", v)}
        />
        <NumberField
          id="playbook-cooldown-days"
          label={PLAYBOOK_FIELD_LABELS.multi_project_cooldown_days}
          value={form.multi_project_cooldown_days}
          onChange={(v) => set("multi_project_cooldown_days", v)}
        />
      </fieldset>

      {/* Off-limit — TYLKO ODCZYT (precedens: język CV w edytorze Championa).
          Źródłem prawdy jest umowa ramowa; edytowalne pole obok niej byłoby
          drugim źródłem, które przy pierwszej zmianie zaczyna kłamać. */}
      <div>
        <span className="mb-1 block text-xs font-medium">{PLAYBOOK_FIELD_LABELS.off_limits}</span>
        <div
          className="flex items-center rounded-md border bg-muted/60 px-3 py-2 text-sm"
          data-testid="playbook-off-limits"
        >
          {formatOffLimits(playbook?.off_limits ?? null) ?? (
            <span className="text-muted-foreground">
              brak — ustala się w warunkach umowy
            </span>
          )}
        </div>
        {playbook?.off_limits?.notes ? (
          <p className="mt-1 text-xs text-muted-foreground">{playbook.off_limits.notes}</p>
        ) : null}
      </div>

      <div>
        <label htmlFor="playbook-rate-policy" className="mb-1 block text-xs font-medium">
          {PLAYBOOK_FIELD_LABELS.rate_policy}
        </label>
        <input
          id="playbook-rate-policy"
          value={form.rate_policy}
          onChange={(e) => set("rate_policy", e.target.value)}
          maxLength={PLAYBOOK_LIMITS.rate_policy}
          placeholder="np. Nie przekraczamy stawek umownych; wyjątek: architekci."
          className={FIELD_CLASS}
        />
        <p className="mt-1 text-xs text-muted-foreground">
          {form.rate_policy.length}/{PLAYBOOK_LIMITS.rate_policy}
        </p>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div>
          <label htmlFor="playbook-about" className="mb-1 block text-xs font-medium">
            {PLAYBOOK_FIELD_LABELS.about_for_candidate}
          </label>
          <textarea
            id="playbook-about"
            rows={4}
            value={form.about_for_candidate}
            onChange={(e) => set("about_for_candidate", e.target.value)}
            maxLength={PLAYBOOK_LIMITS.text}
            placeholder="Np. skandynawski bank, zespoły produktowe, praca po angielsku…"
            className={FIELD_CLASS}
          />
          <p className="mt-1 text-xs text-muted-foreground">
            {form.about_for_candidate.length}/{PLAYBOOK_LIMITS.text}
          </p>
        </div>
        <div>
          <label htmlFor="playbook-priority" className="mb-1 block text-xs font-medium">
            {PLAYBOOK_FIELD_LABELS.priority_rules}
          </label>
          <textarea
            id="playbook-priority"
            rows={3}
            value={form.priority_rules}
            onChange={(e) => set("priority_rules", e.target.value)}
            maxLength={PLAYBOOK_LIMITS.text}
            placeholder="np. kandydaci z bankowością w pierwszej kolejności"
            className={FIELD_CLASS}
          />
          <p className="mt-1 text-xs text-muted-foreground">
            {form.priority_rules.length}/{PLAYBOOK_LIMITS.text}
          </p>
        </div>
      </div>

      <MarkdownField
        id="playbook-process"
        label={PLAYBOOK_FIELD_LABELS.process_rules_md}
        value={form.process_rules_md}
        onChange={(v) => set("process_rules_md", v)}
      />
      <MarkdownField
        id="playbook-onboarding"
        label={PLAYBOOK_FIELD_LABELS.onboarding_md}
        value={form.onboarding_md}
        onChange={(v) => set("onboarding_md", v)}
      />

      <fieldset className="space-y-2">
        <legend className="text-xs font-medium">{PLAYBOOK_FIELD_LABELS.documents}</legend>
        <ul className="space-y-2">
          {form.documents.map((doc, index) => (
            <li key={index} className="flex flex-wrap items-center gap-2">
              <input
                aria-label={`Dokument ${index + 1}: nazwa`}
                value={doc.name}
                maxLength={200}
                placeholder="np. NDA klienta"
                className="w-56 rounded-md border px-2 py-1 text-sm"
                onChange={(e) => updateDocument(index, { name: e.target.value })}
              />
              <input
                aria-label={`Dokument ${index + 1}: link`}
                type="url"
                value={doc.url}
                maxLength={2000}
                placeholder="https://b2bnetsa.sharepoint.com/…"
                className="min-w-64 flex-1 rounded-md border px-2 py-1 text-sm"
                onChange={(e) => updateDocument(index, { url: e.target.value })}
              />
              <button
                type="button"
                className="text-xs text-destructive hover:underline"
                onClick={() =>
                  set(
                    "documents",
                    form.documents.filter((_, i) => i !== index),
                  )
                }
              >
                usuń
              </button>
            </li>
          ))}
        </ul>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={form.documents.length >= PLAYBOOK_LIMITS.documents}
          onClick={() => set("documents", [...form.documents, { name: "", url: "" }])}
        >
          Dodaj dokument
        </Button>
        <p className="text-xs text-muted-foreground">
          Wiersz bez nazwy albo bez linku nie zostanie zapisany.
        </p>
      </fieldset>

      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {info ? (
        <p role="status" className="text-sm text-emerald-600">
          {info}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center gap-2 border-t pt-3">
        <button
          type="button"
          disabled={busy}
          onClick={save}
          className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
        >
          Zapisz kartę
        </button>
        {dirty ? (
          <span className="text-xs text-amber-700 dark:text-amber-400">
            Niezapisane zmiany karty
          </span>
        ) : null}
      </div>

      <section className="space-y-2" data-testid="playbook-history">
        <h5 className="text-xs font-medium">Historia karty (ostatnie 10)</h5>
        {history.isError ? (
          <p className="text-xs text-destructive">Nie udało się pobrać historii karty.</p>
        ) : !history.isSuccess ? (
          <p className="text-xs text-muted-foreground">Ładowanie…</p>
        ) : history.data.length === 0 ? (
          <p className="text-xs text-muted-foreground">Brak wpisów.</p>
        ) : (
          <ul className="divide-y rounded-md border">
            {history.data.map((event) => (
              <li key={event.id} className="p-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">
                    {PLAYBOOK_EVENT_LABELS[event.action] ?? event.action}
                  </span>
                  <span className="rounded-full border px-2 text-xs text-muted-foreground">
                    {`v${event.playbook_version}`}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {`${formatDate(event.created_at)}${event.actor_name ? ` · ${event.actor_name}` : ""}`}
                  </span>
                </div>
                <ChangeList event={event} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

// ── Pola ────────────────────────────────────────────────────────────────────

function NumberField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium">
        {label}
      </label>
      <input
        id={id}
        type="number"
        min={0}
        step={1}
        inputMode="numeric"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="—"
        className={FIELD_CLASS}
      />
    </div>
  );
}

/** Markdown bez TipTapa: textarea + podgląd na żywo (wzorzec `ProcedureEditorModal`). */
function MarkdownField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      <div className="space-y-2">
        <label htmlFor={id} className="block text-xs font-medium">
          {label}
        </label>
        <textarea
          id={id}
          rows={12}
          value={value}
          maxLength={PLAYBOOK_LIMITS.markdown}
          onChange={(e) => onChange(e.target.value)}
          placeholder={"## Etapy\n1. Screening HR\n2. Zadanie techniczne"}
          className="w-full rounded-md border px-3 py-2 font-mono text-xs"
        />
        <p className="text-xs text-muted-foreground">
          {value.length}/{PLAYBOOK_LIMITS.markdown}
        </p>
      </div>
      <div className="space-y-2">
        <span className="block text-xs font-medium">Podgląd</span>
        <div
          aria-live="polite"
          className="min-h-[200px] max-h-[400px] overflow-y-auto rounded-lg border border-border bg-background p-4 prose prose-sm max-w-none prose-headings:font-semibold prose-headings:text-foreground prose-a:text-primary"
        >
          {value.trim() ? (
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
          ) : (
            <p className="text-xs text-muted-foreground">
              Zacznij pisać, żeby zobaczyć podgląd.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Historia ────────────────────────────────────────────────────────────────

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "short" });
}

const DIFF_VALUE_MAX = 120;

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "tak" : "nie";
  if (Array.isArray(value)) {
    const parts = value.map((v) =>
      v && typeof v === "object" && "name" in (v as object)
        ? String((v as { name: unknown }).name)
        : String(v),
    );
    return parts.join(", ") || "—";
  }
  if (typeof value === "object") return JSON.stringify(value);
  const text = String(value);
  return text.length > DIFF_VALUE_MAX ? `${text.slice(0, DIFF_VALUE_MAX - 1)}…` : text;
}

function ChangeList({ event }: { event: PlaybookEvent }) {
  const entries = Object.entries(event.changes ?? {});
  if (entries.length === 0) return null;
  return (
    <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
      {entries.map(([field, change]) => {
        const label = PLAYBOOK_FIELD_LABELS[field] ?? field;
        if (
          change &&
          typeof change === "object" &&
          "from" in (change as object) &&
          "to" in (change as object)
        ) {
          return (
            <li key={field}>
              <span className="font-medium text-foreground">{label}:</span>{" "}
              <span className="line-through">{renderValue(change.from)}</span> →{" "}
              {renderValue(change.to)}
            </li>
          );
        }
        return (
          <li key={field}>
            <span className="font-medium text-foreground">{label}:</span>{" "}
            {renderValue(change)}
          </li>
        );
      })}
    </ul>
  );
}
