"""Tests for app.services.evaluation_scoring."""

import math

from app.services.evaluation_scoring import (
    ScoreSummary,
    compare_experiments,
    summarize_scores,
)


def test_empty_scores():
    result = summarize_scores([])
    assert result.count == 0
    assert result.mean is None
    assert result.median is None


def test_all_none_scores():
    result = summarize_scores([None, None, None])
    assert result.count == 0
    assert result.mean is None


def test_single_score():
    result = summarize_scores([0.85])
    assert result.count == 1
    assert result.mean == 0.85
    assert result.median == 0.85
    assert result.min_score == 0.85
    assert result.max_score == 0.85
    assert result.std_dev == 0.0


def test_multiple_scores():
    scores = [0.7, 0.8, 0.9, 1.0]
    result = summarize_scores(scores)
    assert result.count == 4
    assert result.mean == 0.85
    assert result.median == 0.85
    assert result.min_score == 0.7
    assert result.max_score == 1.0
    # Population std dev
    expected_std = round(math.sqrt(sum((s - 0.85) ** 2 for s in scores) / 4), 4)
    assert result.std_dev == expected_std


def test_odd_number_of_scores_median():
    scores = [0.5, 0.7, 0.9]
    result = summarize_scores(scores)
    assert result.median == 0.7


def test_scores_with_nones_excluded():
    scores = [None, 0.6, None, 0.8, 0.4]
    result = summarize_scores(scores)
    assert result.count == 3
    assert result.min_score == 0.4
    assert result.max_score == 0.8


def test_compare_experiments():
    data = {
        "baseline": [0.5, 0.6, 0.7],
        "improved": [0.8, 0.9, 0.95],
    }
    results = compare_experiments(data)
    assert set(results.keys()) == {"baseline", "improved"}
    assert results["baseline"].count == 3
    assert results["improved"].count == 3
    assert results["improved"].mean > results["baseline"].mean


def test_compare_experiments_empty():
    results = compare_experiments({})
    assert results == {}


def test_compare_experiments_one_empty():
    data = {"exp_a": [0.5], "exp_b": []}
    results = compare_experiments(data)
    assert results["exp_a"].count == 1
    assert results["exp_b"].count == 0
