"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "@/components/ui/button";

const LONG = 280;

/** Stopka Atlasa odsyła do zakładki „Transkrypcje”, której NEXUS nie ma — wycinamy ją. */
export function stripTranscriptFooter(body: string): string {
  return body.replace(/\n*[-_]*\s*\*?Pełna transkrypcja[^\n]*$/i, "").trim();
}

/** Treść wpisu: notatki jako Markdown (podsumowania Fireflies z Atlasa), maile jako tekst; długie zwinięte. */
export function ActivityBody({ body, markdown = true }: { body: string; markdown?: boolean }) {
  const [open, setOpen] = useState(false);
  const text = stripTranscriptFooter(body);
  const long = text.length > LONG;
  return (
    <div className="text-muted-foreground">
      <div
        className={`prose prose-sm max-w-none text-muted-foreground prose-p:my-1 prose-ul:my-1 prose-li:my-0 prose-strong:text-foreground ${
          long && !open ? "line-clamp-4" : ""
        }`}
      >
        {markdown ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        ) : (
          <p className="whitespace-pre-line">{text}</p>
        )}
      </div>
      {long && (
        <Button size="sm" variant="quiet" className="h-6 px-0" onClick={() => setOpen((value) => !value)}>
          {open ? "Zwiń" : "Pokaż całość"}
        </Button>
      )}
    </div>
  );
}
