"""Zmyślone pliki FA(3) do testów wizualizacji (firmy, NIP-y i kwoty fikcyjne)."""

from __future__ import annotations

NS = "http://crd.gov.pl/wzor/2025/06/25/13775/"


def correction_eur(
    *,
    seller_nip: str = "1111111111",
    buyer_nip: str = "2222222222",
    number: str = "KOR/7/11/2026",
    item_name: str = "Usługi programistyczne",
) -> bytes:
    """Korekta w EUR z trzema stawkami (23%, 8%, zw.), MPP, terminem i rachunkiem."""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Faktura xmlns="{NS}">
  <Naglowek>
    <KodFormularza kodSystemowy="FA (3)" wersjaSchemy="1-0E">FA</KodFormularza>
    <WariantFormularza>3</WariantFormularza>
    <DataWytworzeniaFa>2026-11-10T10:00:00Z</DataWytworzeniaFa>
  </Naglowek>
  <Podmiot1>
    <DaneIdentyfikacyjne><NIP>{seller_nip}</NIP><Nazwa>Dostawca Przykładowy sp. z o.o.</Nazwa></DaneIdentyfikacyjne>
    <Adres><KodKraju>PL</KodKraju><AdresL1>ul. Zmyślona 1</AdresL1><AdresL2>00-001 Warszawa</AdresL2></Adres>
  </Podmiot1>
  <Podmiot2>
    <DaneIdentyfikacyjne><NIP>{buyer_nip}</NIP><Nazwa>Nabywca Testowy S.A.</Nazwa></DaneIdentyfikacyjne>
    <Adres><KodKraju>PL</KodKraju><AdresL1>ul. Próbna 2</AdresL1></Adres>
  </Podmiot2>
  <Podmiot3>
    <DaneIdentyfikacyjne><NIP>3333333333</NIP><Nazwa>Faktor Testowy</Nazwa></DaneIdentyfikacyjne>
    <Rola>1</Rola>
  </Podmiot3>
  <Fa>
    <KodWaluty>EUR</KodWaluty>
    <P_1>2026-11-10</P_1>
    <P_1M>Kraków</P_1M>
    <P_2>{number}</P_2>
    <OkresFa><P_6_Od>2026-10-01</P_6_Od><P_6_Do>2026-10-31</P_6_Do></OkresFa>
    <P_13_1>-100.00</P_13_1><P_14_1>-23.00</P_14_1><P_14_1W>-98.21</P_14_1W>
    <P_13_2>50.00</P_13_2><P_14_2>4.00</P_14_2><P_14_2W>17.08</P_14_2W>
    <P_13_7>10.00</P_13_7>
    <P_15>-59.00</P_15>
    <KursWalutyZ>4.2700</KursWalutyZ>
    <Adnotacje>
      <P_16>2</P_16><P_17>2</P_17><P_18>2</P_18><P_18A>1</P_18A>
      <Zwolnienie><P_19>1</P_19><P_19A>art. 43 ust. 1 pkt 37 ustawy o VAT</P_19A></Zwolnienie>
      <NoweSrodkiTransportu><P_22N>1</P_22N></NoweSrodkiTransportu>
      <P_23>2</P_23>
      <PMarzy><P_PMarzyN>1</P_PMarzyN></PMarzy>
    </Adnotacje>
    <RodzajFaktury>KOR</RodzajFaktury>
    <PrzyczynaKorekty>Rabat za październik</PrzyczynaKorekty>
    <TypKorekty>2</TypKorekty>
    <DaneFaKorygowanej>
      <DataWystFaKorygowanej>2026-11-02</DataWystFaKorygowanej>
      <NrFaKorygowanej>FV/3/11/2026</NrFaKorygowanej>
      <NrKSeF>1</NrKSeF>
      <NrKSeFFaKorygowanej>{seller_nip}-20261102-0A0B0C0D0E0F-11</NrKSeFFaKorygowanej>
    </DaneFaKorygowanej>
    <DodatkowyOpis><Klucz>Projekt</Klucz><Wartosc>Alfa</Wartosc></DodatkowyOpis>
    <FaWiersz>
      <NrWierszaFa>1</NrWierszaFa><P_7>{item_name}</P_7><P_8A>godz.</P_8A><P_8B>10</P_8B>
      <P_9A>50.00</P_9A><P_11>500.00</P_11><P_12>23</P_12><StanPrzed>1</StanPrzed>
    </FaWiersz>
    <FaWiersz>
      <NrWierszaFa>2</NrWierszaFa><P_7>{item_name}</P_7><P_8A>godz.</P_8A><P_8B>8</P_8B>
      <P_9A>50.00</P_9A><P_11>400.00</P_11><P_12>23</P_12>
    </FaWiersz>
    <FaWiersz>
      <NrWierszaFa>3</NrWierszaFa><P_7>Licencja</P_7><P_8A>szt.</P_8A><P_8B>1</P_8B>
      <P_9A>50.00</P_9A><P_11>50.00</P_11><P_12>8</P_12>
    </FaWiersz>
    <FaWiersz>
      <NrWierszaFa>4</NrWierszaFa><P_7>Szkolenie</P_7><P_8A>szt.</P_8A><P_8B>1</P_8B>
      <P_9A>10.00</P_9A><P_11>10.00</P_11><P_12>zw</P_12>
    </FaWiersz>
    <Platnosc>
      <TerminPlatnosci><Termin>2026-11-24</Termin></TerminPlatnosci>
      <FormaPlatnosci>6</FormaPlatnosci>
      <RachunekBankowy><NrRB>PL61109010140000071219812874</NrRB><SWIFT>WBKPPLPP</SWIFT><NazwaBanku>Bank Testowy</NazwaBanku></RachunekBankowy>
    </Platnosc>
    <WarunkiTransakcji><Zamowienia><DataZamowienia>2026-09-15</DataZamowienia><NrZamowienia>ZAM-42</NrZamowienia></Zamowienia></WarunkiTransakcji>
  </Fa>
  <Stopka>
    <Informacje><StopkaFaktury>Dziękujemy za współpracę.</StopkaFaktury></Informacje>
    <Rejestry><KRS>0000000000</KRS><REGON>000000000</REGON></Rejestry>
  </Stopka>
</Faktura>
""".encode("utf-8")
