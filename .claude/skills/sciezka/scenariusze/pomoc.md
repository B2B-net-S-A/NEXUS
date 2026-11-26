# Scenariusz: Pomoc (Procedury, Klienci, Materiały admina)

Reguła: `docs/claude/ui/pomoc-bez-wzorow-word-dokumenty-w-generatorach.md`,
karta klienta: `docs/claude/klienci/karta-klienta-client-playbooks.md`.

Kto → co robi → co widzi następny:

1. **Rekruter** otwiera Pomoc. Widzi pasek „Wzorów w Wordzie już tu nie ma”
   z odnośnikami, do których ma dostęp, i dwie zakładki: Procedury, Klienci.
   Materiałów nie ma; stary link `/help?tab=materials` otwiera Procedury.
   Klik w „Profil Championa” prowadzi do Rekrutacji.
2. **Rekruter** otwiera rekrutację klienta z formularzami onboardingowymi
   (np. VeloBank, Tauron) → „Pełna karta klienta →” → karta w Pomocy ma
   formularze w „Dokumentach”; link otwiera plik w SharePoincie.
3. **Rekruter** w Rozmowach otwiera „Zaproś na prep”: treść zaproszenia jest
   (wiersz w Materiałach nie został odpublikowany).
4. **Delivery Lead** w profilu klienta → „Zasady współpracy” widzi te same
   dokumenty w formularzu karty i może dopisać nowy; w historii karty jest wpis
   kroku jednorazowego.
5. **Admin** widzi zakładkę Materiały z dopiskiem „Widoczne tylko dla admina”,
   wzory i przeniesione formularze jako szkic, zaproszenie na prep opublikowane
   i edytowalne.

Rola, która ma nie widzieć: rekruter — Materiałów nie ma w zakładkach (lista
`/api/help-materials` dalej odpowiada, bo czyta ją okno zaproszenia).

Krok jednorazowy zmienia karty klientów, więc backend gałęzi stoi na własnej
kopii bazy (`nexus_branch_<port>`), nie na wspólnej bazie stagingu.
