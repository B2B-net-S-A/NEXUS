"use client";

/**
 * Reguły CV klienta — formularz współdzielony przez okno edycji klienta
 * („Edytuj firmę" w profilu) i przegląd zbiorczy w Ustawieniach
 * (`/settings/cv-rules`).
 *
 * Świadomie NIE jest częścią payloadu PATCH klienta i nie siedzi
 * w `ClientFormFields`: tamten komponent jest współdzielony z oknem
 * DODAWANIA klienta, a zakładanie reguł przy tworzeniu firmy oznaczałoby
 * regułę bez świadomej decyzji (i bez szansy porównania jej z szablonem
 * Championa). Reguła ma własną tabelę, własne endpointy i własny zapis.
 *
 * Dwa przyciski zapisu, bo są dwie różne sytuacje:
 *
 *  * „Zapisz i zatwierdź" — reguła wpisana świadomie przez Delivery Leada /
 *    TAC-a JEST jego decyzją. Osobne kliknięcie „Zatwierdź" nie dodawało
 *    żadnej weryfikacji, a gubiło ludzi: zapisana i niezatwierdzona reguła
 *    wygląda w generatorze dokładnie jak jej brak.
 *  * „Zapisz jako propozycję" — wersja robocza, której autor nie chce jeszcze
 *    włączyć. Edycja obowiązującej reguły tą ścieżką ZDEJMUJE zatwierdzenie
 *    (robi to serwer): zmiana wzoru nazwy pliku nie wchodzi na produkcję bez
 *    decyzji.
 *
 * Usuwanie ma dwustopniowe potwierdzenie W KOMPONENCIE, nie `window.confirm`
 * — natywny dialog zamraża automatyzację przeglądarki, którą weryfikujemy UI.
 *
 * Dwa wolne pola i to nie jest duplikat: `notes` czyta CZŁOWIEK (baner
 * w generatorze), `generator_instructions` czyta MODEL (blok
 * `<client_presentation_rules>` w prompcie). Reguła szukania („kandydatów
 * z bankowości rozważamy w pierwszej kolejności") należy do notatki — w polu
 * dla modelu byłaby zaproszeniem do koloryzowania doświadczenia bankowego.
 */

import { useEffect, useState } from "react";

// Import DOMYŚLNY, nie nazwany: istniejące testy modali mockują
// „@/lib/api" w całości i wystawiają wyłącznie `default` — nazwany `api`
// byłby tam `undefined`, a komponent wywracałby cudze testy.
import api from "@/lib/api";

const TOKENS = ["{STANOWISKO}", "{IMIE_NAZWISKO}", "{PROJEKT}", "{DATA}"];

export interface ClientCvRuleForm {
  filename_pattern: string;
  spaces_to_underscores: boolean;
  cv_language: "" | "pl" | "en";
  requires_en_copy: boolean;
  requires_rodo_consent_block: boolean;
  notes: string;
  generator_instructions: string;
}

export const GENERATOR_INSTRUCTIONS_MAX_LENGTH = 2000;

export interface ClientCvRuleResponse {
  client_id: number;
  client_name: string | null;
  filename_pattern: string | null;
  spaces_to_underscores: boolean;
  cv_language: "pl" | "en" | null;
  requires_en_copy: boolean;
  requires_rodo_consent_block: boolean;
  notes: string | null;
  /** Jedyne pole reguły, które trafia do promptu generatora. */
  generator_instructions: string | null;
  seed_key: string | null;
  is_active: boolean;
  confirmed_at: string | null;
  confirmed_by_name: string | null;
  /** `null` = klient nie ma wiersza reguły; `""` = wiersz jest, ale nie
   * obowiązuje; niepusty = opis zastosowanej polityki. */
  client_policy: string | null;
  filename_preview: string | null;
}

/** Czy odpowiedź opisuje ISTNIEJĄCY wiersz (także niezatwierdzony). */
export function hasStoredRule(rule: ClientCvRuleResponse | null): boolean {
  return rule !== null && rule.client_policy !== null;
}

interface Props {
  clientId: number;
  /** Po każdym udanym zapisie — przegląd zbiorczy odświeża listę. */
  onChanged?: (rule: ClientCvRuleResponse) => void;
  /** Po usunięciu reguły. */
  onDeleted?: () => void;
  /** Pokaż „Usuń regułę". Okno edycji klienta go nie ma — tam usuwanie reguły
   * obok pól firmy czytałoby się jak usuwanie klienta. */
  allowDelete?: boolean;
}

function errorDetail(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const first = detail[0] as { msg?: unknown } | undefined;
    if (first && typeof first.msg === "string") return first.msg;
  }
  return fallback;
}

export function ClientCvRulesSection({
  clientId,
  onChanged,
  onDeleted,
  allowDelete = false,
}: Props) {
  const [form, setForm] = useState<ClientCvRuleForm | null>(null);
  const [rule, setRule] = useState<ClientCvRuleResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setForm(null);
    setRule(null);
    setError("");
    setInfo("");
    setLoadFailed(false);
    setConfirmingDelete(false);
    (async () => {
      try {
        const res = await api.get<ClientCvRuleResponse>(
          `/api/clients/${clientId}/cv-rule`,
        );
        if (cancelled) return;
        setRule(res.data);
        setForm({
          filename_pattern: res.data.filename_pattern ?? "",
          spaces_to_underscores: res.data.spaces_to_underscores,
          cv_language: res.data.cv_language ?? "",
          requires_en_copy: res.data.requires_en_copy,
          requires_rodo_consent_block: res.data.requires_rodo_consent_block,
          notes: res.data.notes ?? "",
          generator_instructions: res.data.generator_instructions ?? "",
        });
      } catch {
        // Awaria odczytu nie może udawać „klient nie ma reguł" — to dwie różne
        // rzeczy, a druga zaprasza do wpisania reguły, która już istnieje.
        if (!cancelled) setLoadFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [clientId]);

  const set = <K extends keyof ClientCvRuleForm>(
    key: K,
    value: ClientCvRuleForm[K],
  ) => setForm((f) => (f ? { ...f, [key]: value } : f));

  const save = async (confirm: boolean) => {
    if (!form) return;
    setBusy(true);
    setError("");
    setInfo("");
    try {
      const res = await api.put<ClientCvRuleResponse>(
        `/api/clients/${clientId}/cv-rule`,
        {
          filename_pattern: form.filename_pattern.trim() || null,
          spaces_to_underscores: form.spaces_to_underscores,
          cv_language: form.cv_language || null,
          requires_en_copy: form.requires_en_copy,
          requires_rodo_consent_block: form.requires_rodo_consent_block,
          notes: form.notes.trim() || null,
          generator_instructions: form.generator_instructions.trim() || null,
          confirm,
        },
      );
      setRule(res.data);
      setInfo(
        confirm
          ? "Zapisano i zatwierdzono — generator już stosuje tę regułę."
          : "Zapisano jako propozycję. Generator zacznie ją stosować dopiero po zatwierdzeniu.",
      );
      onChanged?.(res.data);
    } catch (err) {
      setError(errorDetail(err, "Nie udało się zapisać reguły."));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      await api.delete(`/api/clients/${clientId}/cv-rule`);
      setConfirmingDelete(false);
      onDeleted?.();
    } catch (err) {
      setError(errorDetail(err, "Nie udało się usunąć reguły."));
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
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">Reguły CV</h3>
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

      <div>
        <label className="mb-1 block text-xs font-medium" htmlFor="cvrule-pattern">
          Wzór nazwy pliku CV
        </label>
        <input
          id="cvrule-pattern"
          value={form.filename_pattern}
          onChange={(e) => set("filename_pattern", e.target.value)}
          placeholder="B2B_{STANOWISKO}_{IMIE_NAZWISKO}"
          maxLength={300}
          className="w-full rounded-md border px-3 py-2 font-mono text-sm"
        />
        <p className="mt-1 text-xs text-muted-foreground">
          Dostępne pola: {TOKENS.join(", ")}. Puste = nazwa ogólna.
        </p>
        {rule?.filename_preview ? (
          <p className="mt-1 text-xs text-muted-foreground">
            Przykład: <span className="font-mono">{rule.filename_preview}</span>
          </p>
        ) : null}
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.spaces_to_underscores}
          onChange={(e) => set("spaces_to_underscores", e.target.checked)}
        />
        Spacje w nazwie zamień na podkreślenia
      </label>

      <div>
        <label className="mb-1 block text-xs font-medium" htmlFor="cvrule-lang">
          Wymagany język CV
        </label>
        <select
          id="cvrule-lang"
          value={form.cv_language}
          onChange={(e) =>
            set("cv_language", e.target.value as ClientCvRuleForm["cv_language"])
          }
          className="rounded-md border px-3 py-2 text-sm"
        >
          <option value="">Bez wymogu</option>
          <option value="pl">Tylko polski</option>
          <option value="en">Tylko angielski</option>
        </select>
        <p className="mt-1 text-xs text-muted-foreground">
          Zostaw „bez wymogu", gdy klient oczekuje OBU wersji — wymuszenie
          jednego języka zablokowałoby wygenerowanie drugiej.
        </p>
      </div>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.requires_en_copy}
          onChange={(e) => set("requires_en_copy", e.target.checked)}
        />
        Klient oczekuje CV po polsku ORAZ po angielsku
      </label>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.requires_rodo_consent_block}
          onChange={(e) =>
            set("requires_rodo_consent_block", e.target.checked)
          }
        />
        Wymagany zrzut zgody kandydata na dole CV
      </label>

      <div>
        <label className="mb-1 block text-xs font-medium" htmlFor="cvrule-notes">
          Pozostałe standardy klienta (notatka dla rekrutera)
        </label>
        <textarea
          id="cvrule-notes"
          value={form.notes}
          onChange={(e) => set("notes", e.target.value)}
          rows={3}
          className="w-full rounded-md border px-3 py-2 text-sm"
          placeholder="SLA, off-limit, limity rekomendacji, dokumenty onboardingowe…"
        />
        <p className="mt-1 text-xs text-muted-foreground">
          Rekruter zobaczy tę notatkę w generatorze CV po wybraniu klienta.
          Trafia do człowieka, nie do modelu AI.
        </p>
      </div>

      <div>
        <label
          className="mb-1 block text-xs font-medium"
          htmlFor="cvrule-instructions"
        >
          Instrukcje dla generatora AI
        </label>
        <textarea
          id="cvrule-instructions"
          value={form.generator_instructions}
          onChange={(e) => set("generator_instructions", e.target.value)}
          rows={4}
          maxLength={GENERATOR_INSTRUCTIONS_MAX_LENGTH}
          className="w-full rounded-md border px-3 py-2 text-sm"
          placeholder={
            "Np. maks. 3 projekty na stanowisko; bez sekcji zainteresowań; " +
            "opisy obowiązków do 2 zdań; daty w formacie MM.RRRR"
          }
        />
        <p className="mt-1 text-xs text-muted-foreground">
          Generator stosuje je do KAŻDEGO CV dla tego klienta — ale wyłącznie
          do doboru i formy faktów, które kandydat ma w CV lub notatkach ze
          screeningu (co pominąć, co wyeksponować, jak długo, jakim stylem).
          Polecenie dopisania technologii, obowiązku czy lat doświadczenia
          model ignoruje i zgłasza w ostrzeżeniach. Układ dokumentu (szablon
          DOCX) się nie zmienia.
          {" "}
          {form.generator_instructions.length}/{GENERATOR_INSTRUCTIONS_MAX_LENGTH}
        </p>
      </div>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-600">{info}</p> : null}

      <div className="flex flex-wrap items-center gap-2">
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
          Zatwierdzona{" "}
          {new Date(rule.confirmed_at).toLocaleDateString("pl-PL")}
          {rule.confirmed_by_name ? ` przez ${rule.confirmed_by_name}` : ""}.
        </p>
      ) : null}
    </div>
  );
}
