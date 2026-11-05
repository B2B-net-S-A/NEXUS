"""Słowa z treści CV, które nie są nazwą osoby (05.11.2026).

Reguła nagłówka (`cv_parser._split_name_from_header`) i nazwa pliku
(`cv_backfill.name_from_filename`) biorą pierwsze dwa słowa, które wyglądają jak
imię i nazwisko. Bywa, że to nagłówek sekcji, miasto, stanowisko albo technologia:
21 profili miało taką nazwę w kolumnach, a ich CV o nazwę nikt już nie pytał.

Lista to słowa z co najmniej 4,5% z 64 964 tekstów CV (kopia produkcji z 04.11.2026),
po zdjęciu ogonków. Na tej liście nazwa odpada tylko wtedy, gdy częste są WSZYSTKIE
jej słowa, bo pojedyncze słowo bywa prawdziwym nazwiskiem. Pomiar: 6394 odczyty
nagłówka i 2645 nazw z pliku inne niż dziś, 0 straconych nazw potwierdzonych mailem
albo LinkedInem. Przy progu 4% takich strat jest już 6.

Wyjęte, bo to głównie imiona: „jan” i „maja” (w CV to też styczeń i maj). Lista jest
migawką; nie dopisuj tu imion ani nazwisk, nawet częstych. Reguła:
`docs/claude/kandydaci-wyszukiwanie/nazwa-z-naglowka-i-pliku-a-czeste-slowa-cv.md`.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

COMMON_CV_WORDS = frozenset(
    """
ability about academy acceptance access accordance according account accounting
accounts accuracy achievements across act actions active actively activities ad
additional address administracja administracji administration administrator adobe
adres advanced after agent agile agree agreement ai akademia al alignment all also
am an analityczne analityk analiza analizy analysis analyst analysts analytical
analytics analyzed analyzing and android angielski angular any apache api apis
aplikacji app application applications applied applying approach apps apr april
architect architecture are area areas art as assessment assistant assisted associate
assurance at audit aug august authentication automate automated automation
automatyzacja automatyzacji availability aws azure bachelor back backend background
backlog bank banking based bash basic basics baz bazy be beda best between
bezpieczenstwa bi big bitbucket biznesowych bledow board boot bootstrap both bpmn
branzy budget budowanie bug bugs build building built business by byc can career
case cases cd celow celu center centrum certificate certificates certification
certifications certified certyfikat certyfikaty challenges change changes chwili ci
cisco claude clean clear client clients closely cloud cms co code collaborated
collaborating collaboration com commerce commercial communication companies company
complete completed complex compliance components comprehensive computer concepts
conducted conducting configuration confluence consent consistency consultant
consulting contact content continuous contract contracts contributed contributing
control cooperation coordinated coordinating coordination coordinator core corporate
cost council course courses coverage create created creating creation credit
critical crm cross css current currently curriculum custom customer customers cv
cybersecurity cycle czasie czasu daily dalej dalszego dane danych dashboards data
database databases date day db dbanie dec december decision decisions dedicated deep
defects degree deliver delivered delivering delivery department departments deployed
deployment deployments design designed designer designing desktop detail detailed
details detection dev develop developed developer developers developing development
devices devops different digital direct directive directly directory distributed dla
dlatego dnia do dobra docker document documentation documents dodatkowe dokumentach
dokumentacja dokumentacji dokumentow domain dostepu doswiadczenie doswiadczeniem
drive driven driving ds during dynamic dyrektywy dz dzialan dzialania ec economics
education edukacja effective effectively efficiency efficient electronics em email
employees enabling end engagement engine engineer engineering engineers english
enhance enhanced enhancing ensure ensured ensuring enterprise environment
environments erp etc etl eu europe european europejskiego event events excel
exchange executed execution existing experience experienced expert expertise express
external faculty fast feature features feb february feedback field figma finance
financial firmy first fizycznych flow flows fluent focus focused for foundation
framework frameworks free freelance from front frontend full functional
functionalities functionality functions fundamentals funkcjonalnosci future game
games gathering gcp gdansk gdpr general generation german git github gitlab give
global gmail go goals good google governance grafana group growth handling hands
hardware have health help hereby hibernate high highly history hobbies hobby hr html
https hybrid ibm ich identified identify identifying ii im impact implement
implementacja implementation implemented implementing improve improved improvement
improvements improving in incident incidents included including industry informacji
information informatyk informatyka informatyki infrastructure initiatives insights
institute insurance integracja integrated integrating integration integrations
intelligence interactive interests interface interfaces intermediate intern internal
international internetowych into introduction inzynier ios ip is issue issues istqb
it item itil its jak jako jakosci january java javascript jazdy jednoczesnie jenkins
jerozolimskie jest jestem jezyk jezyka jezyki jezykow jira job journal js json jul
july jun june junior junit kafka kanban kat kazdej kazdym key kierunek klienta
klientami klientem klientow knowledge kompetencje komunikacja komunikacji
komunikatywnosc konfiguracja kontakt kontrola koordynacja kpi krakow ktore
kubernetes kurs kursy kwietnia language languages large lat lata laws lead leader
leadership leading learn learning led legacy letnim level libraries library
licencjat liceum life lifecycle like line linkedin linux live llm load local lodz
logic logistics long machine magister mail main maintain maintained maintaining
maintenance major making manage managed management manager managers managing manual
mar march market marketing master material materialow materials maven may me media
meet meetings member members mentoring methodologies methodology methods metrics mi
microservices microsoft migration ml mnie mobile model modeling models modern
modules moga moich moim mongodb monitored monitoring monitorowanie months more
movement ms multi multiple my mysql na nad nadzor name narzedzi narzedzia national
native natural necessary needs net network networking networks new next niemiecki
niezbedne niezbednych no node non nov november now nowe nowych nr number numpy obce
obecnie obsluga obslugi obszarze ochronie ochrony oct october od odpowiedzialnosc of
office ojczysty on onboarding one ongoing online open operacyjnych operating
operational operations opportunities oprogramowania optimization optimize optimized
optimizing optymalizacja optymalizacji or oracle oraz order organizacja organizacji
organization organizational oriented os osob osobowych oswiadczam other out outlook
over overall own owner ownership page pandas parlamentu parliament part participated
participation partners party passionate patterns payment people performance
performed performing person personal persons phone photoshop php pipeline pipelines
pl plan planning planowanie plans platform platforms playwright po pod podczas
podstawie podstawowy podstawy podsumowanie point poland policies polish politechnika
polska polski ponad ponadto poprzez portfolio posiadam position post postgraduate
postgresql postman potential potrzeb potrzeby power powerpoint powershell poz poziom
poznan praca prace pracownikow practical practices pracy prawa prawo preparation
prepared preparing present principles problem problemow problems procedures procesie
procesow process processed processes processing procesu procesy product production
products produktow professional proficiency proficient profil profile program
programista programming programowania programowanie programs progress project
projects projekt projektach projektami projektow projektowanie projektu projekty
protection proven provide provided providing prowadzenia prowadzenie przepisow
przeplywu przeprowadzanie przetwarzanie przetwarzaniem przez przeze przy
przygotowanie przygotowywanie public purpose purposes pursuant python qa quality
queries query rabbitmq rady ramach raportow raportowanie react real realising
realizacja realizacji record recruitment redis reduced reducing redux regard
regression regular regulation regulatory rekrutacja rekrutacji rekrutacyjnym relacji
related relationships release releases reliability reliable remote repealing report
reporting reports request requests requirements research resolution resolve resolved
resolving resource resources response responsibilities responsible responsive rest
results review reviews risk risks robust rodo rok roku role roles rowniez roznych
rozporzadzenia rozporzadzeniem rozwiazan rozwiazania rozwiazywanie rozwoj rozwoju
running russian sa saas sales sap satisfaction scalability scalable scale scenarios
school science scope scratch scripting scripts scrum seamless search sector secure
security selenium self senior sep september server servers service servicenow
services sessions set sharepoint side sie sieci siedziba site skilled skills soap
social soft software solid solution solutions solving source sp specialist
specialization specific specifications specjalista specjalizacja sport sprawie
spring sprint sprzedaz sprzedazy sprzetu sql srednio srodowisku stability stack
stakeholder stakeholders standard standards stanowisko state status storage store
strategic strategies strategy strong structured student studia studies studio study
successful successfully such suite summary support supported supporting swagger
swobodnego system systemami systemow systems systemu systemy szczegolnosci szkol
szkola szkolen szkolenia szkolenie tailwind takich taking takze task tasks team
teams teamwork tech technical technician techniczna techniczne technicznej
technicznych technik techniques technologie technologies technologii technology
telefon term terraform test tester testing testow testowanie tests testy that the
their them thesis thinking third this through time timely to tool tools top track
tracking training trainings transformation tresci troubleshooting two tworzenie
tworzeniu tym typescript uat uchylenia udzial udzialem udzialu ue ui uk ukrainian ul
umiejetnosc umiejetnosci uml umow under understanding unit university uniwersytet up
updates urodzenia urzadzen use used user users using uslug ustaw ustawa utrzymanie
utrzymywanie ux uzytkownikow validation value various vba verification version via
video visual visualization warehouse warsaw warszawa warszawie was waterfall
wdrazanie wdrozenie we web website websites well weryfikacja where which while
wiadomosci windows with within word wordpress work worked workflow workflows working
workshops world writing wroclaw wsb wsparcia wsparcie wspolpraca wspolpracy ww www
wykorzystaniem wyksztalcenie wylacznie wymagan wynikow wyrazam wyzsza xml year years
za zaawansowany zadan zadanie zainteresowania zakresie zakresu zarzadzania
zarzadzanie zawartych zawodowe zawodowy ze zespol zespolami zespole zespolem zespolu
zgode zgodnie zgody znajomosc zostaly zwiazanych zwiazku
""".split()
)

_SPECIAL_TRANSLITERATION = str.maketrans({"ł": "l", "Ł": "l"})


def _fold(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word.translate(_SPECIAL_TRANSLITERATION))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def is_common_cv_word(word: str) -> bool:
    """Słowo jest na liście częstych słów CV, bez względu na wielkość liter i ogonki."""
    return _fold(word) in COMMON_CV_WORDS


def only_common_cv_words(words: Iterable[str]) -> bool:
    """Wszystkie słowa są częste, więc razem nie tworzą nazwy osoby."""
    return all(is_common_cv_word(word) for word in words)
