# Controlled tools

Agents receive a `ToolRegistry`; they never receive the raw host path or
`Workspace` object. Each tool publishes a Pydantic input schema for future
provider adapters and returns a structured result.

| Tool | Behavior |
| --- | --- |
| `list_directory` | Sorted, bounded directory inventory |
| `read_file` | UTF-8 text read with a byte limit |
| `search_code` | Literal or regex search with glob and result bounds |
| `write_file` | Atomic create-or-replace operation |
| `edit_file` | Exact replacement with an expected-match count |
| `create_file` | Atomic creation that fails if the target exists |
| `run_command` | Argument-vector execution inside the task container |
| `run_tests` | Executes the task manifest's test command |
| `git_diff` | Git-style patch against the harness-owned baseline |

Filesystem paths are resolved beneath the copied workspace. Absolute paths,
parent traversal, and symlinks that resolve outside the workspace are rejected.
Commands have no host fallback: the registry requires a workspace whose runtime
declares process isolation.

The patch baseline is captured by the harness after task setup and before the
agent starts. It is not stored in the container, so agent commands cannot erase
the comparison by modifying Git state. Standard test/cache artifacts are excluded
from the patch.

