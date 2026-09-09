"use client";

/**
 * Edytor reguły CV klienta — pełna recepta Delivery Leada w czterech
 * zakładkach: „Ustawienia" (plik i język → wskazówki → zaawansowane, wszystko
 * w jednej zakładce z progresywnym odsłanianiem), „Podgląd", „Karta klienta"
 * (osobny zapis) i „Historia".
 *
 * Do 09.2026 recepta była rozbita na trzy równorzędne zakładki („Podstawy" +
 * „Generator" + „Treść i AI") z 25 polami różnej wagi na jednym poziomie — DL
 * nie wiedział, które trzy są ważne. Teraz codzienne 90% (nazwa pliku, język,
 * notatka, instrukcje) jest zawsze widoczne, a blokady/polityka/słownik siedzą
 * pod zwiniętym „Zaawansowane". Nad zakładkami pasek „Ta reguła robi" streszcza
 * efekt zwykłym językiem.
 *
 * Zmienia się układ i etykiety, NIE kontrakt zapisu: `formToPayload` nadal
 * wysyła KOMPLET pól (pominięte pole = ciche wyzerowanie na serwerze), a dwa
 * przyciski to te same wywołania co dawniej — „Zapisz i włącz regułę"
 * (confirm=true, dawne „Zapisz i zatwierdź") i „Zapisz szkic" (propozycja;
 * edycja obowiązującej reguły tą ścieżką ZDEJMUJE zatwierdzenie — robi to serwer).
 *
 * Usuwanie ma dwustopniowe potwierdzenie W KOMPONENCIE, nie `window.confirm`
 * — natywny dialog zamraża automatyzację przeglądarki, którą weryfikujemy UI.
 */

import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { extractErrorMsg } from "@/lib/api";
import { CV_CONTENT_MODES } from "@/lib/cv-generator";
import type { CvContentMode } from "@/lib/cv-generator";
import {
  countActiveAdvanced,
  cvRulesApi,
  formToPayload,
  hasStoredRule,
  ruleToForm,
  type ClientCvRule,
  type CvRuleForm,
} from "@/lib/cv-rules";
import {
  ClientSinglePicker,
  type ClientRef,
} from "@/components/clients/ClientSinglePicker";
import { TabbedNav } from "@/components/ds/TabbedNav";

import { CvRuleHistoryTab } from "./CvRuleHistoryTab";
import { CvRulePlaybookTab } from "./CvRulePlaybookTab";
import { CvRulePreviewTab } from "./CvRulePreviewTab";
import { CvRuleSettingsTab } from "./CvRuleSettingsTab";

const MODE_LABEL: Record<CvContentMode, string> = Object.fromEntries(
  CV_CONTENT_MODES.map((m) => [m.value, m.label]),
) as Record<CvContentMode, string>;

const TABS = [
  { value: "settings", label: "Ustawienia" },
  { value: "preview", label: "Podgląd" },
  { value: "playbook", label: "Karta klienta" },
  { value: "history", label: "Historia" },
];
const TAB_VALUES = new Set(TABS.map((t) => t.value));
/** `?tab=` z adresu bywa dowolnym stringiem — nieznana wartość wraca na „Ustawienia". */
function resolveInitialTab(requested?: string): string {
  return requested && TAB_VALUES.has(requested) ? requested : "settings";
}

/** Jedno zdanie „co ta reguła robi" — czytane wprost z formularza. */
function ruleSummary(form: CvRuleForm) {
  const file = form.filename_pattern.trim() || "nazwa ogólna";
  const language =
    form.cv_language === "pl"
      ? "PL"
      : form.cv_language === "en"
        ? "EN"
        : form.requires_en_copy
          ? "PL + EN"
          : "dowolny";
  const mode = !form.content_mode
    ? "wolny wybór"
    : `${MODE_LABEL[form.content_mode] ?? form.content_mode} ${
        form.content_mode_locked ? "(zablokowany)" : "(domyślny)"
      }`;
  const lines = form.generator_instructions
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean).length;
  const instructions =
    lines === 0 ? "brak" : lines === 1 ? "1 linia" : `${lines} linie`;
  return {
    file,
    language,
    mode,
    instructions,
    advanced: countActiveAdvanced(form),
  };
}

function SummaryFact({ k, v }: { k: string; v: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border bg-background px-2 py-1 text-xs">
      <span className="text-muted-foreground">{k}</span>
      <span className="font-medium">{v}</span>
    </span>
  );
}

interface Props {
  clientId: number;
  onChanged?: (rule: ClientCvRule) => void;
  onDeleted?: () => void;
  allowDelete?: boolean;
  /** Zakładka startowa (deep link `?tab=` z `/settings/cv-rules`). */
  initialTab?: string;
}

export function CvRuleEditor({
  clientId,
  onChanged,
  onDeleted,
  allowDelete = false,
  initialTab,
}: Props) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState(() => resolveInitialTab(initialTab));
  const [rule, setRule] = useState<ClientCvRule | null>(null);
  const [form, setForm] = useState<CvRuleForm | null>(null);
  const [savedForm, setSavedForm] = useState<CvRuleForm | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [copySource, setCopySource] = useState<ClientRef | null>(null);
  // Id CV próbnego trzymane TU, nie w zakładce: przełączenie zakładki
  // odmontowuje jej stan, a zadanie w tle (i dwa obciążenia kwoty) już
  // poszło — wynik musi dać się obejrzeć po powrocie.
  const [previewId, setPreviewId] = useState<number | null>(null);
  // Karta ma WŁASNY szkic w zakładce. Odmontowanie przy przełączeniu zakładki
  // (jak robią pozostałe) kasowałoby niezapisane 20 000 znaków markdownu, więc
  // po pierwszym wejściu zakładka zostaje zamontowana i tylko chowana. Montaż
  // dopiero po wejściu: edytor otwierany dla reguły nie ma strzelać po kartę.
  const [playbookVisited, setPlaybookVisited] = useState(
    () => resolveInitialTab(initialTab) === "playbook",
  );
  useEffect(() => {
    if (tab === "playbook") setPlaybookVisited(true);
  }, [tab]);

  const load = async (cancelledRef?: { current: boolean }) => {
    try {
      const res = await cvRulesApi.get(clientId);
      if (cancelledRef?.current) return;
      setRule(res);
      const f = ruleToForm(res);
      setForm(f);
      setSavedForm(f);
    } catch {
      // Awaria odczytu nie może udawać „klient nie ma reguł" — to dwie różne
      // rzeczy, a druga zaprasza do wpisania reguły, która już istnieje.
      if (!cancelledRef?.current) setLoadFailed(true);
    }
  };

  useEffect(() => {
    const cancelled = { current: false };
    setForm(null);
    setSavedForm(null);
    setRule(null);
    setError("");
    setInfo("");
    setLoadFailed(false);
    setConfirmingDelete(false);
    setCopySource(null);
    setPreviewId(null);
    // Zakładka startowa liczona TU, nie z efektu po `tab`: przy starcie na
    // karcie oba efekty biegną w jednym przebiegu i sam reset `visited`
    // zostawiłby ją niezamontowaną, mimo że jest aktywna.
    const startTab = resolveInitialTab(initialTab);
    setTab(startTab);
    setPlaybookVisited(startTab === "playbook");
    void load(cancelled);
    return () => {
      cancelled.current = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId]);

  const set = <K extends keyof CvRuleForm>(key: K, value: CvRuleForm[K]) =>
    setForm((f) => (f ? { ...f, [key]: value } : f));

  const dirty = useMemo(
    () => JSON.stringify(form) !== JSON.stringify(savedForm),
    [form, savedForm],
  );

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["settings-cv-rules"] });
    void queryClient.invalidateQueries({ queryKey: ["client-cv-rule", clientId] });
    void queryClient.invalidateQueries({ queryKey: ["cv-rule-history", clientId] });
    void queryClient.invalidateQueries({ queryKey: ["cv-rule-versions", clientId] });
    void queryClient.invalidateQueries({ queryKey: ["cv-rule-prompt-preview", clientId] });
  };

  const save = async (confirm: boolean) => {
    if (!form) return;
    setBusy(true);
    setError("");
    setInfo("");
    try {
      const res = await cvRulesApi.save(clientId, { ...formToPayload(form, confirm), expected_revision: rule?.edit_revision ?? 0 });
      setRule(res);
      const f = ruleToForm(res);
      setForm(f);
      setSavedForm(f);
      setInfo(
        confirm
          ? `Zapisano i zatwierdzono (wersja ${res.version}) — generator już stosuje tę regułę.`
          : res.is_active
            ? `Zapisano szkic. Generator nadal stosuje opublikowaną wersję ${res.version}.`
            : "Zapisano szkic. Generator zacznie go stosować dopiero po zatwierdzeniu.",
      );
      invalidate();
      onChanged?.(res);
    } catch (err) {
      setError(extractErrorMsg(err) || "Nie udało się zapisać reguły.");
    } finally {
      setBusy(false);
    }
  };

  const restoreVersion = async (version: number) => {
    if (dirty || busy) return;
    setBusy(true);
    setError("");
    try {
      const res = await cvRulesApi.restore(clientId, version, rule?.edit_revision ?? 0);
      setRule(res);
      const next = ruleToForm(res);
      setForm(next);
      setSavedForm(next);
      setTab("settings");
      setInfo(`Wersję ${version} przywrócono do szkicu. Sprawdź ją przed publikacją.`);
      invalidate();
      onChanged?.(res);
    } catch (err) {
      setError(extractErrorMsg(err) || "Nie udało się przywrócić wersji.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      await cvRulesApi.remove(clientId, rule?.edit_revision ?? 0);
      setConfirmingDelete(false);
      invalidate();
      onDeleted?.();
    } catch (err) {
      setError(extractErrorMsg(err) || "Nie udało się usunąć reguły.");
    } finally {
      setBusy(false);
    }
  };

  const copyFrom = async () => {
    if (!copySource) return;
    setBusy(true);
    setError("");
    setInfo("");
    try {
      const res = await cvRulesApi.copyFrom(clientId, copySource.id, rule?.edit_revision ?? 0);
      setRule(res);
      const f = ruleToForm(res);
      setForm(f);
      setSavedForm(f);
      setInfo(
        `Skopiowano regułę z „${copySource.name}” jako propozycję — sprawdź nazwę pliku i zatwierdź.`,
      );
      setCopySource(null);
      invalidate();
      onChanged?.(res);
    } catch (err) {
      setError(extractErrorMsg(err) || "Nie udało się skopiować reguły.");
    } finally {
      setBusy(false);
    }
  };

  if (loadFailed) {
    return (
      <p className="text-sm text-destructive">
        Nie udało się wczytać reguł CV tego klienta.
      </p>
    );
  }
  if (!form) {
    return <p className="text-sm text-muted-foreground">Ładowanie reguł CV…</p>;
  }

  const stored = hasStoredRule(rule);
  const summary = ruleSummary(form);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">
          Reguły CV{rule?.version && stored ? ` · wersja ${rule.version}` : ""}
        </h3>
        {rule?.is_active ? (
          <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-700 dark:text-emerald-400">
            {rule.draft_payload ? `Obowiązuje v${rule.version} · edytujesz szkic` : "Obowiązuje"}
          </span>
        ) : stored ? (
          <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-xs text-amber-700 dark:text-amber-400">
            Niezatwierdzona
          </span>
        ) : (
          <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            Brak reguły
          </span>
        )}
      </div>

      {/* Pasek „co ta reguła robi" — efekt zwykłym językiem, zanim DL wejdzie w pola. */}
      <div className="rounded-lg border border-primary/20 bg-primary/5 p-3">
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-primary">
          {rule?.draft_payload || dirty ? "Podsumowanie szkicu" : "Ta reguła robi"}
        </p>
        <div className="flex flex-wrap gap-2">
          <SummaryFact k="Plik" v={summary.file} />
          <SummaryFact k="Język" v={summary.language} />
          <SummaryFact k="Tryb" v={summary.mode} />
          <SummaryFact k="Instrukcje AI" v={summary.instructions} />
          <SummaryFact
            k="Zaawansowane"
            v={summary.advanced === 0 ? "brak" : `${summary.advanced} aktywne`}
          />
        </div>
      </div>

      <TabbedNav tabs={TABS} value={tab} onValueChange={setTab} ariaLabel="Sekcje reguły">
        <div className="pt-3">
          {tab === "settings" ? (
            <div className="space-y-4">
              <CvRuleSettingsTab
                form={form}
                set={set}
                clientId={clientId}
                filenamePreview={!dirty && !rule?.draft_payload ? rule?.filename_preview : null}
              />
              <div className="rounded-md border border-dashed p-3">
                <p className="mb-2 text-xs font-medium">Skopiuj regułę z innego klienta</p>
                <div className="flex flex-wrap items-center gap-2">
                  <div className="min-w-64 flex-1">
                    <ClientSinglePicker
                      value={copySource}
                      onChange={setCopySource}
                      queryKey="clients-lookup-cv-rules-copy"
                      placeholder="Klient źródłowy…"
                      allowClear
                    />
                  </div>
                  <button
                    type="button"
                    disabled={!copySource || busy}
                    onClick={copyFrom}
                    className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
                  >
                    Skopiuj jako propozycję
                  </button>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  Kopia zastępuje szkic. Opublikowana reguła pozostaje aktywna do
                  zatwierdzenia zmian; flagi klienta nie są kopiowane.
                </p>
              </div>
            </div>
          ) : null}
          {playbookVisited ? (
            <div className={tab === "playbook" ? undefined : "hidden"}>
              <CvRulePlaybookTab clientId={clientId} />
            </div>
          ) : null}
          {tab === "preview" ? (
            <CvRulePreviewTab
              clientId={clientId}
              dirty={dirty}
              previewId={previewId}
              onPreviewId={setPreviewId}
            />
          ) : null}
          {tab === "history" ? <CvRuleHistoryTab clientId={clientId} onRestore={restoreVersion} restoreDisabled={dirty || busy} /> : null}
        </div>
      </TabbedNav>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-600">{info}</p> : null}

      {/* Na zakładce karty jedynym przyciskiem zapisu ma być „Zapisz kartę"
          (w formularzu karty) — stopka reguły jest tam chowana, żeby nie
          sugerować, że „Zapisz i włącz regułę" obejmuje kartę. */}
      {tab !== "playbook" ? (
        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          <button
            type="button"
            disabled={busy}
            onClick={() => save(true)}
            className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
          >
            Zapisz i włącz regułę
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => save(false)}
            className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
          >
            Zapisz szkic
          </button>
          {dirty ? (
            <span className="text-xs text-amber-700 dark:text-amber-400">
              Niezapisane zmiany
            </span>
          ) : null}
          {allowDelete && stored ? (
            confirmingDelete ? (
              <span className="ml-auto flex items-center gap-2 text-sm">
                <span className="text-muted-foreground">Usunąć regułę?</span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={remove}
                  className="rounded-md bg-destructive px-3 py-1.5 text-sm text-destructive-foreground disabled:opacity-50"
                >
                  Tak, usuń
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => setConfirmingDelete(false)}
                  className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
                >
                  Anuluj
                </button>
              </span>
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={() => setConfirmingDelete(true)}
                className="ml-auto rounded-md px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10 disabled:opacity-50"
              >
                Usuń regułę
              </button>
            )
          ) : null}
        </div>
      ) : null}
      {rule?.confirmed_at ? (
        <p className="text-xs text-muted-foreground">
          Zatwierdzona {new Date(rule.confirmed_at).toLocaleDateString("pl-PL")}
          {rule.confirmed_by_name ? ` przez ${rule.confirmed_by_name}` : ""}.
        </p>
      ) : null}
    </div>
  );
}
