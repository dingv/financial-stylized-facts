import numpy as np
import pytest

from financial_stylized_facts.tail_index import fit_side, sides


def test_selected_tail_matches_full_search_with_ties():
    x = np.array([0.5, 0.5, 1, 1.1, 1.2, 1.2, 1.8, 2.5, 4.0, 9.0])
    candidates = []
    for threshold in np.unique(x)[:-1]:
        tail = x[x >= threshold]
        k = 1 / np.mean(np.log(tail / threshold))
        ranks = [np.mean(tail >= t) for t in tail]
        distance = np.max(np.abs(ranks - (tail / threshold)**-k))
        candidates.append((distance, threshold, k, len(tail)))
    best = min(candidates)
    fitted = fit_side(x)
    assert (fitted["ks"], fitted["xmin"], fitted["k"], fitted["n"]) == pytest.approx(best)


def test_gain_loss_scale_and_missing_side():
    x = np.array([np.nan, 0, 1., 2., 4., 8., -1., -1.])
    fit = sides(x)
    assert fit["loss"]["k"] is None and fit["loss"]["reason"]
    assert fit["gain"]["k"] == pytest.approx(sides(x*10)["gain"]["k"])
    assert fit_side([1, 2])["k"] == pytest.approx(2 / np.log(2))
