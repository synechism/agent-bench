# Initial Skill Context Construction

This note answers one narrow question: when the first user prompt is submitted, how does Claude Code decide which skills the model sees, where do those skills come from on disk, and how do their headers enter the model context window?

## Key Claim

Before a user prompt is submitted, Claude Code has no model context window yet. It has local client state:

- a tool registry, including the generic `Skill` tool;
- enabled plugin metadata and plugin hooks;
- `SessionStart` hook output, if any hook already ran;
- memoized loaders that can discover skills from disk/plugins/MCP when needed.

The context window is built for a model request only after a prompt is submitted. At that point Claude Code formats skill metadata into a model-visible `skill_listing` attachment. The model sees skill **headers** and descriptions, not every full skill body.

## Skill File Locations

Claude Code discovers skills from several locations.

| source | location/pattern | notes |
| --- | --- | --- |
| User skills | `~/.claude/skills/<skill-name>/SKILL.md` | Implemented as `join(getClaudeConfigHomeDir(), "skills")`. |
| Managed/policy skills | `<managed-path>/.claude/skills/<skill-name>/SKILL.md` | Loaded unless policy skills are disabled. |
| Project skills | `<cwd-or-parent>/.claude/skills/<skill-name>/SKILL.md` | Walks from cwd upward to git root/home boundary and checks existing `.claude/skills` dirs. |
| Additional dirs | `<add-dir>/.claude/skills/<skill-name>/SKILL.md` | Comes from additional directories configured for Claude context. |
| Legacy command skills | `.claude/commands` | Legacy markdown commands can be transformed into skill-like prompt commands. |
| Plugin skills | `~/.claude/plugins/cache/<plugin>/<version>/skills/<skill-name>/SKILL.md` | Superpowers lives at `/home/abhi/.claude/plugins/cache/superpowers-local/5.1.0/skills/...`. |
| Bundled skills | Claude Code source/runtime bundled skill registry | Registered synchronously by Claude Code. |
| MCP skills | MCP prompt commands in app state | Included when MCP skills are enabled and model-invocable. |

For the Superpowers install used in this probe, important files are:

```text
/home/abhi/.claude/plugins/cache/superpowers-local/5.1.0/skills/using-superpowers/SKILL.md
/home/abhi/.claude/plugins/cache/superpowers-local/5.1.0/skills/brainstorming/SKILL.md
/home/abhi/.claude/plugins/cache/superpowers-local/5.1.0/hooks/hooks.json
/home/abhi/.claude/plugins/cache/superpowers-local/5.1.0/hooks/session-start
```

## Client-Side Skill Initialization

Skill discovery produces local `Command` objects. Those objects contain:

- skill name, e.g. `superpowers:brainstorming`;
- description and `when_to_use` metadata;
- source/loading metadata;
- allowed tools/model/frontmatter options;
- a lazy `getPromptForCommand(args, context)` function that can expand the full `SKILL.md` body later.

The main source path is:

```text
commands.ts
  -> getSkills(cwd)
      -> getSkillDirCommands(cwd)
      -> getPluginSkills()
      -> getBundledSkills()
      -> getBuiltinPluginSkillCommands()
  -> loadAllCommands(cwd)
  -> getCommands(cwd)
  -> getSkillToolCommands(cwd)
```

`getSkillToolCommands(cwd)` filters down to prompt-based, model-invocable skills and commands. This is the set used to build the model-visible skill listing.

## What Happens Before The First Prompt

Before the user prompt, plugin hooks can already run.

For Superpowers:

```text
Claude Code starts session
  -> loads plugin hooks
  -> finds Superpowers SessionStart hook
  -> runs hooks/session-start
  -> hook reads skills/using-superpowers/SKILL.md
  -> hook returns JSON with hookSpecificOutput.additionalContext
  -> Claude Code stores that as a hook_additional_context attachment message
```

That is where `context_dumps/01_session_start_hook_using_superpowers.md` comes from. It is not the skill listing. It is the rendered `additionalContext` payload produced by the Superpowers startup hook.

## What Happens After The Prompt Is Submitted

When the user submits a prompt, Claude Code processes the prompt and gathers attachments before sending the API request.

The relevant flow is:

```text
user prompt submitted
  -> processUserInputBase(...)
  -> getAttachmentMessages(inputString, context, ...)
  -> getAttachments(...)
  -> getSkillListingAttachments(context)
  -> getSkillToolCommands(cwd)
  -> getMcpSkillCommands(appState.mcp.commands)
  -> filter out skill names already sent for this agent
  -> formatCommandsWithinBudget(newSkills, contextWindowTokens)
  -> create attachment: { type: "skill_listing", content, skillCount, isInitial }
  -> processTextPrompt(...) returns:
       user message
       skill_listing attachment message
       other attachment messages
  -> normalizeMessagesForAPI(...)
  -> skill_listing attachment becomes a model-visible reminder
```

The `skill_listing` message is rendered into text shaped like:

```text
The following skills are available for use with the Skill tool:

- superpowers:brainstorming: You MUST use this before any creative work...
- superpowers:writing-plans: Use when you need to write an implementation plan...
- superpowers:executing-plans: Use when you have a written implementation plan...
```

The skill listing is metadata only. The body of `brainstorming/SKILL.md` is not included at this stage.

## First Request Context Structure

The first model request has several skill-related layers:

```text
API request
  system:
    base Claude Code system prompt
    session-specific guidance saying Skill tool executes listed skills
    environment/memory/MCP/output-style sections

  tools:
    serialized tool schemas
    includes generic Skill tool schema

  messages:
    SessionStart hook additional context, if present
      e.g. Superpowers using-superpowers bootstrap

    user prompt
      e.g. "Brainstorm a small feature..."

    skill listing attachment/reminder
      e.g. "The following skills are available for use with the Skill tool..."
```

Exact ordering can vary by entrypoint and normalization path, but the important semantic layering is stable:

- the **system prompt** tells the model how Claude Code works;
- the **tool schema** tells the model it can call `Skill`;
- the **hook additional context** tells the model to use Superpowers-style skill discipline;
- the **skill listing** tells the model which skills exist and when to use them;
- the **user prompt** provides the actual task that can match a listed skill.

In the captured run, `context_dumps/02_initial_skill_inventory_request1.md` contains the rendered Superpowers hook context plus the initial skill listing. That dump shows `superpowers:brainstorming` as a header/description entry before the full brainstorming body has been loaded.

## Why The Model Calls `superpowers:brainstorming`

Once the first request is assembled, the model sees all relevant ingredients:

```text
using-superpowers hook context:
  "If a skill applies, you must use it."

skill listing:
  "superpowers:brainstorming: You MUST use this before any creative work..."

user prompt:
  "Brainstorm a small feature..."

Skill tool schema:
  name: Skill
  input: { skill, args }
```

The model then emits a normal tool call:

```json
{"name": "Skill", "input": {"skill": "superpowers:brainstorming", "args": "..."}}
```

Only after that does Claude Code resolve the skill command and expand the full body of:

```text
/home/abhi/.claude/plugins/cache/superpowers-local/5.1.0/skills/brainstorming/SKILL.md
```

That expanded body appears in `context_dumps/03_loaded_brainstorming_skill_tool_result.md`.

## Source Anchors

The main source files for this mechanism are:

```text
/tmp/claude-code-source/src/skills/loadSkillsDir.ts
  Loads user, managed, project, additional-dir, and legacy command skills.

/tmp/claude-code-source/src/utils/plugins/loadPluginCommands.ts
  Loads plugin skills from plugin skills directories.

/tmp/claude-code-source/src/commands.ts
  Merges skill sources and exposes getSkillToolCommands(cwd).

/tmp/claude-code-source/src/utils/attachments.ts
  Builds the skill_listing attachment through getSkillListingAttachments().

/tmp/claude-code-source/src/utils/messages.ts
  Renders skill_listing as "The following skills are available for use with the Skill tool".

/tmp/claude-code-source/src/utils/sessionStart.ts
  Converts SessionStart hook additionalContext into hook_additional_context attachment messages.

/tmp/claude-code-source/src/tools/SkillTool/SkillTool.ts
  Handles the model's later Skill tool call.
```
