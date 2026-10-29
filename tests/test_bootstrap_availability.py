from __future__ import annotations

import importlib.util
import itertools
import math
from fractions import Fraction
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('bootstrap_availability',
    Path(__file__).resolve().parents[1] / 'scripts/bootstrap_availability.py')
assert SPEC and SPEC.loader
availability = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(availability)


def enumerate_model(clusters, repetitions, q):
    result = {key: Fraction(0) for key in ('available', 'zero_sample', 'zero_resample', 'iterations')}
    sequences = list(itertools.product(range(clusters), repeat=clusters * repetitions))
    for active in itertools.product((False, True), repeat=clusters):
        mass = q ** sum(active) * (1 - q) ** (clusters - sum(active))
        if not any(active):
            result['zero_sample'] += mass
            continue
        for sequence in sequences:
            weight = mass / len(sequences)
            success = True
            for index in range(repetitions):
                result['iterations'] += weight
                draw = sequence[index * clusters:(index + 1) * clusters]
                if not any(active[j] for j in draw):
                    result['zero_resample'] += weight
                    success = False
                    break
            if success:
                result['available'] += weight
    return result


@pytest.mark.parametrize('clusters,repetitions,q', [(2, 1, Fraction(1, 2)), (2, 2, Fraction(1, 2)),
    (2, 3, Fraction(1, 3)), (3, 2, Fraction(1, 4))])
def test_exact_formula_matches_independent_exhaustive_enumeration(clusters, repetitions, q):
    expected = enumerate_model(clusters, repetitions, q)
    actual = availability.population(clusters, float(q), repetitions)
    for key in expected:
        assert actual[key] == pytest.approx(float(expected[key]), rel=1e-12, abs=1e-14)
    if clusters == repetitions == 2 and q == Fraction(1, 2):
        assert expected['available'] == Fraction(17, 32)


@pytest.mark.parametrize('q', [0.0, 1.0])
def test_all_empty_and_all_active_boundaries(q):
    values = availability.population(5, q, 2000)
    assert values == {'available': q, 'zero_sample': 1 - q, 'zero_resample': 0,
                      'iterations': 2000 * q}


def test_tiny_empty_probability_does_not_destroy_expected_iteration_count():
    result = availability.conditional(50, 1, 2000)
    assert result['zero_resample'] > 0
    assert result['iterations'] == pytest.approx(2000)


@pytest.mark.parametrize('clusters', [5, 20, 50])
def test_probability_partition_and_monotonicity(clusters):
    values = [availability.population(clusters, 0.1, n) for n in (50, 100, 500, 2000, 10000)]
    assert all(left['available'] > right['available'] for left, right in zip(values, values[1:]))
    for value in values:
        assert math.fsum(value[k] for k in ('available', 'zero_sample', 'zero_resample')) == pytest.approx(1)
    assert availability.population(2, 0.5, 100000)['available'] == pytest.approx(0.25)


@pytest.mark.parametrize('args', [(1, 0, 20), (2, -1, 20), (2, 3, 20), (2, 0, 0), (True, 0, 20)])
def test_invalid_conditional_arguments_rejected(args):
    with pytest.raises(ValueError):
        availability.conditional(*args)


@pytest.mark.parametrize('q', [-0.1, 1.1, float('nan'), True])
def test_invalid_activity_probability_rejected(q):
    with pytest.raises(ValueError):
        availability.population(2, q, 20)
