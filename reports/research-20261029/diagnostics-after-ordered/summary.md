# Dataset analysis independent-synthetic-artifacts

Analyzed 4 policy runs. Labels SHA-256: 5e2112d8d5d4ab49b04fc2d91b2c1d363999ecade4adc865d4190a21d7ededf5.

All declared populations have complete matched policy sets. Missing labels and incompatible cohorts are rejected before report creation.

Excluded claims:

None.

Uncertainty and technical outcomes:

- population0/all_validate: uncertain labels 0, insufficient evidence 0, unchecked at current revision 0.
- population0/all_validate validator reason predicate_match: 1.
- population0/all_validate validator reason subject_absent: 1.
- population0/keep_all: uncertain labels 0, insufficient evidence 0, unchecked at current revision 2.
- population1/all_validate: uncertain labels 0, insufficient evidence 0, unchecked at current revision 0.
- population1/all_validate validator reason predicate_match: 1.
- population1/all_validate validator reason subject_absent: 1.
- population1/keep_all: uncertain labels 0, insufficient evidence 0, unchecked at current revision 2.

Bootstrap interval diagnostics:

See [intervals.csv](intervals.csv) for every metric/group comparison, interval bounds, unavailable reason, and numbers of clusters with positive denominators on the left, right, and both sides. Left-minus-right follows the comparison name.

Blank support counts mean diagnostics were not computed, not zero support. Replay and not-applicable metrics do not run bootstrap. Repetitions is the configured maximum, not a count of completed resamples. More clusters do not by themselves guarantee an available or calibrated interval.

Observed break-even against all_validate:

No selective validation policies supplied.

Limitations:

- Micro rates sum counters; macro rates average repositories with defined rates.
- Chronological, enriched, provenance scenarios, splits, and validator settings are separate.
- Replay sequences are separate descriptive results with no population confidence intervals.
- Reliability is exploratory below 50 contradicted claim/revision cases or 20 independent clusters containing contradictions.
- Cached validation durations reconstruct logical cost and are not measured end-to-end times.
- Three cold uncached replicates in seed-42 shuffled policy order were not supplied.
- Annotation histories are required to verify double-annotation coverage and Cohen's kappa.
- Cluster declarations are authoritative; independent history and episode membership must be fixed before outcomes are inspected.
- Single-annotator limitation; independent double annotation is unverified.
- This dataset is synthetic and does not support real-repository claims.
