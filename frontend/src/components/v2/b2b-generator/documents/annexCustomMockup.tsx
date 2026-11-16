"use client";

// MAKIETA (gałąź claude/mockup-proposals-49c68c, nie do scalenia).
// Typ „aneks z własną nazwą” zaślepiony na froncie: serwer go nie zna, więc
// prefill i lista osób idą jako „zmiana daty startu” (te same pola umowy
// i Partnera), a podgląd bierze prawdziwy HTML z serwera i podmienia w nim
// § 1 na treść z formularza. Wariant z adresu: `?wariant=a|b|c`.

import { Plus, Sparkles, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type {
  DocumentFieldDef,
  DocumentTypeDef,
  DocumentTypesResponse,
  DocumentValue,
  DocumentValues,
} from "@/lib/api/b2bDocuments";

export const MOCK_TYPE_KEY = "annex_custom";
export const MOCK_BACKING_TYPE = "annex_start_date";

export type MockVariant = "a" | "b" | "c";

export function mockVariant(): MockVariant {
  if (typeof window === "undefined") return "c";
  const v = new URLSearchParams(window.location.search).get("wariant");
  return v === "a" || v === "b" ? v : "c";
}

export function backingType(key: string): string {
  return key === MOCK_TYPE_KEY ? MOCK_BACKING_TYPE : key;
}

const field = (
  key: string,
  label: string,
  kind: string,
  extra: Partial<DocumentFieldDef> = {},
): DocumentFieldDef => ({
  key,
  label,
  kind: kind as DocumentFieldDef["kind"],
  required: false,
  sensitive: false,
  help: null,
  options: [],
  show_if: null,
  group: "change",
  lookup: null,
  lookup_fills: [],
  ...extra,
});

function mockType(base: DocumentTypeDef, variant: MockVariant): DocumentTypeDef {
  // Umowa, daty i Partner — dokładnie jak w „zmianie daty startu”.
  const shared = base.fields.filter(
    (f) => f.group !== "change",
  );
  const title = field("annex_title", "Czego dotyczy aneks", "text", {
    required: true,
    help:
      variant === "a"
        ? "Trafi do tytułu dokumentu i do rejestru aneksów, np. „zwolnienie z zakazu konkurencji”."
        : "Trafi do tytułu dokumentu i do rejestru aneksów. Gotowa klauzula wpisze ją sama.",
  });
  const change =
    variant === "a"
      ? field("changes_text", "Treść zmian", "textarea", {
          required: true,
          help: "Każdy akapit to osobny punkt § 1 aneksu. Komparycja, § 2 i podpisy dochodzą same.",
        })
      : field("changes", "Zmiany w umowie", "annex_changes", { required: true });
  return {
    ...base,
    key: MOCK_TYPE_KEY,
    label:
      variant === "a"
        ? "Aneks — inna zmiana"
        : variant === "b"
          ? "Aneks — zmiana postanowień umowy"
          : "Aneks — inna zmiana (własna nazwa)",
    description:
      variant === "c"
        ? "Dowolna zmiana umowy: sam nazywasz aneks, wybierasz gotową klauzulę albo wpisujesz własną treść."
        : "Zmiana, której nie ma na liście — sam nazywasz aneks i wpisujesz treść zmian.",
    effect_label:
      "Kontrakt nie zmieni się sam — aneks pojawi się w zakładce „Aneksy” kontraktu pod swoją nazwą.",
    allows_external: true,
    uses_refs: false,
    fields: [...shared, title, change],
  };
}

export function withMockType(data: DocumentTypesResponse): DocumentTypesResponse {
  const base = data.types.find((t) => t.key === MOCK_BACKING_TYPE);
  if (!base || data.types.some((t) => t.key === MOCK_TYPE_KEY)) return data;
  return { ...data, types: [...data.types, mockType(base, mockVariant())] };
}

// ── Lista zmian (wariant B i C) ─────────────────────────────────────────────

export interface ChangeRow {
  op: "replace" | "add" | "delete" | "free";
  paragraph: string;
  section: string;
  text: string;
}

const OPS: [ChangeRow["op"], string][] = [
  ["replace", "otrzymuje nowe brzmienie"],
  ["add", "dodaje się"],
  ["delete", "skreśla się"],
  ["free", "własny tekst"],
];

const EMPTY_ROW: ChangeRow = { op: "replace", paragraph: "", section: "", text: "" };

interface Clause {
  label: string;
  title: string;
  rows: (values: DocumentValues) => ChangeRow[];
}

const clientOf = (values: DocumentValues) =>
  String(values.mock_client_name ?? "").trim() || "[nazwa Klienta]";

// Treść zwolnienia = zdanie z naszego porozumienia o rozwiązaniu umowy
// (termination_agreement_pl), paragraf z wzoru umowy B2B (§ 10).
const CLAUSES: Clause[] = [
  {
    label: "Zwolnienie z zakazu konkurencji",
    title: "zwolnienie z zakazu konkurencji",
    rows: (values) => [
      {
        op: "add",
        paragraph: "10",
        section: "2a",
        text: `B2B.net S.A. zwalnia Partnera z zakazu konkurencji określonego w § 10 ust. 1 Umowy i zgadza się na bezpośrednie zatrudnienie Partnera lub świadczenie przez Partnera usług bezpośrednio na rzecz: ${clientOf(values)}, spółek macierzystych oraz innych podmiotów powiązanych.`,
      },
    ],
  },
  {
    label: "Skrócenie zakazu konkurencji",
    title: "skrócenie okresu zakazu konkurencji",
    rows: () => [
      {
        op: "replace",
        paragraph: "10",
        section: "1",
        text: "W okresie obowiązywania Umowy oraz przez okres 6 (sześciu) miesięcy po jej rozwiązaniu lub wygaśnięciu, Partner zobowiązuje się powstrzymać od: […]",
      },
    ],
  },
  {
    label: "Pusta zmiana",
    title: "",
    rows: () => [EMPTY_ROW],
  },
];

const SELECT_CLASS =
  "flex h-9 w-full rounded-md border border-border bg-card px-2 text-sm text-foreground focus:outline-hidden focus:ring-2 focus:ring-ring";

export function AnnexChangesField({
  id,
  value,
  values,
  onChange,
  onTitle,
  invalid,
}: {
  id: string;
  value: DocumentValue | undefined;
  values: DocumentValues;
  onChange: (value: DocumentValue) => void;
  onTitle: (title: string) => void;
  invalid?: boolean;
}) {
  const variant = mockVariant();
  const rows: ChangeRow[] = Array.isArray(value)
    ? (value as unknown as ChangeRow[])
    : [EMPTY_ROW];
  const write = (next: ChangeRow[]) => onChange(next as unknown as DocumentValue);
  const patch = (i: number, p: Partial<ChangeRow>) =>
    write(rows.map((r, j) => (j === i ? { ...r, ...p } : r)));

  return (
    <div id={id} className="space-y-3">
      {variant === "c" ? (
        <div className="space-y-1.5 rounded-lg border border-dashed border-primary/40 bg-primary/5 p-3">
          <p className="flex items-center gap-1.5 text-xs font-medium text-foreground">
            <Sparkles className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
            Gotowe klauzule — wpiszą nazwę aneksu, paragraf i treść z wzoru umowy
          </p>
          <div className="flex flex-wrap gap-2">
            {CLAUSES.map((c) => (
              <Button
                key={c.label}
                type="button"
                size="sm"
                variant="outline"
                onClick={() => {
                  write(c.rows(values));
                  if (c.title) onTitle(c.title);
                }}
              >
                {c.label}
              </Button>
            ))}
          </div>
        </div>
      ) : null}
      {rows.map((row, i) => (
        <div
          key={i}
          className={`space-y-2 rounded-lg border p-3 ${invalid ? "border-destructive" : "border-border"}`}
        >
          <div className="grid grid-cols-[4.5rem_4.5rem_1fr_auto] items-end gap-2">
            <label className="space-y-1 text-xs text-muted-foreground">
              §
              <Input
                value={row.paragraph}
                disabled={row.op === "free"}
                onChange={(e) => patch(i, { paragraph: e.target.value })}
              />
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">
              ust.
              <Input
                value={row.section}
                disabled={row.op === "free"}
                onChange={(e) => patch(i, { section: e.target.value })}
              />
            </label>
            <label className="space-y-1 text-xs text-muted-foreground">
              Co się dzieje
              <select
                className={SELECT_CLASS}
                value={row.op}
                onChange={(e) => patch(i, { op: e.target.value as ChangeRow["op"] })}
              >
                {OPS.map(([v, l]) => (
                  <option key={v} value={v}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label={`Usuń zmianę ${i + 1}`}
              disabled={rows.length === 1}
              onClick={() => write(rows.filter((_, j) => j !== i))}
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
          {row.op !== "delete" ? (
            <Textarea
              rows={3}
              placeholder={
                row.op === "free" ? "Treść punktu aneksu" : "Nowa treść ustępu"
              }
              value={row.text}
              onChange={(e) => patch(i, { text: e.target.value })}
            />
          ) : null}
          <p className="text-xs text-muted-foreground">
            W aneksie: <span className="text-foreground">{lead(row)}</span>
          </p>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={() => write([...rows, EMPTY_ROW])}>
        <Plus className="mr-1 h-4 w-4" aria-hidden="true" />
        Dodaj zmianę
      </Button>
    </div>
  );
}

function ref(row: ChangeRow): string {
  const p = row.paragraph.trim() || "…";
  return row.section.trim() ? `§ ${p} ust. ${row.section.trim()}` : `§ ${p}`;
}

function lead(row: ChangeRow): string {
  switch (row.op) {
    case "replace":
      return `${ref(row)} Umowy otrzymuje brzmienie: „…”`;
    case "add":
      return `w § ${row.paragraph.trim() || "…"} Umowy dodaje się ust. ${row.section.trim() || "…"} w brzmieniu: „…”`;
    case "delete":
      return `${ref(row)} Umowy skreśla się.`;
    default:
      return "punkt aneksu z Twoją treścią";
  }
}

// ── Podgląd: § 1 z formularza w prawdziwym HTML-u serwera ───────────────────

const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function changePoints(values: DocumentValues): string[] {
  if (typeof values.changes_text === "string") {
    return values.changes_text
      .split(/\n\s*\n|\n/)
      .map((s) => s.trim())
      .filter(Boolean)
      .map(esc);
  }
  const rows = Array.isArray(values.changes)
    ? (values.changes as unknown as ChangeRow[])
    : [];
  return rows.map((row) => {
    const text = esc(row.text.trim() || "…");
    switch (row.op) {
      case "replace":
        return `${ref(row)} Umowy otrzymuje brzmienie:</p><p class="indent">„${text}”`;
      case "add":
        return `w § ${esc(row.paragraph.trim() || "…")} Umowy dodaje się ust. ${esc(row.section.trim() || "…")} w brzmieniu:</p><p class="indent">„${text}”`;
      case "delete":
        return `${ref(row)} Umowy skreśla się.`;
      default:
        return text;
    }
  });
}

export function mockPreviewHtml(html: string, values: DocumentValues): string {
  const title = String(values.annex_title ?? "").trim();
  const points = changePoints(values);
  const letters = "abcdefghij";
  const body = points.length
    ? points.map((p, i) => `<p>${letters[i] ?? i + 1}) ${p}</p>`).join("")
    : "<p>…</p>";
  const section1 =
    `<p class="center"><strong>§1</strong></p>` +
    `<p>Aneks zgodnym postanowieniem stron wprowadza do umowy nr ${esc(String(values.contract_number ?? "…"))} następujące zmiany:</p>` +
    body;
  return html
    .replace(
      /ANEKS DO UMOWY O WSPÓŁPRACĘ B2B<\/strong><\/p>/,
      `ANEKS DO UMOWY O WSPÓŁPRACĘ B2B</strong></p>${
        title ? `<p class="center">w sprawie: ${esc(title)}</p>` : ""
      }`,
    )
    .replace(/<p class="center"><strong>§1<\/strong><\/p>[\s\S]*?(?=<p class="center"><strong>§ ?2)/, section1);
}

export const MOCK_HIDDEN_MISSING = new Set([
  "Obecna data rozpoczęcia usług",
  "Nowa data rozpoczęcia usług",
  "Zmieniany paragraf (§)",
  "Ustęp",
]);
