# Change-Aware Memory Invalidation for LLM Coding Agents

This project contains the research plan for Sairanbekov Zhanarys, advised by 김진대 at SeoulTech. The current deliverable is a thesis research proposal prepared for advisor review on 1 October 2026 and the research-plan submission window ending 2 October 2026. Advisor approval and submission have not yet occurred.

## Current documents

- [Research proposal](../research_proposal.md) is the authoritative content source.
- [Submission DOCX](../output/submission/thesis_research_plan.docx) is the completed form based on the official email attachment.
- [Print PDF](../output/submission/thesis_research_plan.pdf) is rendered from that DOCX.
- [Submission guide](../output/submission/SUBMISSION_GUIDE_RU.md) explains the advisor meeting, signatures, titles, and SUIS steps in Russian.
- [Verification record](submission_review.md) records evidence and remaining external steps.

The earlier workflow image and files under `tmp/pdfs/thesis_review` are historical design material. They are not the current submission package and may describe broader scope than the final proposal.

## Research scope

The proposed Python system stores claims with evidence and revision identifiers. Repository changes select claims for revalidation; a separate validator checks whether each selected claim remains supported. Uncertain claims are withheld from retrieval. The study will compare selective validation with the same validator applied to all claims, simple invalidation policies, and empty reset.

The planned evaluation includes approximately 600 claim-transition pairs, three sequential replays, provenance ablations, and an optional code-localization experiment. Actual sample sizes and resources will be fixed after a pilot. The contribution is framed as an extension of existing claim-relative invalidation research, with attention to sequential maintenance, provenance cost, and incomplete evidence links.

No indexer, memory engine, dataset, benchmark results, or deployed service is implemented in this repository. The only executable tooling currently included builds and checks the submission document. Planned research is not reported as completed work.

## Rebuilding the document

`scripts/build_submission.py` reads `research_proposal.md` and fills the retained form in `templates/submission/official_notice_and_template.docx`. It preserves all template package parts except the main document and author metadata, and checks citations and required sections. Run `python3 scripts/build_submission.py` with Python and `lxml` installed, or use the bundled Python runtime resolved through Codex workspace dependencies.

The builder writes the DOCX to `output/submission/`, build checks to `docs/verification/submission/build_checks.json`, and temporary extracted text to `tmp/submission/`. The dated `final_checks.json` records the verified submission package; rebuilding the DOCX does not update that record or the PDF.

Render the resulting DOCX using the documents skill renderer, then inspect every page. The macOS bundled renderer needs the local Hangul font directory supplied through the task-local `FONTCONFIG_FILE`; the recorded verification explains the environment. PDF and Markdown content must be compared before replacing the final PDF. A rebuilt file does not automatically contain signatures or become submitted.
