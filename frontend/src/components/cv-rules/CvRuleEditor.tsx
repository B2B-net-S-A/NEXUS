"use client";

/**
 * Edytor reguły CV klienta — pełna recepta Delivery Leada w pięciu zakładkach.
 *
 * Jeden ekran prowadzi wszystko, co decyduje o CV u klienta: nazwę pliku
 * i język (0255), instrukcje dla modelu (0266), blokady dla rekrutera,
 * politykę prezentacji egzekwowaną w kodzie, słownik, podgląd promptu, CV
 * próbne, historię i sygnał zwrotny (0267). Okno „Edytuj firmę" w profilu
 * klienta już formularza nie ma — odsyła tutaj.
 *
 * Dwa przyciski zapisu, bo są dwie różne sytuacje:
 *  * „Zapisz i zatwierdź" — reguła wpisana świadomie przez DL JEST decyzją;
 *  * „Zapisz jako propozycję" — wersja robocza; edycja obowiązującej reguły tą
 *    ścieżką ZDEJMUJE zatwierdzenie (robi to serwer).
 *
 * Usuwanie ma dwustopniowe potwierdzenie W KOMPONENCIE, nie `window.confirm`
 * — natywny dialog zamraża automatyzację przeglądarki, którą weryfikujemy UI.
 */

import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { extractErrorMsg } from "@/lib/api";
import {
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

import { CvRuleBasicsTab } from "./CvRuleBasicsTab";
import { CvRuleContentTab } from "./CvRuleContentTab";
import { CvRuleGeneratorTab } from "./CvRuleGeneratorTab";
import { CvRuleHistoryTab } from "./CvRuleHistoryTab";
import { CvRulePreviewTab } from "./CvRulePreviewTab";

const TABS = [
  { value: "basics", label: "Podstawy" },
  { value: "generator", label: "Generator" },
  { value: "content", label: "Treść i AI" },
  { value: "preview", label: "Podgląd" },
  { value: "history", label: "Historia" },
];

interface Props {
  clientId: number;
  onChanged?: (rule: ClientCvRule) => void;
  onDeleted?: () => void;
  allowDelete?: boolean;
}

export function CvRuleEditor({ clientId, onChanged, onDeleted, allowDelete = false }: Props) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState("basics");
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
    setTab("basics");
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
    void queryClient.invalidateQueries({ queryKey: ["cv-rule-prompt-preview", clientId] });
  };

  const save = async (confirm: boolean) => {
    if (!form) return;
    setBusy(true);
    setError("");
    setInfo("");
    try {
      const res = await cvRulesApi.save(clientId, formToPayload(form, confirm));
      setRule(res);
      const f = ruleToForm(res);
      setForm(f);
      setSavedForm(f);
      setInfo(
        confirm
          ? `Zapisano i zatwierdzono (wersja ${res.version}) — generator już stosuje tę regułę.`
          : `Zapisano jako propozycję (wersja ${res.version}). Generator zacznie ją stosować dopiero po zatwierdzeniu.`,
      );
      invalidate();
      onChanged?.(res);
    } catch (err) {
      setError(extractErrorMsg(err) || "Nie udało się zapisać reguły.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      await cvRulesApi.remove(clientId);
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
      const res = await cvRulesApi.copyFrom(clientId, copySource.id);
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

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">
          Reguły CV{rule?.version && stored ? ` · wersja ${rule.version}` : ""}
        </h3>
        {rule?.is_active ? (
          <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-700 dark:text-emerald-400">
            Obowiązuje
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

      <TabbedNav tabs={TABS} value={tab} onValueChange={setTab} ariaLabel="Sekcje reguły">
        <div className="pt-3">
          {tab === "basics" ? (
            <div className="space-y-4">
              <CvRuleBasicsTab form={form} set={set} filenamePreview={rule?.filename_preview} />
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
                  Kopia nadpisuje pola tej reguły i NIE jest zatwierdzana — sufit
                  trybu i interaktywne CV zostają takie, jakie są u tego klienta.
                </p>
              </div>
            </div>
          ) : null}
          {tab === "generator" ? <CvRuleGeneratorTab form={form} set={set} /> : null}
          {tab === "content" ? (
            <CvRuleContentTab form={form} set={set} clientId={clientId} />
          ) : null}
          {tab === "preview" ? (
            <CvRulePreviewTab
              clientId={clientId}
              dirty={dirty}
              previewId={previewId}
              onPreviewId={setPreviewId}
            />
          ) : null}
          {tab === "history" ? <CvRuleHistoryTab clientId={clientId} /> : null}
        </div>
      </TabbedNav>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-600">{info}</p> : null}

      <div className="flex flex-wrap items-center gap-2 border-t pt-3">
        <button
          type="button"
          disabled={busy}
          onClick={() => save(true)}
          className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
        >
          Zapisz i zatwierdź
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => save(false)}
          className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
        >
          Zapisz jako propozycję
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
      {rule?.confirmed_at ? (
        <p className="text-xs text-muted-foreground">
          Zatwierdzona {new Date(rule.confirmed_at).toLocaleDateString("pl-PL")}
          {rule.confirmed_by_name ? ` przez ${rule.confirmed_by_name}` : ""}.
        </p>
      ) : null}
    </div>
  );
}
