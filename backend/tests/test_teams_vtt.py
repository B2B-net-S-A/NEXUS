"""Parser transkryptu Teams (VTT) i rozpoznanie mówców prepu (0369)."""

from app.services.teams_vtt import (
    classify_speakers,
    normalize_person_name,
    parse_vtt,
    render_plain_text,
)

VTT = """WEBVTT

a1b2c3d4-1/12-0
00:00:03.120 --> 00:00:05.800
<v Anna Nowak>Dzień dobry, zaczynamy prep.</v>

a1b2c3d4-1/13-0
00:00:06.000 --> 00:00:16.000
<v Jan Kowalski (Gość)>Cześć. Ostatnio robiłem na Springu z Kafką.</v>

a1b2c3d4-1/14-0
00:00:16.500 --> 00:00:26.500
<v Jan Kowalski (Gość)>Przez dwa lata w banku.</v>

a1b2c3d4-1/15-0
00:00:27.000 --> 00:00:29.000
<v Anna Nowak>Super.</v>

01:02:03.000 --> 01:02:04.500
Bez podpisu mówcy.
"""


def test_parse_vtt_reads_cues_with_speakers_and_times() -> None:
    cues = parse_vtt(VTT)
    assert len(cues) == 5
    assert cues[0].speaker == "Anna Nowak"
    assert cues[0].text == "Dzień dobry, zaczynamy prep."
    assert cues[1].speaker == "Jan Kowalski (Gość)"
    assert abs(cues[1].seconds - 10.0) < 1e-6
    assert cues[4].speaker is None
    assert abs(cues[4].start - 3723.0) < 1e-6


def test_parse_vtt_tolerates_bom_crlf_and_mm_ss_timestamps() -> None:
    raw = "\ufeffWEBVTT\r\n\r\n00:01.000 --> 00:03.000\r\n<v Ola>Hej</v>\r\n"
    cues = parse_vtt(raw)
    assert [(c.speaker, c.text, c.seconds) for c in cues] == [("Ola", "Hej", 2.0)]


def test_parse_vtt_on_garbage_returns_no_cues() -> None:
    assert parse_vtt("") == []
    assert parse_vtt("to nie jest vtt") == []


def test_plain_text_merges_consecutive_turns_of_one_speaker() -> None:
    text = render_plain_text(parse_vtt(VTT))
    lines = text.splitlines()
    assert lines[0] == "Anna Nowak: Dzień dobry, zaczynamy prep."
    assert lines[1] == (
        "Jan Kowalski (Gość): Cześć. Ostatnio robiłem na Springu z Kafką. "
        "Przez dwa lata w banku."
    )
    assert lines[3] == "Bez podpisu mówcy."


def test_normalize_person_name_folds_polish_letters_and_guest_suffix() -> None:
    assert normalize_person_name("Łukasz Żółć (Gość)") == ("lukasz", "zolc")
    assert normalize_person_name("KOWALSKI, Jan") == ("jan", "kowalski")


def test_classify_marks_staff_candidate_and_talk_share() -> None:
    result = classify_speakers(
        parse_vtt(VTT),
        staff=[(7, "Anna Nowak")],
        candidate_name="Jan Kowalski",
    )
    roles = {s["name"]: s["role"] for s in result.speakers}
    assert roles["Anna Nowak"] == "staff"
    assert roles["Jan Kowalski (Gość)"] == "candidate"
    staff = next(s for s in result.speakers if s["role"] == "staff")
    assert staff["user_id"] == 7
    assert result.candidate_seconds == 20
    assert result.staff_seconds == 5  # 2.68 + 2.0 → zaokrąglone
    assert result.talk_share == 0.81  # 20 / (20 + 4,68)
    # Mowa bez podpisu nie wchodzi do udziału.
    assert result.unknown_seconds == 2


def test_single_non_staff_speaker_is_the_candidate_even_with_other_name() -> None:
    vtt = (
        "WEBVTT\n\n00:00:00.000 --> 00:00:10.000\n<v Anna Nowak>Pytanie</v>\n\n"
        "00:00:10.000 --> 00:00:40.000\n<v JK laptop>Odpowiedź</v>\n"
    )
    result = classify_speakers(
        parse_vtt(vtt), staff=[(7, "Anna Nowak")], candidate_name="Jan Kowalski"
    )
    roles = {s["name"]: s["role"] for s in result.speakers}
    assert roles["JK laptop"] == "candidate"
    assert result.talk_share == 0.75


def test_two_unmatched_guests_stay_unknown_and_share_is_not_computed() -> None:
    vtt = (
        "WEBVTT\n\n00:00:00.000 --> 00:00:10.000\n<v Anna Nowak>Pytanie</v>\n\n"
        "00:00:10.000 --> 00:00:20.000\n<v Gość 1>A</v>\n\n"
        "00:00:20.000 --> 00:00:30.000\n<v Gość 2>B</v>\n"
    )
    result = classify_speakers(
        parse_vtt(vtt), staff=[(7, "Anna Nowak")], candidate_name="Jan Kowalski"
    )
    assert {s["role"] for s in result.speakers} == {"staff", "unknown"}
    assert result.talk_share is None


def test_staff_matched_by_reversed_name_order() -> None:
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:10.000\n<v Nowak Anna>A</v>\n"
    result = classify_speakers(
        parse_vtt(vtt), staff=[(7, "Anna Nowak")], candidate_name="Jan Kowalski"
    )
    assert result.speakers[0]["role"] == "staff"
    # Bez kandydata w rozmowie udziału nie liczymy (nie „0%”).
    assert result.talk_share is None
