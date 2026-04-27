"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bell,
  Loader2,
  Mail,
  Pencil,
  Plus,
  Trash2,
  Wifi,
} from "lucide-react";
import {
  clientNotificationOverridesApi,
  pipelineTemplatesApi,
  type ClientStageNotificationOverride,
  type ClientStageOverrideInput,
  type PipelineTemplateDetail,
  type PipelineTemplateSummary,
  type StageDef,
} from "@/lib/api";
import {
  RECIPIENT_LABELS,
  StageRuleForm,
} from "@/components/StageRuleForm";

interface Props {
  clientId: number;
}

export function NotificationsTab({ clientId }: Props) {
  const [templates, setTemplates] = useState<PipelineTemplateDetail[]>([]);
  const [overrides, setOverrides] = useState<
    ClientStageNotificationOverride[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creatingFor, setCreatingFor] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);

  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [tplListRes, overridesRes] = await Promise.all([
        pipelineTemplatesApi.list(),
        clientNotificationOverridesApi.list(clientId),
      ]);
      const summaries: PipelineTemplateSummary[] = tplListRes.data;
      const fullDetails = await Promise.all(
        summaries.map((s) => pipelineTemplatesApi.get(s.id).then((r) => r.data)),
      );
      setTemplates(fullDetails);
      setOverrides(overridesRes.data);
      setError(null);
    } catch (err: unknown) {
      console.error(err);
      setError("Nie udało się pobrać reguł.");
    } finally {
      setLoading(false);
    }
  }, [clientId]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  // Mapuj wszystkie stage_def-y po id (nazwa + nazwa template'u).
  const stageMeta = useMemo(() => {
    const map = new Map<
      number,
      { stageName: string; templateName: string; stage: StageDef }
    >();
    for (const tpl of templates) {
      for (const stage of tpl.stages) {
        map.set(stage.id, {
          stageName: stage.name,
          templateName: tpl.name,
          stage,
        });
      }
    }
    return map;
  }, [templates]);

  const overridesByStage = useMemo(() => {
    const map = new Map<number, ClientStageNotificationOverride[]>();
    for (const o of overrides) {
      const list = map.get(o.stage_def_id) ?? [];
      list.push(o);
      map.set(o.stage_def_id, list);
    }
    return map;
  }, [overrides]);

  const handleCreate = async (
    stageDefId: number,
    data: ClientStageOverrideInput,
  ) => {
    await clientNotificationOverridesApi.create(clientId, {
      ...data,
      stage_def_id: stageDefId,
    });
    setCreatingFor(null);
    await loadAll();
  };

  const handleUpdate = async (
    overrideId: number,
    data: ClientStageOverrideInput,
  ) => {
    const { stage_def_id: _drop, ...patch } = data;
    void _drop;
    await clientNotificationOverridesApi.update(clientId, overrideId, patch);
    setEditingId(null);
    await loadAll();
  };

  const handleDelete = async (overrideId: number) => {
    if (!confirm("Usunąć override? Stage wróci do baseline.")) return;
    try {
      await clientNotificationOverridesApi.delete(clientId, overrideId);
      await loadAll();
    } catch (err) {
      console.error(err);
      alert("Nie udało się usunąć.");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-gray-500 py-6">
        <Loader2 className="w-4 h-4 animate-spin" />
        Ładuję reguły powiadomień…
      </div>
    );
  }

  if (error) {
    return (
      <p className="text-sm text-red-600 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-700 rounded px-3 py-2">
        {error}
      </p>
    );
  }

  return (
    <div className="space-y-6">
      <div className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
        <h2 className="flex items-center gap-2 text-base font-semibold mb-1">
          <Bell className="w-5 h-5 text-blue-600" />
          Powiadomienia per stage
        </h2>
        <p className="text-sm text-gray-500">
          Override per klient. Jeśli na danym etapie istnieje przynajmniej
          jeden aktywny override poniżej, baseline rules z procesu rekrutacji
          są <strong>całkowicie pomijane</strong> dla tego klienta. Brak
          override → działa baseline z template'u joba.
        </p>
      </div>

      {templates.map((tpl) => (
        <div
          key={tpl.id}
          className="bg-white dark:bg-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 p-4"
        >
          <h3 className="font-medium text-sm mb-3">
            Proces: {tpl.name}
            {tpl.is_default && (
              <span className="ml-2 text-xs text-blue-600">(domyślny)</span>
            )}
          </h3>

          <div className="space-y-2">
            {tpl.stages.map((stage) => {
              const list = overridesByStage.get(stage.id) ?? [];
              const isCreating = creatingFor === stage.id;
              return (
                <div
                  key={stage.id}
                  className="rounded-md border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40"
                >
                  <div className="flex items-center gap-3 px-3 py-2">
                    <span className="font-medium text-sm flex-1">
                      {stage.name}
                    </span>
                    {list.length === 0 ? (
                      <span className="text-xs text-gray-500">
                        Baseline z procesu „{tpl.name}"
                      </span>
                    ) : (
                      <span className="text-xs text-blue-600">
                        Override aktywny ({list.length}) — baseline pominięty
                      </span>
                    )}
                    <button
                      onClick={() =>
                        setCreatingFor(isCreating ? null : stage.id)
                      }
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs text-gray-700 dark:text-gray-200 hover:bg-blue-50 dark:hover:bg-blue-900/30"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      Dodaj override
                    </button>
                  </div>

                  {list.length > 0 && (
                    <ul className="px-3 pb-2 space-y-1">
                      {list.map((o) => {
                        const isEditing = editingId === o.id;
                        return (
                          <li
                            key={o.id}
                            className="rounded border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"
                          >
                            <div className="flex items-center gap-3 px-2 py-1.5">
                              <span
                                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                                  o.is_active
                                    ? "bg-blue-50 text-blue-700 border border-blue-200"
                                    : "bg-gray-100 text-gray-500 border border-gray-200"
                                }`}
                              >
                                {RECIPIENT_LABELS[o.recipient_type]}
                                {o.role ? ` · ${o.role}` : ""}
                                {o.specific_user_id
                                  ? ` · #${o.specific_user_id}`
                                  : ""}
                              </span>
                              <span className="flex items-center gap-2 text-xs text-gray-500">
                                {o.notify_inapp && (
                                  <span className="inline-flex items-center gap-1">
                                    <Wifi className="w-3 h-3" /> in-app
                                  </span>
                                )}
                                {o.notify_email && (
                                  <span className="inline-flex items-center gap-1">
                                    <Mail className="w-3 h-3" /> email
                                  </span>
                                )}
                                {!o.is_active && (
                                  <span className="text-amber-600">
                                    (wyłączony)
                                  </span>
                                )}
                              </span>
                              <div className="ml-auto flex items-center gap-1">
                                <button
                                  onClick={() => setEditingId(o.id)}
                                  className="p-1 text-gray-500 hover:text-gray-800 dark:hover:text-gray-300"
                                  title="Edytuj"
                                >
                                  <Pencil className="w-3.5 h-3.5" />
                                </button>
                                <button
                                  onClick={() => handleDelete(o.id)}
                                  className="p-1 text-red-400 hover:text-red-600"
                                  title="Usuń"
                                >
                                  <Trash2 className="w-3.5 h-3.5" />
                                </button>
                              </div>
                            </div>
                            {isEditing && (
                              <div className="px-2 pb-2">
                                <StageRuleForm
                                  initial={{
                                    recipient_type: o.recipient_type,
                                    specific_user_id: o.specific_user_id,
                                    role: o.role,
                                    notify_inapp: o.notify_inapp,
                                    notify_email: o.notify_email,
                                    is_active: o.is_active,
                                  }}
                                  onCancel={() => setEditingId(null)}
                                  onSave={(data) =>
                                    handleUpdate(o.id, {
                                      ...data,
                                      stage_def_id: o.stage_def_id,
                                    })
                                  }
                                  saveLabel="Zapisz zmiany"
                                />
                              </div>
                            )}
                          </li>
                        );
                      })}
                    </ul>
                  )}

                  {isCreating && (
                    <div className="px-3 pb-3">
                      <StageRuleForm
                        onCancel={() => setCreatingFor(null)}
                        onSave={(data) =>
                          handleCreate(stage.id, {
                            ...data,
                            stage_def_id: stage.id,
                          })
                        }
                        saveLabel="Dodaj override"
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {templates.length === 0 && (
        <p className="text-sm text-gray-500">
          Brak procesów rekrutacyjnych w systemie.
        </p>
      )}
    </div>
  );
}

// ── Helper: pull stageMeta when needed (kept inline above for simplicity) ───
// Eksport stageMeta zostaje na potrzeby ewentualnego reuse'u przez inny tab.
