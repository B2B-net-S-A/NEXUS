"use client";

import { useState } from "react";
import { Check, Copy, Mail, MessageSquare, Phone } from "lucide-react";
import { Linkedin } from "@/components/icons/Linkedin";

import { cn } from "@/lib/utils";

// Szybki kontakt z telefonu (decyzja Artura 14.11.2026, zmienia regułę z 05.11).
// Jedyny plik podglądu z linkami `tel:`, `sms:` i `mailto:` — pilnuje tego
// `phone-preview-read-only.test.ts`.

/** „+48 507 988 829” → „+48507988829”; bez cyfr = brak numeru. */
export function dialable(phone: string | null | undefined): string | null {
  const raw = (phone ?? "").trim();
  const digits = raw.replace(/\D/g, "");
  if (digits.length < 7) return null;
  return raw.startsWith("+") ? `+${digits}` : digits;
}

/** Czy wpisany tekst wygląda na numer (np. z nieodebranego połączenia). */
export function looksLikePhone(q: string): boolean {
  return /^[+\d\s()-]{6,}$/.test(q.trim()) && q.replace(/\D/g, "").length >= 6;
}

function Action({ href, icon: Icon, label, primary }: { href: string; icon: typeof Phone; label: string; primary?: boolean }) {
  return (
    <a
      href={href}
      target={href.startsWith("http") ? "_blank" : undefined}
      rel={href.startsWith("http") ? "noreferrer" : undefined}
      className={cn(
        "flex h-16 flex-col items-center justify-center gap-1 rounded-xl text-xs font-medium",
        primary ? "bg-primary text-primary-foreground" : "border bg-card",
      )}
    >
      <Icon className="h-5 w-5" />
      {label}
    </a>
  );
}

function CopyRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(value).then(() => setCopied(true));
      }}
      className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left"
    >
      <span className="min-w-0">
        <span className="block text-xs text-muted-foreground">{label}</span>
        <span className="block truncate text-base font-medium tabular-nums">{value}</span>
      </span>
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-muted" aria-label={`Kopiuj: ${label}`}>
        {copied ? <Check className="h-4 w-4 text-success-muted-foreground" /> : <Copy className="h-4 w-4" />}
      </span>
    </button>
  );
}

/** Wiersz przycisków (Zadzwoń, SMS, E-mail, LinkedIn) + numer i mail do skopiowania. */
export function ContactActions({ phone, email, linkedin }: { phone?: string | null; email?: string | null; linkedin?: string | null }) {
  const tel = dialable(phone);
  const actions = [
    tel ? { href: `tel:${tel}`, icon: Phone, label: "Zadzwoń", primary: true } : null,
    tel ? { href: `sms:${tel}`, icon: MessageSquare, label: "SMS" } : null,
    email ? { href: `mailto:${email}`, icon: Mail, label: "E-mail" } : null,
    linkedin ? { href: linkedin.startsWith("http") ? linkedin : `https://${linkedin}`, icon: Linkedin, label: "LinkedIn" } : null,
  ].filter((a): a is NonNullable<typeof a> => a !== null);
  if (!actions.length) {
    return <p className="rounded-xl border bg-card p-3 text-sm text-muted-foreground">Brak numeru i adresu e-mail w NEXUSIE.</p>;
  }
  return (
    <div className="space-y-2">
      <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${actions.length}, minmax(0, 1fr))` }}>
        {actions.map((a) => <Action key={a.label} {...a} />)}
      </div>
      <div className="divide-y rounded-xl border bg-card">
        {phone ? <CopyRow label="Telefon" value={phone} /> : null}
        {email ? <CopyRow label="E-mail" value={email} /> : null}
      </div>
    </div>
  );
}

/** Mały okrągły przycisk „Zadzwoń” do wiersza listy. */
export function CallButton({ phone }: { phone: string | null | undefined }) {
  const tel = dialable(phone);
  if (!tel) return null;
  return (
    <a href={`tel:${tel}`} aria-label="Zadzwoń" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
      <Phone className="h-5 w-5" />
    </a>
  );
}

/** Adres e-mail jako link do poczty, w jednej linii pod nazwą. */
export function MailLink({ email }: { email: string | null | undefined }) {
  if (!email) return null;
  return <a href={`mailto:${email}`} className="block truncate text-xs text-primary">{email}</a>;
}
