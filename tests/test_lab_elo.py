from football_lab.models import Match
from football_lab.rankings.elo import EloEngine


def match(mid, home, away, hs, aas, rnd=1):
    return Match(mid, "T", "S", rnd, None, home, away, hs, aas, "finished")


def test_equal_teams_winner_goes_up_loser_down():
    snap = EloEngine(initial_rating=1500, k=20, home_advantage=0).calculate([match("m", "A", "B", 1, 0)], teams=["A", "B"])
    assert snap.ratings["A"] > 1500
    assert snap.ratings["B"] < 1500


def test_upset_change_is_larger_than_favorite_win():
    engine = EloEngine(k=20, home_advantage=0)
    expected_favorite = engine.expected(1700, 1300)
    favorite_change = 20 * (1 - expected_favorite)
    expected_weak = engine.expected(1300, 1700)
    upset_change = 20 * (1 - expected_weak)
    assert upset_change > favorite_change


def test_no_matches_starts_all_known_teams_at_initial_rating():
    snap = EloEngine(initial_rating=1500).calculate([], teams=["A", "B"])
    assert snap.ratings == {"A": 1500, "B": 1500}
