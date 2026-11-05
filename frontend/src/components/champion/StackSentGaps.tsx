"use client";

import { useState } from "react";

import { SentGapCallout } from "@/components/champion/RequirementRowCallouts";
import type { RequirementSentGaps } from "@/components/champion/RequirementRowsEditor";
import {
  addLegacyMustVariant,
  mustItemWords,
  removeLegacyMustItem,
  sentGapForRow,
  type LegacyRequirements,
  type TalkItem,
} from "@/lib/requirement-rows";
import { cn } from "@/lib/utils";

/**
 * Ostrzeżenie „nie ma nikt z wysłanych” przy starym profilu bez edytora wierszy
 * (05.11.2026): te same akcje co pod wierszem, tylko na polach „Musi mieć”
 * i wymaganiach do wyszukiwania. Słowo z podpowiedzi to wariant „A lub B”,
 * bo tak ta lista zapisuje alternatywę.
 */
export function StackSentGaps<T extends { name: string }>({
  must,
  requirements,
  critical,
  gaps,
  onChange,
  onMoveToTalk,
  className,
}: LegacyRequirements<T> & {
  gaps: RequirementSentGaps;
  onChange: (next: LegacyRequirements<T>) => void;
  onMoveToTalk: (item: TalkItem) => void;
  className?: string;
}) {
  const [dismissed, setDismissed] = useState<ReadonlySet<string>>(new Set());
  const legacy = { must, requirements, critical };
  const shown = must.flatMap((item) => {
    const words = mustItemWords(item.name);
    const gap = dismissed.has(item.name) ? null : sentGapForRow(words, gaps.rows);
    return gap ? [{ name: item.name, words, label: gap.label }] : [];
  });
  if (shown.length === 0) return null;
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {shown.map(({ name, words, label }) => (
        <SentGapCallout
          key={name}
          word={name}
          gap={{
            sent: gaps.sent,
            words: gaps.wordsFor(label),
            canAsk: gaps.canAsk,
            asking: gaps.asking,
            askError: gaps.askError,
          }}
          countEnabled
          onAsk={gaps.onAsk}
          onAddWord={(word) => onChange(addLegacyMustVariant(legacy, name, word))}
          onTalk={() => {
            onChange(removeLegacyMustItem(legacy, name));
            onMoveToTalk({ name: words.join(" / "), kind: "skills", level: "must" });
          }}
          onKeep={() => setDismissed((prev) => new Set(prev).add(name))}
        />
      ))}
    </div>
  );
}
