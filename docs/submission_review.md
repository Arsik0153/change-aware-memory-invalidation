# Submission verification — 30 September 2026

The research-plan package is prepared for advisor review on 1 October and the submission deadline of 2 October 2026. It is not approved, signed, or submitted. Sairanbekov Zhanarys confirmed his name and advisor 김진대; topic approval remains pending.

## Deliverables and checks

- The [DOCX](../output/submission/thesis_research_plan.docx) fills the official email attachment's form, retaining its A4 page setup, bordered form, and template package resources. Only `word/document.xml` and `docProps/core.xml` changed. The form is extended over seven continuation pages.
- The [PDF](../output/submission/thesis_research_plan.pdf) was rendered from that final DOCX. All seven pages were visually inspected. Korean names and title render correctly, paragraphs are complete, and no text is clipped.
- Automated extraction confirms the complete DOCX and PDF text matches the source-derived expected text after whitespace normalization. Every extracted PDF character lies within its page. There are seven nonempty A4 pages.
- Six numbered references and their in-text citations were checked during the build. Required form sections, researcher, advisor, and department-head names are present. Approval signatures and date remain blank.
- The [Russian guide](../output/submission/SUBMISSION_GUIDE_RU.md) includes the meeting pitch, titles to copy, approval steps, SUIS workflow, and final submission checklist.

Machine-readable checks and SHA-256 hashes are retained in [build_checks.json](verification/submission/build_checks.json) and [final_checks.json](verification/submission/final_checks.json). The unmodified official attachment is retained in [templates/submission](../templates/submission/official_notice_and_template.docx). Earlier source snapshots remain local under the ignored `tmp/submission/originals` directory.

The bundled document renderer needed a task-local fontconfig file to resolve the installed macOS Korean font. The local, ignored `tmp/submission/fonts/fonts.conf` records that environment. Font copies and caches are not committed; rendering on another machine requires a font that supports Hangul. Latin body text uses the renderer's compatible serif fallback; the editable DOCX retains the template's Times New Roman setting.

## Scientific review

The proposal distinguishes selecting potentially affected memories from proving a claim false. Its evaluation specifies the same validator for selective and exhaustive validation, clear metric denominators, parent-revision-only claim generation, held-out repositories, uncertainty handling, and a separate sequential replay. Planned experiments are consistently described as future work.

A closely related September 2026 preprint already discusses claim-relative invalidation. The proposal acknowledges this and frames its intended extension around sequential maintenance, provenance cost, and incomplete provenance. This is a proposed contribution for advisor discussion, not a verified novelty claim.

Primary literature checked:

1. [MemGPT](https://arxiv.org/abs/2310.08560).
2. [A-MEM](https://arxiv.org/abs/2502.12110).
3. [SWE-agent](https://arxiv.org/abs/2405.15793).
4. [SWE-bench](https://arxiv.org/abs/2310.06770).
5. [GumTree project and publication record](https://github.com/GumTreeDiff/gumtree).
6. [Impact Is Not Invalidation: Ask About the Claim, Not the Diff](https://arxiv.org/abs/2609.25130).

## Administrative evidence and remaining steps

The requirements come from the [department email dated 28 September 2026](https://mail.google.com/mail/u/?authuser=arsik0153%40gmail.com#all/1a0e5e59626372c6), including its Korean announcement and English DOCX attachment. The submission window is 28 September–2 October; no exact closing time is given. The department requests advisor confirmation and department-organized confirmation by 주임교수 강동완. The general notice's statement that no separate file submission to the department is needed does not remove those approval steps.

The [official IT service page](https://itc.seoultech.ac.kr/service/suis) confirms the SUIS service. The user's authenticated SUIS form, accepted upload formats, and file-size limit were not inspected. Before saving, compare the portal's current form and requirements, obtain genuine approvals, enter both agreed titles, and verify the saved attachment. The user intends to complete these steps himself after the advisor meeting.

The research system, dataset, and experimental results do not yet exist in this repository. The proposed sample sizes, second annotator, compute resources, and October–December research schedule require advisor discussion and pilot validation. December is a proposed research milestone, not a confirmed graduation deadline.
