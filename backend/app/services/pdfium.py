"""Jedna blokada procesu na PDFium (pypdfium2), 25.11.2026.

PDFium nie jest bezpieczne wątkowo (dokumentacja pypdfium2, „Incompatibility
with Threading”): dwa wywołania naraz z `run_in_threadpool` mogą wywrócić cały
proces uvicorna, a nie dać 503. Render Worda „Nowego CV” (dwa naraz w slotach
`cv_new_pdf`) i strona panelu w PDF korzystają z PDFium w wątkach — każde
otwarcie, render i zapis dokumentu idzie pod tą blokadą. Wywołania trwają
dziesiątki milisekund, więc kolejka jest krótka.
"""

from __future__ import annotations

import threading

PDFIUM_LOCK = threading.Lock()
