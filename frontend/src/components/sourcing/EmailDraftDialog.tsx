"use client";

import { useState } from "react";
import { Copy, Mail, X } from "lucide-react";

interface Props {
  title: string;
  to?: string;
  subject: string;
  textBody: string;
  htmlBody?: string;
  onClose: () => void;
}

/**
 * Read-only preview of a generated draft (shortlist email or client proposal).
 *
 * MVP scope: shows the draft, lets the user copy text/html to clipboard, and
 * advises pasting into the recruiter's email client. Real send happens
 * separately via the existing /api/emails/send endpoint once the user is
 * ready (intentional friction so we never auto-fire to a candidate or client).
 */
export function EmailDraftDialog({
  title,
  to,
  subject,
  textBody,
  htmlBody,
  onClose,
}: Props) {
  const [copied, setCopied] = useState<"text" | "html" | "subject" | null>(null);

  const copy = async (kind: "text" | "html" | "subject", value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(kind);
      window.setTimeout(() => setCopied((c) => (c === kind ? null : c)), 2000);
    } catch {
      // best effort – clipboard might be denied
    }
  };

  const mailtoHref = to
    ? `mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(textBody)}`
    : null;

  return (
    <div
      className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="bg-card dark:bg-card rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-border dark:border-border p-4">
          <h2 className="font-semibold text-foreground dark:text-foreground flex items-center gap-2">
            <Mail className="w-5 h-5 text-purple-500" />
            {title}
          </h2>
          <button
            onClick={onClose}
            aria-label="Zamknij"
            className="text-muted-foreground hover:text-foreground"
          >
            <X className="w-5 h-5" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {to && (
            <Field label="Do">
              <span className="text-sm font-mono">{to}</span>
            </Field>
          )}
          <Field label="Temat">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium flex-1">{subject}</span>
              <CopyButton
                onClick={() => copy("subject", subject)}
                copied={copied === "subject"}
              />
            </div>
          </Field>
          <Field label="Treść (plain text)">
            <div className="relative">
              <pre className="bg-muted dark:bg-muted border border-border dark:border-border rounded p-3 text-xs whitespace-pre-wrap font-mono max-h-72 overflow-y-auto">
                {textBody}
              </pre>
              <CopyButton
                onClick={() => copy("text", textBody)}
                copied={copied === "text"}
                absolute
              />
            </div>
          </Field>

          {htmlBody && (
            <Field label="Podgląd (HTML)">
              <div
                className="bg-muted dark:bg-muted border border-border dark:border-border rounded p-3 max-h-72 overflow-y-auto"
                // eslint-disable-next-line react/no-danger
                dangerouslySetInnerHTML={{ __html: htmlBody }}
              />
            </Field>
          )}

          <div className="flex gap-2 pt-2">
            {mailtoHref && (
              <a
                href={mailtoHref}
                target="_blank"
                rel="noopener noreferrer"
                className="bg-primary hover:bg-primary/90 text-white text-sm font-medium px-4 py-2 rounded-md inline-flex items-center gap-2"
              >
                <Mail className="w-4 h-4" /> Otwórz w kliencie pocztowym
              </a>
            )}
            <button
              onClick={onClose}
              className="text-sm text-muted-foreground hover:text-foreground px-3 py-2 rounded-md"
            >
              Zamknij
            </button>
          </div>

          <p className="text-xs text-muted-foreground italic">
            Draft jest przeglądowy – wyślesz go z własnego klienta poczty
            (Gmail, Outlook, M365), żeby utrzymać tożsamość nadawcy. Nic nie
            zostało jeszcze wysłane.
          </p>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground font-semibold mb-1">
        {label}
      </div>
      {children}
    </div>
  );
}

function CopyButton({
  onClick,
  copied,
  absolute,
}: {
  onClick: () => void;
  copied: boolean;
  absolute?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      className={`text-xs flex items-center gap-1 px-2 py-1 rounded border ${
        copied
          ? "bg-green-100 text-green-700 border-green-300"
          : "bg-card dark:bg-muted text-muted-foreground hover:text-foreground border-border"
      } ${absolute ? "absolute top-2 right-2" : ""}`}
    >
      <Copy className="w-3 h-3" />
      {copied ? "Skopiowano" : "Kopiuj"}
    </button>
  );
}
