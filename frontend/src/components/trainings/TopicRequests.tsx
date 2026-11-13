"use client";

import { useState } from "react";
import { Megaphone } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { FormField } from "@/components/ui/form-field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { TopicInput, TrainingTopic } from "@/lib/api/trainings";

const EMPTY: TopicInput = {
  title: "",
  description: "",
  audience: "",
  open: true,
};

function applicantsLabel(count: number): string {
  if (count === 0) return "nikt się jeszcze nie zgłosił";
  if (count === 1) return "1 zgłoszenie";
  const last = count % 10;
  const teen = count % 100 >= 12 && count % 100 <= 14;
  return `${count} ${last >= 2 && last <= 4 && !teen ? "zgłoszenia" : "zgłoszeń"}`;
}

interface TopicRequestsProps {
  topics: readonly TrainingTopic[];
  /** Nowy temat (`id` = null) albo zmiana; `true` = zapisane, formularz się czyści. */
  onSave: (id: number | null, input: TopicInput) => Promise<boolean>;
  busy?: boolean;
}

/**
 * „Szukamy trenerów” (0698): tematy, które konsultanci widzą w panelu i na które
 * mogą się zgłosić. Zamknięty temat znika z panelu, zgłoszenia zostają.
 */
export function TopicRequests({ topics, onSave, busy }: TopicRequestsProps) {
  const [draft, setDraft] = useState<TopicInput>(EMPTY);
  const open = topics.filter((topic) => topic.status === "open");
  const closed = topics.filter((topic) => topic.status === "closed");
  const toggle = (topic: TrainingTopic) =>
    void onSave(topic.id, {
      title: topic.title,
      description: topic.description,
      audience: topic.audience,
      open: topic.status !== "open",
    });

  return (
    <Card size="sm" className="space-y-4 p-4" data-testid="topic-requests">
      <div>
        <h2 className="inline-flex items-center gap-2 text-sm font-semibold text-foreground">
          <Megaphone className="h-4 w-4 text-muted-foreground" aria-hidden />{" "}
          Szukamy trenerów
        </h2>
        <p className="text-xs text-muted-foreground">
          Tematy widzą konsultanci w panelu (Szkolenia). „Zgłoś się na temat”
          dopisuje temat do ich zgłoszenia trenera poniżej.
        </p>
      </div>

      {open.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          Nie szukamy teraz trenerów na żaden temat.
        </p>
      ) : (
        <ul className="space-y-2">
          {open.map((topic) => (
            <li
              key={topic.id}
              className="flex flex-wrap items-start justify-between gap-2 rounded-md border border-border px-3 py-2"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium text-foreground">
                  {topic.title}
                </p>
                <p className="text-xs text-muted-foreground">
                  {[topic.audience, applicantsLabel(topic.applicants)]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
                {topic.description ? (
                  <p className="mt-1 whitespace-pre-line text-xs text-foreground">
                    {topic.description}
                  </p>
                ) : null}
              </div>
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => toggle(topic)}
              >
                Zamknij
              </Button>
            </li>
          ))}
        </ul>
      )}

      <form
        className="grid gap-2 border-t border-border pt-3 md:grid-cols-[minmax(0,1fr)_minmax(0,14rem)]"
        onSubmit={async (event) => {
          event.preventDefault();
          if (await onSave(null, draft)) setDraft(EMPTY);
        }}
      >
        <FormField label="Nowy temat" htmlFor="topic-title" required>
          <Input
            id="topic-title"
            value={draft.title}
            maxLength={200}
            placeholder="np. Terraform i IaC dla zespołów bankowych"
            onChange={(event) =>
              setDraft({ ...draft, title: event.target.value })
            }
          />
        </FormField>
        <FormField label="Dla kogo" htmlFor="topic-audience">
          <Input
            id="topic-audience"
            value={draft.audience}
            maxLength={200}
            placeholder="np. rekruterzy IT"
            onChange={(event) =>
              setDraft({ ...draft, audience: event.target.value })
            }
          />
        </FormField>
        <FormField
          label="Czego oczekujemy"
          htmlFor="topic-description"
          className="md:col-span-2"
        >
          <Textarea
            id="topic-description"
            rows={2}
            value={draft.description}
            maxLength={1000}
            onChange={(event) =>
              setDraft({ ...draft, description: event.target.value })
            }
          />
        </FormField>
        <div>
          <Button
            type="submit"
            size="sm"
            disabled={busy || draft.title.trim() === ""}
          >
            Opublikuj temat
          </Button>
        </div>
      </form>

      {closed.length > 0 ? (
        <details className="border-t border-border pt-2 text-sm">
          <summary className="cursor-pointer text-xs text-muted-foreground">
            Zamknięte tematy ({closed.length})
          </summary>
          <ul className="mt-2 space-y-1">
            {closed.map((topic) => (
              <li
                key={topic.id}
                className="flex items-center justify-between gap-2"
              >
                <span className="text-muted-foreground">
                  {topic.title}{" "}
                  <Badge variant="soft">
                    {applicantsLabel(topic.applicants)}
                  </Badge>
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => toggle(topic)}
                >
                  Otwórz ponownie
                </Button>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </Card>
  );
}
