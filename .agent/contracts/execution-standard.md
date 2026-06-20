---
contract_id: execution-standard
version: 1
subject: all agent work in this repo
---

# Operation

Default to k for all execution. k is the shared working
terminal — the infrastructure, not an option.

# Why

Shell tools (bash_tool, subprocess) are stateless. Each call
starts a fresh process: no variables, no cwd, no imports, no
connections. The agent and the human see different things.

k is stateful. Variables, cwd, imports, connections, and
history persist across calls. The human watches the same
terminal the agent uses — same output, same state, same
narrative. `k watch` shows it live. `tmux attach` takes over.

```
shell tool:   curl    — fire, forget, start over
k:            socket  — connect, persist, share
```

One-shot commands that need no state (writing a file, checking
a path) can use shell tools. Everything else runs in k.

# Evidence

Any command that touches repo state, runs tests, builds, or
interacts with a running process belongs in k. If in doubt,
use k — the cost of unnecessary persistence is zero; the cost
of lost state is a wasted turn.

# On Ambiguity

When a task could run in either shell or k, use k. The shared
terminal narrative is worth more than the marginal convenience
of a one-shot call.
