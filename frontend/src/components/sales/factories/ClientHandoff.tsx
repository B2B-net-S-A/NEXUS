import { StatusDot } from "@/components/ds/StatusDot";
import type { FactoryClient } from "@/lib/api/sales-factories";

/**
 * Firma jest klientem NEXUSA: popyt u klienta prowadzi jego Delivery Lead
 * (decyzja z 22.10.2026), więc wiersz mówi, do kogo iść, zamiast zachęcać do kontaktu.
 */
export function ClientHandoff({ client }: { client: FactoryClient }) {
  if (client.delivery_lead) {
    return (
      <StatusDot
        tone="info"
        title={`${client.name} to klient NEXUSA. Temat prowadzi Delivery Lead: ${client.delivery_lead}.`}
      >
        Uzgodnij z DL: {client.delivery_lead}
      </StatusDot>
    );
  }
  return (
    <StatusDot tone="warning" title={`${client.name} to klient NEXUSA, ale nie ma przypisanego Delivery Leada.`}>
      Klient bez Delivery Leada: zgłoś do Heada
    </StatusDot>
  );
}
