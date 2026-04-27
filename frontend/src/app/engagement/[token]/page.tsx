"use client";

/**
 * Public self-service deklaracja „Otwartość na dodatkowe projekty".
 *
 * Phase „Otwartość" Faza 2.6. Magic-link wygenerowany przez rekrutera
 * (POST /api/candidates/{id}/engagement-declaration-link). Kandydat
 * klika link → ten formularz → backend update flag + token.used_at.
 *
 * Bez auth. Brak nawigacji. Tylko 3 checkboxy + opcjonalna notatka.
 */

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import axios from "axios";
import { Sparkles, CheckCircle2, AlertCircle } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://api.nexus.dynaminds.pl";

interface ViewResponse {
  candidate_first_name: string;
  open_to_side_projects: boolean;
  open_to_sales_support: boolean;
  open_to_expert_consult: boolean;
  expires_at: string;
}

const FLAGS = [
  {
    key: "open_to_side_projects",
    label: "Side-projekty",
    description: "Mógłbym wziąć dodatkowy projekt obok głównego angażu.",
  },
  {
    key: "open_to_sales_support",
    label: "Wsparcie sprzedaży",
    description: "Chętnie dołączę do rozmów przedsprzedażowych z klientami.",
  },
  {
    key: "open_to_expert_consult",
    label: "Konsultacje eksperckie",
    description: "Jestem dostępny do godzinowych konsultacji eksperckich.",
  },
] as const;

type FlagKey = (typeof FLAGS)[number]["key"];

export default function EngagementDeclarationPage() {
  const params = useParams();
  const token = String(params?.token ?? "");

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<ViewResponse | null>(null);
  const [flags, setFlags] = useState<Record<FlagKey, boolean>>({
    open_to_side_projects: false,
    open_to_sales_support: false,
    open_to_expert_consult: false,
  });
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const res = await axios.get<ViewResponse>(
          `${API_BASE}/api/public/engagement-declaration/${token}`
        );
        setView(res.data);
        setFlags({
          open_to_side_projects: res.data.open_to_side_projects,
          open_to_sales_support: res.data.open_to_sales_support,
          open_to_expert_consult: res.data.open_to_expert_consult,
        });
      } catch (e) {
        const msg =
          (e as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail ?? "Nie udało się pobrać formularza.";
        setError(msg);
      } finally {
        setLoading(false);
      }
    }
    if (token) load();
  }, [token]);

  const onSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await axios.post(`${API_BASE}/api/public/engagement-declaration/${token}`, {
        ...flags,
        notes: notes.trim() || null,
      });
      setSubmitted(true);
    } catch (e) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Nie udało się zapisać. Spróbuj ponownie lub skontaktuj się z rekruterem.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <main className="max-w-xl mx-auto p-6 pt-16">
        <div className="animate-pulse text-center text-sm text-gray-500">
          Ładowanie formularza…
        </div>
      </main>
    );
  }

  if (error && !view) {
    return (
      <main className="max-w-xl mx-auto p-6 pt-16">
        <div className="rounded-lg border border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950 p-6 text-center">
          <AlertCircle className="w-10 h-10 text-red-500 mx-auto mb-3" />
          <h1 className="text-lg font-semibold text-red-900 dark:text-red-100">
            Link nieaktywny
          </h1>
          <p className="text-sm text-red-700 dark:text-red-300 mt-2">{error}</p>
          <p className="text-xs text-gray-500 mt-4">
            Skontaktuj się z osobą, która Ci go wysłała — wygeneruje nowy link.
          </p>
        </div>
      </main>
    );
  }

  if (submitted) {
    return (
      <main className="max-w-xl mx-auto p-6 pt-16">
        <div className="rounded-lg border border-green-200 bg-green-50 dark:border-green-900 dark:bg-green-950 p-8 text-center">
          <CheckCircle2 className="w-12 h-12 text-green-500 mx-auto mb-4" />
          <h1 className="text-xl font-semibold text-green-900 dark:text-green-100">
            Dziękujemy!
          </h1>
          <p className="text-sm text-green-700 dark:text-green-300 mt-3">
            Twoje preferencje zostały zapisane. Rekruter otrzymał aktualizację.
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="max-w-xl mx-auto p-6 pt-12">
      <div className="rounded-lg border border-gray-200 bg-white dark:bg-gray-900 dark:border-gray-700 p-6 shadow-sm">
        <div className="flex items-start gap-3 mb-5">
          <Sparkles className="w-5 h-5 text-amber-500 mt-1 shrink-0" />
          <div>
            <h1 className="text-lg font-semibold">
              Witaj{view?.candidate_first_name ? `, ${view.candidate_first_name}` : ""}!
            </h1>
            <p className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              Zaznacz, w jakich dodatkowych formach zaangażowania chciałbyś z
              nami współpracować — pomożesz mi (rekruterowi) lepiej dobierać
              propozycje. Każda flaga jest opcjonalna.
            </p>
          </div>
        </div>

        <div className="space-y-3">
          {FLAGS.map((f) => (
            <label
              key={f.key}
              className="flex items-start gap-3 p-3 rounded-md border border-gray-200 dark:border-gray-700 hover:border-amber-400 cursor-pointer transition-colors"
            >
              <input
                type="checkbox"
                checked={flags[f.key]}
                onChange={(e) =>
                  setFlags((prev) => ({ ...prev, [f.key]: e.target.checked }))
                }
                className="mt-1 w-4 h-4"
              />
              <div className="flex-1">
                <div className="text-sm font-medium">{f.label}</div>
                <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  {f.description}
                </div>
              </div>
            </label>
          ))}
        </div>

        <label className="block mt-5">
          <span className="text-sm font-medium">
            Coś jeszcze? <span className="text-gray-500 font-normal">(opcjonalnie)</span>
          </span>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className="mt-1 w-full border border-gray-200 dark:border-gray-700 rounded-md px-3 py-2 text-sm bg-white dark:bg-gray-950 focus:border-amber-400 outline-none"
            placeholder="np. tylko Python, max 8h tygodniowo, najchętniej fintech…"
          />
        </label>

        {error && (
          <div className="mt-4 text-xs text-red-600 dark:text-red-400">{error}</div>
        )}

        <button
          type="button"
          onClick={onSubmit}
          disabled={submitting}
          className="mt-5 w-full bg-amber-500 hover:bg-amber-600 text-white text-sm font-medium px-4 py-2.5 rounded-md disabled:opacity-50"
        >
          {submitting ? "Zapisywanie…" : "Zapisz preferencje"}
        </button>

        {view?.expires_at && (
          <p className="mt-3 text-[10px] text-center text-gray-400">
            Link ważny do {new Date(view.expires_at).toLocaleDateString("pl-PL")}
          </p>
        )}
      </div>
    </main>
  );
}
