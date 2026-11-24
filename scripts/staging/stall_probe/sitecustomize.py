# Tylko test na stagingu (PYTHONPATH w kontenerze testowym): SIGUSR1 blokuje pętlę zdarzeń procesu
# czystym Pythonem na STALL_SECONDS, jak zastój z 24.11.2026 (CPU, GIL zwalniany).
import os
import signal
import time


def _stall(_signum, _frame):
    end = time.monotonic() + float(os.environ.get("STALL_SECONDS", "30"))
    while time.monotonic() < end:
        pass


signal.signal(signal.SIGUSR1, _stall)
