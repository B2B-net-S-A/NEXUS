"use client";

import { useCallback, useEffect, useState } from "react";
import { Bell, Loader2, Mail, Pencil, Plus, Trash2, Wifi, X } from "lucide-react";
import {
  stageNotificationRulesApi,
  type StageNotificationRule,
  type StageNotificationRuleInput,
} from "@/lib/api";
import { RECIPIENT_LABELS, StageRuleForm } from "./StageRuleForm";

interface Props {
  templateId: number;
  stageDefId: number;
  stageName: string;
  onClose: () => void;
}

export function StageNotificationRulesModal({
  templateId,
  stageDefId,
  stageName,
  onClose,
}: Props) {
  const [rules, setRules] = useState<StageNotificationRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<number | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadRules = useCallback(async () => {
    setLoading(true);
    try {
      const res = await stageNotificationRulesApi.list(templateId, stageDefId);
      setRules(res.data);
      setError(null);
    } catch (err: unknown) {
      console.error(err);
      setError("Nie udało się pobrać reguł.");
    } finally {
      setLoading(false);
    }
  }, [templateId, stageDefId]);

  useEffect(() => {
    void loadRules();
  }, [loadRules]);

  const handleCreate = async (data: StageNotificationRuleInput) => {
    await stageNotificationRulesApi.create(templateId, stageDefId, data);
    setEditingId(null);
    await loadRules();
  };

  const handleUpdate = async (
    ruleId: number,
    data: StageNotificationRuleInput,
  ) => {
    await stageNotificationRulesApi.update(templateId, stageDefId, ruleId, data);
    setEditingId(null);
    await loadRules();
  };

  const handleDelete = async (ruleId: number) => {
    if (!confirm("Usunąć regułę ? ")) return;
    try {
      await stageNotificationRulesApi.delete(templateId, stageDefId, ruleId);
      await loadRules();
    } catch (err: unknown) {
      console.error(err);
      alert("Nie udało się usunąć reguły.");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-lg bg-card dark:bg-muted shadow-xl">
        <div className="sticky top-0 flex items-center justify-between border-b border-border dark:border-border bg-card dark:bg-muted px-5 py-4">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <Bell className="w-5 h-5 text-primary" />
              Powiadomienia: {stageName}
            </h2>
            <p className="text-xs text-muted-foreground mt-0.5">
              Reguły wyzwalane gdy kandydat WCHODZI na ten etap (forward-only,
              real-time).
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded p-1 hover:bg-muted dark:hover:bg-muted"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          {error && (
            <p className="text-sm text-destructive bg-destructive/10 dark:bg-destructive/15 border border-destructive/20 dark:border-red-700 rounded px-3 py-2">
              {error}
            </p>
          )}

          {loading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-6">
              <Loader2 className="w-4 h-4 animate-spin" />
              Ładuję reguły…
            </div>
          ) : (
            <>
              {rules.length === 0 && editingId !== "new" && (
                <p className="text-sm text-muted-foreground py-2">
                  Brak reguł. Dodaj pierwszą – kandydat na tym etapie nie
                  wygeneruje powiadomień, dopóki nie skonfigurujesz adresatów.
                </p>
              )}

              <ul className="space-y-2">
                {rules.map((r) => {
                  const isEditing = editingId === r.id;
                  return (
                    <li
                      key={r.id}
                      className="rounded-md border border-border dark:border-border bg-card dark:bg-muted"
                    >
                      <div className="flex items-center gap-3 px-3 py-2">
                        <span
                          className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                            r.is_active
                              ? "bg-primary/10 text-primary border border-primary/20"
                              : "bg-muted text-muted-foreground border border-border"
                          }`}
                        >
                          {RECIPIENT_LABELS[r.recipient_type]}
                          {r.role ? ` · ${r.role}` : ""}
                          {r.specific_user_id
                            ? ` · #${r.specific_user_id}`
                            : ""}
                        </span>
                        <span className="flex items-center gap-2 text-xs text-muted-foreground">
                          {r.notify_inapp && (
                            <span
                              title="In-app"
                              className="inline-flex items-center gap-1"
                            >
                              <Wifi className="w-3.5 h-3.5" /> in-app
                            </span>
                          )}
                          {r.notify_email && (
                            <span
                              title="Email"
                              className="inline-flex items-center gap-1"
                            >
                              <Mail className="w-3.5 h-3.5" /> email
                            </span>
                          )}
                          {!r.is_active && (
                            <span className="text-amber-600">(wyłączona)</span>
                          )}
                        </span>
                        <div className="ml-auto flex items-center gap-1">
                          <button
                            onClick={() => setEditingId(r.id)}
                            className="text-muted-foreground hover:text-foreground dark:hover:text-muted-foreground p-1"
                            title="Edytuj"
                          >
                            <Pencil className="w-4 h-4" />
                          </button>
                          <button
                            onClick={() => handleDelete(r.id)}
                            className="text-red-400 hover:text-destructive p-1"
                            title="Usuń"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>

                      {isEditing && (
                        <div className="px-3 pb-3">
                          <StageRuleForm
                            initial={{
                              recipient_type: r.recipient_type,
                              specific_user_id: r.specific_user_id,
                              role: r.role,
                              notify_inapp: r.notify_inapp,
                              notify_email: r.notify_email,
                              is_active: r.is_active,
                            }}
                            onCancel={() => setEditingId(null)}
                            onSave={(data) => handleUpdate(r.id, data)}
                            saveLabel="Zapisz zmiany"
                          />
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>

              {editingId === "new" ? (
                <StageRuleForm
                  onCancel={() => setEditingId(null)}
                  onSave={handleCreate}
                  saveLabel="Dodaj regułę"
                />
              ) : (
                <button
                  onClick={() => setEditingId("new")}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-md border border-dashed border-border dark:border-border text-sm text-foreground dark:text-muted-foreground hover:bg-muted dark:hover:bg-muted"
                >
                  <Plus className="w-4 h-4" />
                  Dodaj regułę
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
