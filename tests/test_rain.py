from backend import rain


def test_summarise_converts_units_and_flags_the_cap():
    # Four 15-minute steps at 0.02 m/h (20 mm/h) is 20 mm in an hour.
    s = rain.summarise([0.02, 0.02, 0.02, 0.02, float("nan"), -0.001], "a", "b", (29.8, -95.4))
    assert s["mm"] == 20.0 and s["inches"] == 0.8 and s["peak_mm_per_h"] == 20.0 and not s["capped"]
    assert rain.summarise([0.075, 0.01], "a", "b", (0, 0))["capped"]


def test_observed_caches_per_cell_and_fails_soft(tmp_path, monkeypatch):
    monkeypatch.setattr(rain, "CACHE", tmp_path)
    calls = []

    def read(lat, lon, start, end):
        calls.append((lat, lon))
        return [0.004] * 8, (29.8, -95.4)

    first = rain.observed(29.7604, -95.3698, "2024-07-07T12:00:00", "2024-07-09T00:00:00", read=read)
    again = rain.observed(29.7612, -95.3701, "2024-07-07T12:00:00", "2024-07-09T00:00:00", read=read)   # same 0.1 degree cell
    assert first == again and first["mm"] == 8.0 and len(calls) == 1

    def broken(*a):
        raise OSError("no network")

    assert rain.observed(30.5, -95.0, "2024-07-07T12:00:00", "2024-07-09T00:00:00", read=broken) is None
    assert rain.observed(31.5, -95.0, "2024-07-07T12:00:00", "2024-07-09T00:00:00", read=lambda *a: ([], (0, 0))) is None
