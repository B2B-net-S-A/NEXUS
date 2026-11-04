/**
 * Publiczna strona wypisu z komunikatów informacyjnych — bez powłoki aplikacji
 * i bez logowania (link z tokenem z maila). Ten sam wzór co `/protocol/{token}`.
 */
export default function UnsubscribeLayout({ children }: { children: React.ReactNode }) {
  return <div className="min-h-screen min-h-dvh bg-background text-foreground">{children}</div>;
}
