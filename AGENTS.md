# Agent Workflow

- The primary agent handles planning, coordination, review, progress, and final acceptance only.
- Investigation, implementation, tests, and documentation changes are handled by subagents.
- Subagents default to `gpt-5.6-terra` with `xhigh` reasoning.
- Work is strictly serial unless the user explicitly authorizes parallel work.
- Preserve all user workspace changes, including untracked files; never overwrite or revert them.
