import { redirect } from "next/navigation";

/**
 * /finance/faktury — okruszek „Faktury” nad kartą faktury prowadzi tutaj;
 * lista szkiców i wysłanych żyje w Finanse → Faktury do klientów.
 */
export default function IssuedInvoicesIndex() {
  redirect("/finance?view=sales-invoices");
}
