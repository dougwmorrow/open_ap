# Research: Round 8 Cycle 1 External Evidence — Sub-Agent Self-Improvement Discipline

**Date**: 2026-05-11
**Triggered by**: proactive — Pattern E 5th slot (advisory-research specialist) for Round 8 cycle 1
**Question**: Which claims in `phase1/08_sub_agent_self_improvement.md`, the 7 skill files, and `SELF_IMPROVEMENT_DISCIPLINE.md` are appropriately scoped vs overstate vs differ from external canonical patterns?
**Anchor**: D95-D99 (proposed); NORTH_STAR pillars: Audit-grade + Operationally stable + $120K ceiling

---

## Summary

The Round 8 artifact is internally well-structured and the core design choices (human-in-the-loop, bounded compute, semver prompts, conservative-bias specialties) are substantiated by external precedent. No architectural-class (🔴) concerns were found — consistent with the 5-prior-event 0% 🔴 track record for this specialty. Six 🟡 framing-grade concerns are surfaced: the "break-even round 8+" cost claim is speculative rather than empirical; the semver-for-prompts convention is emerging but not a recognized standard; the Tier α/β/γ/δ classification is invented (not canonical SE pattern, which is fine — but the doc should acknowledge it); the FREEZE semantics partially align with but are not formally grounded in Anthropic's Constitutional AI bounded-autonomy framework; the "auto-revert on regression" pattern differs from canonical CI/CD rollback semantics in one material way; and the reviewer-effectiveness measurement approach lacks citation to the empirical code-review literature that would strengthen its credibility. All 🟡 findings are advisory and non-blocking.

---

## Sources cited

| # | URL | Date accessed | Authority |
|---|---|---|---|
| 1 | https://arxiv.org/abs/2507.17131 | 2026-05-11 | Academic (ARIA framework; TikTok Pay deployment) |
| 2 | https://www.getmaxim.ai/articles/prompt-versioning-and-its-best-practices-2025/ | 2026-05-11 | Community/practitioner |
| 3 | https://agenta.ai/blog/prompt-versioning-guide | 2026-05-11 | Community/practitioner |
| 4 | https://nesbitt.io/2025/12/01/promptver.html | 2026-05-11 | Community/practitioner |
| 5 | https://dasroot.net/posts/2026/02/prompt-versioning-devops-ai-driven-operations/ | 2026-05-11 | Community/practitioner |
| 6 | https://www.anthropic.com/research/constitutional-ai-harmlessness-from-ai-feedback | 2026-05-11 | Anthropic (primary) |
| 7 | https://www.anthropic.com/constitution | 2026-05-11 | Anthropic (primary) |
| 8 | https://cookbook.openai.com/examples/partners/self_evolving_agents/autonomous_agent_retraining | 2026-05-11 | OpenAI (primary) |
| 9 | https://arxiv.org/abs/2303.17651 | 2026-05-11 | Academic (Self-Refine) |
| 10 | https://hokstadconsulting.com/blog/rollback-automation-best-practices-for-ci-cd | 2026-05-11 | Community/practitioner |
| 11 | https://docs.aws.amazon.com/wellarchitected/2025-02-25/framework/ops_mit_deploy_risks_auto_testing_and_rollback.html | 2026-05-11 | AWS (vendor primary) |
| 12 | https://ietresearch.onlinelibrary.wiley.com/doi/full/10.1049/iet-sen.2020.0134 | 2026-05-11 | Academic (code review effectiveness) |
| 13 | https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/bosu2015useful.pdf | 2026-05-11 | Academic/Microsoft Research |
| 14 | https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-2/ | 2026-05-11 | Kimball Group (primary) |

---

## Findings

### Finding 1: "Break-even round 8+" cost claim — speculative framing
- Source: [#1] (ARIA framework) + [#8] (OpenAI self-evolving agents cookbook)
- Quote / paraphrase: The ARIA paper and OpenAI cookbook both describe self-improvement loops, but neither provides a generic "N rounds to break-even" estimate. Break-even depends on artifact complexity, team composition, and prior discipline maturity — all project-specific.
- Quote from spec doc: "Break-even: round 8+ (Phase 2 first 3 rounds amortize the Round 8 investment)."
- Relevance: The $120K ceiling pillar (NORTH_STAR) grounds every compute-cost claim in evidence. This specific break-even claim is derived from the project's own retrospective estimate (7 hours over Phase 1 vs 30-40 min/round post-Round-8). That is a valid project-internal calculation, but it is presented as a certainty rather than a projection.
- Confidence: medium — the logic is sound but depends on the "60 min/round" pre-Round-8 baseline being accurate and the "30-40 min/round" post-Round-8 estimate materializing. Neither has been validated yet.

### Finding 2: Semver applied to system prompts — emerging convention, not established standard
- Source: [#2] [#3] [#4] [#5]
- Quote / paraphrase: Multiple 2025 practitioner sources recommend semver for prompt versioning. Source [2] explicitly maps MAJOR/MINOR/PATCH to structural/feature/fix changes. Source [4] (PromptVer, Dec 2025) formalizes a prompt-specific variant of semver. Source [5] (Feb 2026) describes PromptOps as "emerging."
- Relevance: D98 (agent prompt versioning convention) adopts semver MAJOR/MINOR/PATCH with MAJOR=structural, MINOR=directive addition, PATCH=wording polish — this maps closely to Source [2]'s mapping. The convention is grounded in emerging community practice, not a formal standard.
- The spec doc does not currently cite any external source for this convention. Adding a citation to [2] or [4] would strengthen D98's credibility at Gate 2.
- Confidence: high — semver for prompts is real and growing; the specific MAJOR/MINOR/PATCH mapping in D98 is consistent with Source [2]. The finding is that citing a source would improve rigor, not that the choice is wrong.

### Finding 3: Tier α/β/γ/δ complexity classification — project-invented, not canonical SE taxonomy
- Source: No external sources found matching this exact four-tier scheme.
- Paraphrase: The SE literature uses informal artifact-size categories (e.g., "small/medium/large") but no recognized taxonomy maps directly to KB-size thresholds with Greek-letter tier names and specific cadence prescriptions.
- Relevance: D97 locks this tier mapping. The spec doc presents it as an empirical finding from 7 rounds of internal data — which is appropriate and honest. The concern is that no "Tier α/β/γ/δ" framing is acknowledged as project-invented. Reviewers 1-4 who encounter this without that acknowledgment might incorrectly assume it derives from external SE practice.
- Confidence: high — confirmed via negative search: no matching external taxonomy found.

### Finding 4: "FREEZE the loop" semantics — partially aligned with, but not cited against, Anthropic's bounded-autonomy framework
- Source: [#6] [#7]
- Quote / paraphrase (Anthropic Constitutional AI): "Claude can help prevent harmful issues by valuing the ability of humans to understand and correct its dispositions and actions where necessary, and supporting human oversight means not acting to undermine appropriate oversight mechanisms of AI." The constitution establishes: (1) be safe and support human oversight, (2) behave ethically, (3) follow guidelines, (4) be helpful.
- The SELF_IMPROVEMENT_DISCIPLINE.md "FREEZE the loop" escape conditions include: specialty effectiveness declining, new bug class from applied delta, carryover rising, user declines 50%+, D-number contradiction. These align well with Anthropic's human-oversight-priority framing.
- Gap: The FREEZE semantics are grounded via internal project discipline (D95) but not anchored to the external framework that inspired them. A framing note acknowledging the Anthropic Constitutional AI parallel would be appropriate, especially given that Claude agents are executing this discipline.
- Confidence: medium — the alignment is real but the external grounding is implicit rather than cited.

### Finding 5: "Auto-revert on regression" — differs from canonical CI/CD rollback in one material way
- Source: [#10] [#11]
- Quote / paraphrase: AWS Well-Architected (Source [11]): "Automate testing and rollback... monitoring and observation used to detect failure criteria and automatically reverse changes when specific rollback criteria are met." Source [10]: "Automatic deployment failure detection can revert to a stable version without human intervention."
- The spec doc's auto-revert pattern (§ 7.6 / SELF_IMPROVEMENT_DISCIPLINE.md § Bounds) has a meaningful difference from canonical CI/CD rollback: canonical CI/CD reverts immediately on detected regression (same-deploy-window detection), while the spec doc auto-reverts at the NEXT round close-out after round N+1's FIRST cycle shows regression. This means a bad prompt delta stays live for at least one full validation cycle (one full round) before auto-revert executes.
- Relevance: For software deployment this delay would be a gap. For agent-prompt management at round cadence (not continuous deployment), it is likely acceptable — but the spec doc should acknowledge the deliberate choice to tolerate one-round lag rather than presenting it as equivalent to CI/CD auto-revert semantics.
- Confidence: medium — the one-round lag is probably intentional (bounded compute per constraint in § 0.3), but it is not surfaced as a deliberate tradeoff.

### Finding 6: Reviewer-effectiveness measurement — no citation to the empirical code-review literature
- Source: [#12] [#13]
- Quote / paraphrase: Source [12] (IET Software, 2020): "Code review effectiveness correlates with review speed; design and code reviews detect 55-60% of defects." Source [13] (Microsoft Research, Bosu 2015): "Useful code reviews correlate with reviewer expertise and familiarity; false-clean rates vary widely across reviewers."
- The spec's reviewer-effectiveness measurement approach (false-clean rate threshold > 25% → RETIRE-OR-PAIR; > 10% → REFINE) is grounded in 7 rounds of internal evidence. But the thresholds themselves (25%, 10%) are not anchored to external benchmarks. The code-review effectiveness literature shows that false-negative rates in software inspection range from 20% to 60% depending on artifact complexity — suggesting 25% as a RETIRE-OR-PAIR threshold may be conservative relative to human baseline.
- Relevance: Operationally stable pillar (NORTH_STAR): measurement thresholds that are too conservative will trigger unnecessary specialty rotation; thresholds too lenient will let underperforming specialties persist. Anchoring to external baselines would strengthen the threshold choices.
- Confidence: medium — the 25%/10% thresholds are defensible empirically from internal data; the concern is only that they are not compared against external benchmarks.

### Finding 7: Self-refine and ARIA framework alignment with the discipline loop — confirms design direction
- Source: [#1] [#8] [#9]
- Quote / paraphrase (OpenAI self-evolving agents cookbook): "A repeatable retraining loop that captures issues, learns from feedback, and promotes improvements back into production-like workflows, assembling a self-healing workflow that combines human review, LLM-as-judge evals, and iterative prompt refinement."
- Self-Refine [#9] describes iterative LLM self-improvement without requiring supervised training data; uses a single LLM as generator, refiner, and feedback provider.
- Relevance: The Round 8 discipline loop (8.A retrospective-collector → 8.B-8.G analysis → user review → 8.F apply) matches the OpenAI pattern's "capture issues → learn from feedback → promote improvements" structure. The human-in-the-loop at every batch-apply is more conservative than Self-Refine (which is LLM-only) and aligns with Anthropic's human-oversight priority.
- Confidence: high — the design is well-grounded in multiple external patterns.

---

## Recommendation

1. **D98 semver convention** (Finding 2): add a one-line citation to Source [2] (getmaxim.ai) or Source [4] (PromptVer) in D98's decision text. Low effort; strengthens the "industry-emerging" claim from unattributed to attributed.

2. **Tier α/β/γ/δ** (Finding 3): add one sentence acknowledging that the four-tier scheme is "a project-derived taxonomy based on N=7 rounds of empirical evidence, not an external SE standard." This prevents reviewer confusion without changing D97's content.

3. **Break-even cost claim** (Finding 1): rephrase "Break-even: round 8+" to "Projected break-even: round 8+ (based on Phase 1 retrospective estimate; to be confirmed after Phase 2 rounds 1-3 invocation)." One sentence change; preserves the analysis while flagging its projection-nature.

4. **FREEZE semantics** (Finding 4): in SELF_IMPROVEMENT_DISCIPLINE.md, add a parenthetical noting the FREEZE design is "consistent with Anthropic's human-oversight-priority framework (Constitutional AI, 2022)" with a link. Two-line addition.

5. **Auto-revert lag** (Finding 5): in § 7.6 / SELF_IMPROVEMENT_DISCIPLINE.md § Bounds auto-revert section, add one sentence: "Note: unlike same-deployment CI/CD auto-revert, the one-round lag is a deliberate bounded-compute tradeoff (per § 0.3 constraint)."

6. **Reviewer-effectiveness thresholds** (Finding 6): in the udm-specialty-tuner skill, add a note that the 25%/10% thresholds are calibrated from internal evidence and "may be revisited against external code-review defect-detection baselines (Jureczko 2020, Bosu 2015) after Phase 2 accumulates 15+ events."

All six are 🟡 framing-grade. None change the design. All are non-blocking for Round 8 validation cycle verdict.

---

## Counter-evidence

- Against Finding 2 (semver is established): Source [4] (PromptVer, Dec 2025) is recent enough that it represents emerging, not established, practice. No ISO, IEEE, or CNCF standard for prompt versioning was found — supporting the "emerging" characterization rather than "established standard."
- Against Finding 5 (auto-revert lag is a gap): The ARIA paper [#1] operates in a continuously-deployed production environment (TikTok Pay) where immediate revert is possible. The UDM validation system operates at round cadence — rounds are weeks-long. One-round lag = one validation cycle, which may be acceptable for prompt-level changes that are not safety-critical.
- Against Finding 6 (thresholds should be external-benchmarked): The external literature shows high variability (20-60% false-negative rates in human inspection). Applying generic defect-detection benchmarks to LLM-agent specialties is not a direct comparison. Internal calibration from project data may be more appropriate here than external baselines.

---

## What this research does NOT cover

- Whether the specific 7 skill implementations (Tier 0 stubs, Python dataclass contracts) are correctly specified — that is Reviewer R8C1-3 (column-walk) territory.
- Whether the B-item triage in § 11 is complete — that is Reviewer R8C1-2 (internal-consistency) territory.
- Whether Pattern F findings are correctly classified as evidence for 8.G — that is the cascade-audit specialty.
- Implementation feasibility of the skills as Python modules — Round 0.5 spike territory.

---

## Confidence assessment

Overall confidence in the recommendation:
🟢 High — multiple authoritative sources confirm the design direction (self-improvement loop, human-in-the-loop, semver). Framing concerns are well-grounded. No counter-evidence found that would reverse any recommendation.

---

## Suggested follow-up

- Producer may add D98 citation reference to [2] or [4] — trivial one-line change, no validation cycle needed.
- B-item: optionally add a new B-item for "anchor reviewer-effectiveness thresholds to external code-review defect-detection literature after Phase 2 accumulates 15+ events" — low priority, Phase 2 scope.
- Validation gate 2 can mark the six 🟡 framing concerns as acknowledged / non-blocking. No architecture changes required.
