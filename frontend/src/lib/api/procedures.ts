import api from "@/lib/api";

export interface ProcedureSummary {
  id: number;
  slug: string;
  title: string;
  sort_order: number;
  is_published: boolean;
  updated_at: string;
}

export interface Procedure extends ProcedureSummary {
  content: string;
  created_by: number | null;
  updated_by: number | null;
  created_at: string;
}

export interface ProcedureCreateInput {
  title: string;
  content: string;
  sort_order?: number;
  is_published?: boolean;
}

export interface ProcedureUpdateInput {
  title?: string;
  content?: string;
  sort_order?: number;
  is_published?: boolean;
}

export const proceduresApi = {
  list: (params?: { q?: string; published_only?: boolean }) =>
    api
      .get<ProcedureSummary[]>("/api/procedures", {
        params: {
          q: params?.q?.trim() || undefined,
          published_only: params?.published_only,
        },
      })
      .then((r) => r.data),

  get: (idOrSlug: string | number) =>
    api.get<Procedure>(`/api/procedures/${idOrSlug}`).then((r) => r.data),

  create: (data: ProcedureCreateInput) =>
    api.post<Procedure>("/api/procedures", data).then((r) => r.data),

  update: (id: number, data: ProcedureUpdateInput) =>
    api.put<Procedure>(`/api/procedures/${id}`, data).then((r) => r.data),

  remove: (id: number) => api.delete(`/api/procedures/${id}`),
};
