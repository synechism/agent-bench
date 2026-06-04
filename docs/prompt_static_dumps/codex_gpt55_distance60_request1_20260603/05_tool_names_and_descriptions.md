# Tool Names And Descriptions

Source run: `20260603T173458_codex_semantic_memory_sentinel_semantic_memory_sentinel_distance_60_nocap_rep0`

- model: `gpt-5.5`
- tool count: 8
- schema chars: 7,324
- schema sha256: `1f2eda85798da1d0bc04dd121d42a9ae2c7eaf274af7a9fafe1c7ef018b89abb`

## 1. `exec_command`

Runs a command in a PTY, returning output or a session ID for ongoing interaction.

- strict: `False`
- required: `cmd`
- properties:
  - `cmd` (string): Shell command to execute.
  - `justification` (string): Only set if sandbox_permissions is \"require_escalated\".
                    Request approval from the user to run this command outside the sandbox.
                    Phrased as a simple question that summarizes the purpose of the
                    command as it relates to the task at hand - e.g. 'Do you want to
                    fetch and pull the latest version of this git branch?'
  - `login` (boolean): Whether to run the shell with -l/-i semantics. Defaults to true.
  - `max_output_tokens` (number): Maximum number of tokens to return. Excess output will be truncated.
  - `prefix_rule` (array): Only specify when sandbox_permissions is `require_escalated`.
                        Suggest a prefix command pattern that will allow you to fulfill similar requests from the user in the future.
                        Should be a short but reasonable prefix, e.g. [\"git\", \"pull\"] or [\"uv\", \"run\"] or [\"pytest\"].
  - `sandbox_permissions` (string): Sandbox permissions for the command. Set to "require_escalated" to request running without sandbox restrictions; defaults to "use_default".
  - `shell` (string): Shell binary to launch. Defaults to the user's default shell.
  - `tty` (boolean): Whether to allocate a TTY for the command. Defaults to false (plain pipes); set to true to open a PTY and access TTY process.
  - `workdir` (string): Optional working directory to run the command in; defaults to the turn cwd.
  - `yield_time_ms` (number): How long to wait (in milliseconds) for output before yielding.

## 2. `write_stdin`

Writes characters to an existing unified exec session and returns recent output.

- strict: `False`
- required: `session_id`
- properties:
  - `chars` (string): Bytes to write to stdin (may be empty to poll).
  - `max_output_tokens` (number): Maximum number of tokens to return. Excess output will be truncated.
  - `session_id` (number): Identifier of the running unified exec session.
  - `yield_time_ms` (number): How long to wait (in milliseconds) for output before yielding.

## 3. `update_plan`

Updates the task plan.
Provide an optional explanation and a list of plan items, each with a step and status.
At most one step can be in_progress at a time.


- strict: `False`
- required: `plan`
- properties:
  - `explanation` (string)
  - `plan` (array): The list of steps

## 4. `request_user_input`

Request user input for one to three short questions and wait for the response. This tool is only available in Plan mode.

- strict: `False`
- required: `questions`
- properties:
  - `questions` (array): Questions to show the user. Prefer 1 and do not exceed 3

## 5. `apply_patch`

Use the `apply_patch` tool to edit files. This is a FREEFORM tool, so do not wrap the patch in JSON.

- format type: `grammar`
- format syntax: `lark`

## 6. `view_image`

View a local image from the filesystem (only use if given a full filepath by the user, and the image isn't already attached to the thread context within <image ...> tags).

- strict: `False`
- required: `path`
- properties:
  - `detail` (string): Optional detail override. Supported values are `high` and `original`; omit this field for default high resized behavior. Use `original` to preserve the file's original resolution instead of resizing to fit. This is important when high-fidelity image perception or precise localization is needed, especially for CUA agents.
  - `path` (string): Local filesystem path to an image file

## 7. `tool_search`

# Tool discovery

Searches over deferred tool metadata with BM25 and exposes matching tools for the next model call.

You have access to tools from the following sources:
- Multi-agent tools: Spawn and manage sub-agents.
Some of the tools may not have been provided to you upfront, and you should use this tool (`tool_search`) to search for the required tools. For MCP tool discovery, always use `tool_search` instead of `list_mcp_resources` or `list_mcp_resource_templates`.

- required: `query`
- properties:
  - `limit` (number): Maximum number of tools to return (defaults to 8).
  - `query` (string): Search query for deferred tools.

## 8. `web_search`
