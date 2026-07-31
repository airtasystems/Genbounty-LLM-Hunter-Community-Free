"""Job manager - spawn, track, stream, and cancel long-running tasks."""

from __future__ import annotations

import asyncio
import io
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_root = Path(__file__).resolve().parent.parent

# Ensure the project root and browser-bot package dir are importable once at
# module load, so hot-path helpers don't re-check/insert sys.path on every call.
for _p in (str(_root), str(_root / "browser-bot")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _prepare_component_context(job: Job) -> None:
    """Set GENBOUNTY_SITE/COMPONENT and apply per-component browser settings overrides."""
    if job.site:
        os.environ["GENBOUNTY_SITE"] = job.site
    if job.component:
        os.environ["GENBOUNTY_COMPONENT"] = job.component
    if not (job.site and job.component):
        return
    from browser_bot.config import apply_component_settings

    apply_component_settings(job.site, job.component)


def _apply_gen_attributes_env(job: Job, env: dict[str, str]) -> bool:
    """If the job opted in, set GENBOUNTY_GEN_ATTRIBUTES* on ``env``. Returns True when set."""
    enabled = job.params.get("gen_attributes_enabled")
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        env.pop("GENBOUNTY_GEN_ATTRIBUTES", None)
        env.pop("GENBOUNTY_GEN_ATTRIBUTES_JSON", None)
        return False
    attrs = job.params.get("gen_attributes")
    if not isinstance(attrs, dict):
        env.pop("GENBOUNTY_GEN_ATTRIBUTES", None)
        env.pop("GENBOUNTY_GEN_ATTRIBUTES_JSON", None)
        return False
    try:
        import json as _json

        gen_dir = _root / "generate-tests"
        if str(gen_dir) not in sys.path:
            sys.path.insert(0, str(gen_dir))
        from prompt_attributes import normalize_attributes

        normalized = normalize_attributes(attrs)
        env["GENBOUNTY_GEN_ATTRIBUTES"] = "1"
        env["GENBOUNTY_GEN_ATTRIBUTES_JSON"] = _json.dumps(normalized, separators=(",", ":"))
        job.output.append(
            "[attributes] Auto-apply on generate/enhance: "
            f"temp={normalized['temperature']} max_tokens={normalized['max_tokens']} "
            f"top_k={normalized['top_k']} top_p={normalized['top_p']}"
        )
        return True
    except Exception as exc:
        env.pop("GENBOUNTY_GEN_ATTRIBUTES", None)
        env.pop("GENBOUNTY_GEN_ATTRIBUTES_JSON", None)
        job.output.append(f"[attributes] Auto-apply skipped (invalid settings): {exc}")
        return False


def _apply_gen_transform_pipeline_env(job: Job, env: dict[str, str]) -> bool:
    """If the job opted in, set GENBOUNTY_GEN_TRANSFORM_PIPELINE* on ``env``."""
    enabled = job.params.get("gen_transforms_enabled")
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
    if not enabled:
        env.pop("GENBOUNTY_GEN_TRANSFORM_PIPELINE", None)
        env.pop("GENBOUNTY_GEN_TRANSFORM_PIPELINE_JSON", None)
        return False
    steps = job.params.get("gen_transforms")
    if not isinstance(steps, list) or not steps:
        env.pop("GENBOUNTY_GEN_TRANSFORM_PIPELINE", None)
        env.pop("GENBOUNTY_GEN_TRANSFORM_PIPELINE_JSON", None)
        return False
    try:
        import json as _json

        gen_dir = _root / "generate-tests"
        if str(gen_dir) not in sys.path:
            sys.path.insert(0, str(gen_dir))
        from prompt_gen_pipeline import normalize_pipeline_steps

        normalized = normalize_pipeline_steps(steps)
        if not normalized:
            env.pop("GENBOUNTY_GEN_TRANSFORM_PIPELINE", None)
            env.pop("GENBOUNTY_GEN_TRANSFORM_PIPELINE_JSON", None)
            return False
        env["GENBOUNTY_GEN_TRANSFORM_PIPELINE"] = "1"
        env["GENBOUNTY_GEN_TRANSFORM_PIPELINE_JSON"] = _json.dumps(
            normalized, separators=(",", ":")
        )
        spec = " → ".join(f"{s['kind']}:{s['name']}" for s in normalized)
        job.output.append(f"[transforms] Auto-apply on generate/enhance: {spec}")
        return True
    except Exception as exc:
        env.pop("GENBOUNTY_GEN_TRANSFORM_PIPELINE", None)
        env.pop("GENBOUNTY_GEN_TRANSFORM_PIPELINE_JSON", None)
        job.output.append(f"[transforms] Auto-apply skipped (invalid pipeline): {exc}")
        return False


def _apply_gen_auto_apply_env(job: Job, env: dict[str, str]) -> None:
    """Apply Generate & Enhance auto-apply env (transform pipeline + attributes)."""
    _apply_gen_transform_pipeline_env(job, env)
    _apply_gen_attributes_env(job, env)


class _BoundedOutput(list):
    """A list that caps retained lines, evicting the oldest in batches.

    ``dropped`` counts lines trimmed from the front so consumers can map an
    absolute line index (total lines ever produced) to a current slot.
    """

    _MAX_LINES = 50_000
    _TRIM_BATCH = 10_000

    def __init__(self) -> None:
        super().__init__()
        self.dropped = 0

    def append(self, item: str) -> None:  # type: ignore[override]
        super().append(item)
        if len(self) > self._MAX_LINES + self._TRIM_BATCH:
            del self[: self._TRIM_BATCH]
            self.dropped += self._TRIM_BATCH


@dataclass
class Job:
    id: str
    type: str
    status: str  # pending | running | done | failed | cancelled
    site: str
    component: str
    params: dict
    output: list[str] = field(default_factory=_BoundedOutput)
    created_at: datetime = field(default_factory=datetime.now)
    _process: asyncio.subprocess.Process | None = field(default=None, repr=False)
    _task: asyncio.Task | None = field(default=None, repr=False)
    _event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    run_log_dir: str = ""
    theory_state: dict[str, Any] | None = field(default=None, repr=False)
    theory_decision: dict[str, Any] | None = field(default=None, repr=False)
    _theory_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "site": self.site,
            "component": self.component,
            "params": self.params,
            "created_at": self.created_at.isoformat(),
            "output_lines": getattr(self.output, "dropped", 0) + len(self.output),
        }
        if self.status == "awaiting_theory" and self.theory_state:
            d["theory_state"] = self.theory_state
        return d


class _OutputCapture(io.TextIOBase):
    """File-like that appends lines to a Job's output buffer and pokes its event."""

    def __init__(self, job: Job):
        self._job = job

    def write(self, s: str) -> int:
        if s:
            for line in s.split("\n"):
                stripped = line.rstrip("\r")
                if stripped.strip():
                    self._job.output.append(stripped)
                    self._job._event.set()
        return len(s)

    def flush(self) -> None:
        pass


_jobs: dict[str, Job] = {}

# Keep at most this many finished (done/failed/cancelled) jobs in memory; the
# oldest beyond the limit are evicted so long-lived servers don't grow forever.
_MAX_FINISHED_JOBS = 200


def _evict_finished_jobs() -> None:
    finished = [
        j for j in _jobs.values()
        if j.status in ("done", "failed", "cancelled")
    ]
    excess = len(finished) - _MAX_FINISHED_JOBS
    if excess <= 0:
        return
    finished.sort(key=lambda j: j.created_at)
    for job in finished[:excess]:
        _jobs.pop(job.id, None)

_ALL_STRATEGIES = [
    "zero_shot", "adaptive", "multi_shot", "few_shot", "iterative", "chain_of_thought",
    "prompt_chaining", "tree_of_thoughts", "self_consistency", "self_reflection",
    "directional_stimulus", "jailbreak", "multimodal",
]


def _suite_path_for_generate(site: str, component: str, strategy: str, playbook: str) -> Path:
    return (
        _root
        / "browser-bot"
        / "sites"
        / site
        / component
        / "tests"
        / strategy.replace("_", "-")
        / f"{playbook.replace('_', '-')}.json"
    )


def _materialize_multimodal_output(job: Job, strategy: str, playbook: str) -> None:
    """Multimodal payloads are materialized inside generate-tests/core.generate_attack_suite."""
    if strategy != "multimodal" or job.status != "done" or not (job.site and job.component):
        return
    suite_path = _suite_path_for_generate(job.site, job.component, strategy, playbook)
    if suite_path.is_file():
        job.output.append(f"[generate] Multimodal artifacts materialized with suite: {suite_path.name}")
    job._event.set()


def _warn_multimodal_preflight(job: Job, suite_path: Path, suite_data: dict) -> None:
    """Print warnings when suite has payloads but upload config or artifact files are missing."""
    has_payloads = False
    for cat in suite_data.get("categories") or suite_data.get("mandates") or []:
        if not isinstance(cat, dict):
            continue
        for p in cat.get("prompts") or []:
            payload = p.get("payload") if isinstance(p, dict) else None
            if isinstance(payload, dict) and (payload.get("generator") or payload.get("path")):
                has_payloads = True
                break
        if has_payloads:
            break
    if not has_payloads:
        return

    from browser_bot.sites import get_submission_config

    sub = get_submission_config(job.site, job.component) or {}
    transport = (sub.get("transport") or "ui").lower()
    upload_ok = transport in ("api_document", "api_multipart")
    if not upload_ok and transport == "ui":
        inputs = sub.get("inputs") or []
        upload_ok = any(
            i.get("type") == "file" or i.get("path_from") == "payload" for i in inputs if isinstance(i, dict)
        )
    if not upload_ok:
        print(
            "[warn] Suite includes file payloads but component config has no file upload "
            "(UI input type: file with path_from: payload, or transport api_document/api_multipart)."
        )

    try:
        from payloads.materialize import artifact_status_for_suite

        for row in artifact_status_for_suite(suite_path):
            pid = row.get("id") or "?"
            status = row.get("status")
            if status == "missing_path":
                art = str(row.get("path") or "").strip()
                art_name = Path(art).name if art else "?"
                print(f"[warn] Missing artifact file for prompt {pid}: {art_name}")
            elif status == "lazy":
                print(f"[info] Prompt {pid}: will generate payload at run time ({row.get('generator')})")
    except Exception:
        pass

from pipeline.report import SEVERITY_ORDER as _SEVERITY_ORDER

# Log batch windows for security assessment and export (UI → job params).
LOG_TIME_WINDOWS: dict[str, float] = {
    "1h": 1.0,
    "4h": 4.0,
    "24h": 24.0,
}
# Legacy alias
ASSESS_TIME_WINDOWS = LOG_TIME_WINDOWS


def _component_logs_dir(site: str, component: str) -> Path:
    from browser_bot.sites import get_component_path

    return get_component_path(site, component) / "logs"


def _paths_in_time_window(paths: list[Path], window_id: str) -> list[Path]:
    hours = LOG_TIME_WINDOWS.get(window_id)
    if hours is None:
        return []
    import time

    cutoff = time.time() - hours * 3600
    return [p for p in paths if p.stat().st_mtime >= cutoff]


def _time_window_label(window_id: str) -> str:
    return {"1h": "last hour", "4h": "last 4 hours", "24h": "last 24 hours"}.get(
        window_id, window_id
    )


def _list_attack_log_paths(site: str, component: str) -> list[Path]:
    """Attack logs for a component, newest first (probes + attack + manual)."""
    from pipeline.log_paths import list_attack_logs

    return list_attack_logs(site, component)


def _list_pipeline_report_paths(site: str, component: str) -> list[Path]:
    """Pipeline reports for a component, newest first (probes + attack + manual)."""
    from pipeline.log_paths import list_pipeline_reports

    return list_pipeline_reports(site, component)


def _list_probe_attack_log_paths(site: str, component: str) -> list[Path]:
    """Suite probe-lane attack logs only (for enhance pre-assess)."""
    from pipeline.log_paths import LOG_KIND_PROBES, list_attack_logs

    return list_attack_logs(site, component, kinds=(LOG_KIND_PROBES,))


def _attack_logs_in_window(site: str, component: str, window_id: str) -> list[Path]:
    return _paths_in_time_window(_list_attack_log_paths(site, component), window_id)


def _pipeline_reports_in_window(site: str, component: str, window_id: str) -> list[Path]:
    return _paths_in_time_window(_list_pipeline_report_paths(site, component), window_id)


def _norm_strategy(value: Any) -> str:
    """Normalize strategy ids; treat '-' and '_' as equivalent."""
    return str(value or "").strip().lower().replace("-", "_")


def _attack_log_matches_play(
    log_data: dict[str, Any],
    playbook_id: str,
    strategy: str,
) -> bool:
    if playbook_id and _norm_strategy(log_data.get("playbook_id")) != _norm_strategy(playbook_id):
        return False
    if strategy:
        # Empty log strategy must not wildcard-match a concrete strategy filter.
        if _norm_strategy(log_data.get("strategy")) != _norm_strategy(strategy):
            return False
    return True


def _read_attack_log_meta(path: Path) -> dict[str, Any] | None:
    import json as _json

    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
    except (OSError, _json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _find_latest_attack_log_for_play(
    site: str,
    component: str,
    playbook_id: str,
    strategy: str,
) -> Path | None:
    """Newest probe-lane attack_log.json for this playbook + strategy, or None."""
    for path in _list_probe_attack_log_paths(site, component):
        meta = _read_attack_log_meta(path)
        if meta and _attack_log_matches_play(meta, playbook_id, strategy):
            return path
    return None


def _attack_log_needs_assessment(attack_log: Path) -> bool:
    """True when the run dir has no pipeline report or the log is newer than its report."""
    report_path = attack_log.parent / "pipeline_report.json"
    if not report_path.is_file():
        return True
    try:
        return attack_log.stat().st_mtime > report_path.stat().st_mtime
    except OSError:
        return True


def _play_has_fresh_assessment(
    site: str,
    component: str,
    playbook_id: str,
    strategy: str,
) -> bool:
    """True when this play/strategy already has an up-to-date pipeline_report.json."""
    attack_log = _find_latest_attack_log_for_play(site, component, playbook_id, strategy)
    if attack_log is None:
        return False
    return not _attack_log_needs_assessment(attack_log)


async def _baseline_run_suite_before_enhance(
    job: Job,
    suite_path: Path,
    playbook_id: str,
    strategy: str,
) -> bool:
    """Run the on-disk suite + assess when no fresh report exists.

    Enhance must not regenerate newly created probes until they have been tested
    and risk-assessed at least once. Returns False on cancel/failure.
    """
    if _play_has_fresh_assessment(job.site, job.component, playbook_id, strategy):
        job.output.append(
            "[enhance] Fresh Analysis present - starting enhance rounds "
            "(no baseline re-run)."
        )
        job._event.set()
        return True

    if not suite_path.is_file():
        job.output.append(
            f"[!] Cannot baseline-run before enhance: suite missing ({suite_path.name})."
        )
        job._event.set()
        return False

    job.output.append(
        "[enhance] Baseline: running existing suite + Analysis before any "
        "enhance regen (newly generated probes are never enhanced cold)…"
    )
    job._event.set()
    try:
        _preflight_run_suite(job, suite_path)
    except ValueError as exc:
        job.output.append(f"[!] {exc}")
        job._event.set()
        return False

    rc = await _run_subprocess_job(
        job,
        _build_run_test_cmd(job, suite_path),
        env=_make_run_tests_env(job),
        set_status=False,
    )
    if _is_cancelled(job):
        return False
    if rc != 0:
        job.output.append(
            f"[!] Baseline run exited {rc}; refusing enhance without Analysis."
        )
        job._event.set()
        return False

    report_path = await _after_assessed_run(job, suite_path)
    if _is_cancelled(job):
        return False
    if not report_path or not report_path.is_file():
        job.output.append(
            "[!] Baseline Analysis did not produce pipeline_report.json; "
            "refusing enhance."
        )
        job._event.set()
        return False

    job.output.append(
        f"[+] Baseline complete ({report_path.parent.name}) - starting enhance rounds."
    )
    job._event.set()
    return True


async def _run_assess_attack_log_in_thread(job: Job, attack_log: Path) -> Path | None:
    """Assess one attack log in a worker thread; stream stdout into the job output."""
    import json as _json

    if _is_cancelled(job):
        job.output.append("[!] Analysis skipped: job cancelled.")
        job._event.set()
        return None

    job.output.append(
        "[genbounty_progress] "
        + _json.dumps({"type": "risk_start", "phase": "risk"}, ensure_ascii=False)
    )
    job._event.set()

    def _wrapped() -> Path:
        try:
            from dotenv import load_dotenv

            load_dotenv(_root / ".config")
            load_dotenv(_root / ".env")
        except ImportError:
            pass
        _prepare_component_context(job)
        return _assess_attack_log(attack_log)

    def _run() -> Path:
        cap = _OutputCapture(job)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = cap  # type: ignore[assignment]
        sys.stderr = cap  # type: ignore[assignment]
        try:
            return _wrapped()
        finally:
            sys.stdout, sys.stderr = old_out, old_err

    try:
        report_path = await asyncio.to_thread(_run)
    except asyncio.CancelledError:
        job.output.append("[!] Analysis cancelled.")
        job._event.set()
        raise
    except Exception as exc:
        job.output.append(f"[!] Analysis failed: {exc}")
        job._event.set()
        return None

    if _is_cancelled(job):
        job.output.append("[!] Analysis finished after cancel - discarding further pipeline steps.")
        job._event.set()
        return report_path

    job.output.append(
        "[genbounty_progress] "
        + _json.dumps({"type": "risk_done", "phase": "risk"}, ensure_ascii=False)
    )
    job._event.set()
    return report_path


async def _auto_recon_from_report(job: Job, report_path: Path | None) -> bool:
    """Merge a pipeline report into intel/{playbook_id}.json after assessment."""
    import json as _json

    if not report_path or not report_path.is_file():
        return False
    if not (job.site and job.component):
        job.output.append("[!] Auto intel skipped: no site/component context.")
        job._event.set()
        return False

    job.output.append("[intel] Auto-updating playbook intel…")
    job.output.append(
        "[genbounty_progress] "
        + _json.dumps({"type": "recon_auto_start", "phase": "recon"}, ensure_ascii=False)
    )
    job._event.set()

    def _run() -> Path:
        try:
            from dotenv import load_dotenv

            load_dotenv(_root / ".config")
            load_dotenv(_root / ".env")
        except ImportError:
            pass
        _prepare_component_context(job)
        from pipeline.recon_auto import save_intel_from_pipeline_report

        return save_intel_from_pipeline_report(job.site, job.component, report_path)

    try:
        await asyncio.to_thread(_run)
    except ValueError as exc:
        job.output.append(f"[recon] Auto intel skipped: {exc}")
        job._event.set()
        await _maybe_auto_credentials_and_paths(job, report_path)
        return False
    except Exception as exc:
        job.output.append(f"[!] Auto intel failed: {exc}")
        job._event.set()
        await _maybe_auto_credentials_and_paths(job, report_path)
        return False

    job.output.append("[+] Playbook intel auto-updated")
    job.output.append(
        "[genbounty_progress] "
        + _json.dumps({"type": "recon_auto_done", "phase": "recon"}, ensure_ascii=False)
    )
    job._event.set()
    await _maybe_auto_credentials_and_paths(job, report_path)
    return True


async def _maybe_auto_credentials_and_paths(job: Job, report_path: Path | None) -> None:
    """Extract credentials/paths into component intel inventory when enabled."""
    if not report_path or not report_path.is_file():
        return
    if not (job.site and job.component):
        return
    try:
        from pipeline.credentials_and_paths import maybe_auto_extract_after_assess

        result = await asyncio.to_thread(
            maybe_auto_extract_after_assess, job.site, job.component, report_path
        )
    except Exception as exc:
        job.output.append(f"[!] Credentials/paths extract failed: {exc}")
        job._event.set()
        return
    if result is None:
        return
    if result.get("skipped"):
        job.output.append(
            "[credentials] Inventory already scanned this report (skipped)."
        )
    else:
        job.output.append(
            f"[+] Credentials/paths updated (+{result.get('added', 0)})"
        )
    job._event.set()


async def _ensure_run_assessed(job: Job, suite_path: Path | None = None) -> Path | None:
    """Convert (if needed) and run Analysis for this job's run-log directory."""
    run_dir_raw = str(getattr(job, "run_log_dir", "") or "").strip()
    if not run_dir_raw:
        job.output.append("[!] Analysis skipped: no run log directory on this job.")
        job._event.set()
        return None

    run_dir = Path(run_dir_raw)
    attack_log = run_dir / "attack_log.json"
    run_log = run_dir / "run_log.json"

    if not attack_log.is_file():
        if not run_log.is_file():
            job.output.append(
                "[!] Analysis skipped: no attack_log.json or run_log.json in run directory."
            )
            job._event.set()
            return None
        if suite_path is None or not suite_path.is_file():
            job.output.append(
                "[!] Analysis skipped: cannot convert run log without suite path."
            )
            job._event.set()
            return None
        job.output.append("[*] Converting run log to attack log before assessment…")
        job._event.set()

        def _convert() -> Path:
            _prepare_component_context(job)
            from pipeline.convert_log import convert_run_log

            return convert_run_log(run_log, suite_path)

        try:
            attack_log = await asyncio.to_thread(_convert)
        except Exception as exc:
            job.output.append(f"[!] Convert failed before assessment: {exc}")
            job._event.set()
            return None

    if not _attack_log_needs_assessment(attack_log):
        report_path = attack_log.parent / "pipeline_report.json"
        job.output.append(f"[+] Run already assessed ({report_path.parent.name})")
        job._event.set()
        return report_path

    job.output.append("[*] Running security assessment…")
    job._event.set()
    return await _run_assess_attack_log_in_thread(job, attack_log)


async def _after_assessed_run(job: Job, suite_path: Path | None = None) -> Path | None:
    """Assess when requested, then optional export and playbook intel refresh."""
    import json as _json

    if _is_cancelled(job):
        return None

    report_path: Path | None = None
    assessed_this_call = False
    if _job_wants_assess(job):
        report_path = await _ensure_run_assessed(job, suite_path)
        assessed_this_call = report_path is not None
    if _is_cancelled(job):
        return report_path
    if report_path is None:
        report_path = _pipeline_report_for_job(job)
    # Only promote elite from this job's assess / run-log report - never from an
    # unrelated newest component report when assess was not requested.
    elite_report: Path | None = None
    if assessed_this_call and report_path is not None:
        elite_report = report_path
    else:
        run_dir = str(getattr(job, "run_log_dir", "") or "").strip()
        if (
            run_dir
            and report_path is not None
            and report_path.is_file()
        ):
            try:
                if report_path.resolve().is_relative_to(Path(run_dir).resolve()):
                    elite_report = report_path
            except (OSError, ValueError):
                if str(report_path).startswith(run_dir):
                    elite_report = report_path
    if elite_report is not None:
        playbook_id = ""
        strategy = ""
        if suite_path is not None and suite_path.is_file():
            try:
                suite_data = _json.loads(suite_path.read_text(encoding="utf-8"))
                if isinstance(suite_data, dict):
                    playbook_id = str(suite_data.get("playbook_id") or "").strip()
                    strategy = str(suite_data.get("strategy") or "").strip()
            except Exception:
                playbook_id = ""
                strategy = ""
        if not playbook_id:
            playbook_id = str(
                job.params.get("playbook_id") or job.params.get("playbook") or ""
            ).strip()
        if not strategy:
            strategy = str(job.params.get("strategy") or "").strip()
        _maybe_update_elite_after_assess(
            job,
            elite_report,
            playbook_id=playbook_id,
            strategy=strategy,
        )
    _maybe_export_latest_assessed_report(job)
    await _auto_recon_from_report(job, report_path)
    return report_path


async def _pre_enhance_assess_latest_run(job: Job, playbook_id: str, strategy: str) -> None:
    """Assess the latest matching run before closed-loop enhancement when needed."""
    attack_log = _find_latest_attack_log_for_play(job.site, job.component, playbook_id, strategy)
    if attack_log is None:
        job.output.append(
            f"[enhance] No prior run for {playbook_id}/{strategy}; "
            "enhancement will start open-loop until this job produces an assessed run."
        )
        job._event.set()
        return

    report_path = attack_log.parent / "pipeline_report.json"

    if not _attack_log_needs_assessment(attack_log):
        job.output.append(
            f"[enhance] Prior run already assessed ({attack_log.parent.name}); "
            "using existing pipeline_report.json for enhancement."
        )
        job._event.set()
    else:
        job.output.append(
            f"[enhance] Running Analysis on latest run ({attack_log.parent.name}) "
            "before enhancement…"
        )
        job._event.set()
        report_path = await _run_assess_attack_log_in_thread(job, attack_log)
        if report_path:
            _auto_export_after_assess(job, [report_path])
            job.output.append(f"[+] Pre-enhance assessment complete: {report_path.name}")
        else:
            job.output.append(
                "[!] Pre-enhance assessment failed; enhancement may run open-loop."
            )
            job._event.set()
            return

    if report_path and report_path.is_file():
        _maybe_update_elite_after_assess(
            job, report_path, playbook_id=playbook_id, strategy=strategy
        )
        await _auto_recon_from_report(job, report_path)


def _resolve_security_assess_logs(job: Job) -> list[Path]:
    """Single attack_log, attack_logs list, or time_window batch."""
    time_window = (job.params.get("time_window") or "").strip()
    if time_window:
        if not (job.site and job.component):
            raise ValueError("time_window assessment requires site and component context")
        logs = _attack_logs_in_window(job.site, job.component, time_window)
        label = _time_window_label(time_window)
        if not logs:
            print(f"[!] No attack logs found for {label}")
        else:
            print(f"[*] Batch assessment ({label}): {len(logs)} log(s)")
        return logs

    attack_logs = job.params.get("attack_logs")
    if isinstance(attack_logs, list) and attack_logs:
        paths: list[Path] = []
        for raw in attack_logs:
            cl_path = Path(str(raw))
            if not cl_path.is_absolute():
                cl_path = _root / cl_path
            paths.append(cl_path)
        print(f"[*] Batch assessment: {len(paths)} log(s)")
        return paths

    attack_log = job.params.get("attack_log", "")
    if not attack_log:
        raise ValueError("No attack_log or time_window specified")
    cl_path = Path(attack_log)
    if not cl_path.is_absolute():
        cl_path = _root / cl_path
    return [cl_path]


def _assess_attack_log(cl_path: Path) -> Path:
    """Run security assessment on one attack log; write pipeline_report.json."""
    import importlib.util
    import json as _json

    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    rla_file = _root / "risk-level-agent" / "risk_level_agent.py"
    if rla_file.exists() and "risk_level_agent" not in sys.modules:
        spec = importlib.util.spec_from_file_location("risk_level_agent", rla_file)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules["risk_level_agent"] = mod
            spec.loader.exec_module(mod)

    from pipeline.security_assess import run_security_assessment

    if not cl_path.exists():
        raise FileNotFoundError(f"Attack log not found: {cl_path}")

    print("[*] Running security assessment")
    risk_results = run_security_assessment(cl_path)

    log_data = _json.loads(cl_path.read_text(encoding="utf-8"))
    all_log_results = log_data.get("results", [])
    attack_by_id = {r["id"]: r for r in all_log_results if "id" in r}
    for r in risk_results:
        cl_entry = attack_by_id.get(r.get("id", ""), {})
        for fld in (
            "description",
            "expected_behavior",
            "status",
            "ok",
            "error",
            "strategy",
            "prior_turns",
            "turns",
            "capture_id",
        ):
            if fld not in r:
                r[fld] = cl_entry.get(fld)

    from pipeline.response_html import enrich_adversarial_results_with_response_html

    enrich_adversarial_results_with_response_html(risk_results)

    category_rollup = _category_rollup_from_results(risk_results)

    from datetime import datetime as _dt

    ts = _dt.now().strftime("%Y-%m-%dT%H-%M-%S")
    report = {
        "timestamp": ts,
        "playbook": log_data.get("playbook", log_data.get("framework", "")),
        "playbook_id": log_data.get("playbook_id", ""),
        "source_file": log_data.get("source_file", ""),
        "run_log_dir": str(cl_path.parent),
        "attack_log": str(cl_path),
        "adversarial_results": risk_results,
        "category_rollup": category_rollup,
    }
    target_ctx = log_data.get("target_context")
    if isinstance(target_ctx, dict) and target_ctx.get("source"):
        report["target_context"] = target_ctx
    else:
        from pipeline.recon_context import load_recon_for_assessment, recon_provenance

        recon, _, _ = load_recon_for_assessment(cl_path)[:3]
        if recon:
            report["target_context"] = recon_provenance(recon)
    if log_data.get("strategy"):
        report["strategy"] = log_data["strategy"]
    report_path = cl_path.parent / "pipeline_report.json"
    report_path.write_text(_json.dumps(report, indent=2), encoding="utf-8")
    print("[+] Pipeline report")
    print(f"[+] Assessed: {len(risk_results)}")
    for m, level in sorted(category_rollup.items()):
        print(f"  {m[:60]}: {level}")
    return report_path


def _category_rollup_from_results(risk_results: list) -> dict[str, str]:
    """Per-category worst severity across assessed prompts."""
    from pipeline.report import category_rollup_from_results

    return category_rollup_from_results(risk_results)


def list_jobs() -> list[dict]:
    return [j.to_dict() for j in _jobs.values()]


def get_job(job_id: str) -> Job | None:
    return _jobs.get(job_id)


async def stream_job(job_id: str):
    """Async generator yielding SSE-formatted lines as they appear."""
    job = _jobs.get(job_id)
    if not job:
        return
    # ``cursor`` is an absolute line index (total lines ever produced). The
    # buffer may evict old lines, so map to a live slot via ``dropped``.
    cursor = 0
    while True:
        dropped = getattr(job.output, "dropped", 0)
        if cursor < dropped:
            cursor = dropped
        while cursor - getattr(job.output, "dropped", 0) < len(job.output):
            dropped = getattr(job.output, "dropped", 0)
            if cursor < dropped:
                cursor = dropped
                continue
            # Embed any residual newlines as separate SSE data lines so the
            # EventSource parser receives a single logical event per line.
            text = job.output[cursor - dropped].replace("\n", "\ndata: ")
            yield f"data: {text}\n\n"
            cursor += 1
        if job.status in ("done", "failed", "cancelled"):
            yield f"event: done\ndata: {job.status}\n\n"
            return
        job._event.clear()
        try:
            await asyncio.wait_for(job._event.wait(), timeout=30.0)
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"


async def send_stdin(job_id: str, text: str) -> bool:
    """Write text to a subprocess job's stdin. Returns True if sent."""
    job = _jobs.get(job_id)
    if not job or not job._process or job._process.stdin is None:
        return False
    try:
        job._process.stdin.write(text.encode())
        await job._process.stdin.drain()
        return True
    except Exception:
        return False


async def cancel_job(job_id: str) -> bool:
    job = _jobs.get(job_id)
    if not job or job.status not in ("pending", "running", "awaiting_theory"):
        return False
    job.status = "cancelled"
    proc = job._process
    if proc is not None and proc.returncode is None:
        try:
            proc.terminate()
        except Exception:
            pass
        # Kill immediately so fleet/generate loops cannot keep streaming a
        # stubborn generator child after Cancel is clicked.
        try:
            proc.kill()
        except Exception:
            pass
    if job._task and not job._task.done():
        job._task.cancel()
    job._theory_event.set()
    job._event.set()
    return True


def _is_cancelled(job: Job) -> bool:
    return job.status == "cancelled"


async def respond_to_enhance_theory(
    job_id: str,
    *,
    accept: bool,
    reason: str = "",
) -> bool:
    """Accept or reject the pending enhancement theory for an enhance_loop job."""
    job = _jobs.get(job_id)
    if not job or job.status != "awaiting_theory":
        return False
    theory = str((job.theory_state or {}).get("theory") or "").strip()
    if accept:
        job.theory_decision = {"action": "accept", "theory": theory}
    else:
        job.theory_decision = {"action": "reject", "reason": str(reason or "").strip()}
    job._theory_event.set()
    job._event.set()
    return True


def _auto_accept_enhance_theory(job: Job) -> bool:
    """True when Enhance Auto-run should skip the interactive theory modal."""
    raw = job.params.get("auto_accept_theory")
    if raw is None:
        # Backward-compatible: multi-round enhance loops are unattended.
        try:
            return int(job.params.get("max_rounds") or 1) > 1
        except (TypeError, ValueError):
            return False
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _auto_escalate_enhance_theory(job: Job) -> bool:
    """True for multi-round Auto-run - theory must escalate beyond proven canaries."""
    try:
        return int(job.params.get("max_rounds") or 1) > 1
    except (TypeError, ValueError):
        return False


_DEFAULT_ENHANCE_STOP_LEVELS = frozenset({"critical", "high"})
_ALLOWED_ENHANCE_STOP_LEVELS = frozenset({"critical", "high", "medium"})


def _normalize_enhance_stop_levels(raw: object) -> set[str]:
    """Parse Auto-run stop severities; default high+critical when empty/invalid."""
    if isinstance(raw, str):
        candidates = [part.strip() for part in raw.split(",")]
    elif isinstance(raw, (list, tuple, set, frozenset)):
        candidates = list(raw)
    else:
        candidates = []
    levels = {
        str(s).strip().lower()
        for s in candidates
        if str(s).strip().lower() in _ALLOWED_ENHANCE_STOP_LEVELS
    }
    return levels or set(_DEFAULT_ENHANCE_STOP_LEVELS)


def _severity_meets_stop_levels(worst: str, stop_levels: set[str]) -> bool:
    """True when ``worst`` is at least as severe as any selected stop level.

    Selecting Medium stops on medium/high/critical; High stops on high/critical;
    Critical alone continues past high findings.
    """
    level = str(worst or "").strip().lower()
    if level not in _SEVERITY_ORDER:
        return False
    thresholds = [s for s in stop_levels if s in _SEVERITY_ORDER]
    if not thresholds:
        return False
    worst_idx = _SEVERITY_ORDER.index(level)
    # Least-severe selected threshold (highest index among stop levels).
    threshold_idx = max(_SEVERITY_ORDER.index(s) for s in thresholds)
    return worst_idx <= threshold_idx


def _append_enhance_theory_output(
    job: Job,
    theory: str,
    *,
    rnd: int,
    status: str,
) -> None:
    """Print the full enhancement theory into Experiment Output."""
    body = str(theory or "").strip()
    label = {
        "auto_accepted": "Auto-accepted enhancement theory",
        "proposed": "Proposed enhancement theory",
        "accepted": "Accepted enhancement theory",
        "rejected": "Rejected enhancement theory",
    }.get(status, "Enhancement theory")
    job.output.append(f"[enhance] === {label} (round {rnd}) ===")
    if body:
        for line in body.splitlines() or [body]:
            job.output.append(line)
    else:
        job.output.append("(empty theory)")
    job.output.append(f"[enhance] === End theory (round {rnd}) ===")


def _theory_prefer_subset_of_banned(
    theory: str,
    *,
    site: str,
    component: str,
    playbook_id: str,
    strategy: str,
) -> bool:
    """True when non-empty Machine-plan prefer_techniques ⊆ outcome-banned names."""
    gen_dir = _root / "generate-tests"
    if str(gen_dir) not in sys.path:
        sys.path.insert(0, str(gen_dir))
    try:
        from enhance_theory import extract_prefer_techniques
        from strategies.prior_results import (
            load_prior_results,
            outcome_banned_technique_names,
        )
    except Exception:
        return False
    prefers = extract_prefer_techniques(theory)
    if not prefers:
        return False
    try:
        prior = load_prior_results(
            site,
            component,
            playbook_id,
            strategy=strategy,
            require_feedback=False,
        )
        banned = {
            str(n).strip().lower()
            for n in (outcome_banned_technique_names(prior) or [])
            if str(n).strip()
        }
    except Exception:
        return False
    return bool(banned) and prefers.issubset(banned)


def _theory_prefers_recycle_recent(
    theory: str,
    *,
    site: str,
    component: str,
    playbook_id: str,
    strategy: str,
    hunt_mode: str = "compliance",
    custom_enhance: str = "",
) -> bool:
    """True when bounty invent/mutate/broaden theory recycles recent Machine-plan prefers."""
    if not _is_bounty_hunt_mode(hunt_mode):
        return False
    gen_dir = _root / "generate-tests"
    if str(gen_dir) not in sys.path:
        sys.path.insert(0, str(gen_dir))
    try:
        from enhance_theory import (
            build_theory_context,
            prefers_recycle_recent,
            recent_burned_prefer_techniques,
            theory_requests_auto_escalate,
            theory_requests_bounty_escalate,
            theory_requests_freeze_channel,
        )
    except Exception:
        return False
    text = str(theory or "")
    # Compliance freeze/escalate and bounty escalate keep channel; skip prefer rotation.
    if theory_requests_freeze_channel(text) or theory_requests_auto_escalate(text):
        return False
    if theory_requests_bounty_escalate(text):
        return False
    try:
        ctx = build_theory_context(
            site,
            component,
            playbook_id,
            strategy,
            custom_enhance=custom_enhance,
        )
        burned = recent_burned_prefer_techniques(ctx)
        registry = list(ctx.get("registry_technique_names") or [])
        return prefers_recycle_recent(text, burned, registry=registry)
    except Exception:
        return False


async def _confirm_enhance_theory(
    job: Job,
    playbook_id: str,
    strategy: str,
    rnd: int,
    *,
    custom_enhance: str = "",
    abandon_accepted: bool = False,
    freeze_completed: bool = False,
    cool_down: bool = False,
    hunt_mode: str = "compliance",
    open_broaden: bool = False,
) -> str | None:
    """Generate enhancement theory; wait for accept unless auto-run auto-accepts."""
    import json as _json

    gen_dir = _root / "generate-tests"
    if str(gen_dir) not in sys.path:
        sys.path.insert(0, str(gen_dir))
    from enhance_theory import (
        build_theory_context,
        custom_overrides_freeze_enabled,
        generate_enhance_theory,
        infer_theory_validation_phase,
        record_accepted_theory,
        record_rejected_theory,
        should_confirm_enhance_theory,
        theory_requests_auto_escalate,
        theory_requests_hard_refusal_adapt,
        validate_enhance_theory_phase,
    )

    custom = str(custom_enhance or "").strip()
    if not should_confirm_enhance_theory(
        job.site, job.component, playbook_id, strategy, custom_enhance=custom
    ):
        job.output.append(
            "[enhance] Step 1/4: no prior assessment/recon feedback yet - "
            "skipping theory; regenerating open-loop."
        )
        job._event.set()
        return None

    job.output.append(
        f"[enhance] Step 1/4: writing enhancement theory "
        f"(methodologist LLM) for {strategy}/{playbook_id}…"
    )
    job._event.set()

    session_rejections: list[dict] = []
    auto_accept = _auto_accept_enhance_theory(job)
    auto_escalate = _auto_escalate_enhance_theory(job)
    abandon = bool(abandon_accepted)
    override_freeze = bool(job.params.get("custom_overrides_freeze"))
    if not override_freeze:
        override_freeze = custom_overrides_freeze_enabled()
    _CRITIQUE_REASON = (
        "Machine plan prefer_techniques are outcome-banned from prior Lows; "
        "choose unused registry mechanisms and a new wrapper family."
    )
    _RECYCLE_REASON = (
        "Machine plan prefer_techniques recycle last accepted plans; "
        "choose unused registry mechanisms (RECENT PREFER BAN)."
    )

    def _phase_fail_reason(phase: str, errors: list[str]) -> str:
        phase_l = str(phase or "").strip().lower()
        detail = "; ".join(errors[:6])
        if phase_l == "hard_refusal":
            return (
                "Theory failed hard-refusal phase validation; set Machine plan "
                "proof_slot_replacement to a phase-1 fragment ask (not the full "
                f"escalation payload). Errors: {detail}"
            )
        if phase_l == "escalate":
            return (
                "Theory failed escalate phase validation; include exact replacement "
                "text / proof_slot_replacement and clone_of ids where required. "
                f"Errors: {detail}"
            )
        if phase_l in {"freeze", "cool_down", "cooldown"}:
            return (
                "Theory failed freeze/cool-down phase validation; cite clone_of ids "
                f"and avoid high-intent dumps. Errors: {detail}"
            )
        return (
            "Theory failed phase validation; rewrite for the active phase rails. "
            f"Errors: {detail}"
        )

    def _generate(
        *,
        previous_theory: str = "",
        rejection_reason: str = "",
    ) -> str:
        try:
            from dotenv import load_dotenv

            load_dotenv(_root / ".config")
            load_dotenv(_root / ".env")
        except ImportError:
            pass
        _prepare_component_context(job)
        # Theory + closed-loop loaders expect feedback semantics; Enhance & Run
        # previously only set this on the generator subprocess env.
        os.environ["GENBOUNTY_FEEDBACK"] = "1"
        return generate_enhance_theory(
            job.site,
            job.component,
            playbook_id,
            strategy,
            session_rejections=session_rejections,
            custom_enhance=custom,
            auto_escalate=auto_escalate and not _is_bounty_hunt_mode(hunt_mode),
            abandon_accepted=abandon,
            stagnant=abandon,
            freeze_completed=bool(freeze_completed),
            cool_down=bool(cool_down),
            custom_overrides_freeze=override_freeze,
            previous_theory=previous_theory,
            rejection_reason=rejection_reason,
            hunt_mode=hunt_mode,
            open_broaden=bool(open_broaden),
        )

    def _phase_for_validation(
        theory_text: str,
    ) -> tuple[str, str, list[str], list[dict], str]:
        """Infer phase + escalation payload + clone/elite ids + attack_objective."""
        from playbooks.playbook_config import (
            get_attack_objective,
            get_escalation_payload,
        )
        from playbooks.registry import load_playbook

        text = str(theory_text or "")
        phase = infer_theory_validation_phase(
            text,
            cool_down=bool(cool_down),
            freeze_completed=bool(freeze_completed),
            auto_escalate=bool(auto_escalate) and not _is_bounty_hunt_mode(hunt_mode),
        )
        esc = ""
        objective = ""
        clone_ids: list[str] = []
        elite_rows: list[dict] = []
        try:
            pb = load_playbook(playbook_id)
            esc = str(get_escalation_payload(pb) or "").strip()
            objective = str(get_attack_objective(pb) or "").strip()
        except Exception:
            esc = ""
            objective = ""
        try:
            ctx = build_theory_context(
                job.site, job.component, playbook_id, strategy, custom_enhance=custom
            )
            if phase == "bounty_mutate" or _is_bounty_hunt_mode(hunt_mode):
                elite_rows = [
                    s
                    for s in (ctx.get("elite_genomes") or [])
                    if isinstance(s, dict) and str(s.get("id") or "").strip()
                ]
                clone_ids = [
                    str(s.get("id") or "").strip()
                    for s in elite_rows
                    if str(s.get("id") or "").strip()
                ]
            else:
                clone_ids = [
                    str(s.get("id") or "").strip()
                    for s in (ctx.get("winning_clone_sources") or [])
                    if str(s.get("id") or "").strip()
                ]
        except Exception:
            clone_ids = []
            elite_rows = []
        return phase, esc, clone_ids, elite_rows, objective

    async def _maybe_self_critique(theory: str) -> str:
        """Regenerate once when prefers are outcome-banned or recycle recent plans."""
        text = str(theory or "")
        if not text.strip():
            return text
        banned_prefers = await asyncio.to_thread(
            _theory_prefer_subset_of_banned,
            text,
            site=job.site,
            component=job.component,
            playbook_id=playbook_id,
            strategy=strategy,
        )
        if banned_prefers:
            job.output.append(
                "[enhance] Theory self-critique: banned prefer_techniques - regenerating once."
            )
            session_rejections.append({"theory": text, "reason": _CRITIQUE_REASON})
            job._event.set()
            return await asyncio.to_thread(
                _generate,
                previous_theory=text,
                rejection_reason=_CRITIQUE_REASON,
            )
        recycled = await asyncio.to_thread(
            _theory_prefers_recycle_recent,
            text,
            site=job.site,
            component=job.component,
            playbook_id=playbook_id,
            strategy=strategy,
            hunt_mode=hunt_mode,
            custom_enhance=custom,
        )
        if not recycled:
            return text
        job.output.append(
            "[enhance] Theory self-critique: recycled prefer_techniques - regenerating once."
        )
        session_rejections.append({"theory": text, "reason": _RECYCLE_REASON})
        job._event.set()
        return await asyncio.to_thread(
            _generate,
            previous_theory=text,
            rejection_reason=_RECYCLE_REASON,
        )

    async def _maybe_phase_validate(
        theory: str,
        *,
        regen_on_fail: bool = True,
        strict_bounty_invent_format: bool = True,
    ) -> tuple[str, list[str]]:
        """Validate phase rails; optionally regenerate once on failure.

        Auto-run passes ``regen_on_fail=False`` and soft invent format so Step 1
        stays one theory LLM call (plus rare self-critique).
        """
        text = str(theory or "")
        if not text.strip():
            return text, []
        phase, esc, clone_ids, elite_rows, attack_objective = await asyncio.to_thread(
            _phase_for_validation, text
        )
        if not phase:
            return text, []
        require_tripwire = bool(
            phase == "bounty_invent"
            and _is_bounty_hunt_mode(hunt_mode)
            and (
                bool(abandon)
                or bool(open_broaden)
                or not clone_ids
                or (os.getenv("GENBOUNTY_FORCE_BREAKTHROUGH") or "").strip() == "1"
            )
        )
        errors = validate_enhance_theory_phase(
            text,
            phase=phase,
            escalation_payload=esc,
            clone_ids=clone_ids,
            require_tripwire_drop=require_tripwire,
            elite_genomes=elite_rows,
            attack_objective=attack_objective,
            strict_bounty_invent_format=strict_bounty_invent_format,
        )
        if not errors:
            return text, []
        if not regen_on_fail:
            job.output.append(
                "[enhance] Theory phase validation soft warnings (auto-accept, "
                "no regen): "
                + "; ".join(errors[:4])
            )
            job._event.set()
            return text, list(errors)
        job.output.append(
            "[enhance] Theory phase validation failed: "
            + "; ".join(errors[:4])
            + " - regenerating once."
        )
        reason = _phase_fail_reason(phase, errors)
        session_rejections.append({"theory": text, "reason": reason})
        job._event.set()
        retry = await asyncio.to_thread(
            _generate,
            previous_theory=text,
            rejection_reason=reason,
        )
        retry = await _maybe_self_critique(retry)
        if not str(retry or "").strip():
            return text, list(errors)
        # Re-infer from the retry alone - do not sticky the prior phase.
        phase2, esc2, clone_ids2, elite_rows2, attack_objective2 = await asyncio.to_thread(
            _phase_for_validation, retry
        )
        if not phase2:
            return str(retry), []
        require_tripwire2 = bool(
            phase2 == "bounty_invent"
            and _is_bounty_hunt_mode(hunt_mode)
            and (
                bool(abandon)
                or bool(open_broaden)
                or not clone_ids2
                or (os.getenv("GENBOUNTY_FORCE_BREAKTHROUGH") or "").strip() == "1"
            )
        )
        errors2 = validate_enhance_theory_phase(
            retry,
            phase=phase2,
            escalation_payload=esc2,
            clone_ids=clone_ids2,
            require_tripwire_drop=require_tripwire2,
            elite_genomes=elite_rows2,
            attack_objective=attack_objective2,
            strict_bounty_invent_format=strict_bounty_invent_format,
        )
        return str(retry), errors2

    theory = await asyncio.to_thread(_generate)
    theory = await _maybe_self_critique(theory)
    theory, phase_errors = await _maybe_phase_validate(
        theory,
        regen_on_fail=not auto_accept,
        strict_bounty_invent_format=not auto_accept,
    )

    if auto_accept:
        # Unattended Auto-run / Run pipeline: one-shot theory (no outer regen loop).
        # Soft invent-format warnings may remain; accept and advance immediately.
        _AUTO_ACCEPT_ATTEMPTS = 1
        attempt = 1
        accepted = str(theory or "").strip()
        if not accepted:
            return None
        if phase_errors:
            job.output.append(
                "[enhance] Auto-accepting after "
                f"{attempt} attempt(s) despite phase validation: "
                + "; ".join(phase_errors[:4])
            )
        accepted_is_escalate = theory_requests_auto_escalate(accepted)
        accepted_is_hard_refusal = theory_requests_hard_refusal_adapt(accepted)
        job.theory_state = {
            "round": rnd,
            "theory": accepted,
            "status": "auto_accepted",
            "job_id": job.id,
            "phase_validation_failed": bool(phase_errors),
            "phase_validation_errors": list(phase_errors[:8]) if phase_errors else [],
            # Unstick freeze when we accepted a non-escalate / hard-refusal theory
            # after escalate-rail failures (freeze_completed would otherwise stick).
            "reset_freeze_completed": bool(
                accepted_is_hard_refusal
                or (phase_errors and not accepted_is_escalate)
            ),
        }
        await asyncio.to_thread(
            record_accepted_theory,
            job.site,
            job.component,
            playbook_id,
            strategy,
            accepted,
            round_num=rnd,
            job_id=job.id,
        )
        _append_enhance_theory_output(
            job, accepted, rnd=rnd, status="auto_accepted"
        )
        job.output.append(
            "[enhance] Auto-accepted (Enhance and Auto-Run) - regenerating prompts…"
        )
        job.output.append(
            "[genbounty_progress] "
            + _json.dumps(
                {
                    "type": "theory_auto_accepted",
                    "phase": "theory",
                    "enhance_phase": _resolve_enhance_phase(
                        theory_text=accepted,
                        cool_down=bool(cool_down),
                        hunt_mode=hunt_mode,
                    ),
                    "thesis": _playbook_enhancement_thesis(playbook_id),
                    "round": rnd,
                    "job_id": job.id,
                    "hunt_mode": _normalize_hunt_mode(hunt_mode),
                },
                ensure_ascii=False,
            )
        )
        job._event.set()
        return accepted

    if phase_errors:
        job.output.append(
            "[enhance] Phase validation warnings: " + "; ".join(phase_errors[:4])
        )
    _append_enhance_theory_output(job, theory, rnd=rnd, status="proposed")
    job.output.append(
        f"[enhance] Round {rnd} theory printed above - awaiting confirmation in the modal…"
    )
    job._event.set()

    while True:
        if _is_cancelled(job):
            return None
        job.theory_state = {
            "round": rnd,
            "theory": theory,
            "status": "pending",
            "job_id": job.id,
        }
        job.theory_decision = None
        job.status = "awaiting_theory"
        job.output.append(
            "[genbounty_progress] "
            + _json.dumps(
                {
                    "type": "theory_review",
                    "phase": "theory",
                    "enhance_phase": _resolve_enhance_phase(
                        theory_text=theory,
                        cool_down=bool(cool_down),
                        hunt_mode=hunt_mode,
                    ),
                    "thesis": _playbook_enhancement_thesis(playbook_id),
                    "round": rnd,
                    "theory": theory,
                    "job_id": job.id,
                    "hunt_mode": _normalize_hunt_mode(hunt_mode),
                },
                ensure_ascii=False,
            )
        )
        job._event.set()

        job._theory_event.clear()
        await job._theory_event.wait()
        if _is_cancelled(job):
            return None

        decision = job.theory_decision or {}
        action = str(decision.get("action") or "").strip().lower()
        if action == "accept":
            accepted = str(decision.get("theory") or theory).strip()
            job.status = "running"
            accepted_is_hard_refusal = theory_requests_hard_refusal_adapt(accepted)
            job.theory_state = {
                **job.theory_state,
                "status": "accepted",
                "theory": accepted,
                "reset_freeze_completed": bool(accepted_is_hard_refusal),
            }
            await asyncio.to_thread(
                record_accepted_theory,
                job.site,
                job.component,
                playbook_id,
                strategy,
                accepted,
                round_num=rnd,
                job_id=job.id,
            )
            if accepted != str(theory or "").strip():
                _append_enhance_theory_output(
                    job, accepted, rnd=rnd, status="accepted"
                )
            job.output.append("[enhance] Theory accepted - regenerating prompts…")
            job._event.set()
            return accepted

        if action == "reject":
            reason = str(decision.get("reason") or "").strip()
            job.status = "running"
            session_rejections.append({"theory": theory, "reason": reason})
            await asyncio.to_thread(
                record_rejected_theory,
                job.site,
                job.component,
                playbook_id,
                strategy,
                theory,
                reason,
                round_num=rnd,
                job_id=job.id,
            )
            if reason:
                job.output.append(
                    f"[enhance] Theory rejected ({reason[:120]}) - proposing a new theory…"
                )
            else:
                job.output.append("[enhance] Theory rejected - proposing a new theory…")
            job._event.set()
            theory = await asyncio.to_thread(_generate)
            theory = await _maybe_self_critique(theory)
            _append_enhance_theory_output(job, theory, rnd=rnd, status="proposed")
            continue

        # Spurious wake - wait again.
        continue


def _set_final_status(job: Job, status: str) -> None:
    if not _is_cancelled(job):
        job.status = status


def _emit_job_progress(job: Job, payload: dict[str, Any]) -> None:
    """Append a structured progress line for the UI status bar / SSE clients."""
    import json as _json

    job.output.append(
        "[genbounty_progress] " + _json.dumps(payload, ensure_ascii=False)
    )
    job._event.set()


# ---------------------------------------------------------------------------
# Job runners
# ---------------------------------------------------------------------------

async def _run_subprocess_job(
    job: Job,
    cmd: list[str],
    *,
    cwd: str | None = None,
    env: dict | None = None,
    set_status: bool = True,
):
    """Run a command as an async subprocess, streaming stdout line by line."""
    if _is_cancelled(job):
        return 1
    # Never resurrect a cancelled job (enhance loop uses set_status=False).
    if not _is_cancelled(job):
        job.status = "running"
        job._event.set()
    proc: asyncio.subprocess.Process | None = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.PIPE,
            cwd=cwd or str(_root),
            env=env,
        )
        job._process = proc
        assert proc.stdout
        async for raw_line in proc.stdout:
            if _is_cancelled(job):
                break
            line = raw_line.decode(errors="replace").rstrip("\n")
            job.output.append(line)
            job._event.set()
        if _is_cancelled(job) and proc.returncode is None:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except Exception:
                pass
            return 1
        await proc.wait()
        if _is_cancelled(job):
            return 1
        if set_status:
            _set_final_status(job, "done" if proc.returncode == 0 else "failed")
        return proc.returncode
    except asyncio.CancelledError:
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass
        _set_final_status(job, "cancelled")
        raise
    except Exception as exc:
        job.output.append(f"[error] {exc}")
        if set_status:
            _set_final_status(job, "failed")
        return 1
    finally:
        job._process = None
        job._event.set()


async def _run_thread_job(job: Job, fn, *args: Any, **kwargs: Any):
    """Run a blocking function in a thread, capturing its stdout."""
    if _is_cancelled(job):
        return None
    if not _is_cancelled(job):
        job.status = "running"
        job._event.set()

    def _wrapped():
        cap = _OutputCapture(job)
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = cap  # type: ignore[assignment]
        sys.stderr = cap  # type: ignore[assignment]
        try:
            return fn(*args, **kwargs)
        finally:
            sys.stdout, sys.stderr = old_out, old_err

    try:
        await asyncio.to_thread(_wrapped)
        if _is_cancelled(job):
            _set_final_status(job, "cancelled")
        else:
            job.status = "done"
    except asyncio.CancelledError:
        job.status = "cancelled"
    except Exception as exc:
        job.output.append(f"[error] {exc}")
        job.status = "failed"
    finally:
        job._event.set()


# ---------------------------------------------------------------------------
# Public start_job dispatcher
# ---------------------------------------------------------------------------

async def start_job(job_type: str, site: str, component: str, params: dict | None = None) -> Job:
    params = params or {}
    _evict_finished_jobs()
    job = Job(
        id=uuid.uuid4().hex[:12],
        type=job_type,
        status="pending",
        site=site,
        component=component,
        params=params,
    )
    _jobs[job.id] = job

    # Community Premium gates (defense in depth before task spawn).
    def _fail_closed_premium(feature: str) -> None:
        detail = (
            f"{feature.replace('_', ' ').title()} is available in Genbounty LLM Hunter "
            "Premium. See https://genbounty.com/llm-hunter"
        )
        try:
            job.output.append(f"[!] {detail}")
        except Exception:
            pass
        job.status = "failed"
        if hasattr(job, "_event") and job._event is not None:
            try:
                job._event.set()
            except Exception:
                pass

    try:
        from pipeline.edition import (
            fail_job_premium,
            is_premium_strategy,
        )

        if job_type == "credentials_from_reports":
            fail_job_premium(job, "intel")
            return job
        if job_type == "enhance_loop":
            hm = str(params.get("hunt_mode") or "").strip().lower().replace("-", "_")
            if hm in ("open_hunt", "open", "openhunt"):
                fail_job_premium(job, "open_hunt")
                return job
        if job_type in ("generate", "run_tests", "enhance_loop"):
            strat = str(params.get("strategy") or "").strip()
            if is_premium_strategy(strat):
                fail_job_premium(job, "adaptive")
                return job
            if job_type == "run_tests":
                suite = str(params.get("suite") or "")
                if suite:
                    from browser_bot.submit import is_adaptive_suite

                    if is_adaptive_suite(suite) and is_premium_strategy("adaptive"):
                        fail_job_premium(job, "adaptive")
                        return job
    except ImportError:
        # Fail closed if edition helpers are missing from the package.
        if job_type == "credentials_from_reports":
            _fail_closed_premium("intel")
            return job
        if job_type == "enhance_loop":
            hm = str(params.get("hunt_mode") or "").strip().lower().replace("-", "_")
            if hm in ("open_hunt", "open", "openhunt"):
                _fail_closed_premium("open_hunt")
                return job
        if job_type in ("generate", "run_tests", "enhance_loop"):
            strat = str(params.get("strategy") or "").strip().lower().replace("-", "_")
            if strat == "adaptive":
                _fail_closed_premium("adaptive")
                return job
            if job_type == "run_tests":
                suite = str(params.get("suite") or "")
                if suite and "/adaptive/" in suite.replace("\\", "/"):
                    _fail_closed_premium("adaptive")
                    return job

    if job_type == "generate":
        job._task = asyncio.create_task(_start_generate(job))
    elif job_type == "login":
        job._task = asyncio.create_task(_start_login(job))
    elif job_type == "discover":
        job._task = asyncio.create_task(_start_discover(job))
    elif job_type == "manual_discover":
        job._task = asyncio.create_task(_start_manual_discover(job))
    elif job_type == "api_discover":
        job._task = asyncio.create_task(_start_api_discover(job))
    elif job_type == "recon":
        job._task = asyncio.create_task(_start_recon(job))
    elif job_type == "run_tests":
        job._task = asyncio.create_task(_start_run_tests(job))
    elif job_type == "enhance_loop":
        job._task = asyncio.create_task(_start_enhance_loop(job))
    elif job_type == "recon_round":
        job._task = asyncio.create_task(_start_recon_round(job))
    elif job_type == "recon_from_report":
        job._task = asyncio.create_task(_start_recon_from_report(job))
    elif job_type == "credentials_from_reports":
        job._task = asyncio.create_task(_start_credentials_from_reports(job))
    elif job_type == "sample_request":
        job._task = asyncio.create_task(_start_sample_request(job))
    elif job_type == "security_assess":
        job._task = asyncio.create_task(_start_security_assess(job))
    elif job_type == "export":
        job._task = asyncio.create_task(_start_export(job))
    elif job_type == "clear_cache":
        job._task = asyncio.create_task(_start_clear_cache(job))
    elif job_type == "nuke":
        job._task = asyncio.create_task(_start_nuke(job))
    elif job_type == "prompt_attributes":
        job._task = asyncio.create_task(_start_prompt_attributes(job))
    else:
        job.status = "failed"
        job.output.append(f"[error] Unknown job type: {job_type}")
        job._event.set()

    return job


# ---------------------------------------------------------------------------
# Per-type starters
# ---------------------------------------------------------------------------

async def _start_generate(job: Job):
    generator_py = _root / "generate-tests" / "generator.py"
    requested_strategy = str(job.params.get("strategy") or "").strip()
    multimodal_requested = bool(job.params.get("multimodal"))
    strategy = "multimodal" if multimodal_requested else requested_strategy
    from playbooks.registry import default_playbook_id
    playbook = job.params.get("playbook") or default_playbook_id()
    if not playbook:
        job.output.append("[!] No play selected. Create a play first.")
        job.status = "failed"
        return
    if strategy in ("", "__campaign__", "__recommended__"):
        job.output.append(
            "[!] Select a concrete strategy or All strategies "
            "(recommended campaigns were removed)."
        )
        job.status = "failed"
        job._event.set()
        return

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    if job.site:
        env["GENBOUNTY_SITE"] = job.site
    if job.component:
        env["GENBOUNTY_COMPONENT"] = job.component
    if playbook:
        from playbooks.registry import normalize_playbook_id

        env["GENBOUNTY_PLAYBOOK"] = normalize_playbook_id(str(playbook))
    if strategy and strategy not in ("", "__all__", "multimodal", "__campaign__", "__recommended__"):
        env["GENBOUNTY_STRATEGY"] = str(strategy).strip().replace("-", "_")

    # Auto-enable closed-loop feedback when a prior assessed report exists.
    env["GENBOUNTY_FEEDBACK"] = "0"
    try:
        gen_tests = _root / "generate-tests"
        if str(gen_tests) not in sys.path:
            sys.path.insert(0, str(gen_tests))
        from strategies.generation_mode import auto_feedback_enabled
        from strategies.prior_results import has_assessed_report
        from playbooks.registry import load_playbook, normalize_playbook_id

        playbook_id = normalize_playbook_id(playbook)
        strat_for_report = strategy.replace("-", "_") if strategy not in (
            "__all__", "multimodal"
        ) else None
        rubric = load_playbook(playbook_id) or {}
        if (
            auto_feedback_enabled()
            and job.site
            and job.component
            and has_assessed_report(
                job.site,
                job.component,
                playbook_id,
                strategy=strat_for_report,
                playbook_rubric=rubric,
            )
        ):
            env["GENBOUNTY_FEEDBACK"] = "1"
            job.output.append(
                "[generate] Prior assessment found - closed-loop feedback enabled"
            )
    except Exception as exc:
        logging.debug("Auto-feedback check skipped: %s", exc)

    if multimodal_requested and requested_strategy:
        env["GENBOUNTY_MULTIMODAL_BASE_STRATEGY"] = str(requested_strategy)

    _apply_gen_auto_apply_env(job, env)

    def _build_cmd(strat: str) -> list[str]:
        cmd = [sys.executable, "-u", str(generator_py), "--strategy", strat, "--playbook", playbook]
        if job.site and job.component:
            cmd += ["--site", job.site, "--component", job.component]
        return cmd

    def _resolve_strategies() -> list[str]:
        if strategy == "__all__":
            from playbooks.campaign import resolve_generate_strategies
            return resolve_generate_strategies(
                "__all__", playbook, job.site or "", job.component or ""
            )
        return [strategy]

    if multimodal_requested:
        job.output.append(
            f"[generate] Multimodal enabled; using artifact-backed multimodal generation "
            f"(requested strategy={requested_strategy}, playbook={playbook})"
        )
        if requested_strategy not in ("", "__all__", "multimodal"):
            job.output.append(
                f"[generate] Applying multimodal style profile from selected strategy: {requested_strategy}"
            )

    # Block multi-turn strategies on stateless / no-history API targets.
    from playbooks.campaign import assert_strategy_allowed_for_target

    gate_err = assert_strategy_allowed_for_target(
        strategy if not multimodal_requested else "multimodal",
        site=job.site or "",
        component=job.component or "",
        playbook_id=str(playbook),
    )
    if gate_err:
        job.output.append(f"[!] {gate_err}")
        job.status = "failed"
        job._event.set()
        return

    if strategy == "__all__":
        job.status = "running"
        job.output.append(f"[generate] Starting all-strategies generation for playbook={playbook}")
        job.output.append("[generate] Resolving strategy plan and target context...")
        job._event.set()
        strategies = _resolve_strategies()
        if not strategies:
            job.output.append(
                "[!] No strategies available for this target "
                "(multi-turn strategies are skipped without conversation history)."
            )
            job.status = "failed"
            job._event.set()
            return
        total = len(strategies)
        try:
            from playbooks.campaign import MULTI_TURN_STRATEGIES, detect_capabilities
            caps = detect_capabilities(
                job.site or "", job.component or "", playbook_id=str(playbook)
            )
            if not caps.get("multi_turn", True):
                skipped = sorted(MULTI_TURN_STRATEGIES)
                job.output.append(
                    "[generate] Target has no conversation history - skipping "
                    f"multi-turn strategies: {', '.join(skipped)}"
                )
                job._event.set()
            for i, strat in enumerate(strategies, 1):
                if _is_cancelled(job):
                    break
                job.output.append(f"[{i}/{total}] Generating (all): strategy={strat}, playbook={playbook}...")
                job.output.append(
                    "[generate] Running category experts, judge synthesis, "
                    "dedup/backfill, and suite write for this strategy..."
                )
                job._event.set()
                proc = await asyncio.create_subprocess_exec(
                    *_build_cmd(strat),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    stdin=asyncio.subprocess.PIPE,
                    cwd=str(_root),
                    env=env,
                )
                job._process = proc
                assert proc.stdout
                try:
                    async for raw_line in proc.stdout:
                        if _is_cancelled(job):
                            break
                        line = raw_line.decode(errors="replace").rstrip("\n")
                        job.output.append(line)
                        job._event.set()
                    await proc.wait()
                finally:
                    if proc.returncode is None:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    job._process = None
                if _is_cancelled(job):
                    break
                if proc.returncode != 0:
                    job.output.append(f"[!] Generator exited {proc.returncode} for {strat}/{playbook}")
                elif strat == "multimodal":
                    _set_final_status(job, "done")
                    _materialize_multimodal_output(job, strat, playbook)
                else:
                    job.output.append(f"[generate] Strategy complete: {strat}/{playbook}")
            if _is_cancelled(job):
                job.output.append("[generate] Cancelled.")
                _set_final_status(job, "cancelled")
            else:
                job.output.append(f"[+] All {total} strategies complete for playbook={playbook} (all).")
                _set_final_status(job, "done")
        except asyncio.CancelledError:
            job.output.append("[generate] Cancelled.")
            job.status = "cancelled"
        except Exception as exc:
            job.output.append(f"[error] {exc}")
            _set_final_status(job, "failed")
        finally:
            job._event.set()
    else:
        job.output.append(f"[generate] Starting strategy={strategy}, playbook={playbook}")
        job.output.append("[generate] Running category experts, judge synthesis, dedup/backfill, and suite write...")
        job._event.set()
        await _run_subprocess_job(job, _build_cmd(strategy), env=env)
        _materialize_multimodal_output(job, strategy, playbook)


def _coerce_login_url(value: object) -> str:
    """Normalize login URL from job params (UI may send a string or nested object)."""
    raw = ""
    if isinstance(value, str):
        raw = value.strip()
    elif isinstance(value, dict):
        for key in ("url", "login_url", "start_url"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                raw = nested.strip()
                break
    elif value:
        raw = str(value).strip()
    if not raw:
        return ""
    try:
        from browser_bot.sites import normalize_target_access_url

        return normalize_target_access_url(raw) or raw
    except Exception:
        return raw


async def _start_login(job: Job):
    worker = _root / "web" / "login_worker.py"
    url = _coerce_login_url(job.params.get("url", ""))
    if not url:
        job.output.append("[!] No URL provided for login")
        job.status = "failed"
        job._event.set()
        return
    if str(_root / "browser-bot") not in sys.path:
        sys.path.insert(0, str(_root / "browser-bot"))
    from browser_bot.auth import is_google_login_target, login_cdp_output_lines
    from pipeline.component_settings import parse_browser_config_py

    use_cdp = bool(job.params.get("use_cdp")) or bool(
        parse_browser_config_py().get("USE_CDP_BROWSER")
    )
    if use_cdp or is_google_login_target(job.site or "", url):
        for line in login_cdp_output_lines(
            job.site or "",
            url,
            job.component or None,
            auto_launch=use_cdp,
            google_blocked=is_google_login_target(job.site or "", url) and not use_cdp,
        ):
            job.output.append(line)
        job._event.set()
    cmd = [sys.executable, "-u", str(worker), job.site, job.component, url]
    if use_cdp:
        cmd.append("--use-cdp")
    await _run_subprocess_job(job, cmd)


async def _start_discover(job: Job):
    worker = _root / "web" / "discover_worker.py"
    cmd = [sys.executable, "-u", str(worker), job.site, job.component]
    await _run_subprocess_job(job, cmd)


async def _start_api_discover(job: Job):
    worker = _root / "web" / "api_discover_worker.py"
    params = {
        "api_url": job.params.get("api_url", ""),
        "api_method": job.params.get("api_method", "POST"),
        "api_headers": job.params.get("api_headers") or {},
        "api_body": job.params.get("api_body"),
        "api_response_path": job.params.get("api_response_path", "response"),
        "api_model": job.params.get("api_model", ""),
        "probe_prompt": job.params.get("probe_prompt", "Hello from Genbounty Hunter"),
        "transport": job.params.get("transport", "api"),
        "upload_url": job.params.get("upload_url", ""),
        "upload_file_field": job.params.get("upload_file_field", "file"),
        "upload_response_path": job.params.get("upload_response_path", "document_id"),
        "multipart_prompt_field": job.params.get("multipart_prompt_field", "prompt"),
        "multipart_file_field": job.params.get("multipart_file_field", "file"),
    }
    import json as _json

    cmd = [sys.executable, "-u", str(worker), job.site, job.component, _json.dumps(params)]
    await _run_subprocess_job(job, cmd)


async def _start_manual_discover(job: Job):
    worker = _root / "web" / "manual_discover_worker.py"
    env = os.environ.copy()
    env["GENBOUNTY_JOB_ID"] = job.id
    cmd = [sys.executable, "-u", str(worker), job.site, job.component]
    if bool(job.params.get("guided")):
        cmd.append("--guided")
    if bool(job.params.get("use_cdp")):
        cmd.append("--use-cdp")
    await _run_subprocess_job(job, cmd, env=env)


async def _start_recon(job: Job):
    worker = _root / "web" / "recon_worker.py"
    params = {
        "mode": job.params.get("mode", "connected"),
        "manual_url": job.params.get("manual_url"),
        "overwrite": bool(job.params.get("overwrite", True)),
    }
    import json as _json

    cmd = [sys.executable, "-u", str(worker), job.site, job.component, _json.dumps(params)]
    await _run_subprocess_job(job, cmd)


async def _start_recon_round(job: Job):
    """Assess latest run if needed, send recon probes, merge into recon.json."""
    import json as _json

    _prepare_component_context(job)

    playbook = str(job.params.get("playbook") or "").strip()
    strategy = str(job.params.get("strategy") or "").strip()

    def _fail(msg: str) -> None:
        job.output.append(msg)
        _set_final_status(job, "failed")
        job._event.set()

    if not (job.site and job.component):
        _fail("[!] Recon Round requires a site/component context.")
        return
    if not playbook or not strategy or strategy in ("", "__all__", "__campaign__", "__recommended__"):
        _fail("[!] Recon Round needs a single play and a concrete strategy (not 'All'/'Recommended').")
        return

    bb_dir = _root / "browser-bot"
    if str(bb_dir) not in sys.path:
        sys.path.insert(0, str(bb_dir))
    from browser_bot.sites import (
        describe_submission_config_issue,
        get_submission_config,
        load_component_config,
    )

    if not get_submission_config(job.site, job.component):
        reason = describe_submission_config_issue(load_component_config(job.site, job.component))
        _fail(
            f"[!] Cannot run recon round for {job.site}/{job.component}: {reason}. "
            "Run Discovery / Connect via API or complete the component submission config first."
        )
        return

    suite_param = str(job.params.get("suite") or "").strip()
    selected_suite: Path | None = None
    if suite_param:
        selected_suite = Path(suite_param)
        if not selected_suite.is_absolute():
            selected_suite = _root / selected_suite

    playbook_id = ""
    if selected_suite and selected_suite.is_file():
        try:
            _suite_data = _json.loads(selected_suite.read_text(encoding="utf-8"))
            playbook_id = str(_suite_data.get("playbook_id") or "").strip()
        except (OSError, _json.JSONDecodeError):
            playbook_id = ""
    if not playbook_id:
        playbook_id = playbook.replace("-", "_")

    rubric_path = _root / "playbooks" / f"{playbook_id}.json"
    if not rubric_path.is_file():
        src = selected_suite.name if selected_suite else playbook
        _fail(
            f"[!] Playbook '{playbook_id}' not found (resolved from {src}). "
            "Generate probes for this play first, then run Recon Round."
        )
        return

    job.output.append(
        f"[recon_round] Starting recon round for {playbook_id}/{strategy} "
        "(assess latest run if needed, plan targeted probes from recon + playbook, then probe target)…"
    )
    job._event.set()

    await _pre_enhance_assess_latest_run(job, playbook_id, strategy)

    worker = _root / "web" / "recon_round_worker.py"
    params = {
        "playbook_id": playbook_id,
        "strategy": strategy,
    }
    cmd = [sys.executable, "-u", str(worker), job.site, job.component, _json.dumps(params)]
    rc = await _run_subprocess_job(job, cmd)
    if rc == 0:
        job.output.append("[+] Recon round complete - playbook intel updated for next enhancement.")
        job._event.set()


async def _start_recon_from_report(job: Job):
    """Aggregate recon intelligence from one or all pipeline_report.json files."""
    import json as _json

    if not (job.site and job.component):
        job.output.append("[!] Report recon requires a site/component context.")
        _set_final_status(job, "failed")
        job._event.set()
        return

    report_paths = _resolve_recon_from_report_paths(job)
    if not report_paths:
        if job.params.get("aggregate_all"):
            job.output.append("[!] No pipeline_report.json files found for this component.")
        else:
            job.output.append("[!] Select a pipeline_report.json path.")
        _set_final_status(job, "failed")
        job._event.set()
        return

    total = len(report_paths)
    if total > 1:
        job.output.append(
            f"[recon_from_report] Aggregating recon from {total} report(s) for "
            f"{job.site}/{job.component} (oldest first)…"
        )
        job.output.append(
            "[genbounty_progress] "
            + _json.dumps(
                {"type": "batch_start", "phase": "recon_from_report", "total": total},
                ensure_ascii=False,
            )
        )
    else:
        job.output.append(
            f"[recon_from_report] Reviewing {report_paths[0].name} and merging playbook-aligned "
            "intelligence into intel/{playbook_id}.json…"
        )
    job._event.set()

    worker = _root / "web" / "recon_from_report_worker.py"
    succeeded = 0
    failed = 0

    for i, resolved in enumerate(report_paths, 1):
        if not resolved.is_file():
            job.output.append(
                f"[!] Pipeline report not found: {resolved.parent.name}/{resolved.name}"
            )
            failed += 1
            job._event.set()
            continue

        if total > 1:
            job.output.append(
                f"[recon_from_report] ({i}/{total}) Reviewing {resolved.parent.name}/{resolved.name}…"
            )
            job.output.append(
                "[genbounty_progress] "
                + _json.dumps(
                    {
                        "type": "batch_progress",
                        "phase": "recon_from_report",
                        "current": i,
                        "total": total,
                        "report": resolved.name,
                    },
                    ensure_ascii=False,
                )
            )
            job._event.set()

        params = {"pipeline_report": str(resolved)}
        cmd = [sys.executable, "-u", str(worker), job.site, job.component, _json.dumps(params)]
        rc = await _run_subprocess_job(job, cmd, set_status=False)
        if rc == 0:
            succeeded += 1
            if total > 1:
                job.output.append(f"[+] ({i}/{total}) Merged recon from {resolved.parent.name}")
        else:
            failed += 1
            if total > 1:
                job.output.append(f"[!] ({i}/{total}) Failed on {resolved.parent.name}")
        job._event.set()

    if total > 1:
        job.output.append(
            "[genbounty_progress] "
            + _json.dumps(
                {"type": "batch_done", "phase": "recon_from_report", "total": total},
                ensure_ascii=False,
            )
        )

    if succeeded == 0:
        _set_final_status(job, "failed")
    elif failed:
        job.output.append(
            f"[+] Report intel batch complete - {succeeded}/{total} report(s) merged into intel files."
        )
        _set_final_status(job, "done")
    else:
        if total > 1:
            job.output.append(
                f"[+] Report intel batch complete - all {total} report(s) merged into intel files."
            )
        else:
            job.output.append("[+] Report intel complete - playbook intel updated.")
        _set_final_status(job, "done")
    job._event.set()


async def _start_credentials_from_reports(job: Job):
    """Pull credentials/paths from one or all pipeline_report.json files."""
    import json as _json

    if not (job.site and job.component):
        job.output.append("[!] Credentials extract requires a site/component context.")
        _set_final_status(job, "failed")
        job._event.set()
        return

    report_paths = _resolve_recon_from_report_paths(job)
    if not report_paths:
        if job.params.get("aggregate_all"):
            job.output.append("[!] No pipeline_report.json files found for this component.")
        else:
            job.output.append("[!] Select a pipeline_report.json path.")
        _set_final_status(job, "failed")
        job._event.set()
        return

    force = bool(job.params.get("force"))
    total = len(report_paths)
    job.output.append(
        f"[credentials] Scanning {total} report(s) for credentials/paths "
        f"(force={force})…"
    )
    if total > 1:
        job.output.append(
            "[genbounty_progress] "
            + _json.dumps(
                {
                    "type": "batch_start",
                    "phase": "credentials_from_reports",
                    "total": total,
                },
                ensure_ascii=False,
            )
        )
    job._event.set()

    def _run() -> dict:
        try:
            from dotenv import load_dotenv

            load_dotenv(_root / ".config")
            load_dotenv(_root / ".env")
        except ImportError:
            pass
        _prepare_component_context(job)
        from pipeline.credentials_and_paths import extract_and_merge_reports

        return extract_and_merge_reports(
            job.site,
            job.component,
            report_paths,
            force=force,
        )

    try:
        result = await asyncio.to_thread(_run)
    except Exception as exc:
        job.output.append(f"[!] Credentials extract failed: {exc}")
        _set_final_status(job, "failed")
        job._event.set()
        return

    if total > 1:
        job.output.append(
            "[genbounty_progress] "
            + _json.dumps(
                {
                    "type": "batch_done",
                    "phase": "credentials_from_reports",
                    "total": total,
                },
                ensure_ascii=False,
            )
        )
    job.output.append(
        f"[+] Credentials/paths inventory updated: +{result.get('added', 0)} new "
        f"(llm +{result.get('llm_added', 0)}), "
        f"{result.get('reports_scanned', 0)} scanned, "
        f"{result.get('reports_skipped', 0)} skipped, "
        f"{result.get('total_entries', 0)} total"
    )
    _set_final_status(job, "done")
    job._event.set()


def _resolve_recon_from_report_paths(job: Job) -> list[Path]:
    """Single report, explicit list, or all in-scope component reports (oldest first)."""
    if job.params.get("aggregate_all"):
        if not (job.site and job.component):
            return []
        paths = _list_pipeline_report_paths(job.site, job.component)
        return list(reversed(paths))

    report_list = job.params.get("pipeline_reports")
    if isinstance(report_list, list) and report_list:
        paths: list[Path] = []
        for raw in report_list:
            rp = Path(str(raw)).expanduser()
            if not rp.is_absolute():
                rp = _root / rp
            paths.append(rp)
        return paths

    report_path = str(
        job.params.get("pipeline_report") or job.params.get("report_path") or ""
    ).strip()
    if not report_path:
        return []

    resolved = Path(report_path).expanduser()
    if not resolved.is_absolute():
        resolved = _root / resolved
    return [resolved]


def _make_run_tests_env(job: Job) -> dict[str, str]:
    """Subprocess env for a run-tests / enhance-loop run (fresh run-log dir)."""
    env = os.environ.copy()
    env["GENBOUNTY_JOB_ID"] = job.id
    if job.site:
        env["GENBOUNTY_SITE"] = job.site
    if job.component:
        env["GENBOUNTY_COMPONENT"] = job.component
    playbook = str(job.params.get("playbook") or "").strip()
    if playbook:
        from playbooks.registry import normalize_playbook_id

        env["GENBOUNTY_PLAYBOOK"] = normalize_playbook_id(playbook)
    strategy = str(job.params.get("strategy") or "").strip()
    if strategy and strategy not in ("", "__all__", "multimodal"):
        env["GENBOUNTY_STRATEGY"] = strategy.replace("-", "_")
    if job.site and job.component:
        bb_dir = _root / "browser-bot"
        if str(bb_dir) not in sys.path:
            sys.path.insert(0, str(bb_dir))
        from browser_bot.submit.common import RUN_LOG_DIR_ENV, prepare_run_log_dir

        env.pop(RUN_LOG_DIR_ENV, None)
        os.environ.pop(RUN_LOG_DIR_ENV, None)
        run_dir = prepare_run_log_dir(job.site, job.component, reuse_env=False)
        job.run_log_dir = str(run_dir)
        env["GENBOUNTY_RUN_LOG_DIR"] = str(run_dir)
    return env


def _build_run_test_cmd(job: Job, suite_path: Path) -> list[str]:
    """Run browser-bot + convert to attack_log; assessment runs in the web job layer."""
    return [
        sys.executable, "-u", str(_root / "main.py"), "run", str(suite_path),
        "--site", job.site, "--component", job.component,
    ]


def _job_wants_assess(job: Job) -> bool:
    val = job.params.get("assess", False)
    if isinstance(val, str):
        return val.strip().lower() in ("1", "true", "yes", "on")
    return bool(val)


def _preflight_run_suite(job: Job, suite_path: Path) -> None:
    import json as _json

    try:
        from pipeline.edition import adaptive_suite_premium_block_message

        premium_msg = adaptive_suite_premium_block_message(suite_path)
        if premium_msg:
            raise ValueError(premium_msg)
    except ImportError:
        pass

    suite_data = _json.loads(suite_path.read_text(encoding="utf-8"))
    _warn_multimodal_preflight(job, suite_path, suite_data)

    bb_dir = _root / "browser-bot"
    if str(bb_dir) not in sys.path:
        sys.path.insert(0, str(bb_dir))
    from browser_bot.config import count_suite_prompts

    prompt_count = count_suite_prompts(suite_path)
    if prompt_count <= 0:
        raise ValueError(
            f"Suite has no runnable prompts: {suite_path.name}. "
            "Regeneration may have filtered every prompt (e.g. URLs in a text-only strategy)."
        )
    job.output.append(f"[run] Suite ready: {prompt_count} prompt(s) in {suite_path.name}")
    job._event.set()


def _pipeline_report_for_job(job: Job) -> Path | None:
    """Prefer the pipeline report from this job's run-log dir, else newest for the component."""
    run_dir = str(getattr(job, "run_log_dir", "") or "").strip()
    if run_dir:
        candidate = Path(run_dir) / "pipeline_report.json"
        if candidate.is_file():
            return candidate
    if job.site and job.component:
        reports = _list_pipeline_report_paths(job.site, job.component)
        if reports:
            return reports[0]
    return None


def _worst_severity_from_report(report_path: Path) -> str:
    """Worst (most severe) assessed risk level recorded in a pipeline report."""
    import json as _json

    try:
        data = _json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, _json.JSONDecodeError):
        return "indeterminate"
    results = data.get("adversarial_results")
    if not isinstance(results, list):
        return "indeterminate"
    worst_idx = len(_SEVERITY_ORDER)
    worst = "indeterminate"
    for r in results:
        if not isinstance(r, dict):
            continue
        lvl = str(r.get("risk_level") or "indeterminate").strip().lower()
        idx = _SEVERITY_ORDER.index(lvl) if lvl in _SEVERITY_ORDER else len(_SEVERITY_ORDER)
        if idx < worst_idx:
            worst_idx = idx
            worst = lvl
    return worst


def _report_meets_bounty_stop(
    report_path: Path | None,
    stop_levels: set[str],
    *,
    attack_objective: str = "",
    require_leaf_alignment: bool = False,
) -> bool:
    """True when any assessed row meets Enhance bounty exploit/partial evidence stop."""
    if report_path is None or not report_path.is_file():
        return False
    try:
        from pipeline.attack_prompt import report_meets_bounty_stop

        return bool(
            report_meets_bounty_stop(
                report_path,
                stop_levels,
                attack_objective=attack_objective,
                require_leaf_alignment=require_leaf_alignment,
            )
        )
    except Exception:
        return False


def _bounty_stop_followup_decision(
    *,
    worst: str,
    elite: list | None,
    escalation_payload: str = "",
    escalate_followup_deferred: bool = False,
    mutate_followup_deferred: bool = False,
    rnd: int = 1,
    max_rounds: int = 1,
) -> tuple[bool, str]:
    """Decide whether to defer a bounty Stop-at for Critical-path sharpening.

    Precedence (Bug Bounty / Open Hunt only; caller gates hunt mode):
    1. Never defer Critical - the Critical ask already landed.
    2. Channel-proof elite + non-empty ``escalation_payload`` → defer once for
       **BOUNTY ESCALATE** (Critical paste on the proven wrapper).
    3. Elite without channel-proof → defer once for **BOUNTY MUTATE** so a later
       channel-proof hit can still arm escalate (separate escalate defer flag).

    Returns ``(defer, kind)`` where ``kind`` is ``"escalate"``, ``"mutate"``,
    or ``""``.
    """
    if int(rnd) >= int(max_rounds):
        return False, ""
    level = str(worst or "").strip().lower()
    if level == "critical":
        return False, ""
    rows = [g for g in (elite or []) if isinstance(g, dict)]
    if not rows:
        return False, ""
    has_esc = bool(str(escalation_payload or "").strip())
    has_cp = False
    try:
        gen_dir = _root / "generate-tests"
        if str(gen_dir) not in sys.path:
            sys.path.insert(0, str(gen_dir))
        from strategies.channel_proof import elite_has_channel_proof

        has_cp = bool(elite_has_channel_proof(rows))
    except Exception:
        has_cp = any(
            g.get("channel_proof") is True
            or str(g.get("channel_proof") or "").strip().lower()
            in ("1", "true", "yes")
            for g in rows
        )
    if has_esc and has_cp and not escalate_followup_deferred:
        return True, "escalate"
    if (not has_cp) and (not mutate_followup_deferred):
        return True, "mutate"
    return False, ""


def _report_has_non_aligned_stop_candidate(
    report_path: Path | None,
    stop_levels: set[str],
    attack_objective: str,
) -> bool:
    if report_path is None or not report_path.is_file():
        return False
    try:
        from pipeline.attack_prompt import report_has_non_aligned_stop_candidate

        return bool(
            report_has_non_aligned_stop_candidate(
                report_path, stop_levels, attack_objective
            )
        )
    except Exception:
        return False


def _report_results(report_path: Path | None) -> list[dict]:
    import json as _json

    if report_path is None or not report_path.is_file():
        return []
    try:
        data = _json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, _json.JSONDecodeError):
        return []
    results = data.get("adversarial_results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []
    return [r for r in results if isinstance(r, dict)]


def _stamp_report_broaden_lineage(
    report_path: Path | None,
    *,
    enhance_phase: str,
    broadened_ask: str,
) -> None:
    """Copy enhance_phase / broadened_ask onto assessed rows for hit lineage."""
    import json as _json

    if report_path is None or not report_path.is_file():
        return
    phase = str(enhance_phase or "").strip()
    ask = str(broadened_ask or "").strip()
    if not phase and not ask:
        return
    try:
        data = _json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, _json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    results = data.get("adversarial_results")
    if not isinstance(results, list):
        return
    changed = False
    for row in results:
        if not isinstance(row, dict):
            continue
        if phase and not str(row.get("enhance_phase") or "").strip():
            row["enhance_phase"] = phase
            changed = True
        if ask and not str(row.get("broadened_ask") or "").strip():
            row["broadened_ask"] = ask
            changed = True
    if changed:
        report_path.write_text(
            _json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


_ENHANCE_LOW_FAMILY = frozenset({"low", "informational", "indeterminate"})


def _playbook_enhancement_thesis(playbook_id: str) -> str:
    """Resolve mechanism/harm thesis for SSE/UI (family default when unset)."""
    pid = str(playbook_id or "").strip()
    if not pid:
        return ""
    try:
        from playbooks.playbook_config import get_enhancement_thesis
        from playbooks.registry import load_playbook

        return get_enhancement_thesis(load_playbook(pid)) or ""
    except Exception:
        return ""


def _normalize_hunt_mode(raw) -> str:
    try:
        gen_dir = _root / "generate-tests"
        if str(gen_dir) not in sys.path:
            sys.path.insert(0, str(gen_dir))
        from strategies.hunt_mode import normalize_hunt_mode

        return normalize_hunt_mode(raw)
    except Exception:
        m = str(raw or "").strip().lower().replace("-", "_")
        if m in ("bug_bounty", "open_hunt", "compliance"):
            return m
        return "compliance"


def _is_bounty_hunt_mode(mode: str) -> bool:
    return _normalize_hunt_mode(mode) in ("bug_bounty", "open_hunt")


def _maybe_update_elite_after_assess(
    job: Job,
    report_path: Path | None,
    *,
    playbook_id: str = "",
    strategy: str = "",
) -> int:
    """Promote exploited/partial rows into elite genomes after probe assess.

    Returns newly added genome count. On a hit (added > 0) in bounty/open mode,
    also writes playbook strategy_handoff immediately so retries can reseed.
    """
    if report_path is None or not report_path.is_file():
        return 0
    if not (job.site and job.component):
        return 0
    hunt_mode = _normalize_hunt_mode(job.params.get("hunt_mode"))
    if not _is_bounty_hunt_mode(hunt_mode):
        return 0
    added = 0
    try:
        gen_dir = _root / "generate-tests"
        if str(gen_dir) not in sys.path:
            sys.path.insert(0, str(gen_dir))
        from strategies.elite_genomes import maybe_update_elite_from_report

        pb = str(playbook_id or "").strip()
        strat = str(strategy or "").strip()
        added = int(
            maybe_update_elite_from_report(
                job.site,
                job.component,
                report_path,
                bounty_mode=True,
                playbook_id=pb,
                strategy=strat,
            )
            or 0
        )
        if added:
            job.output.append(f"[+] Elite genomes updated (+{added}).")
            job._event.set()
            # Write handoff on hit so pipeline retries / cross-strategy see seeds
            # even if the enhance loop ends abruptly.
            try:
                from strategies.strategy_handoff import maybe_write_handoff_after_enhance

                if not pb:
                    pb = str(
                        job.params.get("playbook_id") or job.params.get("playbook") or ""
                    ).strip()
                if not strat:
                    strat = str(job.params.get("strategy") or "").strip()
                written = maybe_write_handoff_after_enhance(
                    job.site,
                    job.component,
                    pb,
                    strat,
                    reason="hit",
                )
                if written:
                    n_seeds = len(written.get("elite_seeds") or [])
                    job.output.append(
                        f"[handoff] wrote {n_seeds} elite seed(s) from {strat} "
                        f"(reason=hit; mutate_first={bool(written.get('mutate_first'))})."
                    )
            except Exception as hexc:
                job.output.append(f"[handoff] write-on-hit failed: {hexc}")
    except Exception as exc:
        job.output.append(f"[!] Elite update skipped: {exc}")
        job._event.set()
    return added

def _resolve_enhance_phase(
    *,
    theory_text: str = "",
    cool_down: bool = False,
    escalate_active: bool = False,
    freeze_active: bool = False,
    hard_refusal_active: bool = False,
    hunt_mode: str = "compliance",
) -> str:
    """Return enhance_phase label for SSE."""
    text = str(theory_text or "")
    if "OPEN HUNT BROADEN" in text or "genbounty:open_broaden=1" in text:
        return "open_broaden"
    if "BOUNTY ESCALATE" in text or "genbounty:bounty_escalate=1" in text:
        return "bounty_escalate"
    if "BOUNTY MUTATE" in text or "genbounty:bounty_mutate=1" in text:
        return "bounty_mutate"
    if "BOUNTY INVENT" in text or "genbounty:bounty_invent=1" in text:
        return "bounty_invent"
    if "AUTO-RUN ESCALATION" in text or "genbounty:auto_escalate=1" in text:
        return "escalate"
    if "FREEZE CHANNEL" in text or "genbounty:freeze_channel=1" in text:
        return "cool_down" if cool_down else "freeze"
    if "genbounty:hard_refusal_adapt=1" in text or "HARD REFUSAL ADAPTATION" in text:
        return "hard_refusal"
    if escalate_active:
        return "escalate"
    if freeze_active:
        return "cool_down" if cool_down else "freeze"
    if hard_refusal_active:
        return "hard_refusal"
    if cool_down and not _is_bounty_hunt_mode(hunt_mode):
        return "cool_down"
    if _is_bounty_hunt_mode(hunt_mode):
        return "bounty_invent"
    return "theory"


def _enhance_phase_after_round(
    *,
    escalate_active: bool,
    freeze_active: bool,
    worst: str,
    freeze_completed: bool,
) -> tuple[bool, bool]:
    """Return ``(cool_down_pending, freeze_completed)`` after an assessed enhance round.

    Pure helper so cool-down / freeze reset stay outside report-parse try/except.
    Failed escalate (Low-family worst) arms cool-down and resets freeze so the next
    progress round must re-clone before escalating again.
    """
    level = str(worst or "").strip().lower()
    low_family = level in _ENHANCE_LOW_FAMILY
    try:
        gen_dir = _root / "generate-tests"
        if str(gen_dir) not in sys.path:
            sys.path.insert(0, str(gen_dir))
        from enhance_theory import is_stagnation_severity

        low_family = bool(is_stagnation_severity(level))
    except Exception:
        pass

    cool_down = bool(escalate_active and low_family)
    next_freeze_done = bool(freeze_completed)
    if cool_down:
        next_freeze_done = False
    elif freeze_active:
        next_freeze_done = True
    return cool_down, next_freeze_done


async def _start_run_tests(job: Job):
    import json as _json

    suite_param = job.params.get("suite", "")
    assess = _job_wants_assess(job)
    _prepare_component_context(job)

    bb_dir = _root / "browser-bot"
    if str(bb_dir) not in sys.path:
        sys.path.insert(0, str(bb_dir))
    from browser_bot.sites import describe_submission_config_issue, get_submission_config, load_component_config

    if not get_submission_config(job.site, job.component):
        reason = describe_submission_config_issue(load_component_config(job.site, job.component))
        job.output.append(
            f"[!] Cannot run probe suite for {job.site}/{job.component}: {reason}. "
            "Run Discovery / Connect via API or complete the component submission config first."
        )
        job.status = "failed"
        job._event.set()
        return

    def _run_env() -> dict[str, str]:
        return _make_run_tests_env(job)

    def _resolve_suite_path(suite_path_str: str) -> Path:
        suite_path = Path(suite_path_str)
        if not suite_path.is_absolute():
            suite_path = _root / suite_path
        return suite_path

    def _build_run_cmd(suite_path: Path) -> list[str]:
        return _build_run_test_cmd(job, suite_path)

    def _preflight_suite(suite_path: Path) -> None:
        _preflight_run_suite(job, suite_path)

    if suite_param == "__category__":
        raw_playbooks = job.params.get("playbooks") or []
        if not isinstance(raw_playbooks, list):
            raw_playbooks = []
        playbooks: list[str] = []
        seen: set[str] = set()
        for raw in raw_playbooks:
            playbook = str(raw or "").strip()
            if not playbook or "/" in playbook or "\\" in playbook or playbook.startswith("."):
                continue
            playbook = Path(playbook).stem
            if playbook and playbook not in seen:
                seen.add(playbook)
                playbooks.append(playbook)

        tests_dir = bb_dir / "sites" / job.site / job.component / "tests"
        suites: list[tuple[str, Path]] = []
        if tests_dir.is_dir():
            for playbook in playbooks:
                suites.extend(
                    (playbook, sp)
                    for sp in sorted(tests_dir.glob(f"*/{playbook}.json"))
                    if sp.is_file()
                )

        category_label = str(job.params.get("category_label") or job.params.get("category") or "category")
        if not suites:
            job.output.append(f"[!] No probe suites found for category={category_label}")
            job.status = "failed"
            job._event.set()
            return

        total = len(suites)
        job.status = "running"
        job._event.set()
        failed = False
        ran_count = 0
        try:
            for i, (playbook, sp) in enumerate(suites, 1):
                if _is_cancelled(job):
                    break
                strat_name = sp.parent.name
                try:
                    from pipeline.edition import adaptive_suite_premium_block_message

                    skip_msg = adaptive_suite_premium_block_message(sp)
                except ImportError:
                    skip_msg = None
                if skip_msg:
                    job.output.append(
                        f"[{i}/{total}] Skipping category={category_label}: "
                        f"strategy={strat_name}, playbook={playbook} - {skip_msg}"
                    )
                    job._event.set()
                    continue
                progress_line = _json.dumps(
                    {
                        "type": "suite",
                        "current": i,
                        "total": total,
                        "strategy": strat_name,
                        "playbook": playbook,
                    },
                    ensure_ascii=False,
                )
                job.output.append(f"[genbounty_progress] {progress_line}")
                job.output.append(
                    f"[{i}/{total}] Running category={category_label}: "
                    f"strategy={strat_name}, playbook={playbook}..."
                )
                job._event.set()
                try:
                    _preflight_suite(sp)
                except ValueError as exc:
                    job.output.append(f"[!] {exc}")
                    failed = True
                    continue
                ran_count += 1
                rc = await _run_subprocess_job(
                    job, _build_run_cmd(sp), env=_run_env(), set_status=False
                )
                if _is_cancelled(job):
                    break
                if rc != 0:
                    failed = True
                elif assess:
                    await _after_assessed_run(job, sp)
            if not _is_cancelled(job):
                if ran_count == 0:
                    job.output.append(
                        f"[!] No runnable suites for category={category_label} "
                        "(Premium strategies skipped)."
                    )
                    _set_final_status(job, "failed")
                elif failed:
                    _set_final_status(job, "failed")
                else:
                    job.output.append(
                        f"[+] All {ran_count} suite(s) complete for category={category_label}."
                    )
                    _set_final_status(job, "done")
        except asyncio.CancelledError:
            _set_final_status(job, "cancelled")
        except Exception as exc:
            job.output.append(f"[error] {exc}")
            _set_final_status(job, "failed")
        finally:
            job._event.set()
        return

    if suite_param in ("__campaign__", "__recommended__"):
        job.output.append(
            "[!] Recommended campaigns were removed. Pick a concrete strategy or All strategies."
        )
        job.status = "failed"
        job._event.set()
        return

    if suite_param == "__all__":
        playbook = job.params.get("playbook", "")
        tests_dir = bb_dir / "sites" / job.site / job.component / "tests"
        suites = sorted(tests_dir.glob(f"*/{playbook}.json")) if tests_dir.is_dir() else []

        if not suites:
            job.output.append(f"[!] No probe suites found for playbook={playbook}")
            job.status = "failed"
            job._event.set()
            return

        total = len(suites)
        job.status = "running"
        job._event.set()
        failed = False
        ran_count = 0
        try:
            for i, sp in enumerate(suites, 1):
                if _is_cancelled(job):
                    break
                strat_name = sp.parent.name
                try:
                    from pipeline.edition import adaptive_suite_premium_block_message

                    skip_msg = adaptive_suite_premium_block_message(sp)
                except ImportError:
                    skip_msg = None
                if skip_msg:
                    job.output.append(
                        f"[{i}/{total}] Skipping strategy={strat_name}, "
                        f"playbook={playbook} - {skip_msg}"
                    )
                    job._event.set()
                    continue
                progress_line = _json.dumps(
                    {"type": "suite", "current": i, "total": total, "strategy": strat_name},
                    ensure_ascii=False,
                )
                job.output.append(f"[genbounty_progress] {progress_line}")
                job.output.append(f"[{i}/{total}] Running: strategy={strat_name}, playbook={playbook}...")
                job._event.set()
                try:
                    _preflight_suite(sp)
                except ValueError as exc:
                    job.output.append(f"[!] {exc}")
                    failed = True
                    continue
                ran_count += 1
                rc = await _run_subprocess_job(
                    job, _build_run_cmd(sp), env=_run_env(), set_status=False
                )
                if _is_cancelled(job):
                    break
                if rc != 0:
                    failed = True
                elif assess:
                    await _after_assessed_run(job, sp)
            if not _is_cancelled(job):
                if ran_count == 0:
                    job.output.append(
                        f"[!] No runnable strategy suites for playbook={playbook} "
                        "(Premium strategies skipped)."
                    )
                    _set_final_status(job, "failed")
                elif failed:
                    _set_final_status(job, "failed")
                else:
                    job.output.append(
                        f"[+] All {ran_count} strategy suite(s) complete for playbook={playbook}."
                    )
                    _set_final_status(job, "done")
        except asyncio.CancelledError:
            _set_final_status(job, "cancelled")
        except Exception as exc:
            job.output.append(f"[error] {exc}")
            _set_final_status(job, "failed")
        finally:
            job._event.set()
        return

    suite_path = _resolve_suite_path(suite_param)
    if not suite_path.is_file():
        job.output.append(f"[!] Suite not found: {suite_path.name}")
        job.status = "failed"
        job._event.set()
        return

    try:
        _preflight_suite(suite_path)
    except ValueError as exc:
        job.output.append(f"[!] {exc}")
        job.status = "failed"
        job._event.set()
        return

    rc = await _run_subprocess_job(job, _build_run_cmd(suite_path), env=_run_env(), set_status=False)
    if _is_cancelled(job):
        _set_final_status(job, "cancelled")
        job._event.set()
        return
    if rc == 0 and assess:
        await _after_assessed_run(job, suite_path)
    _set_final_status(job, "done" if rc == 0 else "failed")


async def _start_enhance_loop(job: Job):
    """Baseline run+assess (if needed) -> enhance regen -> run -> assess …

    Newly generated suites are never enhanced cold: if this play/strategy has no
    fresh ``pipeline_report.json``, the on-disk suite is run and assessed first.
    Then each Auto-run round is theory → regenerate → run → assess.
    With ``max_rounds > 1`` (auto-run) it repeats until a finding meets the
    Enhance bounty stop (exploit, or severity-in-``stop_levels`` plus
    partial/evidence≥40; severity alone never stops; default stop levels
    ``critical`` / ``high``; UI may also include ``medium``) or the round budget
    is exhausted. All-Low early stop (default 4 in bounty/open) aborts wasted
    Low monocultures; Open Hunt may arm one broaden first. Auto-run also sets
    ``auto_accept_theory`` so enhancement theories are accepted without the
    interactive modal.
    """
    import json as _json

    _prepare_component_context(job)

    playbook = str(job.params.get("playbook") or "").strip()
    strategy = str(job.params.get("strategy") or "").strip()
    suite_param = str(job.params.get("suite") or "").strip()
    try:
        max_rounds = int(job.params.get("max_rounds") or 1)
    except (TypeError, ValueError):
        max_rounds = 1
    max_rounds = max(1, min(max_rounds, 8))
    stop_levels = _normalize_enhance_stop_levels(job.params.get("stop_levels"))

    def _fail(msg: str) -> None:
        job.output.append(msg)
        _set_final_status(job, "failed")
        job._event.set()

    if not (job.site and job.component):
        _fail("[!] Enhance & Re-run requires a site/component context.")
        return
    if not playbook or not strategy or strategy in ("", "__all__", "__campaign__", "__recommended__"):
        _fail("[!] Enhance & Re-run needs a single play and a concrete strategy (not 'All'/'Recommended').")
        return

    bb_dir = _root / "browser-bot"
    if str(bb_dir) not in sys.path:
        sys.path.insert(0, str(bb_dir))
    from browser_bot.sites import (
        describe_submission_config_issue,
        get_submission_config,
        load_component_config,
    )

    if not get_submission_config(job.site, job.component):
        reason = describe_submission_config_issue(load_component_config(job.site, job.component))
        _fail(
            f"[!] Cannot run probe suite for {job.site}/{job.component}: {reason}. "
            "Run Discovery / Connect via API or complete the component submission config first."
        )
        return

    # The selected file stem (run.playbook) may be a manual copy (e.g. "...-3")
    # that is NOT a playbook. Generation is keyed on the real playbook_id stored
    # inside the suite and always writes to the canonical tests/<strategy>/<playbook>.json,
    # so resolve playbook_id from the suite content and target that canonical path.
    selected_suite: Path | None = None
    if suite_param:
        selected_suite = Path(suite_param)
        if not selected_suite.is_absolute():
            selected_suite = _root / selected_suite

    playbook_id = ""
    if selected_suite and selected_suite.is_file():
        try:
            _suite_data = _json.loads(selected_suite.read_text(encoding="utf-8"))
            playbook_id = str(_suite_data.get("playbook_id") or "").strip()
        except (OSError, _json.JSONDecodeError):
            playbook_id = ""
    if not playbook_id:
        playbook_id = playbook.replace("-", "_")

    rubric_path = _root / "playbooks" / f"{playbook_id}.json"
    if not rubric_path.is_file():
        src = selected_suite.name if selected_suite else playbook
        _fail(
            f"[!] Playbook '{playbook_id}' not found (resolved from {src}). "
            "Generate probes for this play first, then Enhance & Re-run."
        )
        return

    suite_path = (
        bb_dir / "sites" / job.site / job.component / "tests"
        / strategy.replace("_", "-")
        / f"{playbook_id.replace('_', '-')}.json"
    )
    if selected_suite and selected_suite.resolve() != suite_path.resolve():
        job.output.append(
            f"[enhance] Enhancing play '{playbook_id}' -> {suite_path.name} "
            f"(selected file {selected_suite.name} is a copy; the canonical suite is regenerated)."
        )

    gen_env = os.environ.copy()
    gen_env["GENBOUNTY_SITE"] = job.site
    gen_env["GENBOUNTY_COMPONENT"] = job.component
    gen_env["GENBOUNTY_PLAYBOOK"] = playbook_id
    gen_env["GENBOUNTY_STRATEGY"] = str(strategy or "").replace("-", "_")
    gen_env["GENBOUNTY_FEEDBACK"] = "1"
    hunt_mode = _normalize_hunt_mode(job.params.get("hunt_mode"))
    if hunt_mode == "open_hunt":
        try:
            from pipeline.edition import fail_job_premium, is_community

            if is_community():
                fail_job_premium(job, "open_hunt")
                return
        except ImportError:
            pass
    gen_env["GENBOUNTY_HUNT_MODE"] = hunt_mode
    bounty_mode = _is_bounty_hunt_mode(hunt_mode)
    gen_env["PYTHONUNBUFFERED"] = "1"
    # Do not inherit prior-job invent_pressure from the parent process env.
    gen_env.pop("GENBOUNTY_LAST_INGENUITY", None)
    os.environ.pop("GENBOUNTY_LAST_INGENUITY", None)
    _apply_gen_auto_apply_env(job, gen_env)
    # Custom enhance applies to both single-round Enhance and Auto-run loops.
    custom_enhance = str(job.params.get("custom_enhance") or "").strip()
    use_custom_enhance = bool(custom_enhance)
    if use_custom_enhance:
        gen_env["GENBOUNTY_CUSTOM_ENHANCE"] = custom_enhance
        if bool(job.params.get("custom_overrides_freeze")):
            gen_env["GENBOUNTY_CUSTOM_OVERRIDES_FREEZE"] = "1"
    generator_py = _root / "generate-tests" / "generator.py"
    gen_cmd = [
        sys.executable, "-u", str(generator_py),
        "--strategy", strategy, "--playbook", playbook_id,
        "--site", job.site, "--component", job.component,
    ]
    # _maybe_export_latest_assessed_report() gates on this flag.
    job.params["assess"] = True

    job.status = "running"
    job._event.set()
    final_status = "done"
    reached: str | None = None
    try:
        if _is_cancelled(job):
            _set_final_status(job, "cancelled")
            return
        await _pre_enhance_assess_latest_run(job, playbook_id, strategy)
        if _is_cancelled(job):
            _set_final_status(job, "cancelled")
            return
        # Never theory/regen a cold suite: baseline run+assess first when needed.
        if not await _baseline_run_suite_before_enhance(
            job, suite_path, playbook_id, strategy
        ):
            if _is_cancelled(job):
                _set_final_status(job, "cancelled")
            else:
                _set_final_status(job, "failed")
            return

        if max_rounds > 1:
            stop_label = "/".join(sorted(stop_levels))
            job.output.append(
                f"[enhance] Auto-run up to {max_rounds} round(s); "
                f"stop on exploit/partial evidence at or above {stop_label} "
                "(severity alone never stops)."
            )
        if bounty_mode:
            job.output.append(
                f"[enhance] Hunt mode={hunt_mode} - elite mutate + mechanism invent "
                "(compliance freeze/escalate rails disabled)."
            )

        stagnation_history: list[dict] = []
        phase_history: list[dict] = []
        by_phase_accum: dict = {}
        freeze_completed = False
        cool_down_pending = False
        open_broaden_pending = False
        open_broaden_arms_used = 0
        open_broaden_hits = 0
        open_broaden_cooldown = 0
        all_low_streak = 0
        invent_zero_streak = 0
        handoff_reason = "max_rounds"
        mutate_followup_deferred = False
        escalate_followup_deferred = False
        try:
            hard_refusal_early_stop = int(job.params.get("hard_refusal_early_stop") or 0)
        except (TypeError, ValueError):
            hard_refusal_early_stop = 0
        hard_refusal_early_stop = max(0, min(hard_refusal_early_stop, max_rounds))
        hard_refusal_streak = 0
        if hard_refusal_early_stop > 0 and max_rounds > 1:
            job.output.append(
                f"[enhance] Hard-refusal early stop after {hard_refusal_early_stop} "
                "consecutive Low hard-refusal rounds (pipeline soft-advance)."
            )
        try:
            circular_enhance_early_stop = int(
                job.params.get("circular_enhance_early_stop") or 0
            )
        except (TypeError, ValueError):
            circular_enhance_early_stop = 0
        circular_enhance_early_stop = max(
            0, min(circular_enhance_early_stop, max_rounds)
        )
        if circular_enhance_early_stop > 0 and max_rounds > 1:
            job.output.append(
                f"[enhance] Circular enhance early stop after {circular_enhance_early_stop} "
                "consecutive Low overlapping rounds (pipeline soft-advance)."
            )
        try:
            all_low_early_stop = int(job.params.get("all_low_early_stop") or 0)
        except (TypeError, ValueError):
            all_low_early_stop = 0
        # Default 4 for multi-round bounty/open; 0 disables.
        if all_low_early_stop <= 0 and max_rounds > 1 and bounty_mode:
            all_low_early_stop = 4
        all_low_early_stop = max(0, min(all_low_early_stop, max_rounds))
        if all_low_early_stop > 0 and max_rounds > 1:
            job.output.append(
                f"[enhance] All-Low early stop after {all_low_early_stop} "
                "consecutive Low rounds with no partial/exploited "
                "(Open Hunt: one broaden then abort)."
            )
        # Invent usefulness-0 → earlier Open Hunt broaden (default 2; explicit 0 disables).
        _raw_invent_zero = job.params.get("invent_zero_broaden_after", None)
        if _raw_invent_zero is None:
            invent_zero_broaden_after = (
                2 if (max_rounds > 1 and hunt_mode == "open_hunt") else 0
            )
        else:
            try:
                invent_zero_broaden_after = int(_raw_invent_zero)
            except (TypeError, ValueError):
                invent_zero_broaden_after = 0
            invent_zero_broaden_after = max(0, min(invent_zero_broaden_after, max_rounds))
        if invent_zero_broaden_after > 0 and max_rounds > 1 and hunt_mode == "open_hunt":
            job.output.append(
                f"[enhance] Invent usefulness-0 broaden after {invent_zero_broaden_after} "
                "consecutive invent round(s) at score 0 (Open Hunt)."
            )

        def _open_broaden_max_arms() -> int:
            return 2 if open_broaden_hits > 0 else 1

        def _may_arm_open_broaden() -> bool:
            if hunt_mode != "open_hunt":
                return False
            if open_broaden_cooldown > 0:
                return False
            return open_broaden_arms_used < _open_broaden_max_arms()

        for rnd in range(1, max_rounds + 1):
            if _is_cancelled(job):
                break
            gen_env.pop("GENBOUNTY_ACCEPTED_THEORY", None)
            gen_env.pop("GENBOUNTY_AUTO_ESCALATE", None)
            gen_env.pop("GENBOUNTY_FREEZE_CHANNEL", None)
            gen_env.pop("GENBOUNTY_HARD_REFUSAL", None)
            gen_env.pop("GENBOUNTY_FORCE_BREAKTHROUGH", None)
            gen_env.pop("GENBOUNTY_OPEN_BROADEN", None)
            gen_env["GENBOUNTY_HUNT_MODE"] = hunt_mode

            cool_down_this_round = bool(cool_down_pending)
            open_broaden_this_round = (
                bool(open_broaden_pending)
                and hunt_mode == "open_hunt"
                and _may_arm_open_broaden()
            )
            if cool_down_this_round:
                cool_down_pending = False
                job.output.append(
                    "[enhance] Cool-down after failed escalate - suppressing "
                    "auto-escalate this round"
                    + (" (bounty resume invent/mutate)." if bounty_mode else ".")
                )
            if open_broaden_pending and hunt_mode == "open_hunt" and not open_broaden_this_round:
                # Keep pending across cooldown so the arm fires after invent/mutate
                # rounds; drop only when the arm budget is exhausted.
                if open_broaden_cooldown > 0 and open_broaden_arms_used < _open_broaden_max_arms():
                    job.output.append(
                        "[enhance] Open Hunt broaden deferred "
                        f"(cooldown={open_broaden_cooldown}, "
                        f"arms_used={open_broaden_arms_used}/"
                        f"{_open_broaden_max_arms()})."
                    )
                else:
                    open_broaden_pending = False
                    job.output.append(
                        "[enhance] Open Hunt broaden skipped "
                        f"(cooldown={open_broaden_cooldown}, "
                        f"arms_used={open_broaden_arms_used}/"
                        f"{_open_broaden_max_arms()})."
                    )
            if open_broaden_this_round:
                open_broaden_pending = False
                open_broaden_arms_used += 1
                gen_env["GENBOUNTY_OPEN_BROADEN"] = "1"
                job.output.append(
                    "[enhance] Open Hunt broaden armed - hypothesis may widen this round "
                    f"(arm {open_broaden_arms_used}/{_open_broaden_max_arms()})."
                )

            job.output.append(
                "[genbounty_progress] "
                + _json.dumps(
                    {
                        "type": "enhance_round",
                        "current": rnd,
                        "total": max_rounds,
                        "enhance_phase": _resolve_enhance_phase(
                            cool_down=cool_down_this_round,
                            hunt_mode=hunt_mode,
                        ),
                        "thesis": _playbook_enhancement_thesis(playbook_id),
                        "hunt_mode": hunt_mode,
                    },
                    ensure_ascii=False,
                )
            )
            job.output.append(f"=== Enhance & Re-run round {rnd}/{max_rounds} ===")
            job._event.set()

            abandon_accepted = False
            try:
                gen_dir = _root / "generate-tests"
                if str(gen_dir) not in sys.path:
                    sys.path.insert(0, str(gen_dir))
                from enhance_theory import stagnation_detected

                abandon_accepted = stagnation_detected(stagnation_history)
            except Exception:
                abandon_accepted = False
            if abandon_accepted:
                job.output.append(
                    f"[enhance] Stagnation detected after {len(stagnation_history)} Low "
                    "rounds - forcing breakthrough + abandoning last accepted theories."
                )
                if hunt_mode == "open_hunt" and not open_broaden_this_round:
                    if _may_arm_open_broaden():
                        open_broaden_this_round = True
                        open_broaden_arms_used += 1
                        gen_env["GENBOUNTY_OPEN_BROADEN"] = "1"
                        job.output.append(
                            "[enhance] Open Hunt broaden armed via stagnation "
                            f"(arm {open_broaden_arms_used}/{_open_broaden_max_arms()})."
                        )
                    else:
                        job.output.append(
                            "[enhance] Open Hunt broaden skipped "
                            f"(cooldown={open_broaden_cooldown}, "
                            f"arms_used={open_broaden_arms_used}/"
                            f"{_open_broaden_max_arms()})."
                        )

            accepted_theory = await _confirm_enhance_theory(
                job,
                playbook_id,
                strategy,
                rnd,
                custom_enhance=custom_enhance,
                abandon_accepted=abandon_accepted,
                freeze_completed=freeze_completed and not bounty_mode,
                cool_down=cool_down_this_round,
                hunt_mode=hunt_mode,
                open_broaden=open_broaden_this_round,
            )
            if _is_cancelled(job):
                break
            escalate_active = False
            freeze_active = False
            hard_refusal_active = False
            if accepted_theory:
                gen_env["GENBOUNTY_ACCEPTED_THEORY"] = accepted_theory
                try:
                    gen_dir = _root / "generate-tests"
                    if str(gen_dir) not in sys.path:
                        sys.path.insert(0, str(gen_dir))
                    from enhance_theory import (
                        theory_requests_auto_escalate,
                        theory_requests_bounty_escalate,
                        theory_requests_freeze_channel,
                        theory_requests_hard_refusal_adapt,
                    )

                    if not bounty_mode:
                        escalate_active = theory_requests_auto_escalate(accepted_theory)
                        freeze_active = theory_requests_freeze_channel(accepted_theory)
                    else:
                        escalate_active = theory_requests_bounty_escalate(
                            accepted_theory
                        ) or theory_requests_auto_escalate(accepted_theory)
                    hard_refusal_active = theory_requests_hard_refusal_adapt(
                        accepted_theory
                    )
                except Exception:
                    if not bounty_mode:
                        escalate_active = "AUTO-RUN ESCALATION" in accepted_theory or (
                            "genbounty:auto_escalate=1" in accepted_theory
                        )
                        freeze_active = "FREEZE CHANNEL" in accepted_theory or (
                            "genbounty:freeze_channel=1" in accepted_theory
                        )
                    else:
                        escalate_active = (
                            "BOUNTY ESCALATE" in accepted_theory
                            or "genbounty:bounty_escalate=1" in accepted_theory
                            or "genbounty:auto_escalate=1" in accepted_theory
                        )
                    hard_refusal_active = (
                        "genbounty:hard_refusal_adapt=1" in accepted_theory
                        or "HARD REFUSAL ADAPTATION" in accepted_theory
                    )
                # Unstick freeze when hard-refusal (no channel) or auto-accept signaled reset.
                reset_freeze = bool(
                    (job.theory_state or {}).get("reset_freeze_completed")
                )
                if hard_refusal_active or reset_freeze:
                    if freeze_completed:
                        job.output.append(
                            "[enhance] Freeze state reset "
                            "(hard-refusal or non-escalate accept after phase failures)."
                        )
                    freeze_completed = False
                if escalate_active:
                    gen_env["GENBOUNTY_AUTO_ESCALATE"] = "1"
                    job.output.append(
                        "[enhance] Auto-run escalation active - generation will "
                        "outrank canary-only attack_objective for this round"
                        + (" (bounty escalate-after-elite)." if bounty_mode else ".")
                    )
                if freeze_active and not bounty_mode:
                    gen_env["GENBOUNTY_FREEZE_CHANNEL"] = "1"
                    job.output.append(
                        "[enhance] Freeze channel active - clone proven wrappers; "
                        "canary filter stays on this round."
                    )
                if hard_refusal_active and not bounty_mode:
                    gen_env["GENBOUNTY_HARD_REFUSAL"] = "1"
                    job.output.append(
                        "[enhance] Hard-refusal adapt active - advance expert "
                        "temperature raised for this round."
                    )
                if abandon_accepted:
                    gen_env["GENBOUNTY_FORCE_BREAKTHROUGH"] = "1"
                if bounty_mode:
                    # Bounty/open always force breakthrough bias when inventing cold.
                    if (
                        "genbounty:bounty_invent=1" in accepted_theory
                        or "BOUNTY INVENT" in accepted_theory
                        or "genbounty:open_broaden=1" in accepted_theory
                    ):
                        gen_env["GENBOUNTY_FORCE_BREAKTHROUGH"] = "1"
                        gen_env["GENBOUNTY_HARD_REFUSAL"] = "1"

            if use_custom_enhance:
                job.output.append(
                    f"[enhance] Step 2/4: regenerating {strategy}/{playbook_id} "
                    "from custom instructions + theory…"
                )
            else:
                job.output.append(
                    f"[enhance] Step 2/4: regenerating {strategy}/{playbook_id} "
                    "probe suite (generator LLM)…"
                )
            job._event.set()
            rc = await _run_subprocess_job(job, gen_cmd, env=gen_env, set_status=False)
            if _is_cancelled(job):
                break
            if rc != 0:
                job.output.append(f"[!] Generation exited {rc}; stopping enhance loop.")
                final_status = "failed"
                break
            # Note: generator.py (core.generate_attack_suite) already materializes
            # multimodal payloads when writing under browser-bot/sites.

            if not suite_path.is_file():
                job.output.append(f"[!] Suite not found after generation: {suite_path.name}")
                final_status = "failed"
                break

            try:
                _preflight_run_suite(job, suite_path)
            except ValueError as exc:
                job.output.append(f"[!] {exc}")
                final_status = "failed"
                break

            job.output.append(
                "[enhance] Step 3/4: running probe suite against the target…"
            )
            job._event.set()
            rc = await _run_subprocess_job(
                job, _build_run_test_cmd(job, suite_path),
                env=_make_run_tests_env(job), set_status=False,
            )
            if _is_cancelled(job):
                break
            if rc != 0:
                job.output.append(f"[!] Run exited {rc}; stopping enhance loop.")
                final_status = "failed"
                break
            job.output.append(
                "[enhance] Step 4/4: Analysis + intel refresh…"
            )
            job._event.set()
            report_path = await _after_assessed_run(job, suite_path)
            if _is_cancelled(job):
                break
            worst = _worst_severity_from_report(report_path) if report_path else "indeterminate"
            hunt_ingenuity: dict | None = None
            generation_stamp: dict | None = None
            try:
                if suite_path.is_file():
                    suite_data = _json.loads(suite_path.read_text(encoding="utf-8"))
                    raw_ing = suite_data.get("hunt_ingenuity")
                    if isinstance(raw_ing, dict):
                        generation_stamp = raw_ing
            except Exception:
                generation_stamp = None
            if generation_stamp is None:
                try:
                    raw_env = (os.environ.get("GENBOUNTY_LAST_INGENUITY") or "").strip()
                    if raw_env:
                        parsed = _json.loads(raw_env)
                        if isinstance(parsed, dict):
                            generation_stamp = parsed
                except Exception:
                    generation_stamp = None
            round_phase = _resolve_enhance_phase(
                theory_text=accepted_theory or "",
                cool_down=cool_down_this_round,
                escalate_active=escalate_active,
                freeze_active=freeze_active,
                hard_refusal_active=hard_refusal_active,
                hunt_mode=hunt_mode,
            )
            round_broadened_ask = ""
            if open_broaden_this_round or round_phase == "open_broaden":
                try:
                    gen_dir = _root / "generate-tests"
                    if str(gen_dir) not in sys.path:
                        sys.path.insert(0, str(gen_dir))
                    from strategies.bounty_ingenuity import extract_broadened_ask

                    round_broadened_ask = extract_broadened_ask(accepted_theory or "")
                except Exception:
                    round_broadened_ask = ""
            if bounty_mode and report_path and report_path.is_file():
                try:
                    gen_dir = _root / "generate-tests"
                    if str(gen_dir) not in sys.path:
                        sys.path.insert(0, str(gen_dir))
                    from strategies.bounty_ingenuity import (
                        finalize_hunt_ingenuity,
                        merge_phase_usefulness,
                        phase_history_entry,
                        round_has_partial_or_exploited,
                    )

                    report_data = _json.loads(report_path.read_text(encoding="utf-8"))
                    results = list(
                        (report_data.get("adversarial_results") or [])
                        if isinstance(report_data, dict)
                        else []
                    )
                    hunt_ingenuity = finalize_hunt_ingenuity(
                        generation=generation_stamp,
                        results=results,
                        enhance_phase=round_phase,
                        broadened_ask=round_broadened_ask,
                    )
                    usefulness_block = (
                        hunt_ingenuity.get("usefulness")
                        if isinstance(hunt_ingenuity.get("usefulness"), dict)
                        else {}
                    )
                    usefulness_metrics = {
                        "n": int(
                            (
                                usefulness_block.get("n")
                                if usefulness_block.get("n") is not None
                                else len(results)
                            )
                            or 0
                        ),
                        "score": float(hunt_ingenuity.get("score") or 0.0),
                        **{
                            k: usefulness_block[k]
                            for k in (
                                "exploit_rate",
                                "partial_rate",
                                "medium_plus_rate",
                                "fabricated_rate",
                                "refused_rate",
                            )
                            if k in usefulness_block
                        },
                    }
                    by_phase_accum = merge_phase_usefulness(
                        by_phase_accum,
                        round_phase,
                        usefulness_metrics,
                    )
                    hunt_ingenuity["by_phase"] = by_phase_accum
                    phase_entry = phase_history_entry(
                        round_n=rnd,
                        phase=round_phase,
                        score=float(hunt_ingenuity.get("score") or 0.0),
                        usefulness=hunt_ingenuity.get("usefulness")
                        if isinstance(hunt_ingenuity.get("usefulness"), dict)
                        else {},
                        broadened_ask=round_broadened_ask,
                        worst=worst,
                    )
                    phase_history.append(phase_entry)
                    hunt_ingenuity["phase_history"] = list(phase_history)
                    if isinstance(report_data, dict):
                        report_data["hunt_ingenuity"] = hunt_ingenuity
                        report_data["enhance_phase"] = round_phase
                        if round_broadened_ask:
                            report_data["broadened_ask"] = round_broadened_ask
                        report_data["phase_history"] = list(phase_history)
                        report_data["by_phase"] = by_phase_accum
                        report_path.write_text(
                            _json.dumps(report_data, ensure_ascii=False, indent=2)
                            + "\n",
                            encoding="utf-8",
                        )
                    _stamp_report_broaden_lineage(
                        report_path,
                        enhance_phase=round_phase,
                        broadened_ask=round_broadened_ask,
                    )
                    os.environ["GENBOUNTY_LAST_INGENUITY"] = _json.dumps(
                        hunt_ingenuity, ensure_ascii=False
                    )
                    # Generation subprocess uses gen_env - keep invent_pressure in sync.
                    gen_env["GENBOUNTY_LAST_INGENUITY"] = os.environ[
                        "GENBOUNTY_LAST_INGENUITY"
                    ]
                    if suite_path.is_file():
                        try:
                            suite_data = _json.loads(
                                suite_path.read_text(encoding="utf-8")
                            )
                            if isinstance(suite_data, dict):
                                suite_data["hunt_ingenuity"] = hunt_ingenuity
                                suite_data["enhance_phase"] = round_phase
                                if round_broadened_ask:
                                    suite_data["broadened_ask"] = round_broadened_ask
                                suite_path.write_text(
                                    _json.dumps(
                                        suite_data, ensure_ascii=False, indent=2
                                    )
                                    + "\n",
                                    encoding="utf-8",
                                )
                        except Exception:
                            pass
                    # Broaden attribution + cooldown only for job-armed rounds.
                    if open_broaden_this_round:
                        if round_has_partial_or_exploited(results):
                            open_broaden_hits += 1
                            job.output.append(
                                "[enhance] Open broaden produced partial/exploited "
                                "signal - attribution credit recorded."
                            )
                        elif float(hunt_ingenuity.get("score") or 0.0) <= 0.0:
                            open_broaden_cooldown = 2
                            job.output.append(
                                "[enhance] Open broaden stayed at usefulness floor - "
                                "invent/mutate cooldown for 2 rounds."
                            )
                except Exception as exc:
                    job.output.append(
                        f"[enhance] hunt_ingenuity usefulness recompute skipped: {exc}"
                    )
                    hunt_ingenuity = generation_stamp
            elif generation_stamp is not None:
                hunt_ingenuity = generation_stamp
            if open_broaden_cooldown > 0 and not open_broaden_this_round:
                open_broaden_cooldown = max(0, open_broaden_cooldown - 1)
            # Invent usefulness-0 streak → arm Open Hunt broaden before All-Low=4.
            if invent_zero_broaden_after > 0 and hunt_mode == "open_hunt":
                score_now = float((hunt_ingenuity or {}).get("score") or 0.0)
                invent_signal = False
                if report_path:
                    try:
                        gen_dir = _root / "generate-tests"
                        if str(gen_dir) not in sys.path:
                            sys.path.insert(0, str(gen_dir))
                        from strategies.bounty_ingenuity import (
                            round_has_partial_or_exploited as _rpe,
                        )

                        invent_signal = _rpe(_report_results(report_path))
                    except Exception:
                        invent_signal = False
                if (
                    round_phase == "bounty_invent"
                    and score_now <= 0.0
                    and not invent_signal
                ):
                    invent_zero_streak += 1
                else:
                    invent_zero_streak = 0
                if (
                    invent_zero_streak >= invent_zero_broaden_after
                    and rnd < max_rounds
                    and _may_arm_open_broaden()
                    and not open_broaden_pending
                    and not open_broaden_this_round
                ):
                    open_broaden_pending = True
                    invent_zero_streak = 0
                    job.output.append(
                        "[enhance] Invent usefulness stayed 0 for "
                        f"{invent_zero_broaden_after} round(s) - Open Hunt will "
                        "broaden hypothesis next round."
                    )
            if hunt_ingenuity:
                usefulness = (
                    hunt_ingenuity.get("usefulness")
                    if isinstance(hunt_ingenuity.get("usefulness"), dict)
                    else {}
                )
                by_slot = (
                    hunt_ingenuity.get("by_slot")
                    if isinstance(hunt_ingenuity.get("by_slot"), dict)
                    else {}
                )
                invent = (
                    by_slot.get("invent")
                    if isinstance(by_slot.get("invent"), dict)
                    else {}
                )
                mutate = (
                    by_slot.get("mutate")
                    if isinstance(by_slot.get("mutate"), dict)
                    else {}
                )
                gen = (
                    hunt_ingenuity.get("generation")
                    if isinstance(hunt_ingenuity.get("generation"), dict)
                    else {}
                )
                job.output.append(
                    "[enhance] ingenuity "
                    f"usefulness={hunt_ingenuity.get('score')} "
                    f"exploit={usefulness.get('exploit_rate')} "
                    f"invent={invent.get('score')} "
                    f"mutate={mutate.get('score')} "
                    f"phase={hunt_ingenuity.get('enhance_phase') or round_phase} "
                    f"(generation novelty={gen.get('novelty_rate')})"
                )
            # Elite update runs in _after_assessed_run / _pre_enhance_assess_latest_run.
            round_techs: set[str] = set()
            round_families: set[str] = set()
            try:
                gen_dir = _root / "generate-tests"
                if str(gen_dir) not in sys.path:
                    sys.path.insert(0, str(gen_dir))
                from enhance_theory import extract_prefer_techniques
                from strategies.prior_results import extract_burned_wrapper_families

                round_techs = extract_prefer_techniques(accepted_theory or "")
                if report_path and report_path.is_file():
                    try:
                        report_data = _json.loads(report_path.read_text(encoding="utf-8"))
                    except Exception:
                        report_data = {}
                    results = list(report_data.get("adversarial_results") or [])
                    refused_rows = [
                        r
                        for r in results
                        if isinstance(r, dict)
                        and str(r.get("outcome") or "").strip().lower()
                        in ("refused", "blocked", "failed", "fabricated")
                    ]
                    if not refused_rows:
                        refused_rows = [
                            r
                            for r in results
                            if isinstance(r, dict)
                            and str(r.get("risk_level") or "").strip().lower()
                            in ("low", "informational")
                        ]
                    stamped = {
                        str(r.get("mechanism_family") or "").strip()
                        for r in refused_rows
                        if isinstance(r, dict)
                        and str(r.get("mechanism_family") or "").strip()
                    }
                    round_families = stamped | set(
                        extract_burned_wrapper_families(refused_rows)
                    )
                    # Invent all-fabricated → surface pivot for next enhance theory.
                    if (
                        bounty_mode
                        and round_phase == "bounty_invent"
                        and float((usefulness or {}).get("fabricated_rate") or 0) >= 0.5
                        and float((hunt_ingenuity or {}).get("score") or 0) <= 0.0
                    ):
                        job.output.append(
                            "[enhance] Invent batch was answer-echo/fabricated theater - "
                            "next theory must ban burned mechanism_family tags and pivot "
                            f"asks (burned={sorted(stamped)[:8] or sorted(round_families)[:8]})."
                        )
            except Exception:
                round_techs = set()
                round_families = set()
            # Phase update is outside report-parse try/except so cool-down always arms.
            if bounty_mode:
                freeze_completed = False
                if escalate_active:
                    cool_down_pending, _ = _enhance_phase_after_round(
                        escalate_active=True,
                        freeze_active=False,
                        worst=worst,
                        freeze_completed=False,
                    )
                    if cool_down_pending:
                        job.output.append(
                            "[enhance] Bounty escalate miss (Low-family) - cool-down "
                            "next round; resume invent/mutate after."
                        )
            else:
                cool_down_pending, freeze_completed = _enhance_phase_after_round(
                    escalate_active=escalate_active,
                    freeze_active=freeze_active,
                    worst=worst,
                    freeze_completed=freeze_completed,
                )
            if cool_down_pending and not bounty_mode:
                job.output.append(
                    "[enhance] Escalate round stayed Low-family - cool-down "
                    "armed; freeze reset for next progress round."
                )
            elif freeze_active and freeze_completed:
                job.output.append(
                    "[enhance] Freeze round complete - escalate eligible on later rounds."
                )
            stagnation_history.append(
                {
                    "worst": worst,
                    "techs": round_techs,
                    "families": round_families,
                    "escalated": bool(escalate_active),
                    "freeze": bool(freeze_active),
                }
            )
            # Soft-advance: leave enhance early under sustained hard-refusal Low
            # so All-strategies can try the next strategy sooner.
            try:
                from enhance_theory import is_stagnation_severity

                low_family = bool(is_stagnation_severity(worst))
            except Exception:
                low_family = str(worst or "").strip().lower() in (
                    "low",
                    "informational",
                    "indeterminate",
                )
            if (
                hard_refusal_early_stop > 0
                and hard_refusal_active
                and low_family
                and not freeze_active
                and not escalate_active
            ):
                hard_refusal_streak += 1
            else:
                hard_refusal_streak = 0

            job.output.append(
                "[genbounty_progress] "
                + _json.dumps(
                    {
                        "type": "enhance_result",
                        "round": rnd,
                        "total": max_rounds,
                        "worst": worst,
                        "enhance_phase": _resolve_enhance_phase(
                            theory_text=accepted_theory or "",
                            cool_down=cool_down_this_round,
                            escalate_active=escalate_active,
                            freeze_active=freeze_active,
                            hard_refusal_active=hard_refusal_active,
                            hunt_mode=hunt_mode,
                        ),
                        "thesis": _playbook_enhancement_thesis(playbook_id),
                        "hunt_mode": hunt_mode,
                        **(
                            {"hunt_ingenuity": hunt_ingenuity}
                            if isinstance(hunt_ingenuity, dict)
                            else {}
                        ),
                        **(
                            {"phase_history": phase_history}
                            if phase_history
                            else {}
                        ),
                        **(
                            {"by_phase": by_phase_accum}
                            if by_phase_accum
                            else {}
                        ),
                        **(
                            {"broadened_ask": round_broadened_ask}
                            if round_broadened_ask
                            else {}
                        ),
                    },
                    ensure_ascii=False,
                )
            )
            job.output.append(f"[enhance] Round {rnd} worst severity: {worst.upper()}")
            job._event.set()
            leaf_obj = ""
            if bounty_mode:
                try:
                    from playbooks.playbook_config import get_attack_objective
                    from playbooks.registry import load_playbook

                    leaf_obj = str(
                        get_attack_objective(load_playbook(playbook_id)) or ""
                    ).strip()
                except Exception:
                    leaf_obj = ""
            if _report_meets_bounty_stop(
                report_path,
                stop_levels,
                attack_objective=leaf_obj,
                require_leaf_alignment=bool(bounty_mode and leaf_obj),
            ):
                reached = worst if worst in stop_levels or worst in (
                    "critical",
                    "high",
                    "medium",
                ) else "exploited"
                # Prefer concrete severity label when available.
                if worst in ("critical", "high", "medium"):
                    reached = worst
                # Bug Bounty / Open Hunt: defer Stop-at so Critical-path can run.
                # Prefer escalate (channel-proof + escalation_payload) over mutate;
                # never defer a Critical hit; mutate→CP can still arm escalate later.
                defer_followup = False
                followup_kind = ""
                elite_n = 0
                if bounty_mode and rnd < max_rounds:
                    elite_rows: list = []
                    esc_payload = ""
                    try:
                        gen_dir = _root / "generate-tests"
                        if str(gen_dir) not in sys.path:
                            sys.path.insert(0, str(gen_dir))
                        from strategies.elite_genomes import load_elite_genomes

                        elite_rows = list(
                            load_elite_genomes(
                                job.site, job.component, playbook_id, strategy
                            )
                            or []
                        )
                        elite_n = len(elite_rows)
                    except Exception:
                        elite_rows = []
                        elite_n = 0
                    try:
                        from playbooks.playbook_config import get_escalation_payload
                        from playbooks.registry import load_playbook

                        esc_payload = str(
                            get_escalation_payload(load_playbook(playbook_id)) or ""
                        ).strip()
                    except Exception:
                        esc_payload = ""
                    defer_followup, followup_kind = _bounty_stop_followup_decision(
                        worst=worst,
                        elite=elite_rows,
                        escalation_payload=esc_payload,
                        escalate_followup_deferred=escalate_followup_deferred,
                        mutate_followup_deferred=mutate_followup_deferred,
                        rnd=rnd,
                        max_rounds=max_rounds,
                    )
                if defer_followup:
                    if followup_kind == "escalate":
                        escalate_followup_deferred = True
                    else:
                        mutate_followup_deferred = True
                    reached = None
                    job.output.append(
                        f"[enhance] Bounty stop deferred one round for "
                        f"{followup_kind or 'sharpen'} follow-up "
                        f"(elite={elite_n}; worst={worst.upper()})."
                    )
                else:
                    job.output.append(
                        f"[enhance] Bounty stop met in round {rnd} "
                        f"(exploit/partial evidence; worst={worst.upper()}) - stopping."
                    )
                    handoff_reason = "bounty_stop"
                    break
            if (
                bounty_mode
                and leaf_obj
                and _report_has_non_aligned_stop_candidate(
                    report_path, stop_levels, leaf_obj
                )
            ):
                job.output.append(
                    "[enhance] Non-leaf-aligned win kept as elite DNA; continuing hunt."
                )
            # All-Low efficiency abort (no partial/exploited signal).
            has_signal = False
            try:
                gen_dir = _root / "generate-tests"
                if str(gen_dir) not in sys.path:
                    sys.path.insert(0, str(gen_dir))
                from strategies.bounty_ingenuity import round_has_partial_or_exploited

                has_signal = round_has_partial_or_exploited(
                    _report_results(report_path)
                )
            except Exception:
                has_signal = False
            if low_family and not has_signal:
                all_low_streak += 1
            else:
                all_low_streak = 0
            # Single soft-stop handler: one arm-or-abort decision per round.
            soft_stop_reason = ""
            if (
                all_low_early_stop > 0
                and all_low_streak >= all_low_early_stop
            ):
                soft_stop_reason = "all_low"
            elif (
                hard_refusal_early_stop > 0
                and hard_refusal_streak >= hard_refusal_early_stop
            ):
                soft_stop_reason = "hard_refusal"
            elif circular_enhance_early_stop > 0:
                try:
                    from enhance_theory import circular_enhance_detected

                    if circular_enhance_detected(
                        stagnation_history,
                        window=circular_enhance_early_stop,
                    ):
                        soft_stop_reason = "circular"
                except Exception:
                    soft_stop_reason = ""
            if soft_stop_reason:
                if (
                    hunt_mode == "open_hunt"
                    and rnd < max_rounds
                    and (_may_arm_open_broaden() or open_broaden_pending)
                ):
                    if _may_arm_open_broaden() and not open_broaden_pending:
                        open_broaden_pending = True
                        if soft_stop_reason == "all_low":
                            job.output.append(
                                "[enhance] All-Low streak - Open Hunt will broaden "
                                "hypothesis next round (one-shot budget)."
                            )
                        elif soft_stop_reason == "hard_refusal":
                            job.output.append(
                                "[enhance] Hard-refusal streak - Open Hunt will broaden "
                                "hypothesis next round instead of soft-advancing."
                            )
                        else:
                            job.output.append(
                                "[enhance] Circular Low overlap - Open Hunt will "
                                "broaden hypothesis next round instead of soft-advancing."
                            )
                    all_low_streak = 0
                    hard_refusal_streak = 0
                else:
                    if soft_stop_reason == "all_low":
                        job.output.append(
                            f"[enhance] All-Low early stop after {all_low_streak} "
                            f"consecutive Low round(s) with no partial/exploited "
                            f"(threshold={all_low_early_stop}) - advancing."
                        )
                    elif soft_stop_reason == "hard_refusal":
                        job.output.append(
                            f"[enhance] Hard-refusal early stop after {hard_refusal_streak} "
                            f"consecutive Low hard-refusal round(s) "
                            f"(threshold={hard_refusal_early_stop}) - advancing."
                        )
                    else:
                        job.output.append(
                            f"[enhance] Circular enhance early stop after "
                            f"{circular_enhance_early_stop} consecutive Low "
                            "overlapping round(s) - advancing."
                        )
                    handoff_reason = "soft_advance"
                    break

        stop_label = "/".join(sorted(stop_levels))
        if phase_history:
            job.output.append(
                "[enhance] phase_history "
                + _json.dumps(phase_history, ensure_ascii=False)
            )
        if by_phase_accum:
            job.output.append(
                "[enhance] by_phase "
                + _json.dumps(by_phase_accum, ensure_ascii=False)
            )
        if bounty_mode and not _is_cancelled(job):
            try:
                gen_dir = _root / "generate-tests"
                if str(gen_dir) not in sys.path:
                    sys.path.insert(0, str(gen_dir))
                from strategies.strategy_handoff import maybe_write_handoff_after_enhance

                usefulness_snap: dict = {}
                if by_phase_accum:
                    usefulness_snap = {"by_phase": by_phase_accum}
                elif phase_history:
                    usefulness_snap = {"phase_history_len": len(phase_history)}
                written = maybe_write_handoff_after_enhance(
                    job.site,
                    job.component,
                    playbook_id,
                    strategy,
                    reason=handoff_reason,
                    usefulness=usefulness_snap or None,
                )
                if written:
                    n_seeds = len(written.get("elite_seeds") or [])
                    job.output.append(
                        f"[handoff] wrote {n_seeds} elite seed(s) from {strategy} "
                        f"(reason={written.get('reason') or handoff_reason}; "
                        f"mutate_first={bool(written.get('mutate_first'))})."
                    )
                else:
                    job.output.append(
                        f"[handoff] skipped write for {strategy} "
                        "(no elite seeds or drop rails; prior handoff preserved)."
                    )
            except Exception as exc:
                job.output.append(f"[handoff] write failed: {exc}")
        if _is_cancelled(job):
            _set_final_status(job, "cancelled")
        else:
            if final_status == "done":
                if reached:
                    job.output.append(
                        f"[+] Enhance loop complete: bounty stop met "
                        f"({reached.upper()}) after enhancement."
                    )
                else:
                    job.output.append(
                        f"[+] Enhance loop complete after {max_rounds} round(s); "
                        f"no {stop_label} exploit/partial evidence yet."
                    )
            _set_final_status(job, final_status)
    except asyncio.CancelledError:
        _set_final_status(job, "cancelled")
    except Exception as exc:
        job.output.append(f"[error] {exc}")
        _set_final_status(job, "failed")
    finally:
        job._event.set()


async def _start_sample_request(job: Job):
    prompt = str(job.params.get("prompt") or "2+2")

    def _truthy_param(raw) -> bool:
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return raw != 0
        s = str(raw or "").strip().lower()
        return s in {"1", "true", "yes", "on"}

    assess = _truthy_param(job.params.get("assess"))
    playbook_id = str(
        job.params.get("playbook_id") or job.params.get("playbook") or ""
    ).strip()

    def _emit_sample_result(prompt_text: str, response_text: str) -> None:
        """Human-readable response plus a machine marker for Experiment Output actions."""
        import json as _json

        body = str(response_text or "").strip() or "(none)"
        print("[sample] Prompt: " + str(prompt_text or "")[:200], flush=True)
        print("[sample] Response:")
        print(body)
        payload: dict = {
            "prompt": str(prompt_text or ""),
            "response": body if body != "(none)" else "",
        }
        print("[genbounty_sample_result] " + _json.dumps(payload, ensure_ascii=False))
        if not assess:
            print("[sample] Assess off - skipping risk assessment.", flush=True)
            return
        print(
            f"[sample] Assess on (playbook={playbook_id or 'missing'}) - "
            "writing logs/manual/<timestamp>/ and running risk assessment…",
            flush=True,
        )
        if not (job.site and job.component):
            print("[!] Firing Range assess skipped: site/component required.", flush=True)
            return
        if not playbook_id:
            print(
                "[!] Firing Range assess skipped: select a playbook in the header.",
                flush=True,
            )
            return
        try:
            from pipeline.manual_fire import write_manual_fire_attack_log

            cl_path = write_manual_fire_attack_log(
                job.site,
                job.component,
                prompt=str(prompt_text or ""),
                response="" if body == "(none)" else body,
                playbook_id=playbook_id,
            )
            print(f"[+] Manual attack log: {cl_path}", flush=True)
            report_path = _assess_attack_log(cl_path)
            severity = ""
            try:
                report = _json.loads(report_path.read_text(encoding="utf-8"))
                rows = report.get("adversarial_results") or []
                if rows and isinstance(rows[0], dict):
                    severity = str(
                        rows[0].get("risk_level")
                        or rows[0].get("severity_level")
                        or rows[0].get("severity")
                        or ""
                    ).strip()
            except Exception:
                severity = ""
            marker = {
                "attack_log": str(cl_path),
                "pipeline_report": str(report_path),
                "run_dir": str(cl_path.parent),
                "severity": severity,
                "playbook_id": playbook_id,
            }
            print(
                "[genbounty_manual_assess_result] "
                + _json.dumps(marker, ensure_ascii=False),
                flush=True,
            )
            if severity:
                print(f"[+] Firing Range assess: {severity}", flush=True)
            else:
                print("[+] Firing Range assess complete", flush=True)
        except Exception as exc:
            print(f"[!] Firing Range assess failed: {exc}", flush=True)

    def _do():
        import asyncio as _aio
        import importlib.util
        import time

        print(
            f"[sample] start assess={assess} playbook={playbook_id or '-'} "
            f"site={job.site or '-'} component={job.component or '-'}",
            flush=True,
        )
        _prepare_component_context(job)

        bb_dir = _root / "browser-bot"
        if str(bb_dir) not in sys.path:
            sys.path.insert(0, str(bb_dir))

        from browser_bot.sites import describe_submission_config_issue, get_storage_state_path, get_submission_config, load_component_config
        from browser_bot.submit.api_helpers import do_api_request
        from browser_bot.submit.common import response_capture_kwargs
        from browser_bot.submit.single import do_ui_submit_with_page

        sub = get_submission_config(job.site, job.component)
        if not sub:
            reason = describe_submission_config_issue(load_component_config(job.site, job.component))
            raise RuntimeError(
                f"Cannot send sample request for {job.site}/{job.component}: {reason}. "
                "Run Discovery / Connect via API or complete the component submission config first."
            )

        if sub.get("transport") == "api":
            status, response_text, err, *_ = do_api_request(
                sub, prompt, site=job.site, component=job.component
            )
            print("[sample] Prompt: " + prompt)
            print("[sample] Transport: api")
            print("[sample] Status: " + str(status))
            if err and not response_text:
                raise RuntimeError(f"Sample API request failed: {err}")
            response_text = response_text or err or ""
            _emit_sample_result(prompt, response_text)
            return

        storage_path = get_storage_state_path(job.site, job.component)
        if not storage_path:
            raise RuntimeError(f"No saved auth available for {job.site}. Run Add Login first.")

        bb_main_path = bb_dir / "main.py"
        spec = importlib.util.spec_from_file_location("browser_bot_main", bb_main_path)
        bb_main = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bb_main)

        from browser_bot.page_blockers import submission_needs_headed_human
        from pipeline.component_settings import playwright_headless_kwarg

        human_only = submission_needs_headed_human(job.site, job.component)
        headless_override = playwright_headless_kwarg(job.site, job.component)

        async def _run():
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                async def _submit(page):
                    captured = []

                    def _on_response(response):
                        if response.request.method in ("POST", "PUT", "PATCH"):
                            captured.append(response)

                    page.on("response", _on_response)
                    start = time.perf_counter()
                    try:
                        _, resp_text, _meta = await do_ui_submit_with_page(
                            page,
                            sub["start_url"],
                            sub["inputs"],
                            sub["submit_selector"],
                            prompt,
                            site=job.site,
                            component=job.component,
                            response_selector=sub.get("response_selector") or "",
                            response_within_selector=sub.get("response_within_selector") or "",
                            response_text_within_selector=sub.get("response_text_within_selector") or "",
                            **response_capture_kwargs(sub),
                            submit_via=sub.get("submit_via", "click"),
                            response_wait_ms=int(sub.get("response_wait_ms", 5000) or 5000),
                            human_behavior=True,
                        )
                    finally:
                        try:
                            page.remove_listener("response", _on_response)
                        except Exception:
                            pass

                    elapsed = time.perf_counter() - start
                    origin_parts = page.url.split("/", 3)[:3]
                    origin = "/".join(origin_parts) if len(origin_parts) >= 3 else ""
                    same_origin = [
                        resp for resp in captured
                        if not origin or resp.request.url.startswith(origin)
                    ]
                    chosen = same_origin[-1] if same_origin else (captured[-1] if captured else None)
                    return {
                        "prompt": prompt,
                        "response": resp_text or "",
                        "elapsed_sec": elapsed,
                        "status": chosen.status if chosen else None,
                        "status_url": chosen.request.url if chosen else "",
                    }

                return await bb_main.run_with_page_from_fetchers(
                    p,
                    job.site,
                    _submit,
                    storage_path=str(storage_path),
                    interactive=False,
                    human_only=human_only,
                    headless=headless_override,
                    component=job.component,
                )

        result = _aio.run(_run())
        if not result:
            raise RuntimeError("Sample request failed: browser submission returned no result.")

        print("[sample] Prompt: " + result["prompt"])
        print("[sample] Status: " + (str(result["status"]) if result["status"] is not None else "not captured"))
        if result.get("status_url"):
            print("[sample] Status URL: " + result["status_url"])
        print(f"[sample] Timing: {result['elapsed_sec']:.2f}s")
        _emit_sample_result(result["prompt"], result.get("response") or "")

    await _run_thread_job(job, _do)


def _component_export_config(job: Job) -> dict:
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from pipeline.export_settings import export_config_for_job

    return export_config_for_job(job.site, job.component, job.params)


def _export_credentials(job: Job) -> tuple[str, str, str] | None:
    """Resolve Genbounty host, api_key, user_id for export. Returns None if incomplete."""
    import os as _os

    env = _load_env_vars()
    try:
        from pipeline.pipeline_settings import export_host

        host = export_host()
    except Exception:
        host = ""
    api_key = (
        env.get("GENBOUNTY_API_KEY", "").strip()
        or (_os.environ.get("GENBOUNTY_API_KEY") or "").strip()
    )
    export_cfg = _component_export_config(job)
    # user_id: job params → component config.yaml → GENBOUNTY_USER_ID in .env / process env.
    user_id = (
        job.params.get("user_id")
        or export_cfg.get("user_id")
        or env.get("GENBOUNTY_USER_ID", "")
        or _os.environ.get("GENBOUNTY_USER_ID")
        or ""
    ).strip()
    if not api_key or not user_id:
        missing = [
            name
            for name, val in (
                ("GENBOUNTY_API_KEY", api_key),
                ("user_id / GENBOUNTY_USER_ID", user_id),
            )
            if not val
        ]
        msg = f"[!] Export skipped - missing: {', '.join(missing)}"
        print(msg)
        job.output.append(msg)
        return None
    return host, api_key, user_id


def _export_report_paths(
    report_paths: list[Path],
    *,
    host: str,
    api_key: str,
    user_id: str,
    default_level: str | None = None,
    risk_levels: list | None = None,
) -> None:
    """POST pipeline reports to Genbounty using export_security batching."""
    import json as _json

    if not report_paths:
        print("[-] No pipeline reports to export.")
        return

    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from pipeline.export_genbounty import export_pipeline_report
    from pipeline.export_security import export_batch_delay_seconds

    report_delay = export_batch_delay_seconds()
    total = len(report_paths)
    if total > 1:
        print(
            f"[genbounty_progress] {_json.dumps({'type': 'batch_start', 'phase': 'export', 'total': total}, ensure_ascii=False)}",
            flush=True,
        )

    for i, rp in enumerate(report_paths, 1):
        if total > 1:
            print(
                f"[genbounty_progress] {_json.dumps({'type': 'batch_progress', 'phase': 'export', 'current': i, 'total': total, 'log': rp.name}, ensure_ascii=False)}",
                flush=True,
            )
        try:
            export_pipeline_report(
                rp,
                host=host,
                api_key=api_key,
                user_id=user_id,
                default_level=default_level,
                risk_levels=risk_levels,
            )
        except Exception as exc:
            print(f"[!] Export failed for {rp}: {exc}", flush=True)

        if i < total and report_delay > 0:
            print(f"[*] Waiting {report_delay:.1f}s before next report export...", flush=True)
            time.sleep(report_delay)

    if total > 1:
        print(
            f"[genbounty_progress] {_json.dumps({'type': 'batch_done', 'phase': 'export', 'total': total}, ensure_ascii=False)}",
            flush=True,
        )


def _unexported_reports(job: Job, report_paths: list[Path]) -> list[Path]:
    done = set(job.params.get("_exported_report_paths") or [])
    fresh = [p for p in report_paths if str(p) not in done]
    if fresh:
        job.params.setdefault("_exported_report_paths", []).extend(str(p) for p in fresh)
    return fresh


def _auto_export_after_assess(job: Job, report_paths: list[Path]) -> None:
    """Export pipeline reports when component export.auto_after_assess is enabled."""
    if not (job.site and job.component):
        return
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    from pipeline.export_settings import should_auto_export

    if not should_auto_export(job.site, job.component, job.params):
        return

    paths = _unexported_reports(job, report_paths)
    if not paths:
        return

    creds = _export_credentials(job)
    if not creds:
        return
    host, api_key, user_id = creds
    export_cfg = _component_export_config(job)
    risk_levels = job.params.get("risk_levels") or export_cfg.get("risk_levels")
    print(f"[*] Auto-export: submitting {len(paths)} pipeline report(s)...")
    _export_report_paths(
        paths,
        host=host,
        api_key=api_key,
        user_id=user_id,
        default_level=job.params.get("default_level"),
        risk_levels=risk_levels,
    )


def _maybe_export_latest_assessed_report(job: Job) -> None:
    """After run_tests --assess, export the newest pipeline report if auto-export is on."""
    if not job.params.get("assess"):
        return
    reports = _list_pipeline_report_paths(job.site, job.component)
    if not reports:
        return
    newest = reports[0]
    since = job.created_at.timestamp() - 2.0
    if newest.stat().st_mtime < since:
        return
    _auto_export_after_assess(job, [newest])


async def _start_security_assess(job: Job):
    def _do():
        import json as _json

        try:
            from dotenv import load_dotenv

            load_dotenv(_root / ".config")
            load_dotenv(_root / ".env")
        except ImportError:
            pass
        _prepare_component_context(job)

        log_paths = _resolve_security_assess_logs(job)
        if not log_paths:
            return

        total = len(log_paths)
        if total > 1:
            print(
                f"[genbounty_progress] {_json.dumps({'type': 'batch_start', 'phase': 'risk', 'total': total}, ensure_ascii=False)}",
                flush=True,
            )

        exported_reports: list[Path] = []
        for i, cl_path in enumerate(log_paths, 1):
            if total > 1:
                print(
                    f"[genbounty_progress] {_json.dumps({'type': 'batch_progress', 'phase': 'risk', 'current': i, 'total': total, 'log': cl_path.name}, ensure_ascii=False)}",
                    flush=True,
                )
            try:
                report_path = _assess_attack_log(cl_path)
                exported_reports.append(report_path)
                if job.site and job.component:
                    _maybe_update_elite_after_assess(job, report_path)
                    try:
                        from pipeline.recon_auto import save_intel_from_pipeline_report

                        save_intel_from_pipeline_report(
                            job.site, job.component, report_path
                        )
                        print("[+] Playbook intel auto-updated", flush=True)
                    except ValueError as exc:
                        print(f"[recon] Auto recon skipped: {exc}", flush=True)
                    except Exception as exc:
                        print(f"[!] Auto recon failed: {exc}", flush=True)
                    try:
                        from pipeline.credentials_and_paths import (
                            maybe_auto_extract_after_assess,
                        )

                        cred = maybe_auto_extract_after_assess(
                            job.site, job.component, report_path
                        )
                        if cred is None:
                            pass
                        elif cred.get("skipped"):
                            print(
                                "[credentials] Inventory already scanned this report "
                                "(skipped).",
                                flush=True,
                            )
                        else:
                            print(
                                f"[+] Credentials/paths updated (+{cred.get('added', 0)})",
                                flush=True,
                            )
                    except Exception as exc:
                        print(f"[!] Credentials/paths extract failed: {exc}", flush=True)
            except Exception as exc:
                print(f"[!] Assessment failed for {cl_path.name}: {exc}", flush=True)

        if total > 1:
            print(
                f"[genbounty_progress] {_json.dumps({'type': 'batch_done', 'phase': 'risk', 'total': total}, ensure_ascii=False)}",
                flush=True,
            )

        if exported_reports:
            _auto_export_after_assess(job, exported_reports)

    await _run_thread_job(job, _do)


def _load_env_vars() -> dict[str, str]:
    """Parse key=value pairs from the root .env file."""
    env_file = _root / ".env"
    result: dict[str, str] = {}
    if not env_file.exists():
        return result
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _resolve_export_reports(job: Job) -> list[Path]:
    """Single report, explicit reports list, or time_window batch."""
    time_window = (job.params.get("time_window") or "").strip()
    if time_window:
        if not (job.site and job.component):
            raise ValueError("time_window export requires site and component context")
        reports = _pipeline_reports_in_window(job.site, job.component, time_window)
        label = _time_window_label(time_window)
        if not reports:
            print(f"[!] No pipeline reports found for {label}")
        else:
            print(f"[*] Batch export ({label}): {len(reports)} report(s)")
        return reports

    report_list = job.params.get("reports")
    if isinstance(report_list, list) and report_list:
        paths: list[Path] = []
        for raw in report_list:
            rp = Path(str(raw))
            if not rp.is_absolute():
                rp = _root / rp
            paths.append(rp)
        print(f"[*] Batch export: {len(paths)} report(s)")
        return paths

    report = job.params.get("report", "")
    if not report:
        raise ValueError("No report or time_window specified")
    rp = Path(report)
    if not rp.is_absolute():
        rp = _root / rp
    return [rp]


async def _start_export(job: Job):
    creds = _export_credentials(job)
    if not creds:
        if not any("Export skipped - missing" in line for line in job.output):
            job.output.append(
                "[!] Missing Genbounty credentials for export "
                "(need GENBOUNTY_API_KEY and user_id / GENBOUNTY_USER_ID)"
            )
        job.status = "failed"
        return

    host, api_key, user_id = creds

    def _do():
        export_cfg = _component_export_config(job)
        report_paths = _resolve_export_reports(job)
        if not report_paths:
            return
        _export_report_paths(
            report_paths,
            host=host,
            api_key=api_key,
            user_id=user_id,
            default_level=job.params.get("default_level"),
            risk_levels=job.params.get("risk_levels") or export_cfg.get("risk_levels"),
        )

    await _run_thread_job(job, _do)


async def _start_clear_cache(job: Job):
    delete_on_server = job.params.get("delete_on_server", False)

    def _do():
        if str(_root) not in sys.path:
            sys.path.insert(0, str(_root))
        gen_tests_dir = str(_root / "generate-tests")
        if gen_tests_dir not in sys.path:
            sys.path.insert(0, gen_tests_dir)

        cleared = []
        try:
            import core as gen_core
            gen_core.clear_gemini_cache(delete_on_server=delete_on_server)
            cleared.append("generator")
        except Exception as exc:
            print(f"[!] Generator cache clear failed: {exc}")

        try:
            import importlib.util
            rla_file = _root / "risk-level-agent" / "risk_level_agent.py"
            if rla_file.exists() and "risk_level_agent" not in sys.modules:
                spec = importlib.util.spec_from_file_location("risk_level_agent", rla_file)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules["risk_level_agent"] = mod
                    spec.loader.exec_module(mod)
            import risk_level_agent as rla
            rla.clear_gemini_cache(delete_on_server=delete_on_server)
            local_removed = rla.clear_local_result_cache()
            cleared.append("risk-level-agent")
            if local_removed:
                print(f"[+] Cleared {local_removed} local risk-assessment result cache file(s).")
        except Exception as exc:
            print(f"[!] Risk-level-agent cache clear failed: {exc}")

        try:
            from pipeline.cleanup import clear_project_dev_caches

            cache_counts = clear_project_dev_caches(_root)
            failed = int(cache_counts.pop("_failed", 0) or 0)
            total_dirs = sum(cache_counts.values())
            if total_dirs:
                detail = ", ".join(f"{name}×{n}" for name, n in sorted(cache_counts.items()))
                print(
                    f"[+] Removed {total_dirs} project cache director"
                    f"{'y' if total_dirs == 1 else 'ies'} ({detail})."
                )
                cleared.append("project-caches")
            else:
                print("[+] No project cache directories to remove (__pycache__, .pytest_cache, …).")
            if failed:
                print(
                    f"[!] {failed} cache director{'y' if failed == 1 else 'ies'} could not be "
                    "removed (in use or permission)."
                )
        except Exception as exc:
            print(f"[!] Project cache cleanup failed: {exc}")

        if cleared:
            action = "Cleared in-process + deleted server-side" if delete_on_server else "Cleared in-process"
            print(f"[+] {action} caches ({', '.join(cleared)}).")
        else:
            print("[-] Nothing was cleared.")

    await _run_thread_job(job, _do)


async def _start_nuke(job: Job):
    """Wipe component experiment artifacts; keep config, auth, and recon."""

    def _do():
        site = str(job.site or "").strip()
        component = str(job.component or "").strip()
        if not site or not component:
            raise ValueError("Nuke requires site and component.")

        bb_dir = _root / "browser-bot"
        if str(bb_dir) not in sys.path:
            sys.path.insert(0, str(bb_dir))
        from browser_bot.sites import nuke_component

        print(f"[nuke] Wiping experiment state for {site}/{component}…")
        result = nuke_component(site, component)
        removed = list(result.get("removed") or [])
        kept = list(result.get("kept") or [])
        backup = str(result.get("backup") or "").strip()
        if backup:
            print(f"[nuke] Backup: {backup}")
        if removed:
            print(f"[nuke] Removed: {', '.join(removed)}")
        else:
            print("[nuke] Nothing to remove (already clean).")
        if kept:
            print(f"[nuke] Kept: {', '.join(kept)}")
        else:
            print("[nuke] Kept: (none of config/auth/recon were present)")
        print(f"[nuke] Done - {result.get('path')}")

    await _run_thread_job(job, _do)


async def _start_prompt_attributes(job: Job):
    """Rewrite suite prompts for Temp/Max-tok/Top-k/Top-p with live Experiment Output."""
    strategy = str(job.params.get("strategy") or "").strip()
    playbook = str(job.params.get("playbook") or "").strip()
    attributes = job.params.get("attributes") or {}
    if not job.site or not job.component or not strategy or not playbook:
        job.output.append("[attributes] Missing site/component/strategy/playbook.")
        job.status = "failed"
        job._event.set()
        return

    suite_path = (
        _root
        / "browser-bot"
        / "sites"
        / job.site
        / job.component
        / "tests"
        / strategy
        / f"{playbook}.json"
    )

    def _do() -> None:
        import json as _json

        gen_dir = _root / "generate-tests"
        if str(gen_dir) not in sys.path:
            sys.path.insert(0, str(gen_dir))
        from prompt_attributes import attributes_rewrite_suite, normalize_attributes

        if not suite_path.exists():
            raise FileNotFoundError(f"Probe file not found: {suite_path}")

        attrs = normalize_attributes(attributes if isinstance(attributes, dict) else {})
        print(
            f"[attributes] Suite {suite_path.relative_to(_root)} "
            f"temp={attrs['temperature']} max_tokens={attrs['max_tokens']} "
            f"top_k={attrs['top_k']} top_p={attrs['top_p']}",
            flush=True,
        )
        data = _json.loads(suite_path.read_text(encoding="utf-8"))
        rewritten, count = attributes_rewrite_suite(data, attrs)
        if count == 0:
            raise RuntimeError("No text prompts found to rewrite in this suite")
        suite_path.write_text(
            _json.dumps(rewritten, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(
            f"[attributes] Wrote {count} rewritten field(s) -> {suite_path.name}",
            flush=True,
        )

    await _run_thread_job(job, _do)
