"""Wspólny dawca stron (`candidate_id` + `client_id`) dla testów umów.

Ten helper istniał w czterech kopiach naraz i to nie była kosmetyka: dwie z nich
zostały naprawione, a dwie zostały z pierwotną, wadliwą regułą — więc czerwień
nie znikała, tylko WĘDROWAŁA. Podział na shardy (`CI_SHARD_*`) jest
round-robinem po plikach, a nie stałym przypisaniem, więc dopisanie DOWOLNEGO
pliku testowego przestawia partycję i wystawia następną nienaprawioną kopię.
Dokładnie tak wyszła kopia w ``test_contract_framework_rate_schedule.py`` — po
dołożeniu testów niezwiązanych z umowami.

Reguła, której trzeba pilnować:

Umowa po USUNIĘTYM kandydacie ma ``candidate_id IS NULL`` — migracja 0225
zdejmuje FK przez ``ON DELETE SET NULL``, żeby skasowanie osoby nie zabrało ze
sobą faktur i dokumentów podpisu. Taka sierota nie może być dawcą stron:
``POST /api/contracts`` wymaga ``candidate_id: int`` i odpowiada 422
(„Input should be a valid integer, input: null").

Lista ``/api/contracts`` nie ma ``ORDER BY``, więc ``items[0]`` to po prostu
pierwszy wiersz zwrócony przez Postgresa — w świeżej bazie CI zwykle
NAJSTARSZY. Taką sierotę zostawia po sobie ``test_candidate_delete.py``.
Bierzemy więc pierwszą umowę z ŻYWYM kandydatem, a nie pierwszą z brzegu, i
pytamy o całą stronę (``page_size=100``), bo przy ``page_size=1`` jedyny
zwrócony wiersz może być właśnie sierotą i helper odda ``None`` mimo że w bazie
stoi komplet użytecznych umów.
"""

from httpx import AsyncClient

__all__ = ["pick_parties"]


async def pick_parties(app_client: AsyncClient, headers: dict):
    """Zwróć ``(candidate_id, client_id)`` z pierwszej umowy z żywym kandydatem.

    ``None``, gdy w bazie nie ma ANI JEDNEJ takiej umowy — wołający pomija
    wtedy test, zamiast wysyłać żądanie, o którym z góry wiadomo, że da 422.
    """
    items = (
        (await app_client.get("/api/contracts?page_size=100", headers=headers))
        .json()
        .get("items", [])
    )
    for item in items:
        if item.get("candidate_id") is not None:
            return item["candidate_id"], item["client_id"]
    return None
