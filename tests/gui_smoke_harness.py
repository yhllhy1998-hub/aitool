"""Minimal, honest Windows GUI/EXE startup harness for the Phase 2B spike.

The harness only automates process startup and filesystem observations.  It
does not synthesize Tk, drag/drop, scrolling, icon, geometry, or theme
evidence.  Those matrix entries are deliberately reported as ``manual`` or
``not_run`` until a visible Windows run supplies evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPO_ROOT / ".slim" / "deepwork" / "evidence"
PYTHON_EXECUTABLE = Path(sys.executable).resolve()
STARTUP_TIMEOUT_SECONDS = 30.0
TERMINATE_WAIT_SECONDS = 5.0
STARTUP_SETTLE_SECONDS = 2.0
CONFIGURATION_SETTLE_TIMEOUT_SECONDS = 5.0
CONFIGURATION_RETRY_INTERVAL_SECONDS = 0.25
CLEANUP_RETRY_TIMEOUT_SECONDS = 5.0
CLEANUP_RETRY_INTERVAL_SECONDS = 0.25
ALLOWED_STATUSES = {"pass", "fail", "manual", "not_run"}

MATRIX_NAMES = (
    "title_AiTool",
    "no_Unhandled_exception",
    "first_configuration_initialization",
    "shell_icon_folder",
    "shell_icon_regular_file",
    "shell_icon_associated_type",
    "file_URL_drop",
    "file_icon_drag_out",
    "dynamic_refresh_DND",
    "Ctrl_V_paste",
    "station_internal_scroll",
    "actions_independent_scroll",
    "fixed_statusbar",
    "window_default_min_max",
    "geometry_corrupt_fallback",
    "geometry_restore_clamp",
    "light_dark_readability",
)


@dataclass
class Check:
    name: str
    status: str
    details: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in ALLOWED_STATUSES:
            raise ValueError(f"unsupported smoke status: {self.status}")

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "status": self.status,
            "details": self.details,
        }
        if self.evidence:
            payload["evidence"] = self.evidence
        return payload


@dataclass
class Target:
    kind: str
    identifier: str
    command: list[str]
    cwd: Path
    configuration_root: Path
    environment: dict[str, str]
    temporary_root: Path | None = None


@dataclass
class ProcessObservation:
    started_at: str
    ended_at: str
    returncode: int | None
    timed_out: bool
    output: str
    cleanup: dict[str, Any]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _copy_source_tree() -> Target:
    """Run source from an isolated copy so its fixed ``repo/data`` is safe."""

    temporary_root = Path(tempfile.mkdtemp(prefix="aitool-gui-source-"))
    worktree = temporary_root / "worktree"
    shutil.copytree(
        REPO_ROOT,
        worktree,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "build", "dist"),
    )
    appdata = temporary_root / "appdata"
    appdata.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    # Source mode ignores APPDATA by design; this value still prevents any
    # dependency from writing to the operator's real profile.
    environment["APPDATA"] = str(appdata)
    return Target(
        kind="source",
        identifier=str(worktree / "run_desktop_tool.py"),
        command=[str(PYTHON_EXECUTABLE), str(worktree / "run_desktop_tool.py")],
        cwd=worktree,
        configuration_root=worktree / "data",
        environment=environment,
        temporary_root=temporary_root,
    )


def _prepare_exe(exe_path: Path) -> Target:
    temporary_root = Path(tempfile.mkdtemp(prefix="aitool-gui-exe-"))
    appdata = temporary_root / "APPDATA"
    appdata.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["APPDATA"] = str(appdata)
    return Target(
        kind="exe",
        identifier=str(exe_path),
        command=[str(exe_path)],
        cwd=REPO_ROOT,
        configuration_root=appdata / "AiTool",
        environment=environment,
        temporary_root=temporary_root,
    )


def _cleanup_process_tree(pid: int | None) -> dict[str, Any]:
    """Best-effort child cleanup after the required terminate/wait/kill order."""

    if pid is None:
        return {"attempted": False, "method": None, "returncode": None}
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        output = (result.stdout + result.stderr).strip()[-2000:]
        # PyInstaller one-file bootloaders can disappear while their unpacked
        # GUI child remains.  In that race taskkill cannot traverse the gone
        # parent, so find its direct child and terminate that tree explicitly.
        fallback_pids: list[int] = []
        if result.returncode != 0:
            query = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    (
                        "Get-CimInstance Win32_Process "
                        f"-Filter \"ParentProcessId = {pid}\" | "
                        "ForEach-Object { $_.ProcessId }"
                    ),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            for line in query.stdout.splitlines():
                try:
                    child_pid = int(line.strip())
                except ValueError:
                    continue
                if child_pid > 0:
                    fallback_pids.append(child_pid)
            for child_pid in fallback_pids:
                child_result = subprocess.run(
                    ["taskkill", "/PID", str(child_pid), "/T", "/F"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                output = (output + "\n" + child_result.stdout + child_result.stderr).strip()[-2000:]
        return {
            "attempted": True,
            "method": "taskkill /T /F",
            "returncode": result.returncode,
            "output": output,
            "fallback_pids": fallback_pids,
        }

    try:
        os.killpg(pid, 9)
    except (AttributeError, OSError, ProcessLookupError):
        return {"attempted": True, "method": "killpg", "returncode": None}
    return {"attempted": True, "method": "killpg", "returncode": 0}


def _stop_process(process: subprocess.Popen[str], *, reason: str) -> dict[str, Any]:
    """Stop a GUI process without allowing a failed smoke run to hang."""

    cleanup: dict[str, Any] = {
        "reason": reason,
        "terminate_sent": False,
        "returncode_before_terminate": None,
        "returncode_after_terminate": None,
        "wait_seconds": 0,
    }
    returncode_before_terminate = process.poll()
    cleanup["returncode_before_terminate"] = returncode_before_terminate
    if returncode_before_terminate is None:
        try:
            process.terminate()
        except OSError as exc:
            # A process can disappear between poll() and terminate().  Keep
            # this as observed cleanup data rather than turning the race into
            # a launch exception, and let the startup verdict inspect the
            # returncode below.
            cleanup["terminate_error"] = f"{type(exc).__name__}: {exc}"
        else:
            cleanup["terminate_sent"] = True
            started = time.monotonic()
            try:
                process.wait(timeout=TERMINATE_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                cleanup["wait_seconds"] = round(time.monotonic() - started, 3)
                try:
                    process.kill()
                except OSError as exc:
                    cleanup["kill_error"] = f"{type(exc).__name__}: {exc}"
                else:
                    cleanup["kill_sent"] = True
                    try:
                        process.wait(timeout=TERMINATE_WAIT_SECONDS)
                    except subprocess.TimeoutExpired:
                        cleanup["kill_wait_timeout"] = True
            else:
                cleanup["wait_seconds"] = round(time.monotonic() - started, 3)
    returncode_after_terminate = process.poll()
    cleanup["returncode_after_terminate"] = returncode_after_terminate
    cleanup["process_returncode"] = returncode_after_terminate
    # Keep the PID for the post-probe cleanup phase.  A PyInstaller one-file
    # child may still be initializing configuration, or holding the inherited
    # output handle, so killing that tree here would race configuration
    # observation.  _cleanup_target() terminates it after the bounded settle.
    cleanup["process_pid"] = process.pid
    return cleanup


def _run_process(target: Target) -> ProcessObservation:
    started_at = _iso_now()
    monotonic_start = time.monotonic()
    process: subprocess.Popen[str] | None = None
    output = ""
    timed_out = False
    cleanup: dict[str, Any] = {
        "reason": "not_started",
        "terminate_sent": False,
        "returncode_before_terminate": None,
        "returncode_after_terminate": None,
        "process_returncode": None,
    }
    returncode: int | None = None

    try:
        if target.temporary_root is not None:
            output_path = target.temporary_root / "startup-output.log"
        else:
            output_fd, output_name = tempfile.mkstemp(prefix="aitool-gui-output-", suffix=".log")
            os.close(output_fd)
            output_path = Path(output_name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        with output_path.open("w", encoding="utf-8", errors="replace") as output_file:
            # A file, rather than a PIPE, is intentional: windowed EXEs can
            # leave inherited pipe handles behind while their process tree is
            # being cleaned up, which could make a post-terminate read hang.
            process = subprocess.Popen(
                target.command,
                cwd=target.cwd.resolve(),
                env=target.environment,
                stdout=output_file,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creationflags,
            )
        while time.monotonic() - monotonic_start < STARTUP_TIMEOUT_SECONDS:
            returncode = process.poll()
            if returncode is not None:
                break
            if time.monotonic() - monotonic_start >= STARTUP_SETTLE_SECONDS:
                break
            time.sleep(0.1)

        if process.poll() is None:
            if time.monotonic() - monotonic_start >= STARTUP_TIMEOUT_SECONDS:
                timed_out = True
                cleanup = _stop_process(process, reason="startup_timeout")
            else:
                cleanup = _stop_process(process, reason="startup_probe_complete")
        else:
            returncode = process.returncode
            # The failed process has already exited, so there is no live
            # process to terminate; still record deterministic cleanup data.
            cleanup = {
                "reason": "process_exited_during_startup",
                "terminate_sent": False,
                "returncode_before_terminate": returncode,
                "returncode_after_terminate": returncode,
                "process_returncode": returncode,
                "child_tree": _cleanup_process_tree(process.pid),
            }
        try:
            # Use an explicit context manager so the harness itself never
            # keeps startup-output.log open when target cleanup begins.
            with output_path.open("r", encoding="utf-8", errors="replace") as output_file:
                output = output_file.read()
        except OSError as exc:
            output = f"Unable to read startup output: {type(exc).__name__}: {exc}"
        returncode = process.returncode
    except Exception as exc:
        if process is not None and process.poll() is None:
            cleanup = _stop_process(process, reason="launch_exception")
        output = f"{type(exc).__name__}: {exc}"
        if cleanup.get("reason") == "not_started":
            cleanup = {
                "reason": "launch_exception",
                "terminate_sent": False,
                "returncode_before_terminate": None,
                "returncode_after_terminate": process.poll() if process is not None else None,
                "process_returncode": process.poll() if process is not None else None,
                "exception": output,
            }
        else:
            cleanup["exception"] = output
    finally:
        ended_at = _iso_now()

    return ProcessObservation(
        started_at=started_at,
        ended_at=ended_at,
        returncode=returncode,
        timed_out=timed_out,
        output=output[-10000:],
        cleanup=cleanup,
    )


def _cleanup_target(target: Target, process_cleanup: dict[str, Any] | None = None) -> dict[str, Any]:
    """Remove the isolated target tree and verify that it is gone.

    This record is captured in evidence before the tree is removed.  A
    successful deletion therefore keeps the path and cleanup result auditable,
    but does not claim that deleted files remain available for inspection.
    """

    temporary_root = target.temporary_root
    cleanup: dict[str, Any] = {
        "temporary_root": str(temporary_root) if temporary_root is not None else None,
        "attempted": False,
        "cleanup_verified": False,
        "removed": False,
        "post_cleanup_readable": False,
        "delete_attempts": 0,
    }
    if temporary_root is None:
        cleanup["error"] = "target has no temporary root"
        return cleanup

    cleanup["existed_before"] = temporary_root.exists()
    cleanup["attempted"] = True
    deadline = time.monotonic() + CLEANUP_RETRY_TIMEOUT_SECONDS
    last_error: str | None = None
    process_pid = process_cleanup.get("process_pid") if process_cleanup is not None else None
    process_tree_cleanup: dict[str, Any] | None = None
    while True:
        cleanup["delete_attempts"] += 1
        if process_pid is not None and process_tree_cleanup is None:
            process_tree_cleanup = _cleanup_process_tree(process_pid)
        try:
            if temporary_root.exists():
                shutil.rmtree(temporary_root)
            last_error = None
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"

        cleanup["removed"] = not temporary_root.exists()
        if cleanup["removed"] or time.monotonic() >= deadline:
            break
        if process_pid is not None:
            # The first taskkill is synchronous, but retry the tree cleanup as
            # well when Windows reports the output file still in use.
            process_tree_cleanup = _cleanup_process_tree(process_pid)
        time.sleep(CLEANUP_RETRY_INTERVAL_SECONDS)

    cleanup["cleanup_verified"] = cleanup["removed"]
    if process_tree_cleanup is not None:
        cleanup["process_tree_cleanup"] = process_tree_cleanup
    if cleanup["cleanup_verified"]:
        cleanup["details"] = "temporary tree deleted; files are not available for post-run inspection"
    else:
        cleanup["error"] = last_error or "temporary tree still exists after cleanup"
        cleanup["post_cleanup_readable"] = temporary_root.exists()
    return cleanup


def _cleanup_check(cleanup: dict[str, Any] | None) -> Check:
    if cleanup is not None and cleanup.get("cleanup_verified") is True:
        return Check(
            "temporary_cleanup",
            "pass",
            "pass: temporary tree deletion was verified; the recorded path is no longer readable",
            cleanup,
        )
    return Check(
        "temporary_cleanup",
        "fail",
        "fail: temporary tree cleanup was not confirmed",
        cleanup or {"cleanup_verified": False},
    )


def _wait_for_configuration(target: Target) -> tuple[list[Path], float]:
    """Wait briefly for startup initialization before observing configuration."""

    started = time.monotonic()
    deadline = started + CONFIGURATION_SETTLE_TIMEOUT_SECONDS
    config_files: list[Path] = []
    while True:
        if target.configuration_root.exists():
            config_files = sorted(target.configuration_root.glob("*.json"))
            if config_files:
                break
        if time.monotonic() >= deadline:
            break
        time.sleep(CONFIGURATION_RETRY_INTERVAL_SECONDS)
    return config_files, round(time.monotonic() - started, 3)


def _manual_checks() -> list[Check]:
    details = {
        "title_AiTool": "manual: visible Windows inspection is required; this harness does not fake a window title",
        "shell_icon_folder": "manual: verify a real Windows Shell folder icon; Emoji fallback is failure",
        "shell_icon_regular_file": "manual: verify a real Windows Shell file icon",
        "shell_icon_associated_type": "manual: verify a real associated-type Shell icon",
        "file_URL_drop": "manual: drag a file and URL onto the visible window",
        "file_icon_drag_out": "manual: drag a filename/icon to Explorer",
        "dynamic_refresh_DND": "manual: refresh and then verify DND registration interactively",
        "Ctrl_V_paste": "not_run: requires clipboard interaction in a visible desktop session",
        "station_internal_scroll": "manual: verify the station scrolls independently",
        "actions_independent_scroll": "manual: verify the action area scrolls independently",
        "fixed_statusbar": "manual: verify the bottom statusbar stays fixed",
        "window_default_min_max": "manual: verify default, minimum, and enlarged window geometry",
        "geometry_corrupt_fallback": "manual: exercise a corrupt geometry file and inspect the visible result",
        "geometry_restore_clamp": "manual: verify restore and multi-display clamp on Windows",
        "light_dark_readability": "manual: inspect Light/Dark native and CTk readability",
    }
    return [Check(name, "manual" if detail.startswith("manual:") else "not_run", detail) for name, detail in details.items()]


def _checks_for_target(
    target: Target,
    observation: ProcessObservation | None,
    cleanup: dict[str, Any] | None = None,
) -> list[Check]:
    checks = {check.name: check for check in _manual_checks()}
    startup_failed = False
    if observation is None:
        startup_detail = "fail: process was not launched"
        no_exception = Check("no_Unhandled_exception", "fail", startup_detail)
        startup = Check("process_startup", "fail", startup_detail)
    else:
        process_cleanup = observation.cleanup
        cleanup_reason = process_cleanup.get("reason")
        terminate_sent = process_cleanup.get("terminate_sent") is True
        returncode_before_terminate = process_cleanup.get("returncode_before_terminate")
        returncode_after_terminate = process_cleanup.get("returncode_after_terminate")
        if returncode_after_terminate is None:
            returncode_after_terminate = process_cleanup.get("process_returncode")

        # A probe is successful only when the harness observed a live process
        # immediately before it sent terminate.  In particular, do not infer
        # success from the cleanup reason alone: a process can exit naturally
        # in the small window between the last poll and _stop_process().
        startup_probe_complete = (
            cleanup_reason == "startup_probe_complete"
            and terminate_sent
            and returncode_before_terminate is None
            and returncode_after_terminate is not None
        )
        startup_failed = (
            observation.timed_out
            or cleanup_reason in {"startup_timeout", "launch_exception"}
            or (
                cleanup_reason == "startup_probe_complete"
                and not startup_probe_complete
            )
            or (
                cleanup_reason == "process_exited_during_startup"
                and observation.returncode not in (None, 0)
            )
        )

    if observation is not None and startup_failed:
        if observation.timed_out or observation.cleanup.get("reason") == "startup_timeout":
            startup_detail = "fail: startup exceeded 30 seconds; terminate/wait/kill/tree cleanup was applied"
        elif observation.cleanup.get("reason") == "launch_exception":
            startup_detail = f"fail: launch exception: {observation.output[-1000:]}"
        else:
            startup_detail = f"fail: process exited with code {observation.returncode}: {observation.output[-1000:]}"
        no_exception = Check("no_Unhandled_exception", "fail", startup_detail)
        startup = Check("process_startup", "fail", startup_detail)
    elif observation is not None:
        marker = "Unhandled exception"
        if marker.lower() in observation.output.lower():
            no_exception = Check("no_Unhandled_exception", "fail", "fail: startup output contains Unhandled exception")
        else:
            no_exception = Check("no_Unhandled_exception", "pass", "pass: no Unhandled exception marker in captured startup output")
        if startup_probe_complete:
            startup_detail = "pass: process remained alive through the startup probe and was terminated by the harness"
        else:
            startup_detail = "pass: process exited cleanly during startup"
        startup = Check("process_startup", "pass", startup_detail)

    checks[no_exception.name] = no_exception
    # process_startup is intentionally additional to the product matrix: it
    # makes the actual automated operation explicit without relabeling title
    # or interaction checks as GUI proof.
    checks[startup.name] = startup

    config_files, configuration_wait_seconds = _wait_for_configuration(target)
    if target.kind == "exe" and config_files:
        checks["first_configuration_initialization"] = Check(
            "first_configuration_initialization",
            "pass",
            "pass: fresh EXE APPDATA contains initialized JSON configuration",
            {
                "configuration_files": [str(path) for path in config_files],
                "settle_wait_seconds": configuration_wait_seconds,
            },
        )
    elif target.kind == "source" and target.configuration_root.exists():
        checks["first_configuration_initialization"] = Check(
            "first_configuration_initialization",
            "not_run",
            "not_run: source DATA_DIR is the copied repository data; no first-run claim is made",
            {
                "configuration_root": str(target.configuration_root),
                "configuration_files": [str(path) for path in config_files],
                "settle_wait_seconds": configuration_wait_seconds,
            },
        )
    else:
        checks["first_configuration_initialization"] = Check(
            "first_configuration_initialization",
            "fail" if observation is not None else "not_run",
            "fail: expected initialized configuration was not found after startup settle/retry" if observation is not None else "not_run: configuration was not observable",
            {
                "configuration_root": str(target.configuration_root),
                "configuration_files": [],
                "settle_wait_seconds": configuration_wait_seconds,
            },
        )
    ordered = [checks[name] for name in MATRIX_NAMES] + [checks["process_startup"]]
    if cleanup is not None:
        ordered.append(_cleanup_check(cleanup))
    return ordered


def _diagnostic_snapshot() -> dict[str, Any]:
    """Describe why a separate GUI process has no in-process diagnostic API."""

    return {
        "shell_icons": {
            "status": "not_run",
            "details": "not_run: WindowsIconCache diagnostics require an in-process GUI probe",
            "snapshot": None,
        },
        "dnd": {
            "status": "not_run",
            "details": "not_run: DND diagnostics require an in-process GUI probe",
            "snapshot": None,
        },
    }


def _overall_status(checks: list[Check]) -> str:
    statuses = {check.status for check in checks}
    if "fail" in statuses:
        return "fail"
    if statuses <= {"pass"}:
        return "pass"
    if statuses <= {"not_run"}:
        return "not_run"
    return "manual"


def _write_evidence(payload: dict[str, Any]) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / f"gui-spike-{_timestamp()}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _build_payload(
    target: Target,
    checks: list[Check],
    observation: ProcessObservation | None,
    error: str | None = None,
    cleanup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": target.kind,
        "identifier": target.identifier,
        "command": target.command,
        "working_directory": str(target.cwd),
        "configuration_root": str(target.configuration_root),
        "temporary_root": str(target.temporary_root) if target.temporary_root is not None else None,
        "cleanup_verified": cleanup.get("cleanup_verified", False) if cleanup is not None else False,
        "cleanup": cleanup or {"cleanup_verified": False, "details": "cleanup was not confirmed"},
        "started_at": observation.started_at if observation else _iso_now(),
        "ended_at": observation.ended_at if observation else _iso_now(),
        "status": _overall_status(checks),
        "checks": [check.as_dict() for check in checks],
        "diagnostics": _diagnostic_snapshot(),
        "failure_exception": error,
    }
    if observation is not None:
        payload["process"] = {
            "returncode": observation.returncode,
            "timed_out": observation.timed_out,
            "captured_output": observation.output,
            "cleanup": observation.cleanup,
        }
    return payload


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the honest AiTool GUI startup spike")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--source", action="store_true", help="run python run_desktop_tool.py in a copied worktree")
    group.add_argument("--exe", type=Path, help="run an already-built AiTool executable")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    target: Target | None = None
    checks: list[Check] = []
    observation: ProcessObservation | None = None
    failure_exception: str | None = None
    cleanup: dict[str, Any] | None = None
    try:
        if args.source:
            target = _copy_source_tree()
        else:
            exe_path = args.exe.expanduser()
            if not exe_path.is_absolute():
                exe_path = REPO_ROOT / exe_path
            exe_path = exe_path.resolve()
            if not exe_path.exists():
                # A target is still prepared so the failed invocation emits a
                # complete, useful evidence document.
                target = _prepare_exe(exe_path)
                failure_exception = f"FileNotFoundError: executable does not exist: {exe_path}"
            else:
                target = _prepare_exe(exe_path)
        if target is not None and failure_exception is None:
            observation = _run_process(target)
        if target is not None:
            # Inspect configuration while the isolated tree still exists.
            # Cleanup is then made an explicit verdict before the payload is
            # written, so no diagnostic path is lost from the evidence.
            checks = _checks_for_target(target, observation)
            cleanup = _cleanup_target(target, observation.cleanup if observation is not None else None)
            checks.append(_cleanup_check(cleanup))
            if failure_exception is not None:
                checks = [
                    Check("process_startup", "fail", failure_exception),
                    *[check for check in checks if check.name != "process_startup"],
                ]
            payload = _build_payload(target, checks, observation, failure_exception, cleanup)
            try:
                evidence_path = _write_evidence(payload)
            except Exception as exc:
                print(json.dumps({"status": "fail", "evidence": None, "error": f"evidence write failed: {exc}"}, ensure_ascii=False))
                return 1
            result = {
                "status": payload["status"],
                "kind": target.kind,
                "evidence": str(evidence_path),
                "failed_checks": [check.name for check in checks if check.status == "fail"],
                "manual_or_not_run": [check.name for check in checks if check.status in {"manual", "not_run"}],
            }
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 1 if payload["status"] == "fail" else 0
        raise RuntimeError("no smoke target was prepared")
    except Exception as exc:
        failure_exception = f"{type(exc).__name__}: {exc}"
        if target is None:
            print(json.dumps({"status": "fail", "evidence": None, "error": failure_exception}, ensure_ascii=False))
        else:
            cleanup = cleanup or _cleanup_target(target, observation.cleanup if observation is not None else None)
            checks = checks or [Check("process_startup", "fail", failure_exception)]
            if not any(check.name == "temporary_cleanup" for check in checks):
                checks.append(_cleanup_check(cleanup))
            payload = _build_payload(target, checks, observation, failure_exception, cleanup)
            try:
                evidence_path = _write_evidence(payload)
            except Exception as evidence_exc:
                print(json.dumps({"status": "fail", "evidence": None, "error": f"{failure_exception}; evidence write failed: {evidence_exc}"}, ensure_ascii=False))
                return 1
            print(json.dumps({"status": "fail", "evidence": str(evidence_path), "error": failure_exception}, ensure_ascii=False))
        return 1
    finally:
        # Normal paths clean up before writing evidence so cleanup is part of
        # the verdict.  Keep only a last-resort leak guard for an interruption
        # before normal finalization.
        if target is not None and target.temporary_root is not None and cleanup is None:
            _cleanup_target(target, observation.cleanup if observation is not None else None)


if __name__ == "__main__":
    raise SystemExit(main())
