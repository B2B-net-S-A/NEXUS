"""„Popraw dokument”: DOCX ze śledzeniem zmian Worda i komentarzami.

Część D asystenta prawnego (``docs/asystent-prawny-plan.md``), reguła:
``docs/claude/asystent-prawny/popraw-dokument-docx-ze-sledzeniem-zmian.md``.

* ``model`` — akapit, zmiana, źródło (dane bez logiki),
* ``docx_io`` — odczyt pakietu DOCX i tekstu akapitów (z tabelami),
* ``tracked`` — zmiany jako ``w:ins``/``w:del`` i komentarze ``comments.xml``,
* ``diff`` — dwie wersje tekstu → lista zmian,
* ``proposals`` — propozycje modelu (funkcja AI ``legal_redline``),
* ``foundation`` — cienka warstwa do fundamentu (część A).

Silnik nie zna bazy: dostaje bajty DOCX i listę zmian, oddaje bajty DOCX.
"""
