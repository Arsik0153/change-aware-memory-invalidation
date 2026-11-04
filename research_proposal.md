# Thesis Proposal

Title: Change-Aware Memory Invalidation for LLM Coding Agents in Evolving Software Repositories

Korean title: 지속적으로 변화하는 소프트웨어 저장소에서 LLM 코딩 에이전트를 위한 변경 인지 기반 메모리 무효화

Researcher: Sairanbekov Zhanarys

Academic advisor: 김진대

## 1. Purpose and Motivation

This research will investigate how a coding agent can maintain useful repository memories while the code changes. A stored claim about a function, dependency, or module responsibility may become false after an update. Keeping every claim risks misleading the agent; discarding every claim loses reusable knowledge. The objective is to select claims for revalidation using their supporting evidence and repository changes, then invalidate claims only when current evidence contradicts them.

MemGPT studies management of external memory [1], and A-MEM studies linked, evolving agent memories [2]. SWE-agent demonstrates repository interaction by language-model agents [3], while SWE-bench provides an issue-resolution evaluation setting [4]. AST differencing, exemplified by GumTree, identifies structural code edits [5]. These are relevant foundations, but a changed source element does not by itself establish that a particular memory is false.

EA-Graph anchors verification claims to artifact content and separates evidence strength from freshness, including an unprovable state when changed support is unavailable [7]. These mechanisms are prior work, not a novelty claim of this proposal.

Anand's recent preprint distinguishes claim-relative invalidation from change impact [6]. This proposal will extend that work through sequential memory maintenance, measurement of provenance costs, and deliberately incomplete provenance. Selective checking will be compared with checking every claim using the same validator. Claim-relative invalidation itself is not claimed as new.

The main question is whether provenance and symbol-level changes can reduce revalidation cost while retaining useful memory and limiting stale exposure. Supporting questions concern dependency propagation, incomplete provenance, and code localization. Both improvements and negative results will inform the measured cost and reliability trade-off.

## 2. Content and Methods

### 2-1. Scope and memory representation

The implementation will target Python, with Click, Requests, and pytest as candidate repositories. A pilot will verify reproducible historical environments before selections are frozen. The core excludes automatic rewriting and multi-language or full issue-resolution evaluation.

Each memory will contain one claim, its type, creation and validation commits, evidence paths and ranges, qualified symbols, dependencies, and a state explanation. Structural claims cover symbol properties and dependencies. Behavioral claims will have explicit scope and evidence. Symbol identifiers will include module and enclosing scopes; ambiguous moves or renames will require revalidation.

The states will be valid, needs-validation, stale, and retired. Valid means supported at the recorded revision and scope; stale means contradicted. Missing or ambiguous evidence will require validation. Retirement requires confirmation that the subject disappeared without a supported successor. Retrieval will withhold non-valid claims. Carried-forward and newly verified claims will be recorded separately.

### 2-2. Change analysis and claim revalidation

For each revision transition, an indexer will compare Python ASTs, Git diffs, file hashes, signatures, imports, and resolvable call relationships. Changes will be mapped to claim evidence, with bounded propagation through dependencies. The policy will select directly affected claims and those reached by the chosen propagation depth. Unresolved dependencies, missing provenance, parser failures, and relevant configuration or environment changes will trigger conservative revalidation rather than an assumption that the claim remains valid.

Selection and truth assessment will be separate. Exact structural claims will use deterministic checks against the new revision. Behavioral claims will use an existing or isolated executable check when feasible. Other claims will use a fixed claim-specific LLM prompt with current evidence and three outputs: supported, contradicted, or insufficient evidence. Evidence truncation or unresolved context will produce insufficient evidence. The model, prompt, evidence budget, and sampling settings will be fixed after the pilot. Model judgments will not be used as ground-truth labels.

The full method will be compared with retaining all memory, invalidating claims whose evidence file changed, invalidating claims whose referenced symbol changed, clearing all memory without rebuilding it, and revalidating every claim. The last method will use the same checks and evidence construction as the selective method. An additional file-based selection followed by the same validator will separate the benefit of finer selection from the benefit of validation. All methods will receive the same initial claims and revision transitions. The empty-reset baseline will have zero valid-memory retention. In the localization experiment it will use fresh repository exploration, whose cost will be counted; it will not receive an unmeasured replacement memory.

### 2-3. Dataset and evaluation

The planned initial dataset is approximately 600 claim-transition pairs from 60 parent-child commit pairs, with about ten initially valid claims per pair. The target is 20 commit pairs per repository: ten from a chronological sample and ten enriched for refactoring, API changes, and fixes. The two strata will be reported separately. Claims will be written or generated using only the parent revision, before annotators inspect the child revision. They will include unchanged controls. Change type will be a sampling attribute, not a truth label.

Independent annotation will determine whether each claim is supported, contradicted, or uncertain at the child revision. Code evidence and reproducible tests will be recorded where available. If an old behavioral assertion is executed against new code, the assertion will remain unchanged and environment failures will be separated from semantic failures. A second annotator, to be arranged with the advisor, will independently label at least 20 percent before discussion. Agreement and Cohen's kappa will be reported before adjudication. Without a second annotator, the single-annotator limitation will be disclosed.

Click will provisionally provide development data; Requests and pytest will provide held-out evaluation data. Final choices will be frozen after the environment pilot and before inspecting held-out labels. Related claims and duplicate histories will stay in the same split. Three held-out sequences of ten consecutive transitions will test accumulated staleness. Each sequence will begin with the same ten valid claims for every policy. No claims will be added or rewritten during replay. All initial claims, including withheld ones, will be independently labeled at every revision, giving approximately 300 additional claim-revision labels. Replay will be reported separately and will not overlap development data.

Primary measures will be revalidation calls, total token use, elapsed time, stale exposure, and valid retention. Stale exposure will be the number of contradicted claims still retrievable divided by all contradicted claims. Valid retention will be retrievable supported claims divided by all supported claims. A zero denominator will be reported as not applicable. All methods will be assessed against the same original memory population so that clearing memory cannot appear cost-free or perfectly accurate. Selection recall will measure how many contradicted claims reach the validator. Confirmed-stale precision, recall, and F1 will be reported separately from retrieval withholding. False invalidation will mean the fraction of ground-truth-valid claims incorrectly marked stale or retired. Valid claims temporarily withheld as uncertain will be counted separately. Uncertain ground truth will be excluded from binary scores, with its frequency and coverage reported.

Costs will include initial indexing, incremental indexing, validation, and any reanalysis. Results will show cost versus stale exposure without assuming superiority. Paired differences for independent pairs will use bootstrap intervals clustered by commit, with repository-specific results alongside aggregates. Each replay sequence will be shown separately; three sequences will support exploratory conclusions rather than a precise population estimate. Enriched and chronological samples will remain separate because their stale-claim prevalence may differ. Pilot findings will fix sample sizes and any additional sampling rule before held-out evaluation. Any later extension will be labeled a separate exploratory dataset.

A secondary experiment will use about 30 held-out code-localization tasks with independently checked target files or symbols. Model settings, retrieval budgets, prompts, and task inputs will remain fixed across policies. Ablations will remove dependency propagation and vary provenance completeness. Deliverables will include the prototype, annotated claims, evaluation scripts, and thesis. Dynamic Python behavior, annotation uncertainty, limited repository coverage, and model dependence will constrain generalization.

## 3. Research Schedule

The following dates are proposed research milestones for 2026, not confirmed university thesis-defense or graduation deadlines. Writing and literature review will continue throughout the study.

1-2 October: Discuss the research question, closest related work, scope, and resources with the advisor; complete approval and submit the research plan.

3-16 October: Finalize the literature review, claim schema, annotation guide, and historical-environment pilot; confirm annotation time and API resources, then freeze the evaluation protocol, feasible sample sizes, and data split.

17-30 October: Implement AST indexing, provenance storage, change mapping, and the baseline policies; prepare development annotations.

31 October-13 November: Implement claim revalidation, retrieval filtering, and dependency ablations; freeze model settings and selection policy after pilot analysis.

14-27 November: Complete held-out annotations and sequential replay data; run primary comparisons and record all analysis costs.

28 November-11 December: Run code-localization tasks, estimate uncertainty, and analyze errors and limitations.

12-31 December: Complete the thesis draft, reproducibility package, and advisor revisions. If resources are limited, prioritize claim-level and replay evaluation over the secondary localization experiment.

## References

[1] C. Packer, S. Wooders, K. Lin, V. Fang, S. G. Patil, I. Stoica, and J. E. Gonzalez. MemGPT: Towards LLMs as Operating Systems. arXiv:2310.08560, 2023. https://arxiv.org/abs/2310.08560

[2] W. Xu, Z. Liang, K. Mei, H. Gao, J. Tan, and Y. Zhang. A-MEM: Agentic Memory for LLM Agents. NeurIPS, 2025. arXiv:2502.12110. https://arxiv.org/abs/2502.12110

[3] J. Yang, C. E. Jimenez, A. Wettig, K. Lieret, S. Yao, K. Narasimhan, and O. Press. SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering. arXiv:2405.15793, 2024. https://arxiv.org/abs/2405.15793

[4] C. E. Jimenez, J. Yang, A. Wettig, S. Yao, K. Pei, O. Press, and K. Narasimhan. SWE-bench: Can Language Models Resolve Real-World GitHub Issues? arXiv:2310.06770, 2023. https://arxiv.org/abs/2310.06770

[5] J.-R. Falleri, F. Morandat, X. Blanc, M. Martinez, and M. Monperrus. Fine-grained and accurate source code differencing. ASE, pp. 313-324, 2014. https://doi.org/10.1145/2642937.2642982

[6] A. Anand. Impact Is Not Invalidation: Ask About the Claim, Not the Diff. arXiv:2609.25130, preprint, 20 September 2026. https://arxiv.org/abs/2609.25130

[7] H.-J. Hsu, C.-J. Chi, and H. Everett. EA-Graph: Artifact-Anchored Verification Memory for Coding Agents under Upstream Drift. arXiv:2608.04278v1, preprint, 4 August 2026. https://arxiv.org/abs/2608.04278v1
