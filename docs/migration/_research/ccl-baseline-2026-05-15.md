# CCL token-overhead baseline

- Token method: **heuristic** (approx ~4 chars/token)
- Context window assumed: 200,000 tokens
- Files measured: 61

## Per-stage roll-up

| Stage | Files | Tokens | % of context |
|---|---:|---:|---:|
| Stage 1 | 4 | 69,572 | 34.79% |
| Stage 2 | 3 | 292,582 | 146.29% |
| Stage 3 | 54 | 559,615 | 279.81% |
| **Total** | **61** | **921,769** | **460.88%** |

**CCL Stage 1+2 cost**: 362,154 tokens (181.08% of context window). Plan §9 target: <2,000 lines per invocation.

## Top-5 contributors per stage

### Stage 1

| File | Lines | Chars | Tokens | % of context |
|---|---:|---:|---:|---:|
| `docs/migration/HANDOFF.md` | 428 | 134,251 | 33,563 | 16.78% |
| `docs/migration/CURRENT_STATE.md` | 205 | 110,753 | 27,688 | 13.84% |
| `docs/migration/CHECKS_AND_BALANCES.md` | 346 | 20,704 | 5,176 | 2.59% |
| `docs/migration/NORTH_STAR.md` | 114 | 12,580 | 3,145 | 1.57% |

### Stage 2

| File | Lines | Chars | Tokens | % of context |
|---|---:|---:|---:|---:|
| `docs/migration/_validation_log.md` | 7,519 | 924,155 | 231,039 | 115.52% |
| `docs/migration/BACKLOG.md` | 549 | 221,730 | 55,432 | 27.72% |
| `docs/migration/RISKS.md` | 101 | 24,444 | 6,111 | 3.06% |

### Stage 3

| File | Lines | Chars | Tokens | % of context |
|---|---:|---:|---:|---:|
| `docs/migration/03_DECISIONS.md` | 3,220 | 266,230 | 66,558 | 33.28% |
| `docs/migration/phase1/04_tools.md` | 1,629 | 136,245 | 34,061 | 17.03% |
| `docs/migration/phase1/06_deployment.md` | 1,847 | 135,309 | 33,827 | 16.91% |
| `docs/migration/CODE_BUILD_STATUS.md` | 384 | 128,180 | 32,045 | 16.02% |
| `docs/migration/phase1/03_core_modules.md` | 1,725 | 114,441 | 28,610 | 14.31% |

## Trim recommendations (plan §9 metric: <2,000 lines per CCL invocation)

- Trim `docs/migration/_validation_log.md` by 73% (7519 -> 2000 lines) to hit plan §9 CCL budget

## Full per-file table

| File | Stage | Lines | Chars | Tokens | % of context |
|---|:-:|---:|---:|---:|---:|
| `docs/migration/_validation_log.md` | 2 | 7,519 | 924,155 | 231,039 | 115.52% |
| `docs/migration/03_DECISIONS.md` | 3 | 3,220 | 266,230 | 66,558 | 33.28% |
| `docs/migration/BACKLOG.md` | 2 | 549 | 221,730 | 55,432 | 27.72% |
| `docs/migration/phase1/04_tools.md` | 3 | 1,629 | 136,245 | 34,061 | 17.03% |
| `docs/migration/phase1/06_deployment.md` | 3 | 1,847 | 135,309 | 33,827 | 16.91% |
| `docs/migration/HANDOFF.md` | 1 | 428 | 134,251 | 33,563 | 16.78% |
| `docs/migration/CODE_BUILD_STATUS.md` | 3 | 384 | 128,180 | 32,045 | 16.02% |
| `docs/migration/phase1/03_core_modules.md` | 3 | 1,725 | 114,441 | 28,610 | 14.31% |
| `docs/migration/CURRENT_STATE.md` | 1 | 205 | 110,753 | 27,688 | 13.84% |
| `docs/migration/phase1/02_configuration.md` | 3 | 1,405 | 96,610 | 24,152 | 12.08% |
| `docs/migration/phase1/01_database_schema.md` | 3 | 2,168 | 90,506 | 22,626 | 11.31% |
| `docs/migration/phase1/05_tests.md` | 3 | 827 | 86,954 | 21,738 | 10.87% |
| `docs/migration/GLOSSARY.md` | 3 | 800 | 86,379 | 21,595 | 10.80% |
| `docs/migration/_reviewer_effectiveness.md` | 3 | 519 | 80,750 | 20,188 | 10.09% |
| `docs/migration/MARKDOWN_REFACTOR_PLAN.md` | 3 | 792 | 76,635 | 19,159 | 9.58% |
| `docs/migration/phase1/08_sub_agent_self_improvement.md` | 3 | 1,130 | 68,188 | 17,047 | 8.52% |
| `docs/migration/05_RUNBOOKS.md` | 3 | 1,546 | 64,499 | 16,125 | 8.06% |
| `docs/migration/phase1/07_schema_evolution_governance.md` | 3 | 807 | 64,372 | 16,093 | 8.05% |
| `docs/migration/phase2/01_pilot_prerequisites.md` | 3 | 518 | 56,835 | 14,209 | 7.10% |
| `docs/migration/phase1/01c_data_flow_walkthrough.md` | 3 | 1,147 | 51,393 | 12,848 | 6.42% |
| `docs/migration/phase1/01a_control_tables.md` | 3 | 779 | 44,205 | 11,051 | 5.53% |
| `docs/migration/phase1/04a_phase_0_prep_tools.md` | 3 | 365 | 40,905 | 10,226 | 5.11% |
| `docs/migration/04_EDGE_CASES.md` | 3 | 297 | 36,006 | 9,002 | 4.50% |
| `docs/migration/POLISH_QUEUE.md` | 3 | 323 | 34,832 | 8,708 | 4.35% |
| `docs/migration/02_PHASES.md` | 3 | 327 | 28,288 | 7,072 | 3.54% |
| `docs/migration/PHASE_1_DEEP_DIVE_PLAN.md` | 3 | 340 | 26,203 | 6,551 | 3.28% |
| `docs/migration/PHASE_1_TESTING_BLUEPRINT.md` | 3 | 618 | 25,188 | 6,297 | 3.15% |
| `docs/migration/RISKS.md` | 2 | 101 | 24,444 | 6,111 | 3.06% |
| `docs/migration/09_VISUALS.md` | 3 | 712 | 24,089 | 6,022 | 3.01% |
| `docs/migration/MULTI_AGENT_GUIDE.md` | 3 | 414 | 23,991 | 5,998 | 3.00% |
| `docs/migration/phase1/01b_bronze_stage_example_ddl.md` | 3 | 419 | 23,993 | 5,998 | 3.00% |
| `docs/migration/06_TESTING.md` | 3 | 502 | 23,544 | 5,886 | 2.94% |
| `docs/migration/phase1/03_round_0_5_spike_plan.md` | 3 | 604 | 23,497 | 5,874 | 2.94% |
| `docs/migration/07_LOGGING.md` | 3 | 501 | 21,552 | 5,388 | 2.69% |
| `docs/migration/phase1/07a_schema_contract_examples.md` | 3 | 407 | 21,391 | 5,348 | 2.67% |
| `docs/migration/CHECKS_AND_BALANCES.md` | 1 | 346 | 20,704 | 5,176 | 2.59% |
| `docs/migration/phase1/04b_phase_0_closure_tools.md` | 3 | 257 | 20,645 | 5,161 | 2.58% |
| `docs/migration/phase2/00_phase_overview.md` | 3 | 268 | 19,683 | 4,921 | 2.46% |
| `docs/migration/ONE_OFF_SCRIPTS.md` | 3 | 222 | 19,448 | 4,862 | 2.43% |
| `docs/migration/SECURITY_MODEL.md` | 3 | 408 | 18,462 | 4,616 | 2.31% |
| `docs/migration/01_ARCHITECTURE.md` | 3 | 238 | 17,393 | 4,348 | 2.17% |
| `docs/migration/MAINTENANCE.md` | 3 | 323 | 16,162 | 4,040 | 2.02% |
| `docs/migration/00_OVERVIEW.md` | 3 | 196 | 14,936 | 3,734 | 1.87% |
| `docs/migration/phase1/01d_consumer_query_patterns.md` | 3 | 374 | 14,315 | 3,579 | 1.79% |
| `docs/migration/NORTH_STAR.md` | 1 | 114 | 12,580 | 3,145 | 1.57% |
| `docs/migration/phase0/_sweep_2026-05-12.md` | 3 | 90 | 11,494 | 2,874 | 1.44% |
| `docs/migration/_NEXT_STEPS_2026-05-12.md` | 3 | 135 | 9,682 | 2,420 | 1.21% |
| `docs/migration/OBSIDIAN_GUIDE.md` | 3 | 233 | 9,327 | 2,332 | 1.17% |
| `docs/migration/SKILLS_PLAN.md` | 3 | 144 | 8,693 | 2,173 | 1.09% |
| `docs/migration/SELF_IMPROVEMENT_DISCIPLINE.md` | 3 | 148 | 8,675 | 2,169 | 1.08% |
| `docs/migration/ROUND_1_REVIEW.md` | 3 | 126 | 8,096 | 2,024 | 1.01% |
| `docs/migration/phase1/00_phase_overview.md` | 3 | 164 | 7,491 | 1,873 | 0.94% |
| `docs/migration/_agent_evolution/step-10-verifier-36d500e-2026-05-15.md` | 3 | 110 | 7,432 | 1,858 | 0.93% |
| `docs/migration/phase2/01a_execution_order.md` | 3 | 118 | 6,185 | 1,546 | 0.77% |
| `docs/migration/audit_reports/_TEMPLATE_quarterly.md` | 3 | 176 | 5,525 | 1,381 | 0.69% |
| `docs/migration/SESSION_2026-05-13_BUILD_LOG.md` | 3 | 99 | 5,072 | 1,268 | 0.63% |
| `docs/migration/_agent_evolution/udm-design-reviewer-changelog.md` | 3 | 43 | 3,906 | 976 | 0.49% |
| `docs/migration/audit_reports/_TEMPLATE_q10_weekly.md` | 3 | 65 | 1,979 | 495 | 0.25% |
| `docs/migration/_templates/runbook_template.md` | 3 | 58 | 1,072 | 268 | 0.13% |
| `docs/migration/_templates/decision_template.md` | 3 | 36 | 796 | 199 | 0.10% |
| `docs/migration/_templates/edge_case_template.md` | 3 | 42 | 782 | 196 | 0.10% |

