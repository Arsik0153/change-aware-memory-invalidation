# Background refresh and agent use

`cami watch --repo PATH` runs in the foreground and refreshes the worktree index,
structural facts and manual-note review state through ProductMemory. It observes
uncommitted and untracked Python, JS, JSX, TS and TSX inputs. It does not execute
the project. The existing research `cami run` command keeps its meaning.

Install the trusted compiler once for JS/TS support:

```sh
cami setup-typescript
```

Use your shell to keep watch running. Put logs and context files outside the
repository, or in an explicitly excluded directory. `EVIDENCE` below must already
name an absolute directory outside the repository.

```sh
REPO=/absolute/path/to/project
EVIDENCE=/absolute/path/outside/project/cami-evidence
mkdir -p "$EVIDENCE"
cami watch --repo "$REPO" >"$EVIDENCE/watch.log" 2>"$EVIDENCE/watch.err" &
WATCH_PID=$!  # shell bookkeeping only; CAMI controls use the verified session
cami watch status --repo "$REPO" --format json
```

`--source-root REL` and `--exclude REL` are repeatable and have the same input
selection semantics as foreground memory. Effective TS configuration and its
relative inheritance can remain inputs under a source exclusion. Product state
is excluded by the shared capture policy. Watcher control files live in the Git
administrative directory and a private local socket directory.

```sh
cami watch stop --repo "$REPO"
wait "$WATCH_PID"
cami watch restart --repo "$REPO" --exclude generated
```

`restart` runs a foreground replacement with the supplied settings after the
matched previous session stops and releases its lease. It does not inherit old
scope options. Apply shell backgrounding again if needed. There is no daemon or
service installer. Ctrl-C and TERM request graceful cancellation and cleanup.

There is one watcher per canonical Git worktree, including across different
`XDG_STATE_HOME` values. A duplicate start with equal settings returns
`already_running` (exit 0); different settings return
`watch_configuration_conflict` (exit 2). Unverifiable ownership and timeouts return
exit 4. Status and stop accept the repository only, using the running session's
settings. Stop is idempotent after a verified release. Stop never signals a PID
from discovery metadata.

Polling defaults to 500 ms, debounce to 250 ms, and maximum debounce deferral to
two seconds. An immediate initial refresh runs on start. Failures retry with
0.5, 1, 2, 4, 8, then at most ten seconds between attempts. These are scheduling
defaults. They are not latency promises: continuous writes can make a capture
unstable and delay successful publication. Maximum deferral schedules an attempt;
it cannot make changing bytes coherent.

Status keeps ownership and data observations separate. `latest_successful` is
historical, including during errors or while inputs change. Only
`current_observation.relation` describes the verified capture interval, and
`data_freshness` becomes `unknown` during work or failure. A matching observation
does not promise that files cannot change immediately afterward. A completed
refresh can contain unavailable or uncertain evidence; inspect context coverage,
limitations and withheld reasons before relying on a fact.

The local control exchange has a one-second deadline and stop waits up to ten
seconds for release. Service operations have a 30-second cancellation budget in
an owned worker process. The controller stays responsive while the service writer
is busy. Cancellation unwinds existing transaction/subprocess cleanup. A stuck
kernel I/O operation may delay cleanup; CAMI retains its lease while owned work
is active and reports timeout rather than inventing a completed stop. The owned
operation worker shares the lifetime lease descriptor; Git and compiler children
do not inherit it. After parent process death, that lease remains occupied until
any in-flight worker ends. Recovery runs through ProductMemory on the next start.

If publishing a worker request fails, CAMI closes its request and result streams
and terminates and reaps that worker before propagating the original error.
Startup cleanup allows five seconds for cancellation, then kills the owned
worker and waits up to five more seconds. Cancellation of compiler analysis
kills and reaps its owned Node sidecar before the worker completes. Socket
cleanup, including failed watcher construction, removes only the captured bound
socket identity; a replacement endpoint is preserved.

The lifetime lease is permanent and distinct from disposable index cache. If its
file, inode identity, directory, discovery or endpoint is damaged while active,
CAMI fails closed and reports unknown ownership. It never unlinks, replaces or
quarantines an established lifetime lease. An interrupted first installation or
damaged permanent lease needs inspection while all involved processes are known
to have ended. Removing every Git-admin ownership proof is outside this contract.
This first version uses POSIX file locks, signals and Unix-domain sockets.

## Agent workflow

The watcher prepares background updates. Every `find` and `memory context` call
still validates its own inputs; a watcher status result cannot authorize reuse
of a stale answer during debounce.

```sh
cami find createUser --repo "$REPO" --format json
cami memory context src/lib/users.ts:createUser --repo "$REPO" --format json \
  >"$EVIDENCE/context.json"
cami memory remember symbol_exists src/lib/users.ts:createUser --repo "$REPO" \
  --from-context "$EVIDENCE/context.json" --request-id users-exists-1 --format json
cami memory remember signature_equals src/lib/users.ts:createUser --repo "$REPO" \
  --from-context "$EVIDENCE/context.json" --request-id users-signature-1 --format json
cami memory remember note src/lib/users.ts:createUser --repo "$REPO" \
  --from-context "$EVIDENCE/context.json" --note-key users-contract \
  --text 'Reviewed project contract.' --request-id users-note-1 --format json
```

After an edit, request a new context. Structural predicates can carry their
original check IDs across dependency-equivalent edits. Notes remain
`manual_assertion`; a changed source makes review sticky even after reversion.
Acknowledge a reviewed note with its current ID/revision, a new context, and a new
request ID:

```sh
cami memory context src/lib/users.ts:createUser --repo "$REPO" --format json \
  >"$EVIDENCE/review-context.json"
cami memory update "$NOTE_ID" --repo "$REPO" --if-revision "$NOTE_REV" \
  --from-context "$EVIDENCE/review-context.json" \
  --text 'Reviewed against current source.' --request-id users-note-review-2 --format json
```

Suggested project AGENTS.md text:

> Use `cami find SYMBOL --repo PATH --format json` for indexed definitions and
> relationships. Before relying on stored project knowledge, use
> `cami memory context PATH:SYMBOL --repo PATH --format json`. Inspect coverage,
> limitations and withheld reasons. Treat notes as manual assertions. After
> edits, request a new context. Watcher status describes background operation;
> context establishes the query's own verified readset. Pass the same explicit
> source roots/exclusions as the watcher when those settings are intentional.

Generation IDs can differ when probe sets differ. Registered subjects and note
sources join the background capture catalog. Exact-path queries can add a probe;
compare IDs only for the same canonical inputs and probes, and always compare
source hashes.

## JSON contracts and verification

Status, event, discovery, request, response and operation records have explicit
`schema_version: 1`. Status includes lifecycle, ownership, reason, session,
settings, phase, the current observation, historical latest success, pending time,
last error/retry time and poll/refresh counters. Events are JSON lines with event,
time, session and reason; refresh results and errors carry their typed details.
A slow or closed stdout consumer cannot block the controller; event lines can be
dropped when the output pipe has no capacity. Live status is the authoritative
process observation, not a log line.

Discovery reads are bounded regular-file reads with no-follow/nonblocking opens;
control requests are at most 4 KiB and responses at most 64 KiB. Requests and
responses match a session and fresh nonce, and requests require the private
capability. Endpoint inode identity is pinned before connecting. Discovery PIDs
are diagnostic only. The lock order is lifetime lease, service writer, SQLite;
status and control never take either service lock.

Run the process driver against an installed executable with a trusted compiler:

```sh
python tests/watch/cli_driver.py --cami /installed/bin/cami --out /tmp/new-watch-evidence
```

It starts a real long-lived watcher, edits passive Next-like TS/TSX and Python
fixtures, copies bounded persisted SQLite bytes into an independent in-memory
reader, and checks product head, source references, states and index checksums
before invoking any query that could refresh them. It also checks unchanged
polls, control responsiveness under a held writer lock, catalog changes,
compiler loss/recovery, scope uncertainty, corrupted/missing DB preservation,
restart and owned process cleanup. Separate lifecycle tests cover damaged leases,
special discovery files, unrelated endpoints and cancellation of owned children.
