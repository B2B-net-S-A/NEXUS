"use client";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { CvRuleHistoryTab } from "./CvRuleHistoryTab";
export function useCentralPolicy(clientId?: number | null, stageId?: number | null, uploadedChampion = false) {
  return useQuery<{ managed: boolean; project_ref?: string | null; content_mode: "basic" | "polished" | "tailored"; default_mode?: "basic" | "polished" | "tailored"; content_mode_locked?: boolean; content_mode_notice?: string | null; publication_version?: number; effective_policy?: { key: string; version: number; source_url?: string; filename_pattern: string; cv_language: "pl" | "en" | null; requires_en_copy: boolean; require_recommendation_note: boolean; requires_rodo_consent_block: boolean; require_project_ref: boolean } }>({ queryKey: ["central-cv-policy", clientId ?? null, stageId ?? null, uploadedChampion], queryFn: async () => (await api.get("/api/cv-generator/policy", { params: { client_id: clientId || undefined, stage_id: stageId || undefined, uploaded_champion: uploadedChampion || undefined } })).data, staleTime: 30000 });
}
export function CentralPolicyView({ clientId }: { clientId: number }) {
  const query = useCentralPolicy(clientId);
  const policy = query.data?.effective_policy;
  return <div className="space-y-3 text-sm"><p className="font-medium">Reguły CV są zarządzane centralnie w backendzie.</p>{policy && <><p>Wersja katalogu: {policy.version}. Język: {policy.requires_en_copy ? "PL + EN" : policy.cv_language?.toUpperCase() || "wybierany przez użytkownika"}.</p><p>Nazwa pliku: <code>{policy.filename_pattern}</code></p>{policy.source_url && <a className="underline" href={policy.source_url} target="_blank" rel="noreferrer">Źródłowy Profil Championa</a>}</>}<CvRuleHistoryTab clientId={clientId} /></div>;
}
