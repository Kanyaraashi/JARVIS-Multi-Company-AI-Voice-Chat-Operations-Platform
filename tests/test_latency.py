"""Step 25: the latency maths."""
from app.latency import percentile, summarize, turn_latency


def test_percentile_uses_nearest_rank():
    values = list(range(1, 101))  # 1..100
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile(values, 100) == 100
    assert percentile([7], 95) == 7
    assert percentile([4, 1, 3, 2], 50) == 2
    assert percentile([], 50) is None


def test_measured_gap_is_preferred_over_the_parts():
    user = {"stopped_speaking_at": 100.0, "end_of_turn_delay": 0.3}
    assistant = {"started_speaking_at": 101.2, "llm_node_ttft": 0.5, "tts_node_ttfb": 0.2}
    result = turn_latency(user, assistant)
    assert result["total_ms"] == 1200 and result["source"] == "measured"
    assert (result["listen_ms"], result["think_ms"], result["speak_ms"]) == (300, 500, 200)


def test_parts_are_added_when_the_gap_is_unknown():
    result = turn_latency({"end_of_turn_delay": 0.4}, {"llm_node_ttft": 0.6, "tts_node_ttfb": 0.1})
    assert result["total_ms"] == 1100 and result["source"] == "estimated"


def test_an_impossible_gap_falls_back_to_the_parts():
    user = {"stopped_speaking_at": 100.0, "end_of_turn_delay": 0.2}
    for started in (99.0, 500.0):  # before the caller finished, or minutes later
        result = turn_latency(user, {"started_speaking_at": started, "llm_node_ttft": 0.3})
        assert result["total_ms"] == 500 and result["source"] == "estimated"


def test_nothing_measured_means_no_entry():
    assert turn_latency({}, {}) is None
    assert turn_latency({"end_of_turn_delay": -1}, {"llm_node_ttft": float("nan")}) is None


def test_transcription_delay_is_used_when_the_turn_delay_is_missing():
    assert turn_latency({"transcription_delay": 0.25}, {})["listen_ms"] == 250


def test_summary_numbers_and_target():
    turns = [{"total_ms": ms, "listen_ms": 100, "think_ms": ms - 150, "speak_ms": 50}
             for ms in (800, 900, 1000, 1400, 2600)]
    s = summarize(turns, target_ms=1500)
    assert s["turns"] == 5 and s["avg_ms"] == 1340
    assert s["p50_ms"] == 1000 and s["p95_ms"] == 2600 and s["max_ms"] == 2600
    assert s["within_target_pct"] == 80
    assert s["average_by_part"] == {"listen_ms": 100, "think_ms": 1190, "speak_ms": 50}


def test_summary_of_nothing_is_honest_about_it():
    s = summarize([])
    assert s["turns"] == 0 and s["p50_ms"] is None and s["within_target_pct"] is None
