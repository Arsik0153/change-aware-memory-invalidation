# Full five-block CAMI result-memory development experiment

Frozen source 44ffa92, immutable Linux runtime-v8. Protocol SHA256:
`d6f08d244c430a3830c844454c364a91ae10c27fb8f7d18bfd0dec04126e5b49`.

80 scheduled attempts: plain/static/CAMI/CAMI+exact-result-replay, each following
A,A,B,B in five independent memory initializations. Canonical Click source reset
before every stage; model patches never carry into the next task input. Order
rotates by stage and block. Result memory learns only same-condition successful
source changes during this run; no historical solution import. 70 maximum model
sessions and 10 expected exact-repeat hits. Source-memory arms independently pay
construction and use the same readable display, lexical ranking and catalog.

Success requires all 80 operational and fixed-quality gates, complete telemetry,
uniform provider tier, and strictly lower four-stage token work AND pipeline wall
against EACH comparator in EACH block (15 comparisons per metric). All 10 separate
same-task changed-input rejection probes must pass with unchanged-input positive
controls. Failure or missing evidence prevents support. No retries/replacements/
extensions, pooling with prior runs, or tuning during execution.

Pipeline wall includes reset, guards, preparation, model/auth/cleanup, capture,
record/materialize, and fresh fixed grading. Shared baseline preflight is divided
equally across 20 sequences. This is deliberately more inclusive than the original
36-session protocol; old timings are not pooled. Lightweight host load/free-disk
observations every 10 seconds are recorded by launch.py. The desktop is not an
isolated host; observations and interleaving do not prove absence of host noise.

This is a full DEVELOPMENT replication, still only two historical task instances,
not 80 independent tasks or proof of arbitrary new-task benefit. Heldout remains
unopened. Changed-input probes establish conservative rejection, not successful
semantic adaptation to changed inputs. A positive repeat-cache result is not
misrepresented as a new efficiency result for source-prefix lookup alone.

Admission passed 998 existing/focused integration tests and an additional targeted
strict-criterion check, six real MCP stdio probes and three no-model OpenCode
sessions. Private state was removed; no model calls occurred during admission.
Host precheck: 8 logical CPUs, load averages 1.63/1.68/1.71, about 70GiB free.

Status at freeze: admitted, paid/model execution not yet started.

## Aborted execution (runtime-v8)

This version is invalid and cannot support an efficiency claim. The first real
model session finished, then the controller raised `KeyError: 'model'` while
checking effective configuration. A second static-arm model session started before
the controller was stopped; that worker was explicitly interrupted and removed.
Thus two model sessions were started, not zero; no quality/economy result is claimed.
The scrubbed artifacts are retained in `aborted-v8-evidence.tar.gz`. Private state
was removed. Neither attempt is pooled or reused as a solution in the replacement.
The no-model admission and mocked schedule test had missed the real controller
contract. The repair freezes the model, validates it before any paid subprocess,
and exercises the actual session postconditions for all three arms in tests.
A separate runtime-v9, protocol version2 and empty namespaces are required.
