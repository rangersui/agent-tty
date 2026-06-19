#!/usr/bin/env python3
"""Static contract tests for k/km. No tmux session is started."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
K_PATH = ROOT / "scripts" / "k"
KM_PATH = ROOT / "scripts" / "km"
K_SRC = K_PATH.read_text(encoding="utf-8")
KM_SRC = KM_PATH.read_text(encoding="utf-8")
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        FAILURES.append(f"{name}: {detail}".rstrip(": "))


def parse(path: Path, src: str) -> ast.Module:
    try:
        return ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        FAILURES.append(f"{path.name}: syntax error: {exc}")
        return ast.Module(body=[], type_ignores=[])


K_TREE = parse(K_PATH, K_SRC)
KM_TREE = parse(KM_PATH, KM_SRC)


def function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    FAILURES.append(f"missing function {name}")
    return None


def segment(src: str, node: ast.FunctionDef | None) -> str:
    if node is None:
        return ""
    lines = src.splitlines()
    return "\n".join(lines[node.lineno - 1 : node.end_lineno])


def call_lines(node: ast.FunctionDef | None, name: str) -> list[int]:
    if node is None:
        return []
    out: list[int] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name) and func.id == name:
                out.append(child.lineno)
            elif isinstance(func, ast.Attribute) and func.attr == name:
                out.append(child.lineno)
    return sorted(out)


cmd_fire = function(K_TREE, "cmd_fire")
cmd_run = function(K_TREE, "cmd_run")
cmd_poll = function(K_TREE, "cmd_poll")
cmd_int = function(K_TREE, "cmd_int")
stream_process = function(K_TREE, "_stream_process")
cmd_new = function(K_TREE, "cmd_new")
main = function(K_TREE, "main")

for fn_name, fn in (("cmd_fire", cmd_fire), ("cmd_run", cmd_run)):
    acquire = call_lines(fn, "_acquire")
    ensure = call_lines(fn, "_ensure_pipe")
    send = call_lines(fn, "_send_code")
    check(f"{fn_name}: acquire exists", bool(acquire))
    check(f"{fn_name}: ensure_pipe exists", bool(ensure))
    check(f"{fn_name}: send_code exists", bool(send))
    if acquire and ensure and send:
        check(
            f"{fn_name}: lock before pipe/send",
            min(acquire) < min(ensure) < min(send),
            f"_acquire={acquire}, _ensure_pipe={ensure}, _send_code={send}",
        )
    seg = segment(K_SRC, fn)
    check(f"{fn_name}: pipe failure releases lock", "pipe failed" in seg and "_release(session, cell_id)" in seg)

poll_seg = segment(K_SRC, cmd_poll)
check("poll: timeout marks lock", 'lmeta["timed_out"] = True' in poll_seg)
check("poll: timed_out blocks orphan release", 'meta.get("timed_out")' in poll_seg and "use k int or k kill" in poll_seg)
check("poll: wrong explicit cell is unknown", 'meta.get("cell_id") != cell_id' in poll_seg and '"unknown cell"' in poll_seg)

int_seg = segment(K_SRC, cmd_int)
check("int: writes error/interrupted", '"status": "error"' in int_seg and '"output": "interrupted"' in int_seg)
check("int: overwrites stale timeout result", "not os.path.exists(rpath)" not in int_seg)
check("int: kills watcher before release", int_seg.find("os.kill") < int_seg.find("_release") if "os.kill" in int_seg and "_release" in int_seg else False)

new_seg = segment(K_SRC, cmd_new)
stream_seg = segment(K_SRC, stream_process)
check("hook: canonicalises path", "os.path.abspath(os.path.expanduser(prompt))" in new_seg)
check("hook: checks executable", "os.access(prompt, os.X_OK)" in new_seg)
check("hook: runtime uses absolute file path", "os.path.isabs(prompt)" in stream_seg and '"/" in prompt' not in stream_seg)

main_seg = segment(K_SRC, main)
check("session: _bg validates session", 'verb == "_bg"' in main_seg and "_validate_name(session)" in main_seg)
check("session: notify direct path validates session", 'verb == "notify"' in main_seg and "_validate_name(rest[0])" in main_seg)
check("session: k safe name exists", "_SAFE_NAME" in K_SRC and "def _validate_name" in K_SRC)
check("session: km safe name exists", "_SAFE_NAME" in KM_SRC and "def _validate_name" in KM_SRC and "_validate_name(session)" in KM_SRC)

check("pipe-pane: k replace mode", '"-o"' not in K_SRC)
check("pipe-pane: km replace mode", '"-o"' not in KM_SRC)

# cmd_kill must terminate bg watcher before killing session
cmd_kill = function(K_TREE, "cmd_kill")
kill_seg = segment(K_SRC, cmd_kill)
check("kill: terminates bg watcher", "os.kill(meta" in kill_seg and "signal.SIGTERM" in kill_seg)

# cmd_fire must store bg_pid in lock for orphan detection
fire_seg = segment(K_SRC, cmd_fire)
check("fire: stores bg_pid in lock", '"bg_pid"' in fire_seg and "bg.pid" in fire_seg)

# ANSI_RE must be consistent between k and km (compare compiled patterns)
def _extract_ansi_re(tree: ast.Module, src: str) -> str:
    """Find ANSI_RE assignment via AST, exec it, return .pattern."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "ANSI_RE":
                    lines = src.splitlines()
                    chunk = "\n".join(lines[node.lineno - 1 : node.end_lineno])
                    ns = {"re": __import__("re")}
                    exec(chunk, ns)
                    return ns["ANSI_RE"].pattern
    return ""

k_pat = _extract_ansi_re(K_TREE, K_SRC)
km_pat = _extract_ansi_re(KM_TREE, KM_SRC)
check("ansi_re: k and km consistent", k_pat == km_pat and k_pat != "",
      f"k={k_pat[:60]}... km={km_pat[:60]}...")

if FAILURES:
    print("contract failures:")
    for failure in FAILURES:
        print(f"  - {failure}")
    raise SystemExit(1)

print("contract tests passed")
