"use client";

import { useState } from "react";
import { Plus } from "lucide-react";

import { useToast } from "@/components/Toast";
import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useDeleteFaq,
  usePortalStatus,
  useSaveFaq,
  useStaffFaq,
  type PortalTopicKey,
  type StaffFaq,
  type StaffFaqItem,
} from "@/lib/api/portal-staff";

import { PORTAL_STATE_LABELS } from "./portal-tabs-model";

function FaqDialog({
  item,
  topics,
  onClose,
}: {
  item: StaffFaqItem | null;
  topics: StaffFaq["topics"];
  onClose: () => void;
}) {
  const { showToast } = useToast();
  const save = useSaveFaq();
  const [topic, setTopic] = useState<PortalTopicKey>(item?.topic ?? topics[0]?.key ?? "invoice");
  const [question, setQuestion] = useState(item?.question ?? "");
  const [answer, setAnswer] = useState(item?.answer ?? "");
  const [published, setPublished] = useState(item?.published ?? true);
  const ready = question.trim().length >= 3 && answer.trim().length >= 3;
  return (
    <AppModal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={item ? "Zmień pytanie" : "Nowe pytanie"}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Anuluj
          </Button>
          <Button
            disabled={!ready || save.isPending}
            onClick={() =>
              save.mutate(
                {
                  id: item?.id ?? null,
                  input: {
                    topic,
                    question: question.trim(),
                    answer: answer.trim(),
                    position: item?.position ?? 0,
                    published,
                  },
                },
                {
                  onSuccess: onClose,
                  onError: (error) =>
                    showToast(apiErrorMessage(error, "Nie udało się zapisać pytania."), "error"),
                },
              )
            }
          >
            Zapisz
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <FormField label="Temat" htmlFor="faq-topic">
          <Select value={topic} onValueChange={(value) => setTopic(value as PortalTopicKey)}>
            <SelectTrigger id="faq-topic">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {topics.map((option) => (
                <SelectItem key={option.key} value={option.key}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        <FormField label="Pytanie" htmlFor="faq-question">
          <Input
            id="faq-question"
            maxLength={300}
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
        </FormField>
        <FormField label="Odpowiedź" htmlFor="faq-answer">
          <Textarea
            id="faq-answer"
            rows={6}
            maxLength={5000}
            value={answer}
            onChange={(event) => setAnswer(event.target.value)}
          />
        </FormField>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={published} onCheckedChange={(value) => setPublished(value === true)} />
          Widoczne w portalu
        </label>
      </div>
    </AppModal>
  );
}

/** Zakładka „FAQ portalu”: treść widoczna dla konsultantów, edytuje ją back office. */
export function PortalFaqTab() {
  const { showToast } = useToast();
  const faq = useStaffFaq();
  const status = usePortalStatus();
  const remove = useDeleteFaq();
  const { askConfirm, confirmDialog } = useConfirmV2();
  const [editing, setEditing] = useState<StaffFaqItem | "new" | null>(null);

  if (faq.isLoading) return <p className="text-sm text-muted-foreground">Wczytujemy pytania…</p>;
  if (faq.isError || !faq.data) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(faq.error, "Nie udało się wczytać pytań.")}
        onRetry={() => faq.refetch()}
      />
    );
  }
  const data = faq.data;
  const confirmDelete = async (item: StaffFaqItem) => {
    const yes = await askConfirm({
      title: "Usunąć to pytanie?",
      description: item.question,
      confirmLabel: "Usuń",
      variant: "destructive",
    });
    if (!yes) return;
    remove.mutate(item.id, {
      onError: (error) => showToast(apiErrorMessage(error, "Nie udało się usunąć pytania."), "error"),
    });
  };
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">
          {status.data ? PORTAL_STATE_LABELS[status.data.state] : null}
        </p>
        <Button size="sm" onClick={() => setEditing("new")}>
          <Plus aria-hidden className="size-4" /> Nowe pytanie
        </Button>
      </div>
      {data.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">Nie ma jeszcze pytań.</p>
      ) : (
        data.topics.map((topic) => {
          const rows = data.items.filter((item) => item.topic === topic.key);
          if (rows.length === 0) return null;
          return (
            <section key={topic.key} className="rounded-xl border bg-card">
              <h3 className="border-b px-4 py-2 text-sm font-semibold">{topic.label}</h3>
              <ul className="divide-y">
                {rows.map((item) => (
                  <li key={item.id} className="flex flex-wrap items-start justify-between gap-3 px-4 py-3 text-sm">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">
                        {item.question}{" "}
                        {item.published ? null : (
                          <Badge variant="neutral" size="sm">
                            szkic
                          </Badge>
                        )}
                      </p>
                      <p className="mt-1 whitespace-pre-line text-muted-foreground">{item.answer}</p>
                    </div>
                    <div className="flex gap-2">
                      <Button size="sm" variant="outline" onClick={() => setEditing(item)}>
                        Zmień
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => confirmDelete(item)}>
                        Usuń
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          );
        })
      )}
      {editing ? (
        <FaqDialog
          item={editing === "new" ? null : editing}
          topics={data.topics}
          onClose={() => setEditing(null)}
        />
      ) : null}
      {confirmDialog}
    </div>
  );
}
