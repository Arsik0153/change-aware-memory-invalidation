"""Synthetic development evaluation of the existing paired cluster bootstrap."""
from __future__ import annotations

import argparse
import math
import platform
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

import numpy as np
from pydantic import Field, model_validator

from cami.artifacts import canonical, file_hash, load, reserve, write_json
from cami.evaluation import BootstrapInterval, paired_cluster_bootstrap
from cami.models import Value

ROOT = Path(__file__).resolve().parents[1]
Probability = Annotated[float, Field(ge=0, le=1)]
PositiveInt = Annotated[int, Field(gt=0)]


class Scenario(Value):
    id: str
    clusters: Annotated[int, Field(ge=2)]
    active_probability: Annotated[float, Field(gt=0, le=1)]


class Protocol(Value):
    study_id: str
    generator: Literal['paired_nested_bernoulli_v1']
    seed: Annotated[int, Field(ge=0)]
    trials_per_scenario: PositiveInt
    bootstrap_repetitions: PositiveInt
    cluster_sizes: tuple[PositiveInt, ...] = Field(min_length=1)
    left_probabilities: tuple[Probability, ...] = Field(min_length=1)
    right_probability_multiplier: Probability
    scenarios: tuple[Scenario, ...] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_scenarios(self) -> Protocol:
        if len({s.id for s in self.scenarios}) != len(self.scenarios):
            raise ValueError('scenario IDs must be unique')
        return self

    @property
    def truth(self) -> float:
        return float(np.mean(self.left_probabilities)) * (1 - self.right_probability_multiplier)


class Trial(Value):
    scenario: str
    trial: int
    left: dict[str, tuple[int, int]]
    right: dict[str, tuple[int, int]]
    empty_clusters: int
    probability_undefined_resample: float
    interval: BootstrapInterval
    covered: bool | None


def undefined_probability(empty: int, clusters: int, repetitions: int) -> float:
    single = (empty / clusters) ** clusters
    if single == 1:
        return 1.0
    return -math.expm1(repetitions * math.log1p(-single))


def generate_trial(protocol: Protocol, scenario_index: int, trial: int) -> Trial:
    scenario = protocol.scenarios[scenario_index]
    rng = np.random.default_rng(np.random.SeedSequence([protocol.seed, scenario_index, trial, 0]))
    bootstrap_seed = int(np.random.SeedSequence(
        [protocol.seed, scenario_index, trial, 1]).generate_state(1)[0])
    left, right = {}, {}
    for cluster in range(scenario.clusters):
        active = rng.random() < scenario.active_probability
        size = int(rng.choice(protocol.cluster_sizes))
        probability = float(rng.choice(protocol.left_probabilities))
        values = rng.random(size)
        left[str(cluster)] = (int(np.sum(values < probability)), size) if active else (0, 0)
        right[str(cluster)] = (int(np.sum(values < probability *
                                         protocol.right_probability_multiplier)), size
                              ) if active else (0, 0)
    empty = sum(den == 0 for _, den in left.values())
    interval = paired_cluster_bootstrap(left, right,
        repetitions=protocol.bootstrap_repetitions, seed=bootstrap_seed)
    covered = (interval.lower <= protocol.truth <= interval.upper
               if interval.lower is not None and interval.upper is not None else None)
    return Trial(scenario=scenario.id, trial=trial, left=left, right=right,
                 empty_clusters=empty, probability_undefined_resample=undefined_probability(
                     empty, scenario.clusters, protocol.bootstrap_repetitions),
                 interval=interval, covered=covered)


def summarize(rows: list[Trial], truth: float) -> dict[str, object]:
    available = [row for row in rows if row.covered is not None]
    covered = sum(row.covered is True for row in rows)
    estimates = [row.interval.estimate for row in rows if row.interval.estimate is not None]
    return {
        'trials': len(rows), 'available': len(available), 'covered': covered,
        'availability': len(available) / len(rows),
        'conditional_coverage': covered / len(available) if available else None,
        'joint_available_and_covered': covered / len(rows),
        'unavailable_reasons': dict(Counter(row.interval.reason for row in rows
                                           if row.covered is None)),
        'mean_width_when_available': float(np.mean([
            row.interval.upper - row.interval.lower for row in available
            if row.interval.upper is not None and row.interval.lower is not None
        ])) if available else None,
        'defined_estimates': len(estimates),
        'bias_when_estimate_defined': float(np.mean(estimates)) - truth if estimates else None,
        'max_mcse_unconditional': 0.5 / math.sqrt(len(rows)),
        'max_mcse_conditional': 0.5 / math.sqrt(len(available)) if available else None,
        'expected_unavailable_count': sum(row.probability_undefined_resample for row in rows),
    }


def run(protocol_path: Path, output: Path) -> None:
    protocol = load(protocol_path, Protocol)
    source_paths = [Path(__file__).resolve(), ROOT / 'src/cami/evaluation.py', ROOT / 'uv.lock']
    hashes = {str(path.relative_to(ROOT)): file_hash(path) for path in source_paths}
    reserve(output)
    (output / 'protocol.json').write_bytes(protocol_path.read_bytes())
    manifest = {
        'status': 'running', 'study_id': protocol.study_id, 'truth': protocol.truth,
        'protocol_sha256': file_hash(output / 'protocol.json'), 'source_hashes': hashes,
        'git_head': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                                            text=True).strip(),
        'python': sys.version, 'numpy': np.__version__, 'platform': platform.platform(),
    }
    write_json(output / 'manifest.json', manifest)
    summaries = {}
    with (output / 'trials.jsonl').open('wb') as stream:
        for index, scenario in enumerate(protocol.scenarios):
            rows = []
            for trial in range(protocol.trials_per_scenario):
                row = generate_trial(protocol, index, trial)
                stream.write(canonical(row) + b'\n')
                rows.append(row)
            stream.flush()
            summaries[scenario.id] = summarize(rows, protocol.truth)
            print(f'{scenario.id}: {len(rows)} trials completed', flush=True)
    if hashes != {str(path.relative_to(ROOT)): file_hash(path) for path in source_paths}:
        raise RuntimeError('source snapshots differ; study remains incomplete')
    write_json(output / 'summary.json', {'truth': protocol.truth, 'scenarios': summaries})
    manifest.update({'status': 'complete', 'artifact_hashes': {
        name: file_hash(output / name) for name in ('protocol.json', 'trials.jsonl', 'summary.json')}})
    write_json(output / 'manifest.json', manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path, default=ROOT / 'examples/bootstrap_study/protocol.json')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    run(args.protocol, args.out)


if __name__ == '__main__':
    main()
