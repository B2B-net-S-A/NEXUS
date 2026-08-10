"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ExternalLink,
  File,
  FileSpreadsheet,
  FileText,
  FileType,
  FolderOpen,
  Library,
  Pencil,
  PencilLine,
  Search,
  Trash2,
} from "lucide-react";

import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { HelpMaterial, helpMaterialsApi } from "@/lib/api/help-materials";

// ── Stałe prezentacyjne ─────────────────────────────────────────────────────
// Świadomie TUTAJ, nie w `@/lib/api/help-materials`: testy mockują moduły API
// w całości, więc etykiety trzymane po stronie API wychodziłyby jako
// `undefined` (udokumentowana pułapka w CLAUDE.md tego repo).

type MaterialFileKind = "word" | "pdf" | "spreadsheet" | "folder" | "other";

const FILE_KIND_META: Record<
  MaterialFileKind,
  { Icon: typeof FileText; label: string }
> = {
  word: { Icon: FileText, label: "Dokument Word" },
  pdf: { Icon: FileType, label: "Plik PDF" },
  spreadsheet: { Icon: FileSpreadsheet, label: "Arkusz kalkulacyjny" },
  folder: { Icon: FolderOpen, label: "Folder" },
  other: { Icon: File, label: "Dokument" },
};

/**
 * SharePoint koduje typ zasobu w segmencie ścieżki: `/:w:/` = Word,
 * `/:b:/` = PDF, `/:x:/` = Excel, `/:f:/` = folder. Gdy linka nie da się
 * rozpoznać, schodzimy na rozszerzenie w tytule.
 */
export function fileKindFor(material: Pick<HelpMaterial, "url" | "title">): MaterialFileKind {
  const url = material.url.toLowerCase();
  if (url.includes("/:w:/")) return "word";
  if (url.includes("/:b:/")) return "pdf";
  if (url.includes("/:x:/")) return "spreadsheet";
  if (url.includes("/:f:/")) return "folder";

  const ext = material.title.toLowerCase().trim().match(/\.([a-z0-9]{2,5})$/)?.[1];
  if (!ext) return "other";
  if (["doc", "docx", "docm", "rtf", "odt"].includes(ext)) return "word";
  if (ext === "pdf") return "pdf";
  if (["xls", "xlsx", "xlsm", "csv", "ods"].includes(ext)) return "spreadsheet";
  return "other";
}

/** Znaki sterujące — patrz komentarz w `safeExternalHref`. */
const CONTROL_CHARS_RE = /[\u0000-\u001F\u007F]/g;

/**
 * Druga linia obrony przed stored-XSS w `href`.
 *
 * Pierwszą jest walidacja w Pydantic (tylko http/https), ale ona pilnuje
 * WYŁĄCZNIE zapisów przez API. Seed materiałów wchodzi kanałem
 * `_DATA_STATEMENTS` w `entrypoint.sh` — surowym SQL-em, który omija warstwę
 * API w całości. Skoro to udokumentowana, zalecana ścieżka wprowadzania
 * danych, `javascript:` może fizycznie trafić do bazy bez żadnej walidacji.
 *
 * Wymagamy adresu BEZWZGLĘDNEGO http(s) — wszystko inne zwraca `null`.
 * Adresy bez schematu też odpadają: przeglądarka rozwiązuje je względem
 * originu NEXUSa, więc „Otwórz" wyrzucałby użytkownika na 404 aplikacji przy
 * wierszu wyglądającym na sprawny. Widoczne „Nieprawidłowy link" jest lepsze,
 * bo mówi adminowi, co poprawić.
 */
export function safeExternalHref(rawUrl: string): string | null {
  // Przeglądarki historycznie usuwały znaki sterujące z href PRZED
  // interpretacją schematu, więc "java\nscript:" potrafiło się wykonać.
  // Schemat oceniamy na wersji oczyszczonej, renderujemy oryginał.
  const cleaned = rawUrl.trim().replace(CONTROL_CHARS_RE, "");
  return /^https?:\/\//i.test(cleaned) ? rawUrl : null;
}

/**
 * Doklej `action=edit` (skrót do edycji w Word Online).
 *
 * Linki SharePointa MAJĄ już query (`?e=...`), więc parametr dokładamy przez
 * `URL`/`URLSearchParams` — konkatenacja `"?action=edit"` rozwaliłaby link.
 * Niepoprawny URL zwraca `null`: degradujemy do zwykłego „Otwórz" zamiast
 * wywalać stronę wyjątkiem.
 */
export function buildWordEditUrl(rawUrl: string): string | null {
  try {
    const parsed = new URL(rawUrl);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    parsed.searchParams.set("action", "edit");
    return parsed.toString();
  } catch {
    return null;
  }
}

interface MaterialGroup {
  category: string;
  materials: HelpMaterial[];
  /** Najniższy `sort_order` w grupie — decyduje o kolejności grup. */
  minSortOrder: number;
}

function groupByCategory(items: HelpMaterial[]): MaterialGroup[] {
  const byCategory = new Map<string, HelpMaterial[]>();
  for (const item of items) {
    const bucket = byCategory.get(item.category);
    if (bucket) bucket.push(item);
    else byCategory.set(item.category, [item]);
  }

  return Array.from(byCategory.entries())
    .map(([category, materials]) => ({
      category,
      materials: [...materials].sort(
        (a, b) =>
          a.sort_order - b.sort_order || a.title.localeCompare(b.title, "pl"),
      ),
      minSortOrder: materials.reduce(
        (min, m) => Math.min(min, m.sort_order),
        Number.POSITIVE_INFINITY,
      ),
    }))
    .sort(
      (a, b) =>
        a.minSortOrder - b.minSortOrder ||
        a.category.localeCompare(b.category, "pl"),
    );
}

export interface HelpMaterialsSectionProps {
  isAdmin: boolean;
  /** Otwiera modal edytora na istniejącym wpisie (modal jest własnością strony). */
  onEdit?: (material: HelpMaterial) => void;
  /** CTA „dodaj pierwszy materiał" w pustym stanie dla admina. */
  onAdd?: () => void;
  onToast?: (message: string) => void;
  /**
   * Kategorie obecne na liście — strona karmi nimi datalist w edytorze.
   * Wołane z `useEffect`, więc referencja musi być stabilna (`useCallback`).
   */
  onCategoriesChange?: (categories: string[]) => void;
}

/**
 * Biblioteka dokumentów firmowych jako linki do SharePointa.
 *
 * NEXUS nie hostuje plików — dokumenty zostają w SharePoincie, gdzie są
 * natywnie edytowalne w Word Online z wersjonowaniem M365. Nasze własne wzory
 * (`is_editable_template`) dostają dodatkowy skrót do trybu edycji.
 */
export function HelpMaterialsSection({
  isAdmin,
  onEdit,
  onAdd,
  onToast,
  onCategoriesChange,
}: HelpMaterialsSectionProps) {
  const queryClient = useQueryClient();
  const [rawQuery, setRawQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");

  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(rawQuery), 250);
    return () => clearTimeout(handle);
  }, [rawQuery]);

  const listQuery = useQuery({
    queryKey: ["help-materials", { q: debouncedQuery, asAdmin: isAdmin }],
    queryFn: () =>
      helpMaterialsApi.list({
        q: debouncedQuery || undefined,
        published_only: !isAdmin,
      }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => helpMaterialsApi.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["help-materials"] });
      onToast?.("Materiał usunięty");
    },
    onError: () => onToast?.("Nie udało się usunąć materiału"),
  });

  const items: HelpMaterial[] = useMemo(() => listQuery.data ?? [], [listQuery.data]);
  const groups = useMemo(() => groupByCategory(items), [items]);

  // Referencja stabilna: `items` zmienia się dopiero przy realnej zmianie
  // danych (react-query robi structural sharing), więc efekt się nie zapętla.
  const categories = useMemo(
    () =>
      Array.from(new Set(items.map((i) => i.category))).sort((a, b) =>
        a.localeCompare(b, "pl"),
      ),
    [items],
  );

  useEffect(() => {
    onCategoriesChange?.(categories);
  }, [categories, onCategoriesChange]);

  const handleDelete = (material: HelpMaterial) => {
    if (typeof window !== "undefined") {
      const ok = window.confirm(
        `Usunąć materiał "${material.title}"? Operacja nieodwracalna (dokument w SharePoincie zostaje).`,
      );
      if (!ok) return;
    }
    deleteMutation.mutate(material.id);
  };

  const searching = debouncedQuery.trim().length > 0;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="w-full sm:max-w-sm">
          <Input
            leadingIcon={<Search className="h-4 w-4" />}
            placeholder="Szukaj po tytule, kategorii lub opisie…"
            aria-label="Szukaj materiałów"
            value={rawQuery}
            onChange={(e) => setRawQuery(e.target.value)}
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Dokumenty są przechowywane w SharePoincie — otwierają się w nowej karcie.
        </p>
      </div>

      {listQuery.isLoading ? (
        <div className="rounded-lg border border-border bg-card p-6">
          <p className="text-sm text-muted-foreground">Ładowanie materiałów…</p>
        </div>
      ) : listQuery.error ? (
        <div className="rounded-lg border border-border bg-card p-6">
          <p className="text-sm text-muted-foreground">
            Nie udało się wczytać materiałów. Odśwież stronę i spróbuj ponownie.
          </p>
        </div>
      ) : groups.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-10 text-center">
          <Library
            className="h-10 w-10 mx-auto text-muted-foreground opacity-40 mb-3"
            aria-hidden="true"
          />
          <p className="text-sm text-muted-foreground">
            {searching
              ? "Brak materiałów pasujących do wyszukiwania."
              : isAdmin
                ? "Brak materiałów. Dodaj pierwszy link do dokumentu w SharePoincie."
                : "Brak materiałów. Skontaktuj się z administratorem."}
          </p>
          {!searching && isAdmin && onAdd && (
            <Button
              size="sm"
              variant="outline"
              className="mt-4"
              onClick={onAdd}
            >
              Dodaj materiał
            </Button>
          )}
        </div>
      ) : (
        <div className="space-y-5">
          {groups.map((group) => (
            <section
              key={group.category}
              aria-label={group.category}
              className="rounded-lg border border-border bg-card overflow-hidden"
            >
              <h3 className="px-4 py-3 border-b border-border text-sm font-semibold text-foreground flex items-center gap-2">
                <span>{group.category}</span>
                <span className="text-xs font-normal text-muted-foreground tabular-nums">
                  ({group.materials.length})
                </span>
              </h3>
              <ul className="divide-y divide-border">
                {group.materials.map((material) => (
                  <MaterialRow
                    key={material.id}
                    material={material}
                    isAdmin={isAdmin}
                    onEdit={onEdit}
                    onDelete={handleDelete}
                  />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

function MaterialRow({
  material,
  isAdmin,
  onEdit,
  onDelete,
}: {
  material: HelpMaterial;
  isAdmin: boolean;
  onEdit?: (material: HelpMaterial) => void;
  onDelete: (material: HelpMaterial) => void;
}) {
  const { Icon, label } = FILE_KIND_META[fileKindFor(material)];
  const safeHref = safeExternalHref(material.url);
  const editUrl = material.is_editable_template
    ? buildWordEditUrl(material.url)
    : null;

  return (
    <li className="px-4 py-3 flex items-start gap-3 flex-wrap sm:flex-nowrap">
      <span className="shrink-0 mt-0.5 text-muted-foreground" title={label}>
        <Icon className="h-5 w-5" aria-hidden="true" />
        <span className="sr-only">{label}</span>
      </span>

      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-foreground flex items-center gap-2 flex-wrap">
          <span className="break-words">{material.title}</span>
          {!material.is_published && isAdmin && (
            <span className="inline-flex items-center text-[10px] uppercase tracking-wider text-muted-foreground border border-border rounded px-1.5 py-0.5">
              szkic
            </span>
          )}
        </p>
        {material.description && (
          <p className="text-xs text-muted-foreground mt-0.5 break-words">
            {material.description}
          </p>
        )}
      </div>

      <div className="flex items-center gap-1.5 shrink-0 flex-wrap">
        {/* Celowo goły <a> ze stylami `buttonVariants`, nie `<Button asChild>`:
            Button dokłada slot na spinner, więc Radix Slot dostaje dwoje dzieci. */}
        {safeHref ? (
          <a
            href={safeHref}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Otwórz: ${material.title}`}
            className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
          >
            <ExternalLink className="h-4 w-4" aria-hidden="true" /> Otwórz
          </a>
        ) : (
          // Adres inny niż bezwzględny http(s) NIE staje się klikalnym
          // linkiem: `javascript:` wstrzyknięty surowym SQL-em wykonałby się
          // po kliknięciu, a adres bez schematu otworzyłby 404 NEXUSa.
          <span
            className="text-xs text-muted-foreground border border-border rounded px-2 py-1"
            title={`Adres wymaga pełnego http:// lub https:// — zablokowano: ${material.url}`}
          >
            Nieprawidłowy link
          </span>
        )}

        {editUrl && (
          <a
            href={editUrl}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Edytuj w Word Online: ${material.title}`}
            className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
          >
            <PencilLine className="h-4 w-4" aria-hidden="true" /> Edytuj w Word
            Online
          </a>
        )}

        {isAdmin && (
          <>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onEdit?.(material)}
              aria-label={`Edytuj wpis: ${material.title}`}
            >
              <Pencil className="h-4 w-4" aria-hidden="true" /> Edytuj
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => onDelete(material)}
              aria-label={`Usuń wpis: ${material.title}`}
            >
              <Trash2 className="h-4 w-4 text-primary" aria-hidden="true" /> Usuń
            </Button>
          </>
        )}
      </div>
    </li>
  );
}
