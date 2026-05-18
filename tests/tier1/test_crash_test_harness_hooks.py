"""Tier 1 unit tests for B-270 crash-injection harness hooks.

Per B-270 closure + docs/migration/06_TESTING.md Tier 4 + Round 5 § 7.

Verifies the env-var-gated contract holds for all 3 production-module hooks:

* ``_crash_test_harness_c2``  in ``data_load/parquet_writer.py``
* ``_crash_test_harness_c7``  in ``scd2/engine.py``
* ``_crash_test_harness_c11`` in ``tools/parquet_tier_review.py``

Each hook is the BOUNDARY-token half of a Tier 4 deterministic SIGKILL
test: the parent test process spawns a subprocess, waits for the
specific barrier token on stdout, then sends SIGKILL during the
sleep window. This Tier 1 file does NOT exercise the SIGKILL part
(that lives in ``tests/tier4/`` against live Docker SQL Server); it
only proves the in-process contract — env var gating, token emission,
no-op behavior, and the defensive try/except discipline.

Contract under test
-------------------

  (a) env var absent                 -> no-op  (no stdout emission, no sleep)
  (b) env var present + value MATCH  -> emit token + sleep (default 10s)
  (c) env var present + value NOMATCH-> no-op
  (d) hook NEVER raises exceptions   (defensive try/except internal)
  (e) hooks NOT in module __all__    (private API contract)
  (f) C11 token + checkpoint name carry the per-N value

Tests are fast — the matching-case tests override
``CRASH_INJECT_SLEEP_SECONDS=0.01`` so each test completes in ~10 ms.

Run with::

    .venv/Scripts/python.exe -m pytest tests/tier1/test_crash_test_harness_hooks.py -xvs

North Star pillars addressed
----------------------------

  - Idempotent (D15): hooks are pure no-op in production runs (env-var
    absent), so a re-run of any pipeline path is bit-for-bit identical.
  - Audit-grade (D26): hooks emit no PipelineLog rows / no
    PipelineEventLog rows — silent contract; no auditable side effects.
  - Operationally stable (D69): hooks NEVER raise; production paths
    are untouched even if the env-var read fails for an unknown reason.

Decision citations
------------------

  D15 (idempotency at every layer), D26 (append-only audit posture —
  hooks emit no audit rows), D55 (5-gate validation), D67 (Tier 0/1
  smoke-test discipline), D69 (cursor ownership — N/A; hooks have
  no DB surface), D92 (forward-only additive — new hooks).
"""
from __future__ import annotations

import os
import sys
import time
from io import StringIO

import pytest


# ---------------------------------------------------------------------------
# Shared fixture: ensure CRASH_INJECT_POINT is unset at test entry.
#
# Several tests under monkeypatch.setenv() set the var, which the
# monkeypatch fixture undoes at teardown. We add a belt-and-suspenders
# autouse fixture to delete the var BEFORE every test (in case a
# previous fixture leaked it) — defense-in-depth so the "absent"
# branch tests cannot get false positives.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _ensure_clean_env(monkeypatch):
    """Guarantee ``CRASH_INJECT_POINT`` is unset at test entry."""
    monkeypatch.delenv("CRASH_INJECT_POINT", raising=False)
    monkeypatch.delenv("CRASH_INJECT_SLEEP_SECONDS", raising=False)
    yield


# ---------------------------------------------------------------------------
# C2 — data_load/parquet_writer.py
# ---------------------------------------------------------------------------


class TestCrashHarnessC2:
    """B-270: ``_crash_test_harness_c2`` in ``data_load/parquet_writer.py``.

    Boundary: AFTER ``df.write_parquet(inflight_path, ...)`` succeeds,
    BEFORE ``_atomic_rename(inflight_path, final_path)``. A SIGKILL
    during the sleep window leaves the inflight file on disk + no
    registry row — Tier 4 verifies operator recovery from this state.
    """

    def test_noop_when_env_var_absent(self, capsys):
        """(a) env var absent -> no stdout emission, no sleep."""
        from data_load.parquet_writer import _crash_test_harness_c2

        t_start = time.perf_counter()
        _crash_test_harness_c2()
        t_elapsed = time.perf_counter() - t_start

        captured = capsys.readouterr()
        assert "INFLIGHT_WRITE_DONE" not in captured.out
        # Sleep should NOT have fired — hook returns immediately.
        assert t_elapsed < 0.5, f"hook unexpectedly slept {t_elapsed:.3f}s"

    def test_noop_when_env_var_does_not_match(self, monkeypatch, capsys):
        """(c) env var present + value mismatch -> no-op."""
        monkeypatch.setenv("CRASH_INJECT_POINT", "totally_different_checkpoint")
        from data_load.parquet_writer import _crash_test_harness_c2

        t_start = time.perf_counter()
        _crash_test_harness_c2()
        t_elapsed = time.perf_counter() - t_start

        captured = capsys.readouterr()
        assert "INFLIGHT_WRITE_DONE" not in captured.out
        assert t_elapsed < 0.5

    def test_emits_token_and_sleeps_when_match(self, monkeypatch, capsys):
        """(b) env var matches -> emit token + sleep (fast override)."""
        monkeypatch.setenv("CRASH_INJECT_POINT", "after_inflight_write")
        monkeypatch.setenv("CRASH_INJECT_SLEEP_SECONDS", "0.01")
        from data_load.parquet_writer import _crash_test_harness_c2

        t_start = time.perf_counter()
        _crash_test_harness_c2()
        t_elapsed = time.perf_counter() - t_start

        captured = capsys.readouterr()
        assert "INFLIGHT_WRITE_DONE" in captured.out
        # 0.01s sleep should have fired — allow generous lower bound
        # for OS scheduling jitter while excluding the no-op case.
        assert t_elapsed >= 0.005, (
            f"hook returned in {t_elapsed:.4f}s — sleep did not fire"
        )

    def test_custom_checkpoint_name(self, monkeypatch, capsys):
        """Hook accepts checkpoint override (defense-in-depth API)."""
        monkeypatch.setenv("CRASH_INJECT_POINT", "custom_c2_checkpoint")
        monkeypatch.setenv("CRASH_INJECT_SLEEP_SECONDS", "0.01")
        from data_load.parquet_writer import _crash_test_harness_c2

        _crash_test_harness_c2(checkpoint="custom_c2_checkpoint")

        captured = capsys.readouterr()
        assert "INFLIGHT_WRITE_DONE" in captured.out

    def test_never_raises_with_bad_sleep_value(self, monkeypatch):
        """(d) hook NEVER raises — bad CRASH_INJECT_SLEEP_SECONDS swallowed."""
        monkeypatch.setenv("CRASH_INJECT_POINT", "after_inflight_write")
        monkeypatch.setenv("CRASH_INJECT_SLEEP_SECONDS", "not_a_float")
        from data_load.parquet_writer import _crash_test_harness_c2

        # Must NOT raise ValueError from float("not_a_float").
        _crash_test_harness_c2()
        # If we got here, the defensive try/except worked.

    def test_not_in_module_all_export(self):
        """(e) hook is NOT in ``__all__`` (private API contract)."""
        import data_load.parquet_writer as module

        assert "_crash_test_harness_c2" not in module.__all__


# ---------------------------------------------------------------------------
# C7 — scd2/engine.py
# ---------------------------------------------------------------------------


class TestCrashHarnessC7:
    """B-270: ``_crash_test_harness_c7`` in ``scd2/engine.py``.

    Boundary: AFTER ``_execute_bronze_updates(...label_suffix=...)``
    (close-old + delete-close), BEFORE ``_activate_new_versions(...)``
    inside :func:`run_scd2`. A SIGKILL during the sleep window leaves
    the SCD2 batch in the canonical "in-flight orphan" state per
    SCD2-P1-e (Flag=0, op IN {U,R}, both UdmEndDateTime and
    UdmSourceEndDate IS NULL) — Tier 4 verifies recovery via the next
    run's ``_cleanup_orphaned_inactive_rows`` sweep.
    """

    def test_noop_when_env_var_absent(self, capsys):
        """(a) env var absent -> no stdout emission, no sleep."""
        from scd2.engine import _crash_test_harness_c7

        t_start = time.perf_counter()
        _crash_test_harness_c7()
        t_elapsed = time.perf_counter() - t_start

        captured = capsys.readouterr()
        assert "CLOSE_OLD_COMPLETE" not in captured.out
        assert t_elapsed < 0.5

    def test_noop_when_env_var_does_not_match(self, monkeypatch, capsys):
        """(c) env var present + value mismatch -> no-op."""
        monkeypatch.setenv("CRASH_INJECT_POINT", "wrong_value_for_c7")
        from scd2.engine import _crash_test_harness_c7

        t_start = time.perf_counter()
        _crash_test_harness_c7()
        t_elapsed = time.perf_counter() - t_start

        captured = capsys.readouterr()
        assert "CLOSE_OLD_COMPLETE" not in captured.out
        assert t_elapsed < 0.5

    def test_emits_token_and_sleeps_when_match(self, monkeypatch, capsys):
        """(b) env var matches -> emit token + sleep (fast override)."""
        monkeypatch.setenv("CRASH_INJECT_POINT", "after_close_old")
        monkeypatch.setenv("CRASH_INJECT_SLEEP_SECONDS", "0.01")
        from scd2.engine import _crash_test_harness_c7

        t_start = time.perf_counter()
        _crash_test_harness_c7()
        t_elapsed = time.perf_counter() - t_start

        captured = capsys.readouterr()
        assert "CLOSE_OLD_COMPLETE" in captured.out
        assert t_elapsed >= 0.005

    def test_never_raises_with_bad_sleep_value(self, monkeypatch):
        """(d) hook NEVER raises — bad CRASH_INJECT_SLEEP_SECONDS swallowed."""
        monkeypatch.setenv("CRASH_INJECT_POINT", "after_close_old")
        monkeypatch.setenv("CRASH_INJECT_SLEEP_SECONDS", "definitely_not_a_number")
        from scd2.engine import _crash_test_harness_c7

        _crash_test_harness_c7()
        # Reaching this line proves the defensive try/except worked.

    def test_token_does_not_leak_at_import_time(self):
        """Importing scd2.engine MUST NOT trigger the hook side-effect."""
        # Force a re-import in a clean stdout context to verify import
        # is fully side-effect-free.
        import io
        import importlib

        buf = io.StringIO()
        original_stdout = sys.stdout
        try:
            sys.stdout = buf
            import scd2.engine
            importlib.reload(scd2.engine)
        finally:
            sys.stdout = original_stdout

        assert "CLOSE_OLD_COMPLETE" not in buf.getvalue()


# ---------------------------------------------------------------------------
# C11 — tools/parquet_tier_review.py
# ---------------------------------------------------------------------------


class TestCrashHarnessC11:
    """B-270: ``_crash_test_harness_c11`` in ``tools/parquet_tier_review.py``.

    Boundary: BETWEEN consecutive ``_apply_transition(...)`` calls in
    the main --apply batch loop (running counter increments after EACH
    successful transition). A SIGKILL during the sleep window leaves
    the registry partially-transitioned — Tier 4 verifies state-machine
    atomicity per Round 3 § 1.3 (transitioned rows durable + remaining
    rows untouched).

    Distinctive C11 contract: checkpoint name + barrier token both
    incorporate the per-N value, so the parent test process can pick a
    specific transition boundary (e.g. N=3 of 10) to crash at.
    """

    def test_noop_when_env_var_absent(self, capsys):
        """(a) env var absent -> no stdout emission, no sleep."""
        from tools.parquet_tier_review import _crash_test_harness_c11

        t_start = time.perf_counter()
        _crash_test_harness_c11(1)
        t_elapsed = time.perf_counter() - t_start

        captured = capsys.readouterr()
        assert "TRANSITIONS_DONE_" not in captured.out
        assert t_elapsed < 0.5

    def test_noop_when_env_var_does_not_match_value(self, monkeypatch, capsys):
        """(c) env var present + value mismatch -> no-op."""
        monkeypatch.setenv("CRASH_INJECT_POINT", "not_a_c11_checkpoint")
        from tools.parquet_tier_review import _crash_test_harness_c11

        t_start = time.perf_counter()
        _crash_test_harness_c11(5)
        t_elapsed = time.perf_counter() - t_start

        captured = capsys.readouterr()
        assert "TRANSITIONS_DONE_" not in captured.out
        assert t_elapsed < 0.5

    def test_noop_when_env_var_matches_different_n(self, monkeypatch, capsys):
        """(f) per-N gating: env var says N=3 but hook called with N=1 -> no-op.

        This is the load-bearing test for the variable-N contract — the
        parent test process picks a specific N, so the hook MUST be
        no-op for every OTHER N value in the loop.
        """
        monkeypatch.setenv("CRASH_INJECT_POINT", "after_n_transitions_3")
        monkeypatch.setenv("CRASH_INJECT_SLEEP_SECONDS", "0.01")
        from tools.parquet_tier_review import _crash_test_harness_c11

        t_start = time.perf_counter()
        _crash_test_harness_c11(1)
        t_elapsed = time.perf_counter() - t_start

        captured = capsys.readouterr()
        assert "TRANSITIONS_DONE_" not in captured.out
        assert t_elapsed < 0.5

    def test_emits_token_with_n_when_match(self, monkeypatch, capsys):
        """(b) + (f) env var matches per-N value -> emit token_N + sleep.

        Verifies the barrier-token-N invariant: parent process sees
        ``TRANSITIONS_DONE_3`` (not just ``TRANSITIONS_DONE_``) when
        the third transition lands.
        """
        monkeypatch.setenv("CRASH_INJECT_POINT", "after_n_transitions_3")
        monkeypatch.setenv("CRASH_INJECT_SLEEP_SECONDS", "0.01")
        from tools.parquet_tier_review import _crash_test_harness_c11

        t_start = time.perf_counter()
        _crash_test_harness_c11(3)
        t_elapsed = time.perf_counter() - t_start

        captured = capsys.readouterr()
        assert "TRANSITIONS_DONE_3" in captured.out
        assert t_elapsed >= 0.005

    def test_emits_per_n_token_for_first_transition(self, monkeypatch, capsys):
        """N=1 boundary — hook fires on the very first transition."""
        monkeypatch.setenv("CRASH_INJECT_POINT", "after_n_transitions_1")
        monkeypatch.setenv("CRASH_INJECT_SLEEP_SECONDS", "0.01")
        from tools.parquet_tier_review import _crash_test_harness_c11

        _crash_test_harness_c11(1)

        captured = capsys.readouterr()
        assert "TRANSITIONS_DONE_1" in captured.out

    def test_never_raises_with_bad_sleep_value(self, monkeypatch):
        """(d) hook NEVER raises — bad CRASH_INJECT_SLEEP_SECONDS swallowed."""
        monkeypatch.setenv("CRASH_INJECT_POINT", "after_n_transitions_2")
        monkeypatch.setenv("CRASH_INJECT_SLEEP_SECONDS", "garbage")
        from tools.parquet_tier_review import _crash_test_harness_c11

        _crash_test_harness_c11(2)
        # Reaching here proves the defensive try/except worked.

    def test_token_carries_high_n_value(self, monkeypatch, capsys):
        """High N values (e.g. 100th transition in a large batch) format correctly."""
        monkeypatch.setenv("CRASH_INJECT_POINT", "after_n_transitions_100")
        monkeypatch.setenv("CRASH_INJECT_SLEEP_SECONDS", "0.01")
        from tools.parquet_tier_review import _crash_test_harness_c11

        _crash_test_harness_c11(100)

        captured = capsys.readouterr()
        assert "TRANSITIONS_DONE_100" in captured.out
        # Defense-in-depth — ensure we are not accidentally matching
        # a prefix like "TRANSITIONS_DONE_1" against "TRANSITIONS_DONE_100".
        assert "TRANSITIONS_DONE_100\n" in captured.out or captured.out.strip().endswith(
            "TRANSITIONS_DONE_100"
        )


# ---------------------------------------------------------------------------
# Cross-hook contract — applies uniformly to all three hooks.
# ---------------------------------------------------------------------------


class TestCrashHarnessCrossContract:
    """Cross-hook invariants that apply uniformly to C2 / C7 / C11."""

    def test_all_hooks_no_op_when_env_absent_emits_nothing(self, capsys):
        """All three hooks: env absent -> EXACTLY zero stdout output.

        Stronger than individual ``not in`` assertions — verifies that
        no spurious side-effect log line leaks even when all three are
        called back-to-back.
        """
        from data_load.parquet_writer import _crash_test_harness_c2
        from scd2.engine import _crash_test_harness_c7
        from tools.parquet_tier_review import _crash_test_harness_c11

        _crash_test_harness_c2()
        _crash_test_harness_c7()
        _crash_test_harness_c11(1)
        _crash_test_harness_c11(42)

        captured = capsys.readouterr()
        # Expect ZERO output across all 4 calls.
        assert captured.out == "", (
            f"hooks leaked output in no-op mode: {captured.out!r}"
        )

    def test_each_hook_distinct_token(self, monkeypatch, capsys):
        """C2 / C7 / C11 emit DISTINCT tokens — no cross-contamination."""
        from data_load.parquet_writer import _crash_test_harness_c2
        from scd2.engine import _crash_test_harness_c7
        from tools.parquet_tier_review import _crash_test_harness_c11

        monkeypatch.setenv("CRASH_INJECT_SLEEP_SECONDS", "0.01")

        # Fire C2 only.
        monkeypatch.setenv("CRASH_INJECT_POINT", "after_inflight_write")
        _crash_test_harness_c2()
        _crash_test_harness_c7()  # mismatch -> no-op
        _crash_test_harness_c11(1)  # mismatch -> no-op
        c2_out = capsys.readouterr().out
        assert "INFLIGHT_WRITE_DONE" in c2_out
        assert "CLOSE_OLD_COMPLETE" not in c2_out
        assert "TRANSITIONS_DONE" not in c2_out

        # Fire C7 only.
        monkeypatch.setenv("CRASH_INJECT_POINT", "after_close_old")
        _crash_test_harness_c2()  # mismatch -> no-op
        _crash_test_harness_c7()
        _crash_test_harness_c11(1)  # mismatch -> no-op
        c7_out = capsys.readouterr().out
        assert "CLOSE_OLD_COMPLETE" in c7_out
        assert "INFLIGHT_WRITE_DONE" not in c7_out
        assert "TRANSITIONS_DONE" not in c7_out

        # Fire C11 only (N=2).
        monkeypatch.setenv("CRASH_INJECT_POINT", "after_n_transitions_2")
        _crash_test_harness_c2()  # mismatch -> no-op
        _crash_test_harness_c7()  # mismatch -> no-op
        _crash_test_harness_c11(2)
        c11_out = capsys.readouterr().out
        assert "TRANSITIONS_DONE_2" in c11_out
        assert "INFLIGHT_WRITE_DONE" not in c11_out
        assert "CLOSE_OLD_COMPLETE" not in c11_out

    def test_all_hooks_underscore_prefix_convention(self):
        """All three hooks follow the underscore-prefix private-API convention."""
        from data_load.parquet_writer import _crash_test_harness_c2
        from scd2.engine import _crash_test_harness_c7
        from tools.parquet_tier_review import _crash_test_harness_c11

        # Name starts with underscore -> private convention.
        assert _crash_test_harness_c2.__name__.startswith("_")
        assert _crash_test_harness_c7.__name__.startswith("_")
        assert _crash_test_harness_c11.__name__.startswith("_")
