import api from "@/lib/api";

/**
 * Materiały (biblioteka dokumentów firmowych) — zakładka Pomoc → Materiały.
 *
 * NEXUS nie hostuje tych dokumentów: trzymamy WYŁĄCZNIE linki do SharePointa,
 * gdzie pliki są natywnie edytowalne w Word Online (z wersjonowaniem M365).
 * Odczyt: każdy zalogowany. Zapis (POST/PUT/DELETE): tylko rola `admin`.
 */
export interface HelpMaterial {
  id: number;
  slug: string;
  category: string;
  title: string;
  url: string;
  description: string | null;
  /** Nasz własny wzór — dostaje dodatkowy skrót „Edytuj w Word Online". */
  is_editable_template: boolean;
  sort_order: number;
  is_published: boolean;
  created_by: number | null;
  updated_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface HelpMaterialCreateInput {
  category: string;
  title: string;
  url: string;
  description?: string | null;
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
  url?: string;
  description?: string | null;
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
