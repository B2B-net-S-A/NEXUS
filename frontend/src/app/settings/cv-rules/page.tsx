"use client";

/**
 * Reguły CV per klient — przegląd zbiorczy z pełnym zarządzaniem.
 *
 * Do 09.2026 ten ekran był wyłącznie podglądem 14 szablonów Championa
 * zasianych migracją 0255: bez dodawania, bez edycji, bez linku w Ustawieniach.
 * Reguła założona dla piętnastego klienta była tu niewidoczna, a jedyną drogą
 * do jej założenia było okno „Edytuj firmę" w profilu klienta — czyli Delivery
 * Lead nie miał jak „zrobić sobie reguły", choć backend (`TacPlus`) od
 * początku mu na to pozwalał.
 *
 * Teraz: lista WSZYSTKICH reguł, „Dodaj regułę" z pickerem klienta, edycja,
 * zatwierdzanie i usuwanie w miejscu. Akcje widzi rola z capability
 * `cv_rule.manage` (lustro backendowego `DeliveryLeadPlus`: admin /
 * delivery_lead — TAC edytuje kartę klienta, ale reguł CV nie prowadzi);
 * pozostałe role operacyjne mają odczyt. Dla Delivery Leada lista startuje
 * zawężona do jego portfela (`data_scope` z GET /api/auth/me) — to filtr do
 * wyłączenia, nie granica: backend nie skopuje zapisu do portfela, bo reguła
 * CV jest konfiguracją klienta tak jak jego karta.
 *
 * Szablony Championa bez przypisanej reguły idą osobną sekcją — ukrycie ich
 * sprawiłoby, że brak reguły wyglądałby identycznie jak jej nieistnienie
 * i nikt by go nie uzupełnił.
 *
 * Awaria pobrania NIE MOŻE wyglądać jak pusta lista: pustka czyta się jako
 * „nie ma żadnych reguł", czyli jako fakt. Stan liczy `resolveViewState`
 * z `isSuccess`, więc przerwa między ponowieniami też nie udaje pustki.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  FileCheck2,
  FileWarning,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";

import api, { extractErrorMsg } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { useCapability } from "@/hooks/useCapability";
import { resolveViewState } from "@/lib/view-state";
import { AppModal } from "@/components/ds/AppModal";
import { EmptyState } from "@/components/ds/EmptyState";
import { PageHeader } from "@/components/ds/PageHeader";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ClientSinglePicker,
  type ClientRef,
} from "@/components/clients/ClientSinglePicker";
import { CvRuleEditor } from "@/components/cv-rules/CvRuleEditor";
import type {
  ClientCvRule,
  ClientCvRuleListItem,
  CvRulesOverview,
} from "@/lib/cv-rules";
import { CV_CONTENT_MODES } from "@/lib/cv-generator";

export type CvRuleRow = ClientCvRuleListItem;
export type { CvRulesOverview };

const MODE_LABEL: Record<string, string> = Object.fromEntries(
  CV_CONTENT_MODES.map((m) => [m.value, m.label]),
);

type StateFilter = "all" | "active" | "proposed";

const STATE_FILTERS: ReadonlyArray<{ id: StateFilter; label: string }> = [
  { id: "all", label: "Wszystkie" },
  { id: "active", label: "Obowiązujące" },
  { id: "proposed", label: "Niezatwierdzone" },
];

export const QUERY_KEY = ["settings-cv-rules"] as const;

function fold(value: string): string {
  return value
    .toLowerCase()
    .normalize("NFD")
    // Zakres znaków łączących (U+0300–U+036F) jako escape'y, nie surowe bajty
    // w źródle — te potrafią zniknąć w diffie albo edytorze bez śladu.
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ł/g, "l");
}

function StateBadge({ active }: { active: boolean }) {
  if (active) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-400">
        <CheckCircle2 className="h-3 w-3" />
        Obowiązuje
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-700 dark:text-amber-400">
      <FileWarning className="h-3 w-3" />
      Niezatwierdzona
    </span>
  );
}

function Chip({
  children,
  title,
}: {
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground"
    >
      {children}
    </span>
  );
}

function languageLabel(row: CvRuleRow): React.ReactNode {
  if (row.cv_language) return row.cv_language.toUpperCase();
  if (row.requires_en_copy) {
    return <span title="Klient oczekuje obu wersji językowych">PL + EN</span>;
  }
  return <span className="text-muted-foreground">dowolny</span>;
}

function formatDate(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("pl-PL");
}

export default function CvRulesSettingsPage() {
  const user = useAuthStore((s) => s.user);
  const hydrated = useAuthStore((s) => s.hydrated);
  const canEdit = useCapability("cv_rule.manage");
  const queryClient = useQueryClient();
  // `?client=<id>` — link z okna „Edytuj firmę" otwiera edytor tego klienta
  // od razu. Czytane przez efekt, nie w inicjalizatorze stanu: miękka
  // nawigacja App Routera nie odmontowuje strony.
  const searchParams = useSearchParams();
  const deepLinkClient = searchParams.get("client");
  // `&tab=playbook` — link „Załóż kartę" z karty klienta otwiera edytor od
  // razu na zakładce „Karta klienta". Nieznaną wartość edytor zamienia na
  // „Podstawy".
  const deepLinkTab = searchParams.get("tab");

  // Portfel Delivery Leada z `data_scope` — liczy go backend w GET /api/auth/me
  // z tego samego `resolve_dashboard_scope`, którego używają trasy DL. Nie
  // z roli: hybryda HoR+DL dostaje `recruitment_org` i nie ma czego zawężać.
  const myClientIds = useMemo<ReadonlySet<number> | null>(() => {
    const scope = user?.data_scope;
    if (!scope || scope.kind !== "delivery_clients") return null;
    return new Set(scope.allowed_client_ids ?? []);
  }, [user]);

  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState<StateFilter>("all");
  // `null` = domyślnie: DL widzi swój portfel, reszta wszystko.
  const [onlyMineChoice, setOnlyMineChoice] = useState<boolean | null>(null);
  const onlyMine = myClientIds !== null && (onlyMineChoice ?? true);

  const [editor, setEditor] = useState<{
    clientId: number;
    clientName: string;
    initialTab?: string;
  } | null>(null);
  const [adding, setAdding] = useState(false);
  const [addClient, setAddClient] = useState<ClientRef | null>(null);
  const [pendingDelete, setPendingDelete] = useState<CvRuleRow | null>(null);
  const [actionError, setActionError] = useState("");

  const query = useQuery({
    queryKey: QUERY_KEY,
    enabled: hydrated,
    queryFn: async () =>
      (await api.get<CvRulesOverview>("/api/settings/cv-rules")).data,
  });

  const invalidate = (clientId?: number) => {
    void queryClient.invalidateQueries({ queryKey: QUERY_KEY });
    if (clientId !== undefined) {
      // Baner w generatorze cache'uje regułę klienta pod własnym kluczem.
      void queryClient.invalidateQueries({
        queryKey: ["client-cv-rule", clientId],
      });
    }
  };

  const confirmMutation = useMutation({
    mutationFn: async (clientId: number) =>
      (
        await api.post<ClientCvRule>(
          `/api/clients/${clientId}/cv-rule/confirm`,
        )
      ).data,
    onSuccess: (_rule, clientId) => {
      setActionError("");
      invalidate(clientId);
    },
    onError: (err) => setActionError(extractErrorMsg(err)),
  });

  const deleteMutation = useMutation({
    mutationFn: async (clientId: number) => {
      await api.delete(`/api/clients/${clientId}/cv-rule`);
      return clientId;
    },
    onSuccess: (clientId) => {
      setActionError("");
      setPendingDelete(null);
      invalidate(clientId);
    },
    onError: (err) => setActionError(extractErrorMsg(err)),
  });

  const rows = useMemo(() => query.data?.rules ?? [], [query.data]);
  const unassigned = query.data?.unassigned_templates ?? [];
  const activeCount = rows.filter((r) => r.is_active).length;

  useEffect(() => {
    if (!deepLinkClient || !canEdit) return;
    const id = Number.parseInt(deepLinkClient, 10);
    if (!Number.isFinite(id) || id <= 0) return;
    const row = rows.find((r) => r.client_id === id);
    setEditor({
      clientId: id,
      clientName: row?.client_name ?? `#${id}`,
      initialTab: deepLinkTab ?? undefined,
    });
  }, [deepLinkClient, deepLinkTab, canEdit, rows]);

  const filtered = useMemo(() => {
    const q = fold(search.trim());
    return rows.filter((row) => {
      if (stateFilter === "active" && !row.is_active) return false;
      if (stateFilter === "proposed" && row.is_active) return false;
      if (onlyMine && myClientIds && !myClientIds.has(row.client_id)) {
        return false;
      }
      if (!q) return true;
      const haystack = fold(
        [
          row.client_name ?? "",
          row.filename_pattern ?? "",
          row.template_label ?? "",
          row.notes ?? "",
          row.generator_instructions ?? "",
        ].join(" "),
      );
      return haystack.includes(q);
    });
  }, [rows, stateFilter, onlyMine, myClientIds, search]);

  const viewState = resolveViewState({
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: rows.length === 0,
  });

  const openAdd = () => {
    setAddClient(null);
    setAdding(true);
  };
  const closeEditor = () => setEditor(null);
  const closeAdd = () => {
    setAdding(false);
    setAddClient(null);
  };

  const addTargetHasRule =
    addClient !== null && rows.some((r) => r.client_id === addClient.id);

  if (!hydrated) {
    return <div className="p-6 text-muted-foreground">Ładowanie…</div>;
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <PageHeader
        title="Reguły CV per klient"
        description="Jak ma się nazywać plik CV, w jakim ma być języku, czego jeszcze wymaga klient i jakie instrukcje ma dostać generator. Reguła działa od chwili zatwierdzenia — każdy Delivery Lead zakłada i zatwierdza reguły dla swoich klientów sam."
        actions={
          canEdit ? (
            <Button type="button" onClick={openAdd}>
              <Plus className="h-4 w-4" />
              Dodaj regułę
            </Button>
          ) : null
        }
      />

      {actionError ? (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{actionError}</span>
        </div>
      ) : null}

      {viewState === "loading" ? (
        <p className="text-sm text-muted-foreground">Ładowanie…</p>
      ) : viewState === "forbidden" ||
        viewState === "not_found" ||
        viewState === "error" ? (
        <QueryStateNotice
          state={viewState}
          description={
            viewState === "error"
              ? "Nie udało się wczytać reguł CV. Reguły nadal obowiązują w generatorze — to tylko nieudane pobranie listy."
              : undefined
          }
          onRetry={viewState === "error" ? () => query.refetch() : undefined}
        />
      ) : viewState === "empty" ? (
        <EmptyState
          icon={FileCheck2}
          title="Żaden klient nie ma jeszcze reguł CV"
          description="Generator używa ogólnej nazwy pliku i języka wybranego przez rekrutera. Dodaj regułę dla klienta, który ma własne wymagania."
          action={
            canEdit ? (
              <Button type="button" onClick={openAdd}>
                <Plus className="h-4 w-4" />
                Dodaj regułę
              </Button>
            ) : null
          }
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <Input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Szukaj: klient, wzór nazwy, notatka…"
              aria-label="Szukaj reguły"
              className="max-w-xs"
            />
            <div
              role="group"
              aria-label="Stan reguły"
              className="inline-flex rounded-md border border-border p-0.5"
            >
              {STATE_FILTERS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  aria-pressed={stateFilter === f.id}
                  onClick={() => setStateFilter(f.id)}
                  className={
                    stateFilter === f.id
                      ? "rounded px-2.5 py-1 text-xs font-medium bg-primary text-primary-foreground"
                      : "rounded px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-muted"
                  }
                >
                  {f.label}
                </button>
              ))}
            </div>
            {myClientIds !== null ? (
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={onlyMine}
                  onChange={(e) => setOnlyMineChoice(e.target.checked)}
                />
                Tylko moi klienci
              </label>
            ) : null}
            <p className="ml-auto text-sm text-muted-foreground">
              Obowiązuje {activeCount} z {rows.length} reguł
              {filtered.length !== rows.length
                ? ` · pokazuję ${filtered.length}`
                : ""}
              .
            </p>
          </div>

          {filtered.length === 0 ? (
            <p className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">
              Brak reguł pasujących do filtrów.
            </p>
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-sm">
                <thead className="bg-muted/50 text-left">
                  <tr>
                    <th className="p-3 font-medium">Klient</th>
                    <th className="p-3 font-medium">Wzór nazwy pliku</th>
                    <th className="p-3 font-medium">Język</th>
                    <th className="p-3 font-medium">Wymogi</th>
                    <th className="p-3 font-medium">Stan</th>
                    <th className="p-3 font-medium">Zatwierdzona</th>
                    {canEdit ? (
                      <th className="sticky right-0 bg-muted/50 p-3 text-right font-medium">
                        Akcje
                      </th>
                    ) : null}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((row) => {
                    const name = row.client_name ?? `#${row.client_id}`;
                    const mine = myClientIds?.has(row.client_id) ?? false;
                    const confirming =
                      confirmMutation.isPending &&
                      confirmMutation.variables === row.client_id;
                    const noRequirements =
                      !row.requires_en_copy &&
                      !row.requires_rodo_consent_block &&
                      !row.spaces_to_underscores &&
                      !row.notes?.trim() &&
                      !row.generator_instructions?.trim() &&
                      !row.generator_instructions_en?.trim() &&
                      !(row.content_mode && row.content_mode_locked) &&
                      !row.require_screening_notes_min_chars &&
                      !row.require_project_ref &&
                      !row.require_position &&
                      !row.require_champion &&
                      !row.omit_sections?.length &&
                      !row.max_roles &&
                      !row.max_bullets_per_role &&
                      !row.max_bullet_chars &&
                      !row.why_points_max &&
                      !row.date_format &&
                      !row.glossary?.length;
                    return (
                      <tr key={row.client_id} className="border-t align-top">
                        <td className="p-3">
                          <div className="flex flex-wrap items-center gap-2">
                            <Link
                              href={`/clients/${row.client_id}`}
                              className="font-medium text-primary hover:underline"
                            >
                              {name}
                            </Link>
                            {mine ? <Chip>Twój klient</Chip> : null}
                          </div>
                          {row.template_label ? (
                            <p className="mt-0.5 text-xs text-muted-foreground">
                              szablon Championa:{" "}
                              {row.template_url ? (
                                <a
                                  href={row.template_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="inline-flex items-center gap-1 hover:underline"
                                >
                                  {row.template_label}
                                  <ExternalLink className="h-3 w-3" />
                                </a>
                              ) : (
                                row.template_label
                              )}
                            </p>
                          ) : null}
                        </td>
                        <td className="p-3">
                          {row.filename_pattern ? (
                            <span className="font-mono text-xs">
                              {row.filename_pattern}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">
                              nazwa ogólna
                            </span>
                          )}
                          {row.filename_preview ? (
                            <p className="mt-0.5 font-mono text-[11px] text-muted-foreground">
                              {row.filename_preview}
                            </p>
                          ) : null}
                        </td>
                        <td className="p-3">{languageLabel(row)}</td>
                        <td className="p-3">
                          <div className="flex flex-wrap gap-1">
                            {row.requires_en_copy ? (
                              <Chip title="Klient oczekuje CV po polsku oraz po angielsku">
                                obie wersje
                              </Chip>
                            ) : null}
                            {row.requires_rodo_consent_block ? (
                              <Chip title="Wymagany zrzut zgody kandydata na dole CV">
                                zgoda RODO
                              </Chip>
                            ) : null}
                            {row.spaces_to_underscores ? (
                              <Chip title="Spacje w nazwie pliku zamieniane na podkreślenia">
                                podkreślenia
                              </Chip>
                            ) : null}
                            {row.notes?.trim() ? (
                              <Chip title={row.notes}>notatka</Chip>
                            ) : null}
                            {row.generator_instructions?.trim() ||
                            row.generator_instructions_en?.trim() ? (
                              <Chip
                                title={
                                  row.generator_instructions ??
                                  row.generator_instructions_en ??
                                  undefined
                                }
                              >
                                instrukcje AI
                              </Chip>
                            ) : null}
                            {row.content_mode && row.content_mode_locked ? (
                              <Chip title="Tryb obróbki treści zablokowany przez Delivery Leada">
                                tryb: {MODE_LABEL[row.content_mode] ?? row.content_mode}
                              </Chip>
                            ) : null}
                            {row.require_screening_notes_min_chars ||
                            row.require_project_ref ||
                            row.require_position ||
                            row.require_champion ? (
                              <Chip title="Generacja odmawia bez wymaganych wejść">
                                wymagane wejścia
                              </Chip>
                            ) : null}
                            {row.omit_sections?.length ||
                            row.max_roles ||
                            row.max_bullets_per_role ||
                            row.max_bullet_chars ||
                            row.why_points_max ||
                            row.date_format ||
                            row.glossary?.length ? (
                              <Chip title="Polityka prezentacji egzekwowana w kodzie">
                                polityka treści
                              </Chip>
                            ) : null}
                            {noRequirements ? (
                              <span className="text-muted-foreground">—</span>
                            ) : null}
                          </div>
                        </td>
                        <td className="p-3">
                          <StateBadge active={row.is_active} />
                          <p className="mt-0.5 text-[11px] text-muted-foreground">
                            wersja {row.version}
                          </p>
                        </td>
                        <td className="p-3 text-xs text-muted-foreground">
                          {row.confirmed_at
                            ? `${formatDate(row.confirmed_at)}${
                                row.confirmed_by_name
                                  ? ` · ${row.confirmed_by_name}`
                                  : ""
                              }`
                            : "—"}
                        </td>
                        {canEdit ? (
                          <td className="sticky right-0 bg-background p-3">
                            <div className="flex justify-end gap-1">
                              {!row.is_active ? (
                                <Button
                                  type="button"
                                  size="sm"
                                  variant="outline"
                                  loading={confirming}
                                  disabled={confirmMutation.isPending}
                                  aria-label={`Zatwierdź regułę: ${name}`}
                                  onClick={() =>
                                    confirmMutation.mutate(row.client_id)
                                  }
                                >
                                  <CheckCircle2 className="h-3.5 w-3.5" />
                                  Zatwierdź
                                </Button>
                              ) : null}
                              <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                aria-label={`Edytuj regułę: ${name}`}
                                onClick={() =>
                                  setEditor({
                                    clientId: row.client_id,
                                    clientName: name,
                                  })
                                }
                              >
                                <Pencil className="h-3.5 w-3.5" />
                                Edytuj
                              </Button>
                              <Button
                                type="button"
                                size="sm"
                                variant="ghost"
                                aria-label={`Usuń regułę: ${name}`}
                                className="text-destructive hover:text-destructive"
                                onClick={() => setPendingDelete(row)}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                                Usuń
                              </Button>
                            </div>
                          </td>
                        ) : null}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {query.isSuccess && unassigned.length > 0 ? (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold">
            Szablony Championa bez przypisanej reguły
          </h2>
          <p className="text-xs text-muted-foreground">
            Te szablony z Pomocy mają sekcję „Standardy rekrutacji klienta", ale
            nazwa z szablonu pasowała do zera albo do wielu klientów, więc reguła
            nie powstała sama. Wskaż właściwego klienta i wpisz regułę u niego.
          </p>
          <ul className="divide-y rounded-md border">
            {unassigned.map((t) => (
              <li
                key={t.seed_key}
                className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm"
              >
                {t.template_url ? (
                  <a
                    href={t.template_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-primary hover:underline"
                  >
                    {t.label}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                ) : (
                  <span>{t.label}</span>
                )}
                {canEdit ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    aria-label={`Wskaż klienta dla szablonu: ${t.label}`}
                    onClick={openAdd}
                  >
                    Wskaż klienta
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <AppModal
        open={adding}
        onOpenChange={(open) => {
          if (!open) closeAdd();
        }}
        title="Nowa reguła CV"
        description="Wybierz klienta, a potem wpisz jego wymagania. „Zapisz i zatwierdź” włącza regułę od razu."
        size="xl"
      >
        <div className="space-y-4">
          <ClientSinglePicker
            value={addClient}
            onChange={setAddClient}
            queryKey="clients-lookup-cv-rules"
            placeholder="Wybierz klienta…"
          />
          {addClient ? (
            <>
              {addTargetHasRule ? (
                <p className="text-xs text-amber-700 dark:text-amber-400">
                  Ten klient ma już regułę — edytujesz istniejącą.
                </p>
              ) : null}
              <CvRuleEditor
                clientId={addClient.id}
                allowDelete
                onChanged={(rule) => invalidate(rule.client_id)}
                onDeleted={() => {
                  invalidate(addClient.id);
                  closeAdd();
                }}
              />
            </>
          ) : null}
        </div>
      </AppModal>

      <AppModal
        open={editor !== null}
        onOpenChange={(open) => {
          if (!open) closeEditor();
        }}
        title={editor ? `Reguły CV — ${editor.clientName}` : "Reguły CV"}
        size="xl"
      >
        {editor ? (
          <CvRuleEditor
            clientId={editor.clientId}
            initialTab={editor.initialTab}
            allowDelete
            onChanged={(rule) => invalidate(rule.client_id)}
            onDeleted={() => {
              invalidate(editor.clientId);
              closeEditor();
            }}
          />
        ) : null}
      </AppModal>

      <AppModal
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        title="Usunąć regułę CV?"
        description={
          pendingDelete
            ? `${pendingDelete.client_name ?? `#${pendingDelete.client_id}`} wróci do ogólnej nazwy pliku i wolnego wyboru języka.`
            : undefined
        }
        size="sm"
        footer={
          <>
            <Button
              type="button"
              variant="outline"
              onClick={() => setPendingDelete(null)}
              disabled={deleteMutation.isPending}
            >
              Anuluj
            </Button>
            <Button
              type="button"
              variant="destructive"
              loading={deleteMutation.isPending}
              onClick={() =>
                pendingDelete && deleteMutation.mutate(pendingDelete.client_id)
              }
            >
              Usuń regułę
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted-foreground">
          Tej operacji nie da się cofnąć — regułę trzeba będzie wpisać od nowa.
        </p>
      </AppModal>
    </div>
  );
}
