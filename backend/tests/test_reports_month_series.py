"""Trend 12-miesięczny w raportach — seria musi mieć 12 RÓŻNYCH, kolejnych miesięcy.

Regresja jest cicha: arytmetyka `today - timedelta(days=i * 30)` produkowała
dwanaście kubełków opisanych jedenastoma etykietami — luty znikał, a sąsiedni
miesiąc dublował się. Liczby były poprawne, tylko opisywały nie ten miesiąc,
a wynik szedł do Rady Nadzorczej i do wykresu MRR sprzedaży.
"""

from datetime import date

from app.api.reports import _month_window_series


def _labels(anchor: date) -> list[str]:
    return [start.strftime("%Y-%m") for start, _end in _month_window_series(anchor)]


def test_series_ma_dwanascie_roznych_kolejnych_miesiecy():
    # Cztery lata × 12 miesięcy — stara arytmetyka pękała w marcu, kwietniu
    # i maju KAŻDEGO roku (10 z 48 początków miesiąca dawało 11 etykiet).
    for year in (2024, 2025, 2026, 2027):
        for month in range(1, 13):
            labels = _labels(date(year, month, 15))
            assert len(labels) == 12, (year, month, labels)
            assert len(set(labels)) == 12, (year, month, labels)
            assert labels == sorted(labels), (year, month, labels)
            assert labels[-1] == f"{year:04d}-{month:02d}", (year, month, labels)


def test_luty_nie_wypada_z_serii():
    # Dokładny przypadek z audytu: 2026-03-15 gubiło 2026-02 i dublowało 2025-12.
    labels = _labels(date(2026, 3, 15))
    assert "2026-02" in labels
    assert labels.count("2025-12") == 1
    assert labels == [
        "2025-04",
        "2025-05",
        "2025-06",
        "2025-07",
        "2025-08",
        "2025-09",
        "2025-10",
        "2025-11",
        "2025-12",
        "2026-01",
        "2026-02",
        "2026-03",
    ]


def test_okna_sa_polotwarte_i_stykaja_sie_bez_luk():
    series = _month_window_series(date(2026, 3, 31))
    for (start, end), (next_start, _next_end) in zip(series, series[1:]):
        assert start.day == 1
        assert end == next_start, (start, end, next_start)
    # Ostatnie okno domyka się na pierwszym dniu miesiąca następnego po kotwicy.
    assert series[-1][1] == date(2026, 4, 1)


def test_dzien_miesiaca_kotwicy_nie_zmienia_serii():
    assert _labels(date(2026, 3, 1)) == _labels(date(2026, 3, 31))


def test_przelom_roku_liczy_sie_przez_divmod():
    labels = _labels(date(2026, 1, 10))
    assert labels[0] == "2025-02"
    assert labels[-1] == "2026-01"
    assert "2025-12" in labels
