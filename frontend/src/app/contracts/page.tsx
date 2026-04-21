import { cookies } from "next/headers";
import { readUiFlagFromCookies } from "@/lib/ui-flag";
import { ContractsPageV1 } from "@/components/v1/ContractsPageV1";
import { ContractsListV2 } from "@/components/v2/pages/ContractsListV2";

export default async function ContractsPage() {
  const cookieStore = await cookies();
  const ui = readUiFlagFromCookies(cookieStore);
  return ui === "v2" ? <ContractsListV2 /> : <ContractsPageV1 />;
}
