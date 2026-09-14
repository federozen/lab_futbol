from football_lab.models import Match
from football_lab.rankings.colley import colley_ratings
from football_lab.rankings.pagerank import pagerank_ratings


def _m(mid, home, away, hs, aas):
    return Match(mid, "T", "S", 1, None, home, away, hs, aas, "finished")


def test_colley_rewards_winner():
    ratings = colley_ratings([_m("m", "A", "B", 1, 0)], teams=["A", "B"])
    assert ratings["A"] > ratings["B"]


def test_pagerank_points_from_loser_to_winner():
    ratings = pagerank_ratings([_m("m", "A", "B", 2, 0)], teams=["A", "B"])
    assert ratings["A"] > ratings["B"]
