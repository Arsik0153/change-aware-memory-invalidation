from __future__ import annotations

import io
import time
import tokenize
from pathlib import Path
from typing import Any, Literal

import numpy as np

from cami.artifacts import file_hash, reserve, write_bytes, write_json, write_jsonl
from cami.dataset_models import DatasetManifest, DatasetRepository, DatasetRun
from cami.demo import POLICIES
from cami.engine import run_experiment
from cami.errors import InputError
from cami.models import RepoLocation
from cami.repository import chain, git, read_snapshot, resolve


def parent_candidates(source: str) -> tuple[tuple[str, int], ...]:
    tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    indent = 0
    definitions: list[tuple[str, int]] = []
    bindings: dict[str, int] = {}
    for i, token in enumerate(tokens):
        if token.type == tokenize.INDENT:
            indent += 1
        elif token.type == tokenize.DEDENT:
            indent -= 1
        elif indent == 0 and token.type == tokenize.NAME:
            if token.string == "def" and i + 1 < len(tokens):
                name = tokens[i + 1].string
                definitions.append((name, token.start[0]))
                bindings[name] = bindings.get(name, 0) + 1
            elif token.start[1] == 0 and i + 1 < len(tokens) and tokens[i + 1].string in {"=", ":", "+=", "-="}:
                bindings[token.string] = bindings.get(token.string, 0) + 1
            elif token.string in {"class", "import", "from"}:
                # Imports and classes are conservatively excluded if they bind a candidate name.
                line_names = {t.string for t in tokens[i+1:] if t.start[0] == token.start[0] and t.type == tokenize.NAME}
                for name in line_names:
                    bindings[name] = bindings.get(name, 0) + 1
    return tuple((name, line) for name, line in definitions if bindings.get(name) == 1)


def prepare_pilot(repo_path: Path, output: Path, end_ref: str = "8.1.8", count: int = 12,
                  claims_per_pair: int = 10, dataset_kind: Literal["synthetic", "real"] = "real") -> Path:
    if count <= 0 or not 1 <= claims_per_pair <= 10:
        raise InputError("pilot requires positive transitions and 1..10 claims per pair")
    if dataset_kind == "real":
        remote = git(repo_path, "remote", "get-url", "origin").decode().strip()
        if remote not in {"https://github.com/pallets/click.git", "https://github.com/pallets/click"}:
            raise InputError("real pilot requires the declared pallets/click source repository")
    end = resolve(repo_path, end_ref)
    children = tuple(reversed(git(repo_path, "rev-list", "--first-parent", "--no-merges", f"--max-count={count}", end).decode().split()))
    if len(children) != count:
        raise InputError("not enough historical commits for pilot")
    pairs = []
    for child in children:
        parents = git(repo_path, "rev-list", "--parents", "-n", "1", child).decode().split()[1:]
        if len(parents) != 1:
            raise InputError("pilot transition requires one parent")
        chain(repo_path, parents[0], (child,))
        pairs.append((parents[0], child))
    reserve(output)
    repo = RepoLocation(repo_id="click", path=str(repo_path.resolve()), source_roots=("src",))
    rng = np.random.default_rng(42)
    runs = []
    preparation = []
    for pair_index, (parent, child) in enumerate(pairs):
        started = time.perf_counter()
        snapshot = read_snapshot(repo, parent)
        candidates = []
        for blob in snapshot.blobs:
            if not blob.path.startswith("src/click/") or not blob.path.endswith(".py") or blob.content is None:
                continue
            try:
                source = blob.content.decode("utf-8")
                for name, line in parent_candidates(source):
                    candidates.append((blob, name, line))
            except (UnicodeDecodeError, tokenize.TokenError, IndentationError):
                continue
        if not candidates:
            raise InputError(f"no eligible parent candidates at {parent}")
        selected = sorted(int(i) for i in rng.choice(len(candidates), min(claims_per_pair, len(candidates)), replace=False))
        pair_dir = output / "pairs" / f"{pair_index:02d}"
        pair_dir.mkdir(parents=True)
        claims: list[dict[str, Any]] = []
        provenance, receipts = [], []
        for index in selected:
            blob, name, line = candidates[index]
            claim_id = f"click-pilot-{pair_index:02d}-{len(claims):02d}"
            claims.append({"schema_version":1,"claim_id":claim_id,"repo_id":"click","origin_commit":parent,
                "kind":"symbol_exists","text":f"{blob.path} contains the exact top-level function definition {name}.",
                "subject":{"path":blob.path,"qualname":name,"node_kind":"function"},
                "predicate":{"type":"symbol_exists","expected":True},"scope":"Exact syntactic top-level definition only; no behavioral or runtime claim."})
            evidence = pair_dir / "parent_evidence" / f"{claim_id}.json"
            write_json(evidence, {"schema_version":1,"claim_id":claim_id,"commit":parent,"path":blob.path,
                "qualname":name,"line":line,"source":(blob.content or b"").decode(),
                "confirmation":"unique top-level definition observed by independent tokenize traversal",
                "oracle_sha256":file_hash(Path(__file__))})
            receipts.append({"schema_version":1,"claim_id":claim_id,"origin_commit":parent,"status":"supported",
                "confirmation_type":"independent_tokenizer_parent_oracle","evidence_path":str(evidence.relative_to(pair_dir)),
                "evidence_sha256":file_hash(evidence)})
            provenance.append({"schema_version":1,"claim_id":claim_id,"scenario_id":"intact","anchors":[{
                "path":blob.path,"qualname":name,"scope":"symbol","observed_commit":parent,"content_hash":blob.content_hash,
                "origin":"static","start_line":line}],"dependencies":[],"known_incomplete":False,"unresolved_reasons":[]})
        write_jsonl(pair_dir / "claims.jsonl", claims)
        write_jsonl(pair_dir / "provenance.jsonl", provenance)
        write_jsonl(pair_dir / "parent_receipts.jsonl", receipts)
        config = {"schema_version":1,"protocol_version":"1.0","repo":repo.model_dump(mode="json"),
            "parent_commit":parent,"child_commits":[child],"claims_path":"claims.jsonl","provenance_path":"provenance.jsonl",
            "parent_receipts_path":"parent_receipts.jsonl","scenario_id":"intact","dataset_kind":dataset_kind,"split":"development",
            "stratum":"chronological","policy":{"id":"symbol_validate","dependency_depth":1},
            "validation":{"execution":"disabled","llm":"disabled"},"allow_network":False,"max_calls":0,"seed":42}
        write_json(pair_dir / "run.json",config)
        runs.append(DatasetRun(run_id=f"click-pilot-{pair_index:02d}",config_path=str((pair_dir / "run.json").relative_to(output)),
                               split="development",cluster_id="click-8.1.8-pilot-episode"))
        preparation.append({"schema_version":1,"run_id":runs[-1].run_id,"parent_commit":parent,"child_commit":child,
                            "claims":len(claims),"provenance_seconds":time.perf_counter()-started})
    manifest = DatasetManifest(dataset_id="click-8.1.8-pilot",protocol_version="1.0",dataset_kind=dataset_kind,
        repositories=(DatasetRepository(repo_id="click",url="https://github.com/pallets/click.git" if dataset_kind == "real" else "synthetic://click-fixture",path=repo.path,
            source_roots=("src",),environment_restoration="Structural-only pilot uses host analyzer Python 3.12. Historical behavioral environments have not been evaluated."),),
        runs=tuple(runs),notes=("Parent-only tokenizer creates structural claims and parent receipts; AST validator does not create labels.",
        "Child annotation pending. No human authors, annotations, or child truth metrics are fabricated.",
        "All adjacent transitions are one episode cluster. No held-out data are included."))
    write_json(output / "dataset.json",manifest)
    write_jsonl(output / "preparation_costs.jsonl",preparation)
    license_blob = read_snapshot(repo,end).by_path().get("LICENSE.txt")
    if license_blob and license_blob.content:
        write_bytes(output / "CLICK_LICENSE.txt",license_blob.content)
    write_json(output / "sampling.json",{"schema_version":1,"end_ref":end_ref,"end_commit":end,
        "transitions":count,"claims_per_pair":claims_per_pair,"seed":42,"selection":"last non-merge first-parent transitions; parent-only function sample",
        "child_labels":"pending","timing_replicates":0})
    return output / "dataset.json"


def run_pilot(dataset_path: Path, output: Path) -> None:
    from cami.artifacts import load, read_json
    from cami.models import RunConfig
    dataset = load(dataset_path, DatasetManifest)
    reserve(output)
    summaries = []
    for entry in dataset.runs:
        original = (dataset_path.parent / entry.config_path).resolve()
        config = load(original, RunConfig)
        for policy in POLICIES:
            changed = config.model_copy(update={"policy":config.policy.model_copy(update={"id":policy}),
                "claims_path":str(original.parent / config.claims_path),
                "provenance_path":str(original.parent / config.provenance_path),
                "parent_receipts_path":str(original.parent / config.parent_receipts_path)})
            # Parent evidence paths are relative to the receipt's run directory.
            temporary_config = original.parent / f"pilot-{policy}.json"
            if temporary_config.exists():
                if load(temporary_config, RunConfig) != changed:
                    raise InputError(f"different pilot config already exists: {temporary_config}")
            else:
                write_json(temporary_config,changed)
            target = output / entry.run_id / policy
            manifest = run_experiment(temporary_config,target)
            costs = read_json(target / "manifest.json")
            summaries.append({"run_id":entry.run_id,"policy":policy,"status":manifest["status"],
                              "cohort_size":len(manifest["cohort"]),"run_path":str(target.resolve()),
                              "manifest_hash":file_hash(target / "manifest.json"),"started_at":costs["started_at"],
                              "finished_at":costs["finished_at"]})
        print(f"completed {entry.run_id}", flush=True)
    write_json(output / "pilot_report.json",{"schema_version":1,"dataset_kind":dataset.dataset_kind,"dataset_id":dataset.dataset_id,
        "runs":summaries,"quality_metrics":None,"quality_metrics_reason":"independent_child_labels_pending",
        "human_annotation_minutes":None,"environment_restoration":"not measured for behavioral environments",
        "timing_replicates":0,"limitation":"Operational structural pilot only; no scientific hypothesis conclusion."})
