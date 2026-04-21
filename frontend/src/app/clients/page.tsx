import { cookies } from "next/headers";
import { readUiFlagFromCookies } from "@/lib/ui-flag";
import { ClientsPageV1 } from "@/components/v1/ClientsPageV1";
import { ClientsListV2 } from "@/components/v2/pages/ClientsListV2";

export default async function ClientsPage() {
  const cookieStore = await cookies();
  const ui = readUiFlagFromCookies(cookieStore);
  return ui === "v2" ? <ClientsListV2 /> : <ClientsPageV1 />;
}
