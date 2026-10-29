from __future__ import annotations

from decimal import Decimal, localcontext
from fractions import Fraction
from itertools import product
import json
import math

import numpy as np
import pytest

from cami.evaluation import paired_cluster_bootstrap
from scripts.bootstrap_availability import conditional as shared_conditional
from scripts.paired_bootstrap_availability import bad_resample_probability, conditional, load_protocol


@pytest.mark.parametrize('clusters', [2, 3, 4])
def test_single_resample_probability_matches_exhaustive_support_and_draws(clusters):
    draws = list(product(range(clusters), repeat=clusters))
    for left_mask, right_mask in product(range(1 << clusters), repeat=2):
        bad = sum(not any(left_mask & (1 << i) for i in draw)
                  or not any(right_mask & (1 << i) for i in draw) for draw in draws)
        calculated = bad_resample_probability(clusters, left_mask.bit_count(), right_mask.bit_count(),
                                               (left_mask & right_mask).bit_count())
        assert calculated == Fraction(bad, len(draws))


def test_production_availability_matches_all_two_resample_sequences(monkeypatch):
    draws = list(product(range(2), repeat=2))

    class FixedDraws:
        def __init__(self, sequence):
            self.sequence = iter(sequence)

        def integers(self, low, high, size):
            assert (low, high, size) == (0, 2, 2)
            return np.array(next(self.sequence))

    for left_mask, right_mask in product(range(1, 4), repeat=2):
        left = {str(i): (0, int(bool(left_mask & (1 << i)))) for i in range(2)}
        right = {str(i): (0, int(bool(right_mask & (1 << i)))) for i in range(2)}
        available = 0
        for sequence in product(draws, repeat=2):
            monkeypatch.setattr(np.random, 'default_rng', lambda seed: FixedDraws(sequence))
            interval = paired_cluster_bootstrap(left, right, repetitions=2)
            available += interval.reason is None
            assert interval.reason in (None, 'zero_denominator_in_resample')
        result = conditional(2, left_mask.bit_count(), right_mask.bit_count(),
                             (left_mask & right_mask).bit_count(), 2)
        assert Decimal(result['available']) == Decimal(available) / 16


@pytest.mark.parametrize('clusters,active', [(2, 1), (5, 2), (20, 2), (20, 8), (50, 50)])
def test_shared_support_reduces_to_original_formula(clusters, active):
    for repetitions in (1, 10, 50, 2000):
        result = conditional(clusters, active, active, active, repetitions)
        original = shared_conditional(clusters, clusters - active, repetitions)
        assert math.isclose(float(result['available']), original['available'], rel_tol=2e-12, abs_tol=0)


def test_disjoint_support_can_produce_valid_interval_and_tiny_values_survive_serialization():
    assert conditional(2, 1, 1, 0, 2)['available'] == '0.25'
    row = json.loads(json.dumps(conditional(2, 1, 1, 0, 2000)))
    assert Decimal(row['available']) > 0
    assert float(row['available']) == 0  # The report must retain Decimal strings.
    with localcontext() as context:
        context.prec = 100
        assert Decimal(row['available']) == Decimal(2) ** -2000


def test_probability_boundaries_symmetry_and_monotonicity():
    for left, right in product(range(6), repeat=2):
        previous = Decimal(0)
        for joint in range(max(0, left + right - 5), min(left, right) + 1):
            row = conditional(5, left, right, joint, 50)
            assert row == conditional(5, right, left, joint, 50)
            available = Decimal(row['available'])
            assert previous <= available <= 1
            previous = available
            with localcontext() as context:
                context.prec = 100
                assert sum(Decimal(row[k]) for k in ('available','zero_sample','zero_resample')) == 1
            more = conditional(5, left, right, joint, 2000)
            assert Decimal(more['available']) <= available
            assert row['sample_estimate_defined'] is bool(left and right)
    assert conditional(20, 0, 2, 0, 50)['zero_sample'] == '1'
    assert conditional(20, 0, 2, 0, 50)['zero_resample'] == '0'
    assert conditional(20, 20, 20, 20, 2000)['available'] == '1'


@pytest.mark.parametrize('counts', [(1,1,1,1), (True,1,1,1), (5,-1,2,0), (5,2,6,0),
                                   (5,4,4,2), (5,1,2,2), (5,1.0,2,1)])
def test_impossible_support_counts_rejected(counts):
    with pytest.raises(ValueError):
        bad_resample_probability(*counts)


@pytest.mark.parametrize('repetitions', [0, -1, True, 2.0])
def test_invalid_repetition_count_rejected(repetitions):
    with pytest.raises(ValueError):
        conditional(2,1,1,0,repetitions)


def test_protocol_refuses_duplicate_scenarios_and_repetitions(tmp_path):
    path = tmp_path / 'protocol.json'
    scenario = {'id':'a', 'clusters':2, 'left_nonzero':1, 'right_nonzero':1, 'joint_nonzero':0}
    plan = {'analysis_kind':'post_pilot_conditional_paired_denominator_support',
            'scenarios':[scenario,scenario], 'bootstrap_repetitions':[1,2]}
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match='unique'):
        load_protocol(path)
    plan.update(scenarios=[scenario], bootstrap_repetitions=[1,1])
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match='unique'):
        load_protocol(path)
