"use client";

/**
 * Reguły CV per klient — ekran weryfikacji zasianych propozycji.
 *
 * Pokazuje WSZYSTKIE 14 szablonów „Profil Championa" z Pomocy, także te, dla
 * których seed nie stworzył reguły. Seed zakłada wiersz tylko przy dokładnie
 * jednym żywym kliencie pasującym do nazwy, bo dopasowanie nie jest 1:1 —
 * samych bytów „BNP" jest w bazie siedem. Ukrycie pozycji bez reguły
 * sprawiłoby, że brak reguły wyglądałby identycznie jak jej nieistnienie
 * i nikt by go nie uzupełnił.
 *
 * Trzy stany są celowo rozróżnione: `active` (generator ją stosuje),
 * `proposed` (zasiana, ale NIE obowiązuje — czeka na zatwierdzenie),
 * `unassigned` (nie wiadomo, do którego klienta należy).
 */

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  FileWarning,
} from "lucide-react";

import api from "@/lib/api";

interface ChampionTemplateRow {
  seed_key: string;
  label: string;
  template_url: string | null;
  client_id: number | null;
  client_name: string | null;
  filename_pattern: string | null;
  cv_language: string | null;
  requires_en_copy: boolean;
  is_active: boolean;
  state: "active" | "proposed" | "unassigned";
}

const STATE_LABEL: Record<ChampionTemplateRow["state"], string> = {
  active: "Obowiązuje",
  proposed: "Propozycja — niezatwierdzona",
  unassigned: "Wymaga wskazania klienta",
};

function StateBadge({ state }: { state: ChampionTemplateRow["state"] }) {
  if (state === "active") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-400">
        <CheckCircle2 className="h-3 w-3" />
        {STATE_LABEL.active}
      </span>
    );
  }
  if (state === "proposed") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400">
        <FileWarning className="h-3 w-3" />
        {STATE_LABEL.proposed}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
      <AlertTriangle className="h-3 w-3" />
      {STATE_LABEL.unassigned}
    </span>
  );
}

export default function CvRulesSettingsPage() {
  const query = useQuery({
    queryKey: ["settings-cv-rules"],
    queryFn: async () =>
      (await api.get<ChampionTemplateRow[]>("/api/settings/cv-rules")).data,
  });

  const rows = query.data ?? [];
  const activeCount = rows.filter((r) => r.state === "active").length;

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-semibold">Reguły CV per klient</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Każdy szablon „Profil Championa" w Pomocy ma sekcję „Standardy
          rekrutacji klienta" — mówi, jak ma się nazywać plik CV i w jakim ma
          być języku. Reguła zaczyna działać dopiero po zatwierdzeniu.
        </p>
      </div>

      {/* Awaria pobrania nie może wyglądać jak pusta lista — pustka czytałaby
          się jako „nie ma żadnych reguł", czyli jako fakt. */}
      {query.isError ? (
        <div className="rounded-md border border-destructive/40 bg-destructive/5 p-4">
          <p className="text-sm text-destructive">
            Nie udało się wczytać reguł CV.
          </p>
          <button
            type="button"
            onClick={() => query.refetch()}
            className="mt-2 rounded-md border px-3 py-1 text-sm"
          >
            Ponów
          </button>
        </div>
      ) : query.isLoading ? (
        <p className="text-sm text-muted-foreground">Ładowanie…</p>
      ) : !query.isSuccess ? null : (
        <>
          <p className="text-sm text-muted-foreground">
            Obowiązuje {activeCount} z {rows.length} reguł.
          </p>
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left">
                <tr>
                  <th className="p-3 font-medium">Szablon</th>
                  <th className="p-3 font-medium">Klient</th>
                  <th className="p-3 font-medium">Wzór nazwy pliku</th>
                  <th className="p-3 font-medium">Język</th>
                  <th className="p-3 font-medium">Stan</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.seed_key} className="border-t align-top">
                    <td className="p-3">
                      {row.template_url ? (
                        <a
                          href={row.template_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-primary hover:underline"
                        >
                          {row.label}
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      ) : (
                        row.label
                      )}
                    </td>
                    <td className="p-3">
                      {row.client_id ? (
                        <Link
                          href={`/clients/${row.client_id}`}
                          className="text-primary hover:underline"
                        >
                          {row.client_name ?? `#${row.client_id}`}
                        </Link>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="p-3 font-mono text-xs">
                      {row.filename_pattern ?? (
                        <span className="font-sans text-muted-foreground">
                          —
                        </span>
                      )}
                    </td>
                    <td className="p-3">
                      {row.cv_language ? (
                        row.cv_language.toUpperCase()
                      ) : row.requires_en_copy ? (
                        <span title="Klient oczekuje obu wersji językowych">
                          PL + EN
                        </span>
                      ) : (
                        <span className="text-muted-foreground">dowolny</span>
                      )}
                    </td>
                    <td className="p-3">
                      <StateBadge state={row.state} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted-foreground">
            Regułę edytuje się i zatwierdza w profilu klienta (zakładka Profil →
            Edytuj → Reguły CV). Pozycje „wymaga wskazania klienta" powstały,
            bo nazwa z szablonu pasowała do zera albo do wielu klientów — wskaż
            właściwego i zapisz regułę u niego.
          </p>
        </>
      )}
    </div>
  );
}
