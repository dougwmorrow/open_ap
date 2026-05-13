# Data Engineering Skills for Claude Code

A small set of [Claude Code](https://docs.claude.com/en/docs/claude-code) skills that codify a credit-union data engineering team's conventions across SQL, Python, documentation, GitHub workflow, and PII/secrets handling.

These are designed to be **opinionated defaults** — read them, edit to match your team's reality, then publish.

## What's included

| Skill | When it fires |
|---|---|
| [`sql-naming-conventions`](sql-naming-conventions/SKILL.md) | Creating, naming, or reviewing SQL schemas, tables, views, and stored procedures |
| [`python-data-eng-style`](python-data-eng-style/SKILL.md) | Writing Python for Polars / Snowflake / BCP / SCD2 pipelines |
| [`code-documentation-standard`](code-documentation-standard/SKILL.md) | Authoring module/file/function headers in Python or SQL |
| [`github-repo-hygiene`](github-repo-hygiene/SKILL.md) | Branching, committing, opening PRs, scaffolding new repos, responding to leaked secrets |
| [`pii-and-secrets-handling`](pii-and-secrets-handling/SKILL.md) | Anything touching credentials or member PII — cuts across the others |

## Stack assumptions

These skills assume the following stack. Adjust the markdown if yours differs.

- **SQL:** SQL Server warehouse with named schemas per source system (DNA, CCM, DMI, Epicor, Cloud EPM) and per business domain (accounts, lending, risk, etc.)
- **Python:** 3.11+, [Polars](https://pola.rs) for dataframes, [`uv`](https://github.com/astral-sh/uv) for deps, [`ruff`](https://docs.astral.sh/ruff/) for lint+format, [`mypy`](https://mypy-lang.org/) for types
- **Data movement:** [BCP](https://learn.microsoft.com/en-us/sql/tools/bcp-utility) for SQL Server bulk export, [snowflake-connector-python](https://docs.snowflake.com/en/developer-guide/python-connector/python-connector) for Snowflake load, SCD2 effective-dating
- **Tooling:** JIRA for tickets, Confluence for runbooks, GitHub for code

## How to install

### Per-user (recommended for trying it out)

```bash
git clone https://github.com/<you>/data-eng-skills ~/.claude/skills/data-eng
```

Claude Code will discover the skills automatically. Each skill triggers on its own — no top-level glue needed.

### Per-project (recommended for team rollout)

In your project repo:

```bash
git clone https://github.com/<you>/data-eng-skills .claude/skills/data-eng
echo ".claude/skills/data-eng" >> .gitignore  # or commit, your call
```

### As a git submodule

```bash
git submodule add https://github.com/<you>/data-eng-skills .claude/skills/data-eng
```

## How skills work (one-paragraph version)

A Claude Code skill is a markdown file (`SKILL.md`) with a YAML frontmatter `description` that tells the model **when** to invoke the skill. When Claude detects a task matching the description, it reads the rest of the file and follows it. Skills are evaluated against every user turn, so the descriptions need to be specific enough to fire on real intent without firing on everything. See the [skills documentation](https://docs.claude.com/en/docs/claude-code/skills) for the full mechanism.

## Editing for your team

Before publishing, walk each skill and look for:

- **Org-specific names** — "DATA-1234" JIRA prefix, Confluence URL, Snowflake warehouse names.
- **Stack mismatches** — if you use Pandas instead of Polars, or PostgreSQL instead of Snowflake, the patterns need substitution.
- **Schema list** — `sql-naming-conventions` lists this team's specific schemas. Replace with yours.
- **CODEOWNERS / branch protection** — example values; configure to your repo realities.
- **Compliance regime** — `pii-and-secrets-handling` references credit-union-specific rules (GLBA, NCUA). Your industry will differ.

## Conventions used across skills

- Each skill ends with a **"What to do when applying this skill"** section (the action list) and a **"What NOT to do"** section (the anti-patterns). This format makes the skill usable both as a reference and as a runtime instruction set.
- Skill descriptions explicitly enumerate **trigger phrases** ("triggers when the user says...") to maximize trigger reliability.
- Skills cross-reference each other by name (`see github-repo-hygiene skill`) rather than by file path, so they survive rearrangement.

## License

Choose a license before publishing — `MIT` or `CC0` are the easy defaults for skill content.

## Acknowledgments

The skill-authoring conventions follow the patterns used by [obra/superpowers](https://github.com/obra/superpowers).
