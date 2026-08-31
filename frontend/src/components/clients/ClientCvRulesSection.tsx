"use client";

/**
 * Reguły CV klienta w oknie edycji klienta.
 *
 * Świadomie NIE jest częścią payloadu PATCH klienta i nie siedzi
 * w `ClientFormFields`: tamten komponent jest współdzielony z oknem
 * DODAWANIA klienta, a zakładanie reguł przy tworzeniu firmy oznaczałoby
 * regułę bez świadomej decyzji (i bez szansy porównania jej z szablonem
 * Championa). Reguła ma własną tabelę, własne endpointy i własny zapis.
 *
 * Zapis NIE zatwierdza. Zatwierdzenie jest osobnym kliknięciem, bo dopiero ono
 * sprawia, że generator zaczyna używać wzoru — a błędny wzór to plik nazwany
 * inaczej, niż wymaga tego klient, wykryty dopiero po wysyłce.
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
}

interface RuleResponse {
  filename_pattern: string | null;
  spaces_to_underscores: boolean;
  cv_language: "pl" | "en" | null;
  requires_en_copy: boolean;
  requires_rodo_consent_block: boolean;
  notes: string | null;
  is_active: boolean;
  confirmed_at: string | null;
  confirmed_by_name: string | null;
  filename_preview: string | null;
}

export function ClientCvRulesSection({ clientId }: { clientId: number }) {
  const [form, setForm] = useState<ClientCvRuleForm | null>(null);
  const [rule, setRule] = useState<RuleResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.get<RuleResponse>(
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

  const save = async () => {
    if (!form) return;
    setBusy(true);
    setError("");
    setInfo("");
    try {
      const res = await api.put<RuleResponse>(
        `/api/clients/${clientId}/cv-rule`,
        {
          filename_pattern: form.filename_pattern.trim() || null,
          spaces_to_underscores: form.spaces_to_underscores,
          cv_language: form.cv_language || null,
          requires_en_copy: form.requires_en_copy,
          requires_rodo_consent_block: form.requires_rodo_consent_block,
          notes: form.notes.trim() || null,
        },
      );
      setRule(res.data);
      setInfo(
        "Zapisano. Reguła zacznie działać dopiero po zatwierdzeniu.",
      );
    } catch (err) {
      setError(
        (err as { response?: { data?: { detail?: unknown } } })?.response?.data
          ?.detail?.toString?.() ?? "Nie udało się zapisać reguły.",
      );
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      const res = await api.post<RuleResponse>(
        `/api/clients/${clientId}/cv-rule/confirm`,
      );
      setRule(res.data);
      setInfo("Reguła zatwierdzona — generator już jej używa.");
    } catch {
      setError("Nie udało się zatwierdzić reguły.");
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

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">Reguły CV</h3>
        {rule?.is_active ? (
          <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-700 dark:text-emerald-400">
            Obowiązuje
          </span>
        ) : (
          <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-xs text-amber-700 dark:text-amber-400">
            Niezatwierdzona
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
          Pozostałe standardy klienta (notatka)
        </label>
        <textarea
          id="cvrule-notes"
          value={form.notes}
          onChange={(e) => set("notes", e.target.value)}
          rows={3}
          className="w-full rounded-md border px-3 py-2 text-sm"
          placeholder="SLA, off-limit, limity rekomendacji, dokumenty onboardingowe…"
        />
      </div>

      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-600">{info}</p> : null}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={save}
          className="rounded-md border px-3 py-1.5 text-sm disabled:opacity-50"
        >
          Zapisz reguły
        </button>
        <button
          type="button"
          disabled={busy || rule?.is_active === true}
          onClick={confirm}
          className="rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-50"
        >
          Zatwierdź
        </button>
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
