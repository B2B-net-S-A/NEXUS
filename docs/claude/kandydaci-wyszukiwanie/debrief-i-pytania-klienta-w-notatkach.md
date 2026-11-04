# Debrief i pytania klienta w „Notatki → Rozmowy” (04.11.2026)
<!-- indeks: `ClientInterviewNotes`, wariant B, para zamknięta wypada z kalendarza, `aboveList` słucha filtra rekrutacji, panel kalendarza „Pokaż wszystkie z tej rekrutacji” -->

Zgłoszenie Delivery Leada 04.11.2026: kandydata odrzucono we wtorek, w czwartek
klient zaprasza następnego, a pytań z rozmowy nie ma gdzie znaleźć. Para zamknięta
wypada z tablicy kalendarza celowo (`_CLOSED_STAGES` w `services/interview_cycle.py`),
a debrief stał tylko w rozwiniętym wierszu „Rekrutacji”, pod kartą procesu: przy
1280 × 720 poza pierwszym ekranem. Artur wybrał z makiet wariant B (nad notatkami
z prepów). Osobna zakładka przy 1280 px chowała „CV” i „Dokumenty” za przewijaniem paska.

- **Karta `ClientInterviewNotes`** stoi nad listą filtra „Rozmowy”. Pokazuje wpis
  z debriefem albo z pytaniami klienta. Wpis strony klienta bez pytań (ocena, decyzja)
  zostaje w „Rekrutacjach”, bo to nie są notatki po telefonie do kandydata.
- **Sekcja „Feedback po rozmowach” w „Rekrutacjach” zostaje** (spis funkcji `r.feedback`).
  Obie czytają to samo zapytanie, więc to jedno pobranie.
- **Filtr rekrutacji obejmuje kartę** przez `aboveList` w `NotesList`. Nie dokładaj
  jej przed filtrem ani obok `NotesList`, bo wybór rekrutacji przestałby działać.
- **„Inne pytania z rozmów w tej rekrutacji”** czyta `client-questions?job_id=`
  (zadane w tej rekrutacji, `pytania-pod-rekrutacja-tylko-zadane-na-rozmowie.md`)
  bez pytań z tego debriefu. Awaria nie chowa debriefu i nie wygląda jak pusta lista.
- **Panel kalendarza** pokazuje 6 pytań z rekrutacji, a „Pokaż wszystkie z tej
  rekrutacji (N)” resztę. Limit pobrania to 200 (był 50), a „Wszystkie pytania klienta”
  to nadal cała lista klienta z innymi rolami.
- **Karta pokazuje tylko to, co zapisano.** Bez debriefu na profilu zostają prepy.
