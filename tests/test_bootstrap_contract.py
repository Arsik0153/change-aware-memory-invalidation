from __future__ import annotations

import pytest

from cami.errors import InputError
from cami.evaluation import paired_cluster_bootstrap


def test_unequal_clusters_estimate_micro_difference() -> None:
    # Four equiprobable paired resamples have differences 1, -1/2, -1/2, -1.
    # The population micro difference is 1/4 - 3/4, not the macro difference 0.
    result = paired_cluster_bootstrap(
        {'small': (1, 1), 'large': (0, 3)},
        {'small': (0, 1), 'large': (3, 3)},
        repetitions=2000, seed=42,
    )
    assert result.estimate == -0.5
    assert result.lower == -1
    assert result.upper == 1
    assert result.reason is None
    assert result.clusters == 2


def test_identical_policies_have_zero_difference_under_paired_sampling() -> None:
    counts = {'rare': (1, 100), 'common': (90, 100), 'tiny': (1, 1)}
    result = paired_cluster_bootstrap(counts, counts)
    assert result.estimate == result.lower == result.upper == 0


def test_swapping_policies_reverses_interval() -> None:
    left = {'a': (1, 2), 'b': (2, 9), 'c': (7, 10)}
    right = {'a': (0, 3), 'b': (5, 7), 'c': (4, 11)}
    forward = paired_cluster_bootstrap(left, right, seed=123)
    reverse = paired_cluster_bootstrap(right, left, seed=123)
    assert forward.estimate is not None and reverse.estimate is not None
    assert forward.lower is not None and forward.upper is not None
    assert reverse.lower is not None and reverse.upper is not None
    assert forward.estimate == pytest.approx(-reverse.estimate)
    assert forward.lower == pytest.approx(-reverse.upper)
    assert forward.upper == pytest.approx(-reverse.lower)
    assert paired_cluster_bootstrap(dict(reversed(list(left.items()))), right,
                                    seed=123) == forward


def test_undefined_resample_does_not_silently_condition_interval() -> None:
    result = paired_cluster_bootstrap(
        {'empty': (0, 0), 'observed': (1, 2)},
        {'empty': (0, 1), 'observed': (0, 2)},
        seed=42,
    )
    assert result.estimate == 0.5
    assert result.lower is None and result.upper is None
    assert result.reason == 'zero_denominator_in_resample'


@pytest.mark.parametrize('counts', [(-1, 2), (3, 2), (0, -1)])
def test_invalid_counters_are_rejected(counts: tuple[int, int]) -> None:
    with pytest.raises(InputError, match='counters'):
        paired_cluster_bootstrap({'a': counts, 'b': (0, 1)}, {'a': (0, 1), 'b': (0, 1)})


def test_denominator_support_keeps_policy_sides_separate() -> None:
    result = paired_cluster_bootstrap(
        {'a': (1, 1), 'b': (0, 0), 'c': (1, 2)},
        {'a': (0, 0), 'b': (0, 3), 'c': (0, 0)},
    )
    support = result.denominator_support
    assert support is not None
    assert support.left_nonzero_clusters == 2
    assert support.right_nonzero_clusters == 1
    assert support.joint_nonzero_clusters == 0
    assert result.clusters == 3
    assert result.reason == 'zero_denominator_in_resample'


def test_support_remains_visible_when_estimate_undefined() -> None:
    result = paired_cluster_bootstrap({'a': (0, 0)}, {'a': (0, 2)})
    assert result.denominator_support is not None
    assert result.denominator_support.left_nonzero_clusters == 0
    assert result.denominator_support.right_nonzero_clusters == 1
    assert result.reason == 'zero_denominator'


def test_historical_interval_does_not_invent_support() -> None:
    from cami.evaluation import BootstrapInterval

    result = BootstrapInterval.model_validate_json(
        '{"estimate":0.1,"lower":0.0,"upper":0.2,"reason":null,"clusters":20}')
    assert result.denominator_support is None
