# Change-Aware Memory Invalidation for LLM Coding Agents

This repository contains the master's research proposal and the implemented CAMI
research engine and product memory CLI. The proposal was prepared for advisor
review on 1 October 2026. Submission and advisor approval are external steps;
the historical submission checks do not establish their current status.

## Implementation and research evidence, 29 October 2026

- [Project README](../README.md) documents installation and executable commands.
- [Research run record](research_run_2026-10-29.md) records tested changes, commits,
  outstanding work, and the continuing autonomous research session.
- [Bootstrap development study](bootstrap_study_2026-10-29.md) reports 600 synthetic
  datasets with analytically known truth, interval availability, and conditional
  coverage. These are estimator diagnostics, not real-policy effectiveness results.
- [Restored annotation material](annotation_restoration_2026-10-29.md) describes
  630 candidate claims in 63 groups. Independent answers and admission remain pending.
- [Restored provenance review package](provenance_audit_report_ru.md) provides parent-only
  support evidence and 630 blank review forms; all incompleteness flags remain set.
- [Parent review instructions](parent_review_instructions_ru.md) describe blank
  assignments, independent test authorship, double review, and adjudication import.
- [Product memory checks](product_memory_real_repositories_2026-10-29.md) record
  controlled source mutations in pinned local Click, Requests and TypeScript repositories.

The implemented system has been tested; the main empirical thesis hypothesis
still requires independent annotation, cohort admission, provenance review, and
protocol fixation before held-out policy execution. Automated parent environment
observations do not supply independent confirmation receipts.

## Proposal and submission documents

- [Research proposal](../research_proposal.md) is the authoritative content source
  for the submission document, not a current implementation status report.
- [Submission DOCX](../output/submission/thesis_research_plan.docx) is the completed form based on the official email attachment.
- [Print PDF](../output/submission/thesis_research_plan.pdf) is rendered from that DOCX.
- [Submission guide](../output/submission/SUBMISSION_GUIDE_RU.md) explains the advisor meeting, signatures, titles, and SUIS steps in Russian.
- [Verification record](submission_review.md) records evidence and remaining external steps.

The earlier workflow image and files under `tmp/pdfs/thesis_review` are historical design material. They are not the current submission package and may describe broader scope than the final proposal.

## Research scope

The proposed Python system stores claims with evidence and revision identifiers. Repository changes select claims for revalidation; a separate validator checks whether each selected claim remains supported. Uncertain claims are withheld from retrieval. The study will compare selective validation with the same validator applied to all claims, simple invalidation policies, and empty reset.

The planned evaluation includes approximately 600 claim-transition pairs, three sequential replays, provenance ablations, and an optional code-localization experiment. Actual sample sizes and resources will be fixed after a pilot. The contribution is framed as an extension of existing claim-relative invalidation research, with attention to sequential maintenance, provenance cost, and incomplete evidence links.

The repository now implements an indexer, research engine, dataset preparation,
annotation import, and persistent product memory. Synthetic demonstrations and
development checks are documented separately from the pending real experiment.
The earlier proposal describes planned research; its hypotheses are not treated
as established results.

## Rebuilding the document

`scripts/build_submission.py` reads `research_proposal.md` and fills the retained form in `templates/submission/official_notice_and_template.docx`. It preserves all template package parts except the main document and author metadata, and checks citations and required sections. Run `python3 scripts/build_submission.py` with Python and `lxml` installed, or use the bundled Python runtime resolved through Codex workspace dependencies.

The builder writes the DOCX to `output/submission/`, build checks to `docs/verification/submission/build_checks.json`, and temporary extracted text to `tmp/submission/`. The dated `final_checks.json` records the verified submission package; rebuilding the DOCX does not update that record or the PDF.

Render the resulting DOCX using the documents skill renderer, then inspect every page. The macOS bundled renderer needs the local Hangul font directory supplied through the task-local `FONTCONFIG_FILE`; the recorded verification explains the environment. PDF and Markdown content must be compared before replacing the final PDF. A rebuilt file does not automatically contain signatures or become submitted.
