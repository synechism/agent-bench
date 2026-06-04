# Tool Names And Descriptions

Source run: `20260601T202331_codex_empty_baseline_empty_task_nocap_rep0`

- model: `moonbridge`
- tool count: 12
- schema chars: 22,423
- schema sha256: `a99d169906d9f615cb8712ac028df9cb8b3f14e4ddbd6d8ee8649d501b140bad`

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

## 3. `list_mcp_resources`

Lists resources provided by MCP servers. Resources allow servers to share data that provides context to language models, such as files, database schemas, or application-specific information. Prefer resources over web search when possible.

- strict: `False`
- properties:
  - `cursor` (string): Opaque cursor returned by a previous list_mcp_resources call for the same server.
  - `server` (string): Optional MCP server name. When omitted, lists resources from every configured server.

## 4. `list_mcp_resource_templates`

Lists resource templates provided by MCP servers. Parameterized resource templates allow servers to share data that takes parameters and provides context to language models, such as files, database schemas, or application-specific information. Prefer resource templates over web search when possible.

- strict: `False`
- properties:
  - `cursor` (string): Opaque cursor returned by a previous list_mcp_resource_templates call for the same server.
  - `server` (string): Optional MCP server name. When omitted, lists resource templates from all configured servers.

## 5. `read_mcp_resource`

Read a specific resource from an MCP server given the server name and resource URI.

- strict: `False`
- required: `server, uri`
- properties:
  - `server` (string): MCP server name exactly as configured. Must match the 'server' field returned by list_mcp_resources.
  - `uri` (string): Resource URI to read. Must be one of the URIs returned by list_mcp_resources.

## 6. `update_plan`

Updates the task plan.
Provide an optional explanation and a list of plan items, each with a step and status.
At most one step can be in_progress at a time.


- strict: `False`
- required: `plan`
- properties:
  - `explanation` (string)
  - `plan` (array): The list of steps

## 7. `request_user_input`

Request user input for one to three short questions and wait for the response. This tool is only available in Plan mode.

- strict: `False`
- required: `questions`
- properties:
  - `questions` (array): Questions to show the user. Prefer 1 and do not exceed 3

## 8. `apply_patch`

Use the `apply_patch` tool to edit files. This is a FREEFORM tool, so do not wrap the patch in JSON.

- format type: `grammar`
- format syntax: `lark`

## 9. `view_image`

View a local image file from the filesystem when visual inspection is needed. Use this for images already available on disk.

- strict: `False`
- required: `path`
- properties:
  - `path` (string): Local filesystem path to an image file

## 10. `multi_agent_v1`

Tools for spawning and managing sub-agents.


Nested tools advertised inside this namespace:

- `close_agent`: Close an agent and any open descendants when they are no longer needed, and return the target agent's previous status before shutdown was requested. Don't keep agents open for too long if they are not needed anymore.
- `resume_agent`: Resume a previously closed agent by id so it can receive send_input and wait_agent calls.
- `send_input`: Send a message to an existing agent. Use interrupt=true to redirect work immediately. You should reuse the agent by send_input if you believe your assigned task is highly dependent on the context of a previous task.
- `spawn_agent`:                   Available model overrides (optional; inherited parent model is preferred): - `deepseek-v4-flash`:  Reasoning efforts: high (default), xhigh. - `deepseek-v4-pro`:  Reasoning efforts: high (default), xhigh. - `moonbridge`:  Reasoning efforts: high (default), xhigh.         Spawn a sub-agent for a well-scoped task. Returns the spawned agent id plus the user-facing nickname when available. Spawned agents inherit your current model by default. Omit `model` to use that preferred default; set `model` only when an explicit override is needed. This spawn_agent tool provides you access to sub-agents that inherit your current model by default. Do not set the `model` field unless the user explicitly asks for a different model or there is a clear task-specific reason. You should follow the rules and guidelines below to use this tool.  Only use `spawn_agent` if and only if the user explicitly asks for sub-agents, delegation, or parallel agent work. Requests for depth, thoroughness, research, investigation, or detailed codebase analysis do not count as permission to spawn. Agent-role guidance below only helps choose which agent to use after spawning is already authorized; it never authorizes spawning by itself.  ### When to delegate vs. do the subtask yourself - First, quickly analyze the overall user task and form a succinct high-level plan. Identify which tasks are immediate blockers on the critical path, and which tasks are sidecar tasks that are needed but can run in parallel without blocking the next local step. As part of that plan, explicitly decide what immediate task you should do locally right now. Do this planning step before delegating to agents so you do not hand off the immediate blocking task to a submodel and then waste time waiting on it. - Use a subagent when a subtask is easy enough for it to handle and can run in parallel with your local work. Prefer delegating concrete, bounded sidecar tasks that materially advance the main task without blocking your immediate next local step. - Do not delegate urgent blocking work when your immediate next step depends on that result. If the very next action is blocked on that task, the main rollout should usually do it locally to keep the critical path moving. - Keep work local when the subtask is too difficult to delegate well and when it is tightly coupled, urgent, or likely to block your immediate next step.  ### Designing delegated subtasks - Subtasks must be concrete, well-defined, and self-contained. - Delegated subtasks must materially advance the main task. - Do not duplicate work between the main rollout and delegated subtasks. - Avoid issuing multiple delegate calls on the same unresolved thread unless the new delegated task is genuinely different and necessary. - Narrow the delegated ask to the concrete output you need next. - For coding tasks, prefer delegating concrete code-change worker subtasks over read-only explorer analysis when the subagent can make a bounded patch in a clear write scope. - When delegating coding work, instruct the submodel to edit files directly in its forked workspace and list the file paths it changed in the final answer. - For code-edit subtasks, decompose work so each delegated task has a disjoint write set.  ### After you delegate - Call wait_agent very sparingly. Only call wait_agent when you need the result immediately for the next critical-path step and you are blocked until it returns. - Do not redo delegated subagent tasks yourself; focus on integrating results or tackling non-overlapping work. - While the subagent is running in the background, do meaningful non-overlapping work immediately. - Do not repeatedly wait by reflex. - When a delegated coding task returns, quickly review the uploaded changes, then integrate or refine them.  ### Parallel delegation patterns - Run multiple independent information-seeking subtasks in parallel when you have distinct questions that can be answered independently. - Split implementation into disjoint codebase slices and spawn multiple agents for them in parallel when the write scopes do not overlap. - Delegate verification only when it can run in parallel with ongoing implementation and is likely to catch a concrete risk before final integration. - The key is to find opportunities to spawn multiple independent subtasks in parallel within the same round, while ensuring each subtask is well-defined, self-contained, and materially advances the main task.
- `wait_agent`: Wait for agents to reach a final status. Completed statuses may include the agent's final message. Returns empty status when timed out. Once the agent reaches a final status, a notification message will be received containing the same completed status.

## 11. `mcp__deepwiki`

DeepWiki MCP provides AI-powered documentation for GitHub repositories.

Available tools:
- read_wiki_structure: Get a list of documentation topics for a repository
- read_wiki_contents: View full documentation about a repository
- ask_question: Ask any question about a repository and get an AI-powered answer
- list_available_repos: List your available repositories (private mode only)
- generate_wiki: Generate a codebase wiki for a repository — only use when explicitly requested by the user (private mode only)
- devin_knowledge_manage: Manage Devin knowledge notes and suggestions — list, search, get, create, update, delete notes, view folder structure, list/view/dismiss knowledge suggestions (private mode only)
- devin_playbook_manage: Manage Devin playbooks — list, get, create, update, delete (private mode only)
- devin_schedule_manage: Manage scheduled Devin sessions — list, get, create, update, delete (private mode only)
- devin_session_create: Create one or more child Devin sessions (private mode only)
- devin_session_interact: Manage a Devin session — get status, send messages, sleep/terminate/archive, read messages & attachments, manage tags (private mode only)
- devin_session_events: Inspect session events — list summaries, fetch full details, or search event contents (private mode only)
- devin_session_search: Search and filter Devin sessions (private mode only)
- list_integrations: List all native integrations and MCP servers with their status and settings URLs (private mode only)


Nested tools advertised inside this namespace:

- `ask_question`: Ask any question about a GitHub repository and get an AI-powered, context-grounded response.  Args:     repoName: GitHub repository or list of repositories (max 10) in owner/repo format     question: The question to ask about the repository
- `read_wiki_contents`: View documentation about a GitHub repository.  Args:     repoName: GitHub repository in owner/repo format (e.g. "facebook/react")
- `read_wiki_structure`: Get a list of documentation topics for a GitHub repository.  Args:     repoName: GitHub repository in owner/repo format (e.g. "facebook/react")

## 12. `web_search`
