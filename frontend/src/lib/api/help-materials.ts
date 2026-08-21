import api from "@/lib/api";

/**
 * Materiały (biblioteka dokumentów firmowych) — zakładka Pomoc → Materiały.
 *
 * Pozycja jest ALBO linkiem do dokumentu w SharePoincie (`url`), ALBO SZABLONEM
 * TREŚCI (`template_subject` + `template_body`) — np. zaproszeniem
 * kalendarzowym, które nie jest plikiem. Spójności („jedno albo drugie") pilnuje
 * CHECK `ck_help_materials_link_or_template` w bazie i walidator w API.
 *
 * ⚠️ `url` jest NULLOWALNY od migracji 0229. Typ `string` kłamałby o kontrakcie
 * API i — co gorsza — uciszałby `tsc` na `material.url.toLowerCase()`, które na
 * zaseedowanym wierszu-szablonie wywala CAŁĄ sekcję Materiałów.
 *
 * NEXUS nie hostuje dokumentów: pliki zostają w SharePoincie, gdzie są
 * natywnie edytowalne w Word Online (z wersjonowaniem M365).
 * Odczyt: każdy zalogowany. Zapis (POST/PUT/DELETE): tylko rola `admin`.
 */
export interface HelpMaterial {
  id: number;
  slug: string;
  category: string;
  title: string;
  url: string | null;
  description: string | null;
  /** Temat szablonu — obecny tylko dla pozycji-szablonów. */
  template_subject: string | null;
  /** Treść szablonu; jej obecność decyduje, że pozycja JEST szablonem. */
  template_body: string | null;
  /** Nasz własny wzór — dostaje dodatkowy skrót „Edytuj w Word Online". */
  is_editable_template: boolean;
  sort_order: number;
  is_published: boolean;
  created_by: number | null;
  updated_by: number | null;
  created_at: string;
  updated_at: string;
}

/**
 * Pozycja z treścią szablonu — zawężenie typu po `template_body`.
 *
 * Predykat `isTemplateMaterial` mieszka świadomie w `@/lib/help-invite`, nie
 * tutaj: testy mockują ten moduł w CAŁOŚCI, więc funkcja trzymana po stronie
 * API wychodziłaby w nich jako brakujący eksport (udokumentowana pułapka
 * w CLAUDE.md tego repo). Sam TYP jest bezpieczny — znika przy kompilacji.
 */
export type HelpMaterialTemplate = HelpMaterial & { template_body: string };

export interface HelpMaterialCreateInput {
  category: string;
  title: string;
  url?: string | null;
  description?: string | null;
  template_subject?: string | null;
  template_body?: string | null;
  is_editable_template?: boolean;
  sort_order?: number;
  is_published?: boolean;
}

/**
 * PATCH-semantyka częściowa: pominięte pole zostaje na serwerze bez zmian.
 * Nie wysyłaj `undefined` jako „wyczyść" — do wyczyszczenia opisu użyj `null`.
 */
export interface HelpMaterialUpdateInput {
  category?: string;
  title?: string;
  url?: string | null;
  description?: string | null;
  template_subject?: string | null;
  template_body?: string | null;
  is_editable_template?: boolean;
  sort_order?: number;
  is_published?: boolean;
}

export const helpMaterialsApi = {
  list: (params?: { q?: string; published_only?: boolean }) =>
    api
      .get<HelpMaterial[]>("/api/help-materials", {
        params: {
          q: params?.q?.trim() || undefined,
          published_only: params?.published_only,
        },
      })
      .then((r) => r.data),

  create: (data: HelpMaterialCreateInput) =>
    api.post<HelpMaterial>("/api/help-materials", data).then((r) => r.data),

  update: (id: number, data: HelpMaterialUpdateInput) =>
    api.put<HelpMaterial>(`/api/help-materials/${id}`, data).then((r) => r.data),

  remove: (id: number) => api.delete(`/api/help-materials/${id}`),
};
