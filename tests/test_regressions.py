#!/usr/bin/env python3
"""Targeted runtime regressions from audit findings. Starts real tmux sessions."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
K_ARG = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "scripts" / "k")
K_PATH = Path(K_ARG)

if K_PATH.is_absolute() or os.sep in K_ARG or (os.altsep and os.altsep in K_ARG) or K_PATH.exists():
    if not K_PATH.is_absolute():
        K_PATH = ROOT / K_PATH
    K_CMD = [sys.executable, str(K_PATH)]
else:
    K_CMD = [K_ARG]
PASS = 0
FAIL = 0


def run(cmd: list[str], *, cwd: Path | str | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)


def k(*args: str, cwd: Path | str | None = None, timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return run(K_CMD + list(args), cwd=cwd, timeout=timeout)


def check(name: str, expect: str, actual: str) -> None:
    global PASS, FAIL
    if expect in actual:
        PASS += 1
    else:
        print(f"  X {name}")
        print(f"    expect: {expect}")
        first = actual.splitlines()[0] if actual.splitlines() else actual
        print(f"    actual: {first[:120]}")
        FAIL += 1


def parse_json(stdout: str) -> dict:
    return json.loads(stdout)


def cleanup(*sessions: str) -> None:
    for session in sessions:
        k("kill", session)
        shutil.rmtree(Path("/tmp") / "k_cells" / session, ignore_errors=True)
        run(["tmux", "kill-session", "-t", session])


def require(command: str) -> None:
    if shutil.which(command) is None:
        raise SystemExit(f"missing required command: {command}")


def require_working_bash() -> None:
    bash = shutil.which("bash")
    if bash is None:
        raise SystemExit("missing required command: bash")
    if run([bash, "-lc", "true"]).returncode != 0:
        raise SystemExit("missing working bash: bash -lc true failed")


def k_stdout(*args: str, cwd: Path | str | None = None, timeout: int = 30) -> str:
    proc = k(*args, cwd=cwd, timeout=timeout)
    return proc.stdout + proc.stderr


def test_timeout_keeps_lock(base: str) -> None:
    session = f"{base}_timeout"
    cleanup(session)
    assert k("new", session, "bash").returncode == 0
    time.sleep(1)
    cell_id = parse_json(k("fire", "-t", "1", session, "sleep 10").stdout)["cell_id"]
    time.sleep(2)

    first = k_stdout("poll", session, cell_id)
    check("timeout-first-poll", '"status": "timeout"', first)
    second = k_stdout("poll", session, cell_id)
    check("timeout-second-poll-keeps-lock", "use k int or k kill", second)
    blocked = k_stdout("run", "-j", "-t", "1", session, "echo SHOULD_NOT_RUN")
    check("timeout-lock-blocks-new-run", "active cell", blocked)

    k("int", session)
    time.sleep(1)
    interrupted = k_stdout("poll", session, cell_id)
    check("timeout-int-overwrites-result", "interrupted", interrupted)
    recovered = k_stdout("run", "-j", "-t", "5", session, "echo AFTER_TIMEOUT")
    check("timeout-recover", "AFTER_TIMEOUT", recovered)
    cleanup(session)


def test_explicit_cell_ids_do_not_lie(base: str) -> None:
    session = f"{base}_unknown"
    cleanup(session)
    assert k("new", session, "bash").returncode == 0
    time.sleep(1)

    cell_id = parse_json(k("fire", session, "sleep 1 && echo DONE").stdout)["cell_id"]
    time.sleep(2)
    check("known-cell-done", "DONE", k_stdout("poll", session, cell_id))
    check("consumed-cell-unknown", "unknown cell", k_stdout("poll", session, cell_id))

    active_id = parse_json(k("fire", session, "sleep 10").stdout)["cell_id"]
    check("wrong-active-cell-unknown", "unknown cell", k_stdout("poll", session, "000000000000"))
    check("wrong-poll-keeps-active-lock", "active cell", k_stdout("fire", session, "echo nope"))
    k("int", session)
    time.sleep(1)
    k("poll", session, active_id)
    cleanup(session)


def write_hook(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env bash
while IFS= read -r line; do
    case "$line" in
        *'$'|*'$ '|*'#'|*'# ') exit 0 ;;
    esac
done
exit 1
""",
        encoding="utf-8",
    )


def test_hook_path_is_canonical_and_executable(base: str, tmpdir: Path) -> None:
    session = f"{base}_hook"
    bad_session = f"{base}_hookbad"
    cleanup(session, bad_session)

    bad_hook = tmpdir / "not-executable.sh"
    bad_hook.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    bad = k_stdout("new", bad_session, "bash", "--prompt=./not-executable.sh", cwd=tmpdir)
    check("hook-requires-executable", "hook not executable", bad)

    hook = tmpdir / "detect.sh"
    write_hook(hook)
    hook.chmod(0o755)
    created = k("new", session, "bash", "--prompt=./detect.sh", cwd=tmpdir)
    if created.returncode != 0:
        raise RuntimeError(created.stdout + created.stderr)
    time.sleep(1)
    changed_cwd = tmpdir.parent
    result = k_stdout("run", "-j", "-t", "5", session, "echo HOOK_OK", cwd=changed_cwd)
    check("hook-relative-path-survives-cwd-change", "HOOK_OK", result)
    cleanup(session, bad_session)


def main() -> int:
    require("tmux")
    require_working_bash()
    base = f"kr_{os.getpid()}"
    with tempfile.TemporaryDirectory(prefix="k-regress-") as tmp:
        tmpdir = Path(tmp)
        try:
            print("=== targeted regression tests ===")
            test_timeout_keeps_lock(base)
            test_explicit_cell_ids_do_not_lie(base)
            test_hook_path_is_canonical_and_executable(base, tmpdir)
        finally:
            cleanup(f"{base}_timeout", f"{base}_unknown", f"{base}_hook", f"{base}_hookbad")

    print("")
    print(f"=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
