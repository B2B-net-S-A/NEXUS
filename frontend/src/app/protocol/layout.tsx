/**
 * Publiczna strona podpisu protokołu sprzętu — bez powłoki aplikacji i bez
 * logowania (link z tokenem). Ten sam wzór co `/sign/{token}`.
 */
export default function ProtocolLayout({ children }: { children: React.ReactNode }) {
  return <div className="min-h-screen min-h-dvh bg-background text-foreground">{children}</div>;
}
