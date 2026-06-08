# Claude Code Subagent Source Excerpts

- Source root: `/tmp/claude-code-source`
- Purpose: exact code excerpts used for the subagent context lifecycle report.

## Agent tool input schema exposed to the model

- File: `src/tools/AgentTool/AgentTool.tsx`
- Range: `81-138`

```ts
 81: // Base input schema without multi-agent parameters
 82: const baseInputSchema = lazySchema(() => z.object({
 83:   description: z.string().describe('A short (3-5 word) description of the task'),
 84:   prompt: z.string().describe('The task for the agent to perform'),
 85:   subagent_type: z.string().optional().describe('The type of specialized agent to use for this task'),
 86:   model: z.enum(['sonnet', 'opus', 'haiku']).optional().describe("Optional model override for this agent. Takes precedence over the agent definition's model frontmatter. If omitted, uses the agent definition's model, or inherits from the parent."),
 87:   run_in_background: z.boolean().optional().describe('Set to true to run this agent in the background. You will be notified when it completes.')
 88: }));
 89: 
 90: // Full schema combining base + multi-agent params + isolation
 91: const fullInputSchema = lazySchema(() => {
 92:   // Multi-agent parameters
 93:   const multiAgentInputSchema = z.object({
 94:     name: z.string().optional().describe('Name for the spawned agent. Makes it addressable via SendMessage({to: name}) while running.'),
 95:     team_name: z.string().optional().describe('Team name for spawning. Uses current team context if omitted.'),
 96:     mode: permissionModeSchema().optional().describe('Permission mode for spawned teammate (e.g., "plan" to require plan approval).')
 97:   });
 98:   return baseInputSchema().merge(multiAgentInputSchema).extend({
 99:     isolation: ("external" === 'ant' ? z.enum(['worktree', 'remote']) : z.enum(['worktree'])).optional().describe("external" === 'ant' ? 'Isolation mode. "worktree" creates a temporary git worktree so the agent works on an isolated copy of the repo. "remote" launches the agent in a remote CCR environment (always runs in background).' : 'Isolation mode. "worktree" creates a temporary git worktree so the agent works on an isolated copy of the repo.'),
100:     cwd: z.string().optional().describe('Absolute path to run the agent in. Overrides the working directory for all filesystem and shell operations within this agent. Mutually exclusive with isolation: "worktree".')
101:   });
102: });
103: 
104: // Strip optional fields from the schema when the backing feature is off so
105: // the model never sees them. Done via .omit() rather than conditional spread
106: // inside .extend() because the spread-ternary breaks Zod's type inference
107: // (field type collapses to `unknown`). The ternary return produces a union
108: // type, but call() destructures via the explicit AgentToolInput type below
109: // which always includes all optional fields.
110: export const inputSchema = lazySchema(() => {
111:   const schema = feature('KAIROS') ? fullInputSchema() : fullInputSchema().omit({
112:     cwd: true
113:   });
114: 
115:   // GrowthBook-in-lazySchema is acceptable here (unlike subagent_type, which
116:   // was removed in 906da6c723): the divergence window is one-session-per-
117:   // gate-flip via _CACHED_MAY_BE_STALE disk read, and worst case is either
118:   // "schema shows a no-op param" (gate flips on mid-session: param ignored
119:   // by forceAsync) or "schema hides a param that would've worked" (gate
120:   // flips off mid-session: everything still runs async via memoized
121:   // forceAsync). No Zod rejection, no crash — unlike required→optional.
122:   return isBackgroundTasksDisabled || isForkSubagentEnabled() ? schema.omit({
123:     run_in_background: true
124:   }) : schema;
125: });
126: type InputSchema = ReturnType<typeof inputSchema>;
127: 
128: // Explicit type widens the schema inference to always include all optional
129: // fields even when .omit() strips them for gating (cwd, run_in_background).
130: // subagent_type is optional; call() defaults it to general-purpose when the
131: // fork gate is off, or routes to the fork path when the gate is on.
132: type AgentToolInput = z.infer<ReturnType<typeof baseInputSchema>> & {
133:   name?: string;
134:   team_name?: string;
135:   mode?: z.infer<ReturnType<typeof permissionModeSchema>>;
136:   isolation?: 'worktree' | 'remote';
137:   cwd?: string;
138: };
```

## Agent tool prompt: agent list and fork instructions

- File: `src/tools/AgentTool/prompt.ts`
- Range: `39-64`

```ts
39: /**
40:  * Format one agent line for the agent_listing_delta attachment message:
41:  * `- type: whenToUse (Tools: ...)`.
42:  */
43: export function formatAgentLine(agent: AgentDefinition): string {
44:   const toolsDescription = getToolsDescription(agent)
45:   return `- ${agent.agentType}: ${agent.whenToUse} (Tools: ${toolsDescription})`
46: }
47: 
48: /**
49:  * Whether the agent list should be injected as an attachment message instead
50:  * of embedded in the tool description. When true, getPrompt() returns a static
51:  * description and attachments.ts emits an agent_listing_delta attachment.
52:  *
53:  * The dynamic agent list was ~10.2% of fleet cache_creation tokens: MCP async
54:  * connect, /reload-plugins, or permission-mode changes mutate the list →
55:  * description changes → full tool-schema cache bust.
56:  *
57:  * Override with CLAUDE_CODE_AGENT_LIST_IN_MESSAGES=true/false for testing.
58:  */
59: export function shouldInjectAgentListInMessages(): boolean {
60:   if (isEnvTruthy(process.env.CLAUDE_CODE_AGENT_LIST_IN_MESSAGES)) return true
61:   if (isEnvDefinedFalsy(process.env.CLAUDE_CODE_AGENT_LIST_IN_MESSAGES))
62:     return false
63:   return getFeatureValue_CACHED_MAY_BE_STALE('tengu_agent_list_attach', false)
64: }
```

## Agent tool prompt: fork/fresh guidance visible to model

- File: `src/tools/AgentTool/prompt.ts`
- Range: `190-212`

```ts
190:   // When the gate is on, the agent list lives in an agent_listing_delta
191:   // attachment (see attachments.ts) instead of inline here. This keeps the
192:   // tool description static across MCP/plugin/permission changes so the
193:   // tools-block prompt cache doesn't bust every time an agent loads.
194:   const listViaAttachment = shouldInjectAgentListInMessages()
195: 
196:   const agentListSection = listViaAttachment
197:     ? `Available agent types are listed in <system-reminder> messages in the conversation.`
198:     : `Available agent types and the tools they have access to:
199: ${effectiveAgents.map(agent => formatAgentLine(agent)).join('\n')}`
200: 
201:   // Shared core prompt used by both coordinator and non-coordinator modes
202:   const shared = `Launch a new agent to handle complex, multi-step tasks autonomously.
203: 
204: The ${AGENT_TOOL_NAME} tool launches specialized agents (subprocesses) that autonomously handle complex tasks. Each agent type has specific capabilities and tools available to it.
205: 
206: ${agentListSection}
207: 
208: ${
209:   forkEnabled
210:     ? `When using the ${AGENT_TOOL_NAME} tool, specify a subagent_type to use a specialized agent, or omit it to fork yourself — a fork inherits your full conversation context.`
211:     : `When using the ${AGENT_TOOL_NAME} tool, specify a subagent_type parameter to select which agent type to use. If omitted, the general-purpose agent is used.`
212: }`
```

## Agent tool prompt: usage notes, background, worktree, SendMessage

- File: `src/tools/AgentTool/prompt.ts`
- Range: `251-285`

```ts
251:   // Non-coordinator gets the full prompt with all sections
252:   return `${shared}
253: ${whenNotToUseSection}
254: 
255: Usage notes:
256: - Always include a short description (3-5 words) summarizing what the agent will do${concurrencyNote}
257: - When the agent is done, it will return a single message back to you. The result returned by the agent is not visible to the user. To show the user the result, you should send a text message back to the user with a concise summary of the result.${
258:     // eslint-disable-next-line custom-rules/no-process-env-top-level
259:     !isEnvTruthy(process.env.CLAUDE_CODE_DISABLE_BACKGROUND_TASKS) &&
260:     !isInProcessTeammate() &&
261:     !forkEnabled
262:       ? `
263: - You can optionally run agents in the background using the run_in_background parameter. When an agent runs in the background, you will be automatically notified when it completes — do NOT sleep, poll, or proactively check on its progress. Continue with other work or respond to the user instead.
264: - **Foreground vs background**: Use foreground (default) when you need the agent's results before you can proceed — e.g., research agents whose findings inform your next steps. Use background when you have genuinely independent work to do in parallel.`
265:       : ''
266:   }
267: - To continue a previously spawned agent, use ${SEND_MESSAGE_TOOL_NAME} with the agent's ID or name as the \`to\` field. The agent resumes with its full context preserved. ${forkEnabled ? 'Each fresh Agent invocation with a subagent_type starts without context — provide a complete task description.' : 'Each Agent invocation starts fresh — provide a complete task description.'}
268: - The agent's outputs should generally be trusted
269: - Clearly tell the agent whether you expect it to write code or just to do research (search, file reads, web fetches, etc.)${forkEnabled ? '' : ", since it is not aware of the user's intent"}
270: - If the agent description mentions that it should be used proactively, then you should try your best to use it without the user having to ask for it first. Use your judgement.
271: - If the user specifies that they want you to run agents "in parallel", you MUST send a single message with multiple ${AGENT_TOOL_NAME} tool use content blocks. For example, if you need to launch both a build-validator agent and a test-runner agent in parallel, send a single message with both tool calls.
272: - You can optionally set \`isolation: "worktree"\` to run the agent in a temporary git worktree, giving it an isolated copy of the repository. The worktree is automatically cleaned up if the agent makes no changes; if changes are made, the worktree path and branch are returned in the result.${
273:     process.env.USER_TYPE === 'ant'
274:       ? `\n- You can set \`isolation: "remote"\` to run the agent in a remote CCR environment. This is always a background task; you'll be notified when it completes. Use for long-running tasks that need a fresh sandbox.`
275:       : ''
276:   }${
277:     isInProcessTeammate()
278:       ? `
279: - The run_in_background, name, team_name, and mode parameters are not available in this context. Only synchronous subagents are supported.`
280:       : isTeammate()
281:         ? `
282: - The name, team_name, and mode parameters are not available in this context — teammates cannot spawn other teammates. Omit them to spawn a subagent.`
283:         : ''
284:   }${whenToForkSection}${writingThePromptSection}
285: 
```

## Agent listing delta attachment construction

- File: `src/utils/attachments.ts`
- Range: `1478-1557`

```ts
1478: /**
1479:  * Diff the current filtered agent pool against what's already been announced
1480:  * in this conversation (reconstructed from prior agent_listing_delta
1481:  * attachments). Returns [] if nothing changed or the gate is off.
1482:  *
1483:  * The agent list was embedded in AgentTool's description, causing ~10.2% of
1484:  * fleet cache_creation: MCP async connect, /reload-plugins, or
1485:  * permission-mode change → description changes → full tool-schema cache bust.
1486:  * Moving the list here keeps the tool description static.
1487:  *
1488:  * Exported for compact.ts — re-announces the full set after compaction eats
1489:  * prior deltas.
1490:  */
1491: export function getAgentListingDeltaAttachment(
1492:   toolUseContext: ToolUseContext,
1493:   messages: Message[] | undefined,
1494: ): Attachment[] {
1495:   if (!shouldInjectAgentListInMessages()) return []
1496: 
1497:   // Skip if AgentTool isn't in the pool — the listing would be unactionable.
1498:   if (
1499:     !toolUseContext.options.tools.some(t => toolMatchesName(t, AGENT_TOOL_NAME))
1500:   ) {
1501:     return []
1502:   }
1503: 
1504:   const { activeAgents, allowedAgentTypes } =
1505:     toolUseContext.options.agentDefinitions
1506: 
1507:   // Mirror AgentTool.prompt()'s filtering: MCP requirements → deny rules →
1508:   // allowedAgentTypes restriction. Keep this in sync with AgentTool.tsx.
1509:   const mcpServers = new Set<string>()
1510:   for (const tool of toolUseContext.options.tools) {
1511:     const info = mcpInfoFromString(tool.name)
1512:     if (info) mcpServers.add(info.serverName)
1513:   }
1514:   const permissionContext = toolUseContext.getAppState().toolPermissionContext
1515:   let filtered = filterDeniedAgents(
1516:     filterAgentsByMcpRequirements(activeAgents, [...mcpServers]),
1517:     permissionContext,
1518:     AGENT_TOOL_NAME,
1519:   )
1520:   if (allowedAgentTypes) {
1521:     filtered = filtered.filter(a => allowedAgentTypes.includes(a.agentType))
1522:   }
1523: 
1524:   // Reconstruct announced set from prior deltas in the transcript.
1525:   const announced = new Set<string>()
1526:   for (const msg of messages ?? []) {
1527:     if (msg.type !== 'attachment') continue
1528:     if (msg.attachment.type !== 'agent_listing_delta') continue
1529:     for (const t of msg.attachment.addedTypes) announced.add(t)
1530:     for (const t of msg.attachment.removedTypes) announced.delete(t)
1531:   }
1532: 
1533:   const currentTypes = new Set(filtered.map(a => a.agentType))
1534:   const added = filtered.filter(a => !announced.has(a.agentType))
1535:   const removed: string[] = []
1536:   for (const t of announced) {
1537:     if (!currentTypes.has(t)) removed.push(t)
1538:   }
1539: 
1540:   if (added.length === 0 && removed.length === 0) return []
1541: 
1542:   // Sort for deterministic output — agent load order is nondeterministic
1543:   // (plugin load races, MCP async connect).
1544:   added.sort((a, b) => a.agentType.localeCompare(b.agentType))
1545:   removed.sort()
1546: 
1547:   return [
1548:     {
1549:       type: 'agent_listing_delta',
1550:       addedTypes: added.map(a => a.agentType),
1551:       addedLines: added.map(formatAgentLine),
1552:       removedTypes: removed,
1553:       isInitial: announced.size === 0,
1554:       showConcurrencyNote: getSubscriptionType() !== 'pro',
1555:     },
1556:   ]
1557: }
```

## Agent listing delta rendering into system-reminder text

- File: `src/utils/messages.ts`
- Range: `4194-4215`

```ts
4194:     case 'agent_listing_delta': {
4195:       const parts: string[] = []
4196:       if (attachment.addedLines.length > 0) {
4197:         const header = attachment.isInitial
4198:           ? 'Available agent types for the Agent tool:'
4199:           : 'New agent types are now available for the Agent tool:'
4200:         parts.push(`${header}\n${attachment.addedLines.join('\n')}`)
4201:       }
4202:       if (attachment.removedTypes.length > 0) {
4203:         parts.push(
4204:           `The following agent types are no longer available:\n${attachment.removedTypes.map(t => `- ${t}`).join('\n')}`,
4205:         )
4206:       }
4207:       if (attachment.isInitial && attachment.showConcurrencyNote) {
4208:         parts.push(
4209:           `Launch multiple agents concurrently whenever possible, to maximize performance; to do that, use a single message with multiple tool uses.`,
4210:         )
4211:       }
4212:       return wrapMessagesInSystemReminder([
4213:         createUserMessage({ content: parts.join('\n\n'), isMeta: true }),
4214:       ])
4215:     }
```

## AgentTool routing: subagent_type, fork path, agent selection

- File: `src/tools/AgentTool/AgentTool.tsx`
- Range: `318-356`

```ts
318:     // Fork subagent experiment routing:
319:     // - subagent_type set: use it (explicit wins)
320:     // - subagent_type omitted, gate on: fork path (undefined)
321:     // - subagent_type omitted, gate off: default general-purpose
322:     const effectiveType = subagent_type ?? (isForkSubagentEnabled() ? undefined : GENERAL_PURPOSE_AGENT.agentType);
323:     const isForkPath = effectiveType === undefined;
324:     let selectedAgent: AgentDefinition;
325:     if (isForkPath) {
326:       // Recursive fork guard: fork children keep the Agent tool in their
327:       // pool for cache-identical tool defs, so reject fork attempts at call
328:       // time. Primary check is querySource (compaction-resistant — set on
329:       // context.options at spawn time, survives autocompact's message
330:       // rewrite). Message-scan fallback catches any path where querySource
331:       // wasn't threaded.
332:       if (toolUseContext.options.querySource === `agent:builtin:${FORK_AGENT.agentType}` || isInForkChild(toolUseContext.messages)) {
333:         throw new Error('Fork is not available inside a forked worker. Complete your task directly using your tools.');
334:       }
335:       selectedAgent = FORK_AGENT;
336:     } else {
337:       // Filter agents to exclude those denied via Agent(AgentName) syntax
338:       const allAgents = toolUseContext.options.agentDefinitions.activeAgents;
339:       const {
340:         allowedAgentTypes
341:       } = toolUseContext.options.agentDefinitions;
342:       const agents = filterDeniedAgents(
343:       // When allowedAgentTypes is set (from Agent(x,y) tool spec), restrict to those types
344:       allowedAgentTypes ? allAgents.filter(a => allowedAgentTypes.includes(a.agentType)) : allAgents, appState.toolPermissionContext, AGENT_TOOL_NAME);
345:       const found = agents.find(agent => agent.agentType === effectiveType);
346:       if (!found) {
347:         // Check if the agent exists but is denied by permission rules
348:         const agentExistsButDenied = allAgents.find(agent => agent.agentType === effectiveType);
349:         if (agentExistsButDenied) {
350:           const denyRule = getDenyRuleForAgent(appState.toolPermissionContext, AGENT_TOOL_NAME, effectiveType);
351:           throw new Error(`Agent type '${effectiveType}' has been denied by permission rule '${AGENT_TOOL_NAME}(${effectiveType})' from ${denyRule?.source ?? 'settings'}.`);
352:         }
353:         throw new Error(`Agent type '${effectiveType}' not found. Available agents: ${agents.map(a => a.agentType).join(', ')}`);
354:       }
355:       selectedAgent = found;
356:     }
```

## AgentTool context construction: fork vs normal messages/system/tools

- File: `src/tools/AgentTool/AgentTool.tsx`
- Range: `483-636`

```ts
483:     // System prompt + prompt messages: branch on fork path.
484:     //
485:     // Fork path: child inherits the PARENT's system prompt (not FORK_AGENT's)
486:     // for cache-identical API request prefixes. Prompt messages are built via
487:     // buildForkedMessages() which clones the parent's full assistant message
488:     // (all tool_use blocks) + placeholder tool_results + per-child directive.
489:     //
490:     // Normal path: build the selected agent's own system prompt with env
491:     // details, and use a simple user message for the prompt.
492:     let enhancedSystemPrompt: string[] | undefined;
493:     let forkParentSystemPrompt: ReturnType<typeof buildEffectiveSystemPrompt> | undefined;
494:     let promptMessages: MessageType[];
495:     if (isForkPath) {
496:       if (toolUseContext.renderedSystemPrompt) {
497:         forkParentSystemPrompt = toolUseContext.renderedSystemPrompt;
498:       } else {
499:         // Fallback: recompute. May diverge from parent's cached bytes if
500:         // GrowthBook state changed between parent turn-start and fork spawn.
501:         const mainThreadAgentDefinition = appState.agent ? appState.agentDefinitions.activeAgents.find(a => a.agentType === appState.agent) : undefined;
502:         const additionalWorkingDirectories = Array.from(appState.toolPermissionContext.additionalWorkingDirectories.keys());
503:         const defaultSystemPrompt = await getSystemPrompt(toolUseContext.options.tools, toolUseContext.options.mainLoopModel, additionalWorkingDirectories, toolUseContext.options.mcpClients);
504:         forkParentSystemPrompt = buildEffectiveSystemPrompt({
505:           mainThreadAgentDefinition,
506:           toolUseContext,
507:           customSystemPrompt: toolUseContext.options.customSystemPrompt,
508:           defaultSystemPrompt,
509:           appendSystemPrompt: toolUseContext.options.appendSystemPrompt
510:         });
511:       }
512:       promptMessages = buildForkedMessages(prompt, assistantMessage);
513:     } else {
514:       try {
515:         const additionalWorkingDirectories = Array.from(appState.toolPermissionContext.additionalWorkingDirectories.keys());
516: 
517:         // All agents have getSystemPrompt - pass toolUseContext to all
518:         const agentPrompt = selectedAgent.getSystemPrompt({
519:           toolUseContext
520:         });
521: 
522:         // Log agent memory loaded event for subagents
523:         if (selectedAgent.memory) {
524:           logEvent('tengu_agent_memory_loaded', {
525:             ...("external" === 'ant' && {
526:               agent_type: selectedAgent.agentType as AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS
527:             }),
528:             scope: selectedAgent.memory as AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS,
529:             source: 'subagent' as AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS
530:           });
531:         }
532: 
533:         // Apply environment details enhancement
534:         enhancedSystemPrompt = await enhanceSystemPromptWithEnvDetails([agentPrompt], resolvedAgentModel, additionalWorkingDirectories);
535:       } catch (error) {
536:         logForDebugging(`Failed to get system prompt for agent ${selectedAgent.agentType}: ${errorMessage(error)}`);
537:       }
538:       promptMessages = [createUserMessage({
539:         content: prompt
540:       })];
541:     }
542:     const metadata = {
543:       prompt,
544:       resolvedAgentModel,
545:       isBuiltInAgent: isBuiltInAgent(selectedAgent),
546:       startTime,
547:       agentType: selectedAgent.agentType,
548:       isAsync: (run_in_background === true || selectedAgent.background === true) && !isBackgroundTasksDisabled
549:     };
550: 
551:     // Use inline env check instead of coordinatorModule to avoid circular
552:     // dependency issues during test module loading.
553:     const isCoordinator = feature('COORDINATOR_MODE') ? isEnvTruthy(process.env.CLAUDE_CODE_COORDINATOR_MODE) : false;
554: 
555:     // Fork subagent experiment: force ALL spawns async for a unified
556:     // <task-notification> interaction model (not just fork spawns — all of them).
557:     const forceAsync = isForkSubagentEnabled();
558: 
559:     // Assistant mode: force all agents async. Synchronous subagents hold the
560:     // main loop's turn open until they complete — the daemon's inputQueue
561:     // backs up, and the first overdue cron catch-up on spawn becomes N
562:     // serial subagent turns blocking all user input. Same gate as
563:     // executeForkedSlashCommand's fire-and-forget path; the
564:     // <task-notification> re-entry there is handled by the else branch
565:     // below (registerAsyncAgentTask + notifyOnCompletion).
566:     const assistantForceAsync = feature('KAIROS') ? appState.kairosEnabled : false;
567:     const shouldRunAsync = (run_in_background === true || selectedAgent.background === true || isCoordinator || forceAsync || assistantForceAsync || (proactiveModule?.isProactiveActive() ?? false)) && !isBackgroundTasksDisabled;
568:     // Assemble the worker's tool pool independently of the parent's.
569:     // Workers always get their tools from assembleToolPool with their own
570:     // permission mode, so they aren't affected by the parent's tool
571:     // restrictions. This is computed here so that runAgent doesn't need to
572:     // import from tools.ts (which would create a circular dependency).
573:     const workerPermissionContext = {
574:       ...appState.toolPermissionContext,
575:       mode: selectedAgent.permissionMode ?? 'acceptEdits'
576:     };
577:     const workerTools = assembleToolPool(workerPermissionContext, appState.mcp.tools);
578: 
579:     // Create a stable agent ID early so it can be used for worktree slug
580:     const earlyAgentId = createAgentId();
581: 
582:     // Set up worktree isolation if requested
583:     let worktreeInfo: {
584:       worktreePath: string;
585:       worktreeBranch?: string;
586:       headCommit?: string;
587:       gitRoot?: string;
588:       hookBased?: boolean;
589:     } | null = null;
590:     if (effectiveIsolation === 'worktree') {
591:       const slug = `agent-${earlyAgentId.slice(0, 8)}`;
592:       worktreeInfo = await createAgentWorktree(slug);
593:     }
594: 
595:     // Fork + worktree: inject a notice telling the child to translate paths
596:     // and re-read potentially stale files. Appended after the fork directive
597:     // so it appears as the most recent guidance the child sees.
598:     if (isForkPath && worktreeInfo) {
599:       promptMessages.push(createUserMessage({
600:         content: buildWorktreeNotice(getCwd(), worktreeInfo.worktreePath)
601:       }));
602:     }
603:     const runAgentParams: Parameters<typeof runAgent>[0] = {
604:       agentDefinition: selectedAgent,
605:       promptMessages,
606:       toolUseContext,
607:       canUseTool,
608:       isAsync: shouldRunAsync,
609:       querySource: toolUseContext.options.querySource ?? getQuerySourceForAgent(selectedAgent.agentType, isBuiltInAgent(selectedAgent)),
610:       model: isForkPath ? undefined : model,
611:       // Fork path: pass parent's system prompt AND parent's exact tool
612:       // array (cache-identical prefix). workerTools is rebuilt under
613:       // permissionMode 'bubble' which differs from the parent's mode, so
614:       // its tool-def serialization diverges and breaks cache at the first
615:       // differing tool. useExactTools also inherits the parent's
616:       // thinkingConfig and isNonInteractiveSession (see runAgent.ts).
617:       //
618:       // Normal path: when a cwd override is in effect (worktree isolation
619:       // or explicit cwd), skip the pre-built system prompt so runAgent's
620:       // buildAgentSystemPrompt() runs inside wrapWithCwd where getCwd()
621:       // returns the override path.
622:       override: isForkPath ? {
623:         systemPrompt: forkParentSystemPrompt
624:       } : enhancedSystemPrompt && !worktreeInfo && !cwd ? {
625:         systemPrompt: asSystemPrompt(enhancedSystemPrompt)
626:       } : undefined,
627:       availableTools: isForkPath ? toolUseContext.options.tools : workerTools,
628:       // Pass parent conversation when the fork-subagent path needs full
629:       // context. useExactTools inherits thinkingConfig (runAgent.ts:624).
630:       forkContextMessages: isForkPath ? toolUseContext.messages : undefined,
631:       ...(isForkPath && {
632:         useExactTools: true
633:       }),
634:       worktreePath: worktreeInfo?.worktreePath,
635:       description
636:     };
```

## AgentTool async spawn branch

- File: `src/tools/AgentTool/AgentTool.tsx`
- Range: `686-760`

```ts
686:     if (shouldRunAsync) {
687:       const asyncAgentId = earlyAgentId;
688:       const agentBackgroundTask = registerAsyncAgent({
689:         agentId: asyncAgentId,
690:         description,
691:         prompt,
692:         selectedAgent,
693:         setAppState: rootSetAppState,
694:         // Don't link to parent's abort controller -- background agents should
695:         // survive when the user presses ESC to cancel the main thread.
696:         // They are killed explicitly via chat:killAgents.
697:         toolUseId: toolUseContext.toolUseId
698:       });
699: 
700:       // Register name → agentId for SendMessage routing. Post-registerAsyncAgent
701:       // so we don't leave a stale entry if spawn fails. Sync agents skipped —
702:       // coordinator is blocked, so SendMessage routing doesn't apply.
703:       if (name) {
704:         rootSetAppState(prev => {
705:           const next = new Map(prev.agentNameRegistry);
706:           next.set(name, asAgentId(asyncAgentId));
707:           return {
708:             ...prev,
709:             agentNameRegistry: next
710:           };
711:         });
712:       }
713: 
714:       // Wrap async agent execution in agent context for analytics attribution
715:       const asyncAgentContext = {
716:         agentId: asyncAgentId,
717:         // For subagents from teammates: use team lead's session
718:         // For subagents from main REPL: undefined (no parent session)
719:         parentSessionId: getParentSessionId(),
720:         agentType: 'subagent' as const,
721:         subagentName: selectedAgent.agentType,
722:         isBuiltIn: isBuiltInAgent(selectedAgent),
723:         invokingRequestId: assistantMessage?.requestId,
724:         invocationKind: 'spawn' as const,
725:         invocationEmitted: false
726:       };
727: 
728:       // Workload propagation: handlePromptSubmit wraps the entire turn in
729:       // runWithWorkload (AsyncLocalStorage). ALS context is captured at
730:       // invocation time — when this `void` fires — and survives every await
731:       // inside. No capture/restore needed; the detached closure sees the
732:       // parent turn's workload automatically, isolated from its finally.
733:       void runWithAgentContext(asyncAgentContext, () => wrapWithCwd(() => runAsyncAgentLifecycle({
734:         taskId: agentBackgroundTask.agentId,
735:         abortController: agentBackgroundTask.abortController!,
736:         makeStream: onCacheSafeParams => runAgent({
737:           ...runAgentParams,
738:           override: {
739:             ...runAgentParams.override,
740:             agentId: asAgentId(agentBackgroundTask.agentId),
741:             abortController: agentBackgroundTask.abortController!
742:           },
743:           onCacheSafeParams
744:         }),
745:         metadata,
746:         description,
747:         toolUseContext,
748:         rootSetAppState,
749:         agentIdForCleanup: asyncAgentId,
750:         enableSummarization: isCoordinator || isForkSubagentEnabled() || getSdkAgentProgressSummariesEnabled(),
751:         getWorktreeResult: cleanupWorktreeIfNeeded
752:       })));
753:       const canReadOutputFile = toolUseContext.options.tools.some(t => toolMatchesName(t, FILE_READ_TOOL_NAME) || toolMatchesName(t, BASH_TOOL_NAME));
754:       return {
755:         data: {
756:           isAsync: true as const,
757:           status: 'async_launched' as const,
758:           agentId: agentBackgroundTask.agentId,
759:           description: description,
760:           prompt: prompt,
```

## AgentTool sync spawn branch start

- File: `src/tools/AgentTool/AgentTool.tsx`
- Range: `766-856`

```ts
766:       // Create an explicit agentId for sync agents
767:       const syncAgentId = asAgentId(earlyAgentId);
768: 
769:       // Set up agent context for sync execution (for analytics attribution)
770:       const syncAgentContext = {
771:         agentId: syncAgentId,
772:         // For subagents from teammates: use team lead's session
773:         // For subagents from main REPL: undefined (no parent session)
774:         parentSessionId: getParentSessionId(),
775:         agentType: 'subagent' as const,
776:         subagentName: selectedAgent.agentType,
777:         isBuiltIn: isBuiltInAgent(selectedAgent),
778:         invokingRequestId: assistantMessage?.requestId,
779:         invocationKind: 'spawn' as const,
780:         invocationEmitted: false
781:       };
782: 
783:       // Wrap entire sync agent execution in context for analytics attribution
784:       // and optionally in a worktree cwd override for filesystem isolation
785:       return runWithAgentContext(syncAgentContext, () => wrapWithCwd(async () => {
786:         const agentMessages: MessageType[] = [];
787:         const agentStartTime = Date.now();
788:         const syncTracker = createProgressTracker();
789:         const syncResolveActivity = createActivityDescriptionResolver(toolUseContext.options.tools);
790: 
791:         // Yield initial progress message to carry metadata (prompt)
792:         if (promptMessages.length > 0) {
793:           const normalizedPromptMessages = normalizeMessages(promptMessages);
794:           const normalizedFirstMessage = normalizedPromptMessages.find((m): m is NormalizedUserMessage => m.type === 'user');
795:           if (normalizedFirstMessage && normalizedFirstMessage.type === 'user' && onProgress) {
796:             onProgress({
797:               toolUseID: `agent_${assistantMessage.message.id}`,
798:               data: {
799:                 message: normalizedFirstMessage,
800:                 type: 'agent_progress',
801:                 prompt,
802:                 agentId: syncAgentId
803:               }
804:             });
805:           }
806:         }
807: 
808:         // Register as foreground task immediately so it can be backgrounded at any time
809:         // Skip registration if background tasks are disabled
810:         let foregroundTaskId: string | undefined;
811:         // Create the background race promise once outside the loop — otherwise
812:         // each iteration adds a new .then() reaction to the same pending
813:         // promise, accumulating callbacks for the lifetime of the agent.
814:         let backgroundPromise: Promise<{
815:           type: 'background';
816:         }> | undefined;
817:         let cancelAutoBackground: (() => void) | undefined;
818:         if (!isBackgroundTasksDisabled) {
819:           const registration = registerAgentForeground({
820:             agentId: syncAgentId,
821:             description,
822:             prompt,
823:             selectedAgent,
824:             setAppState: rootSetAppState,
825:             toolUseId: toolUseContext.toolUseId,
826:             autoBackgroundMs: getAutoBackgroundMs() || undefined
827:           });
828:           foregroundTaskId = registration.taskId;
829:           backgroundPromise = registration.backgroundSignal.then(() => ({
830:             type: 'background' as const
831:           }));
832:           cancelAutoBackground = registration.cancelAutoBackground;
833:         }
834: 
835:         // Track if we've shown the background hint UI
836:         let backgroundHintShown = false;
837:         // Track if the agent was backgrounded (cleanup handled by backgrounded finally)
838:         let wasBackgrounded = false;
839:         // Per-scope stop function — NOT shared with the backgrounded closure.
840:         // idempotent: startAgentSummarization's stop() checks `stopped` flag.
841:         let stopForegroundSummarization: (() => void) | undefined;
842:         // const capture for sound type narrowing inside the callback below
843:         const summaryTaskId = foregroundTaskId;
844: 
845:         // Get async iterator for the agent
846:         const agentIterator = runAgent({
847:           ...runAgentParams,
848:           override: {
849:             ...runAgentParams.override,
850:             agentId: syncAgentId
851:           },
852:           onCacheSafeParams: summaryTaskId && getSdkAgentProgressSummariesEnabled() ? (params: CacheSafeParams) => {
853:             const {
854:               stop
855:             } = startAgentSummarization(summaryTaskId, syncAgentId, params, rootSetAppState);
856:             stopForegroundSummarization = stop;
```

## runAgent signature and initial context merge

- File: `src/tools/AgentTool/runAgent.ts`
- Range: `248-379`

```ts
248: export async function* runAgent({
249:   agentDefinition,
250:   promptMessages,
251:   toolUseContext,
252:   canUseTool,
253:   isAsync,
254:   canShowPermissionPrompts,
255:   forkContextMessages,
256:   querySource,
257:   override,
258:   model,
259:   maxTurns,
260:   preserveToolUseResults,
261:   availableTools,
262:   allowedTools,
263:   onCacheSafeParams,
264:   contentReplacementState,
265:   useExactTools,
266:   worktreePath,
267:   description,
268:   transcriptSubdir,
269:   onQueryProgress,
270: }: {
271:   agentDefinition: AgentDefinition
272:   promptMessages: Message[]
273:   toolUseContext: ToolUseContext
274:   canUseTool: CanUseToolFn
275:   isAsync: boolean
276:   /** Whether this agent can show permission prompts. Defaults to !isAsync.
277:    * Set to true for in-process teammates that run async but share the terminal. */
278:   canShowPermissionPrompts?: boolean
279:   forkContextMessages?: Message[]
280:   querySource: QuerySource
281:   override?: {
282:     userContext?: { [k: string]: string }
283:     systemContext?: { [k: string]: string }
284:     systemPrompt?: SystemPrompt
285:     abortController?: AbortController
286:     agentId?: AgentId
287:   }
288:   model?: ModelAlias
289:   maxTurns?: number
290:   /** Preserve toolUseResult on messages for subagents with viewable transcripts */
291:   preserveToolUseResults?: boolean
292:   /** Precomputed tool pool for the worker agent. Computed by the caller
293:    * (AgentTool.tsx) to avoid a circular dependency between runAgent and tools.ts.
294:    * Always contains the full tool pool assembled with the worker's own permission
295:    * mode, independent of the parent's tool restrictions. */
296:   availableTools: Tools
297:   /** Tool permission rules to add to the agent's session allow rules.
298:    * When provided, replaces ALL allow rules so the agent only has what's
299:    * explicitly listed (parent approvals don't leak through). */
300:   allowedTools?: string[]
301:   /** Optional callback invoked with CacheSafeParams after constructing the agent's
302:    * system prompt, context, and tools. Used by background summarization to fork
303:    * the agent's conversation for periodic progress summaries. */
304:   onCacheSafeParams?: (params: CacheSafeParams) => void
305:   /** Replacement state reconstructed from a resumed sidechain transcript so
306:    * the same tool results are re-replaced (prompt cache stability). When
307:    * omitted, createSubagentContext clones the parent's state. */
308:   contentReplacementState?: ContentReplacementState
309:   /** When true, use availableTools directly without filtering through
310:    * resolveAgentTools(). Also inherits the parent's thinkingConfig and
311:    * isNonInteractiveSession instead of overriding them. Used by the fork
312:    * subagent path to produce byte-identical API request prefixes for
313:    * prompt cache hits. */
314:   useExactTools?: boolean
315:   /** Worktree path if the agent was spawned with isolation: "worktree".
316:    * Persisted to metadata so resume can restore the correct cwd. */
317:   worktreePath?: string
318:   /** Original task description from AgentTool input. Persisted to metadata
319:    * so a resumed agent's notification can show the original description. */
320:   description?: string
321:   /** Optional subdirectory under subagents/ to group this agent's transcript
322:    * with related ones (e.g. workflows/<runId> for workflow subagents). */
323:   transcriptSubdir?: string
324:   /** Optional callback fired on every message yielded by query() — including
325:    * stream_event deltas that runAgent otherwise drops. Use to detect liveness
326:    * during long single-block streams (e.g. thinking) where no assistant
327:    * message is yielded for >60s. */
328:   onQueryProgress?: () => void
329: }): AsyncGenerator<Message, void> {
330:   // Track subagent usage for feature discovery
331: 
332:   const appState = toolUseContext.getAppState()
333:   const permissionMode = appState.toolPermissionContext.mode
334:   // Always-shared channel to the root AppState store. toolUseContext.setAppState
335:   // is a no-op when the *parent* is itself an async agent (nested async→async),
336:   // so session-scoped writes (hooks, bash tasks) must go through this instead.
337:   const rootSetAppState =
338:     toolUseContext.setAppStateForTasks ?? toolUseContext.setAppState
339: 
340:   const resolvedAgentModel = getAgentModel(
341:     agentDefinition.model,
342:     toolUseContext.options.mainLoopModel,
343:     model,
344:     permissionMode,
345:   )
346: 
347:   const agentId = override?.agentId ? override.agentId : createAgentId()
348: 
349:   // Route this agent's transcript into a grouping subdirectory if requested
350:   // (e.g. workflow subagents write to subagents/workflows/<runId>/).
351:   if (transcriptSubdir) {
352:     setAgentTranscriptSubdir(agentId, transcriptSubdir)
353:   }
354: 
355:   // Register agent in Perfetto trace for hierarchy visualization
356:   if (isPerfettoTracingEnabled()) {
357:     const parentId = toolUseContext.agentId ?? getSessionId()
358:     registerPerfettoAgent(agentId, agentDefinition.agentType, parentId)
359:   }
360: 
361:   // Log API calls path for subagents (ant-only)
362:   if (process.env.USER_TYPE === 'ant') {
363:     logForDebugging(
364:       `[Subagent ${agentDefinition.agentType}] API calls: ${getDisplayPath(getDumpPromptsPath(agentId))}`,
365:     )
366:   }
367: 
368:   // Handle message forking for context sharing
369:   // Filter out incomplete tool calls from parent messages to avoid API errors
370:   const contextMessages: Message[] = forkContextMessages
371:     ? filterIncompleteToolCalls(forkContextMessages)
372:     : []
373:   const initialMessages: Message[] = [...contextMessages, ...promptMessages]
374: 
375:   const agentReadFileState =
376:     forkContextMessages !== undefined
377:       ? cloneFileStateCache(toolUseContext.readFileState)
378:       : createFileStateCacheWithSizeLimit(READ_FILE_STATE_CACHE_SIZE)
379: 
```

## runAgent tools/system/hook/skill/MCP setup

- File: `src/tools/AgentTool/runAgent.ts`
- Range: `500-745`

```ts
500:   const resolvedTools = useExactTools
501:     ? availableTools
502:     : resolveAgentTools(agentDefinition, availableTools, isAsync).resolvedTools
503: 
504:   const additionalWorkingDirectories = Array.from(
505:     appState.toolPermissionContext.additionalWorkingDirectories.keys(),
506:   )
507: 
508:   const agentSystemPrompt = override?.systemPrompt
509:     ? override.systemPrompt
510:     : asSystemPrompt(
511:         await getAgentSystemPrompt(
512:           agentDefinition,
513:           toolUseContext,
514:           resolvedAgentModel,
515:           additionalWorkingDirectories,
516:           resolvedTools,
517:         ),
518:       )
519: 
520:   // Determine abortController:
521:   // - Override takes precedence
522:   // - Async agents get a new unlinked controller (runs independently)
523:   // - Sync agents share parent's controller
524:   const agentAbortController = override?.abortController
525:     ? override.abortController
526:     : isAsync
527:       ? new AbortController()
528:       : toolUseContext.abortController
529: 
530:   // Execute SubagentStart hooks and collect additional context
531:   const additionalContexts: string[] = []
532:   for await (const hookResult of executeSubagentStartHooks(
533:     agentId,
534:     agentDefinition.agentType,
535:     agentAbortController.signal,
536:   )) {
537:     if (
538:       hookResult.additionalContexts &&
539:       hookResult.additionalContexts.length > 0
540:     ) {
541:       additionalContexts.push(...hookResult.additionalContexts)
542:     }
543:   }
544: 
545:   // Add SubagentStart hook context as a user message (consistent with SessionStart/UserPromptSubmit)
546:   if (additionalContexts.length > 0) {
547:     const contextMessage = createAttachmentMessage({
548:       type: 'hook_additional_context',
549:       content: additionalContexts,
550:       hookName: 'SubagentStart',
551:       toolUseID: randomUUID(),
552:       hookEvent: 'SubagentStart',
553:     })
554:     initialMessages.push(contextMessage)
555:   }
556: 
557:   // Register agent's frontmatter hooks (scoped to agent lifecycle)
558:   // Pass isAgent=true to convert Stop hooks to SubagentStop (since subagents trigger SubagentStop)
559:   // Same admin-trusted gate for frontmatter hooks: under ["hooks"] alone
560:   // (skills/agents not locked), user agents still load — block their
561:   // frontmatter-hook REGISTRATION here where source is known, rather than
562:   // blanket-blocking all session hooks at execution time (which would
563:   // also kill plugin agents' hooks).
564:   const hooksAllowedForThisAgent =
565:     !isRestrictedToPluginOnly('hooks') ||
566:     isSourceAdminTrusted(agentDefinition.source)
567:   if (agentDefinition.hooks && hooksAllowedForThisAgent) {
568:     registerFrontmatterHooks(
569:       rootSetAppState,
570:       agentId,
571:       agentDefinition.hooks,
572:       `agent '${agentDefinition.agentType}'`,
573:       true, // isAgent - converts Stop to SubagentStop
574:     )
575:   }
576: 
577:   // Preload skills from agent frontmatter
578:   const skillsToPreload = agentDefinition.skills ?? []
579:   if (skillsToPreload.length > 0) {
580:     const allSkills = await getSkillToolCommands(getProjectRoot())
581: 
582:     // Filter valid skills and warn about missing ones
583:     const validSkills: Array<{
584:       skillName: string
585:       skill: (typeof allSkills)[0] & { type: 'prompt' }
586:     }> = []
587: 
588:     for (const skillName of skillsToPreload) {
589:       // Resolve the skill name, trying multiple strategies:
590:       // 1. Exact match (hasCommand checks name, userFacingName, aliases)
591:       // 2. Fully-qualified with agent's plugin prefix (e.g., "my-skill" → "plugin:my-skill")
592:       // 3. Suffix match on ":skillName" for plugin-namespaced skills
593:       const resolvedName = resolveSkillName(
594:         skillName,
595:         allSkills,
596:         agentDefinition,
597:       )
598:       if (!resolvedName) {
599:         logForDebugging(
600:           `[Agent: ${agentDefinition.agentType}] Warning: Skill '${skillName}' specified in frontmatter was not found`,
601:           { level: 'warn' },
602:         )
603:         continue
604:       }
605: 
606:       const skill = getCommand(resolvedName, allSkills)
607:       if (skill.type !== 'prompt') {
608:         logForDebugging(
609:           `[Agent: ${agentDefinition.agentType}] Warning: Skill '${skillName}' is not a prompt-based skill`,
610:           { level: 'warn' },
611:         )
612:         continue
613:       }
614:       validSkills.push({ skillName, skill })
615:     }
616: 
617:     // Load all skill contents concurrently and add to initial messages
618:     const { formatSkillLoadingMetadata } = await import(
619:       '../../utils/processUserInput/processSlashCommand.js'
620:     )
621:     const loaded = await Promise.all(
622:       validSkills.map(async ({ skillName, skill }) => ({
623:         skillName,
624:         skill,
625:         content: await skill.getPromptForCommand('', toolUseContext),
626:       })),
627:     )
628:     for (const { skillName, skill, content } of loaded) {
629:       logForDebugging(
630:         `[Agent: ${agentDefinition.agentType}] Preloaded skill '${skillName}'`,
631:       )
632: 
633:       // Add command-message metadata so the UI shows which skill is loading
634:       const metadata = formatSkillLoadingMetadata(
635:         skillName,
636:         skill.progressMessage,
637:       )
638: 
639:       initialMessages.push(
640:         createUserMessage({
641:           content: [{ type: 'text', text: metadata }, ...content],
642:           isMeta: true,
643:         }),
644:       )
645:     }
646:   }
647: 
648:   // Initialize agent-specific MCP servers (additive to parent's servers)
649:   const {
650:     clients: mergedMcpClients,
651:     tools: agentMcpTools,
652:     cleanup: mcpCleanup,
653:   } = await initializeAgentMcpServers(
654:     agentDefinition,
655:     toolUseContext.options.mcpClients,
656:   )
657: 
658:   // Merge agent MCP tools with resolved agent tools, deduplicating by name.
659:   // resolvedTools is already deduplicated (see resolveAgentTools), so skip
660:   // the spread + uniqBy overhead when there are no agent-specific MCP tools.
661:   const allTools =
662:     agentMcpTools.length > 0
663:       ? uniqBy([...resolvedTools, ...agentMcpTools], 'name')
664:       : resolvedTools
665: 
666:   // Build agent-specific options
667:   const agentOptions: ToolUseContext['options'] = {
668:     isNonInteractiveSession: useExactTools
669:       ? toolUseContext.options.isNonInteractiveSession
670:       : isAsync
671:         ? true
672:         : (toolUseContext.options.isNonInteractiveSession ?? false),
673:     appendSystemPrompt: toolUseContext.options.appendSystemPrompt,
674:     tools: allTools,
675:     commands: [],
676:     debug: toolUseContext.options.debug,
677:     verbose: toolUseContext.options.verbose,
678:     mainLoopModel: resolvedAgentModel,
679:     // For fork children (useExactTools), inherit thinking config to match the
680:     // parent's API request prefix for prompt cache hits. For regular
681:     // sub-agents, disable thinking to control output token costs.
682:     thinkingConfig: useExactTools
683:       ? toolUseContext.options.thinkingConfig
684:       : { type: 'disabled' as const },
685:     mcpClients: mergedMcpClients,
686:     mcpResources: toolUseContext.options.mcpResources,
687:     agentDefinitions: toolUseContext.options.agentDefinitions,
688:     // Fork children (useExactTools path) need querySource on context.options
689:     // for the recursive-fork guard at AgentTool.tsx call() — it checks
690:     // options.querySource === 'agent:builtin:fork'. This survives autocompact
691:     // (which rewrites messages, not context.options). Without this, the guard
692:     // reads undefined and only the message-scan fallback fires — which
693:     // autocompact defeats by replacing the fork-boilerplate message.
694:     ...(useExactTools && { querySource }),
695:   }
696: 
697:   // Create subagent context using shared helper
698:   // - Sync agents share setAppState, setResponseLength, abortController with parent
699:   // - Async agents are fully isolated (but with explicit unlinked abortController)
700:   const agentToolUseContext = createSubagentContext(toolUseContext, {
701:     options: agentOptions,
702:     agentId,
703:     agentType: agentDefinition.agentType,
704:     messages: initialMessages,
705:     readFileState: agentReadFileState,
706:     abortController: agentAbortController,
707:     getAppState: agentGetAppState,
708:     // Sync agents share these callbacks with parent
709:     shareSetAppState: !isAsync,
710:     shareSetResponseLength: true, // Both sync and async contribute to response metrics
711:     criticalSystemReminder_EXPERIMENTAL:
712:       agentDefinition.criticalSystemReminder_EXPERIMENTAL,
713:     contentReplacementState,
714:   })
715: 
716:   // Preserve tool use results for subagents with viewable transcripts (in-process teammates)
717:   if (preserveToolUseResults) {
718:     agentToolUseContext.preserveToolUseResults = true
719:   }
720: 
721:   // Expose cache-safe params for background summarization (prompt cache sharing)
722:   if (onCacheSafeParams) {
723:     onCacheSafeParams({
724:       systemPrompt: agentSystemPrompt,
725:       userContext: resolvedUserContext,
726:       systemContext: resolvedSystemContext,
727:       toolUseContext: agentToolUseContext,
728:       forkContextMessages: initialMessages,
729:     })
730:   }
731: 
732:   // Record initial messages before the query loop starts, plus the agentType
733:   // so resume can route correctly when subagent_type is omitted. Both writes
734:   // are fire-and-forget — persistence failure shouldn't block the agent.
735:   void recordSidechainTranscript(initialMessages, agentId).catch(_err =>
736:     logForDebugging(`Failed to record sidechain transcript: ${_err}`),
737:   )
738:   void writeAgentMetadata(agentId, {
739:     agentType: agentDefinition.agentType,
740:     ...(worktreePath && { worktreePath }),
741:     ...(description && { description }),
742:   }).catch(_err => logForDebugging(`Failed to write agent metadata: ${_err}`))
743: 
744:   // Track the last recorded message UUID for parent chain continuity
745:   let lastRecordedUuid: UUID | null = initialMessages.at(-1)?.uuid ?? null
```

## runAgent query loop and transcript recording

- File: `src/tools/AgentTool/runAgent.ts`
- Range: `760-860`

```ts
760:       // so TTFT/OTPS update during subagent execution.
761:       if (
762:         message.type === 'stream_event' &&
763:         message.event.type === 'message_start' &&
764:         message.ttftMs != null
765:       ) {
766:         toolUseContext.pushApiMetricsEntry?.(message.ttftMs)
767:         continue
768:       }
769: 
770:       // Yield attachment messages (e.g., structured_output) without recording them
771:       if (message.type === 'attachment') {
772:         // Handle max turns reached signal from query.ts
773:         if (message.attachment.type === 'max_turns_reached') {
774:           logForDebugging(
775:             `[Agent
776: : $
777: {
778:   agentDefinition.agentType
779: }
780: ] Reached max turns limit ($
781: {
782:   message.attachment.maxTurns
783: }
784: )`,
785:           )
786:           break
787:         }
788:         yield message
789:         continue
790:       }
791: 
792:       if (isRecordableMessage(message)) {
793:         // Record only the new message with correct parent (O(1) per message)
794:         await recordSidechainTranscript(
795:           [message],
796:           agentId,
797:           lastRecordedUuid,
798:         ).catch(err =>
799:           logForDebugging(`Failed to record sidechain transcript: ${err}`),
800:         )
801:         if (message.type !== 'progress') {
802:           lastRecordedUuid = message.uuid
803:         }
804:         yield message
805:       }
806:     }
807: 
808:     if (agentAbortController.signal.aborted) {
809:       throw new AbortError()
810:     }
811: 
812:     // Run callback if provided (only built-in agents have callbacks)
813:     if (isBuiltInAgent(agentDefinition) && agentDefinition.callback) {
814:       agentDefinition.callback()
815:     }
816:   } finally {
817:     // Clean up agent-specific MCP servers (runs on normal completion, abort, or error)
818:     await mcpCleanup()
819:     // Clean up agent's session hooks
820:     if (agentDefinition.hooks) {
821:       clearSessionHooks(rootSetAppState, agentId)
822:     }
823:     // Clean up prompt cache tracking state for this agent
824:     if (feature('PROMPT_CACHE_BREAK_DETECTION')) {
825:       cleanupAgentTracking(agentId)
826:     }
827:     // Release cloned file state cache memory
828:     agentToolUseContext.readFileState.clear()
829:     // Release the cloned fork context messages
830:     initialMessages.length = 0
831:     // Release perfetto agent registry entry
832:     unregisterPerfettoAgent(agentId)
833:     // Release transcript subdir mapping
834:     clearAgentTranscriptSubdir(agentId)
835:     // Release this agent's todos entry. Without this, every subagent that
836:     // called TodoWrite leaves a key in AppState.todos forever (even after all
837:     // items complete, the value is [] but the key stays). Whale sessions
838:     // spawn hundreds of agents; each orphaned key is a small leak that adds up.
839:     rootSetAppState(prev => {
840:       if (!(agentId in prev.todos)) return prev
841:       const { [agentId]: _removed, ...todos } = prev.todos
842:       return { ...prev, todos }
843:     })
844:     // Kill any background bash tasks this agent spawned. Without this, a
845:     // `run_in_background` shell loop (e.g. test fixture fake-logs.sh) outlives
846:     // the agent as a PPID=1 zombie once the main session eventually exits.
847:     killShellTasksForAgent(agentId, toolUseContext.getAppState, rootSetAppState)
848:     /* eslint-disable @typescript-eslint/no-require-imports */
849:     if (feature('MONITOR_TOOL')) {
850:       const mcpMod =
851:         require('../../tasks/MonitorMcpTask/MonitorMcpTask.js') as typeof import('../../tasks/MonitorMcpTask/MonitorMcpTask.js')
852:       mcpMod.killMonitorMcpTasksForAgent(
853:         agentId,
854:         toolUseContext.getAppState,
855:         rootSetAppState,
856:       )
857:     }
858:     /* eslint-enable @typescript-eslint/no-require-imports */
859:   }
860: }
```

## forkSubagent: feature gate and synthetic agent

- File: `src/tools/AgentTool/forkSubagent.ts`
- Range: `18-71`

```ts
18: /**
19:  * Fork subagent feature gate.
20:  *
21:  * When enabled:
22:  * - `subagent_type` becomes optional on the Agent tool schema
23:  * - Omitting `subagent_type` triggers an implicit fork: the child inherits
24:  *   the parent's full conversation context and system prompt
25:  * - All agent spawns run in the background (async) for a unified
26:  *   `<task-notification>` interaction model
27:  * - `/fork <directive>` slash command is available
28:  *
29:  * Mutually exclusive with coordinator mode — coordinator already owns the
30:  * orchestration role and has its own delegation model.
31:  */
32: export function isForkSubagentEnabled(): boolean {
33:   if (feature('FORK_SUBAGENT')) {
34:     if (isCoordinatorMode()) return false
35:     if (getIsNonInteractiveSession()) return false
36:     return true
37:   }
38:   return false
39: }
40: 
41: /** Synthetic agent type name used for analytics when the fork path fires. */
42: export const FORK_SUBAGENT_TYPE = 'fork'
43: 
44: /**
45:  * Synthetic agent definition for the fork path.
46:  *
47:  * Not registered in builtInAgents — used only when `!subagent_type` and the
48:  * experiment is active. `tools: ['*']` with `useExactTools` means the fork
49:  * child receives the parent's exact tool pool (for cache-identical API
50:  * prefixes). `permissionMode: 'bubble'` surfaces permission prompts to the
51:  * parent terminal. `model: 'inherit'` keeps the parent's model for context
52:  * length parity.
53:  *
54:  * The getSystemPrompt here is unused: the fork path passes
55:  * `override.systemPrompt` with the parent's already-rendered system prompt
56:  * bytes, threaded via `toolUseContext.renderedSystemPrompt`. Reconstructing
57:  * by re-calling getSystemPrompt() can diverge (GrowthBook cold→warm) and
58:  * bust the prompt cache; threading the rendered bytes is byte-exact.
59:  */
60: export const FORK_AGENT = {
61:   agentType: FORK_SUBAGENT_TYPE,
62:   whenToUse:
63:     'Implicit fork — inherits full conversation context. Not selectable via subagent_type; triggered by omitting subagent_type when the fork experiment is active.',
64:   tools: ['*'],
65:   maxTurns: 200,
66:   model: 'inherit',
67:   permissionMode: 'bubble',
68:   source: 'built-in',
69:   baseDir: 'built-in',
70:   getSystemPrompt: () => '',
71: } satisfies BuiltInAgentDefinition
```

## forkSubagent: buildForkedMessages

- File: `src/tools/AgentTool/forkSubagent.ts`
- Range: `95-168`

```ts
 95: /**
 96:  * Build the forked conversation messages for the child agent.
 97:  *
 98:  * For prompt cache sharing, all fork children must produce byte-identical
 99:  * API request prefixes. This function:
100:  * 1. Keeps the full parent assistant message (all tool_use blocks, thinking, text)
101:  * 2. Builds a single user message with tool_results for every tool_use block
102:  *    using an identical placeholder, then appends a per-child directive text block
103:  *
104:  * Result: [...history, assistant(all_tool_uses), user(placeholder_results..., directive)]
105:  * Only the final text block differs per child, maximizing cache hits.
106:  */
107: export function buildForkedMessages(
108:   directive: string,
109:   assistantMessage: AssistantMessage,
110: ): MessageType[] {
111:   // Clone the assistant message to avoid mutating the original, keeping all
112:   // content blocks (thinking, text, and every tool_use)
113:   const fullAssistantMessage: AssistantMessage = {
114:     ...assistantMessage,
115:     uuid: randomUUID(),
116:     message: {
117:       ...assistantMessage.message,
118:       content: [...assistantMessage.message.content],
119:     },
120:   }
121: 
122:   // Collect all tool_use blocks from the assistant message
123:   const toolUseBlocks = assistantMessage.message.content.filter(
124:     (block): block is BetaToolUseBlock => block.type === 'tool_use',
125:   )
126: 
127:   if (toolUseBlocks.length === 0) {
128:     logForDebugging(
129:       `No tool_use blocks found in assistant message for fork directive: ${directive.slice(0, 50)}...`,
130:       { level: 'error' },
131:     )
132:     return [
133:       createUserMessage({
134:         content: [
135:           { type: 'text' as const, text: buildChildMessage(directive) },
136:         ],
137:       }),
138:     ]
139:   }
140: 
141:   // Build tool_result blocks for every tool_use, all with identical placeholder text
142:   const toolResultBlocks = toolUseBlocks.map(block => ({
143:     type: 'tool_result' as const,
144:     tool_use_id: block.id,
145:     content: [
146:       {
147:         type: 'text' as const,
148:         text: FORK_PLACEHOLDER_RESULT,
149:       },
150:     ],
151:   }))
152: 
153:   // Build a single user message: all placeholder tool_results + the per-child directive
154:   // TODO(smoosh): this text sibling creates a [tool_result, text] pattern on the wire
155:   // (renders as </function_results>\n\nHuman:<text>). One-off per-child construction,
156:   // not a repeated teacher, so low-priority. If we ever care, use smooshIntoToolResult
157:   // from src/utils/messages.ts to fold the directive into the last tool_result.content.
158:   const toolResultMessage = createUserMessage({
159:     content: [
160:       ...toolResultBlocks,
161:       {
162:         type: 'text' as const,
163:         text: buildChildMessage(directive),
164:       },
165:     ],
166:   })
167: 
168:   return [fullAssistantMessage, toolResultMessage]
```

## forkSubagent: child directive and worktree notice

- File: `src/tools/AgentTool/forkSubagent.ts`
- Range: `171-210`

```ts
171: export function buildChildMessage(directive: string): string {
172:   return `<${FORK_BOILERPLATE_TAG}>
173: STOP. READ THIS FIRST.
174: 
175: You are a forked worker process. You are NOT the main agent.
176: 
177: RULES (non-negotiable):
178: 1. Your system prompt says "default to forking." IGNORE IT \u2014 that's for the parent. You ARE the fork. Do NOT spawn sub-agents; execute directly.
179: 2. Do NOT converse, ask questions, or suggest next steps
180: 3. Do NOT editorialize or add meta-commentary
181: 4. USE your tools directly: Bash, Read, Write, etc.
182: 5. If you modify files, commit your changes before reporting. Include the commit hash in your report.
183: 6. Do NOT emit text between tool calls. Use tools silently, then report once at the end.
184: 7. Stay strictly within your directive's scope. If you discover related systems outside your scope, mention them in one sentence at most — other workers cover those areas.
185: 8. Keep your report under 500 words unless the directive specifies otherwise. Be factual and concise.
186: 9. Your response MUST begin with "Scope:". No preamble, no thinking-out-loud.
187: 10. REPORT structured facts, then stop
188: 
189: Output format (plain text labels, not markdown headers):
190:   Scope: <echo back your assigned scope in one sentence>
191:   Result: <the answer or key findings, limited to the scope above>
192:   Key files: <relevant file paths — include for research tasks>
193:   Files changed: <list with commit hash — include only if you modified files>
194:   Issues: <list — include only if there are issues to flag>
195: </${FORK_BOILERPLATE_TAG}>
196: 
197: ${FORK_DIRECTIVE_PREFIX}${directive}`
198: }
199: 
200: /**
201:  * Notice injected into fork children running in an isolated worktree.
202:  * Tells the child to translate paths from the inherited context, re-read
203:  * potentially stale files, and that its changes are isolated.
204:  */
205: export function buildWorktreeNotice(
206:   parentCwd: string,
207:   worktreeCwd: string,
208: ): string {
209:   return `You've inherited the conversation context above from a parent agent working in ${parentCwd}. You are operating in an isolated git worktree at ${worktreeCwd} — same repository, same relative file structure, separate working copy. Paths in the inherited context refer to the parent's working directory; translate them to your worktree root. Re-read files before editing if the parent may have modified them since they appear in the context. Your changes stay in this worktree and will not affect the parent's files.`
210: }
```

## createSubagentContext: isolated context object

- File: `src/utils/forkedAgent.ts`
- Range: `345-462`

```ts
345: export function createSubagentContext(
346:   parentContext: ToolUseContext,
347:   overrides?: SubagentContextOverrides,
348: ): ToolUseContext {
349:   // Determine abortController: explicit override > share parent's > new child
350:   const abortController =
351:     overrides?.abortController ??
352:     (overrides?.shareAbortController
353:       ? parentContext.abortController
354:       : createChildAbortController(parentContext.abortController))
355: 
356:   // Determine getAppState - wrap to set shouldAvoidPermissionPrompts unless sharing abortController
357:   // (if sharing abortController, it's an interactive agent that CAN show UI)
358:   const getAppState: ToolUseContext['getAppState'] = overrides?.getAppState
359:     ? overrides.getAppState
360:     : overrides?.shareAbortController
361:       ? parentContext.getAppState
362:       : () => {
363:           const state = parentContext.getAppState()
364:           if (state.toolPermissionContext.shouldAvoidPermissionPrompts) {
365:             return state
366:           }
367:           return {
368:             ...state,
369:             toolPermissionContext: {
370:               ...state.toolPermissionContext,
371:               shouldAvoidPermissionPrompts: true,
372:             },
373:           }
374:         }
375: 
376:   return {
377:     // Mutable state - cloned by default to maintain isolation
378:     // Clone overrides.readFileState if provided, otherwise clone from parent
379:     readFileState: cloneFileStateCache(
380:       overrides?.readFileState ?? parentContext.readFileState,
381:     ),
382:     nestedMemoryAttachmentTriggers: new Set<string>(),
383:     loadedNestedMemoryPaths: new Set<string>(),
384:     dynamicSkillDirTriggers: new Set<string>(),
385:     // Per-subagent: tracks skills surfaced by discovery for was_discovered telemetry (SkillTool.ts:116)
386:     discoveredSkillNames: new Set<string>(),
387:     toolDecisions: undefined,
388:     // Budget decisions: override > clone of parent > undefined (feature off).
389:     //
390:     // Clone by default (not fresh): cache-sharing forks process parent
391:     // messages containing parent tool_use_ids. A fresh state would see
392:     // them as unseen and make divergent replacement decisions → wire
393:     // prefix differs → cache miss. A clone makes identical decisions →
394:     // cache hit. For non-forking subagents the parent UUIDs never match
395:     // — clone is a harmless no-op.
396:     //
397:     // Override: AgentTool resume (reconstructed from sidechain records)
398:     // and inProcessRunner (per-teammate persistent loop state).
399:     contentReplacementState:
400:       overrides?.contentReplacementState ??
401:       (parentContext.contentReplacementState
402:         ? cloneContentReplacementState(parentContext.contentReplacementState)
403:         : undefined),
404: 
405:     // AbortController
406:     abortController,
407: 
408:     // AppState access
409:     getAppState,
410:     setAppState: overrides?.shareSetAppState
411:       ? parentContext.setAppState
412:       : () => {},
413:     // Task registration/kill must always reach the root store, even when
414:     // setAppState is a no-op — otherwise async agents' background bash tasks
415:     // are never registered and never killed (PPID=1 zombie).
416:     setAppStateForTasks:
417:       parentContext.setAppStateForTasks ?? parentContext.setAppState,
418:     // Async subagents whose setAppState is a no-op need local denial tracking
419:     // so the denial counter actually accumulates across retries.
420:     localDenialTracking: overrides?.shareSetAppState
421:       ? parentContext.localDenialTracking
422:       : createDenialTrackingState(),
423: 
424:     // Mutation callbacks - no-op by default
425:     setInProgressToolUseIDs: () => {},
426:     setResponseLength: overrides?.shareSetResponseLength
427:       ? parentContext.setResponseLength
428:       : () => {},
429:     pushApiMetricsEntry: overrides?.shareSetResponseLength
430:       ? parentContext.pushApiMetricsEntry
431:       : undefined,
432:     updateFileHistoryState: () => {},
433:     // Attribution is scoped and functional (prev => next) — safe to share even
434:     // when setAppState is stubbed. Concurrent calls compose via React's state queue.
435:     updateAttributionState: parentContext.updateAttributionState,
436: 
437:     // UI callbacks - undefined for subagents (can't control parent UI)
438:     addNotification: undefined,
439:     setToolJSX: undefined,
440:     setStreamMode: undefined,
441:     setSDKStatus: undefined,
442:     openMessageSelector: undefined,
443: 
444:     // Fields that can be overridden or copied from parent
445:     options: overrides?.options ?? parentContext.options,
446:     messages: overrides?.messages ?? parentContext.messages,
447:     // Generate new agentId for subagents (each subagent should have its own ID)
448:     agentId: overrides?.agentId ?? createAgentId(),
449:     agentType: overrides?.agentType,
450: 
451:     // Create new query tracking chain for subagent with incremented depth
452:     queryTracking: {
453:       chainId: randomUUID(),
454:       depth: (parentContext.queryTracking?.depth ?? -1) + 1,
455:     },
456:     fileReadingLimits: parentContext.fileReadingLimits,
457:     userModified: parentContext.userModified,
458:     criticalSystemReminder_EXPERIMENTAL:
459:       overrides?.criticalSystemReminder_EXPERIMENTAL,
460:     requireCanUseTool: overrides?.requireCanUseTool,
461:   }
462: }
```

## Agent definitions: built-ins/plugins/custom agents

- File: `src/tools/AgentTool/loadAgentsDir.ts`
- Range: `360-386`

```ts
360:         ...builtInAgents,
361:         ...pluginAgents,
362:         ...customAgents,
363:       ]
364: 
365:       const activeAgents = getActiveAgentsFromList(allAgentsList)
366: 
367:       // Initialize colors for all active agents
368:       for (const agent of activeAgents) {
369:         if (agent.color) {
370:           setAgentColor(agent.agentType, agent.color)
371:         }
372:       }
373: 
374:       return {
375:         activeAgents,
376:         allAgents: allAgentsList,
377:         failedFiles: failedFiles.length > 0 ? failedFiles : undefined,
378:       }
379:     } catch (error) {
380:       const errorMessage =
381:         error instanceof Error ? error.message : String(error)
382:       logForDebugging(`Error loading agent definitions: ${errorMessage}`)
383:       logError(error)
384:       // Even on error, return the built-in agents
385:       const builtInAgents = getBuiltInAgents()
386:       return {
```

## Markdown agent discovery dirs

- File: `src/utils/markdownConfigLoader.ts`
- Range: `300-430`

```ts
300:     cwd: string,
301:   ): Promise<MarkdownFile[]> {
302:     const searchStartTime = Date.now()
303:     const userDir = join(getClaudeConfigHomeDir(), subdir)
304:     const managedDir = join(getManagedFilePath(), '.claude', subdir)
305:     const projectDirs = getProjectDirsUpToHome(subdir, cwd)
306: 
307:     // For git worktrees where the worktree does NOT have .claude/<subdir> checked
308:     // out (e.g. sparse-checkout), fall back to the main repository's copy.
309:     // getProjectDirsUpToHome stops at the worktree root (where the .git file is),
310:     // so it never sees the main repo on its own.
311:     //
312:     // Only add the main repo's copy when the worktree root's .claude/<subdir>
313:     // is absent. A standard `git worktree add` checks out the full tree, so the
314:     // worktree already has identical .claude/<subdir> content — loading the main
315:     // repo's copy too would duplicate every command/agent/skill
316:     // (anthropics/claude-code#29599, #28182, #26992).
317:     //
318:     // projectDirs already reflects existence (getProjectDirsUpToHome checked
319:     // each dir), so we compare against that instead of stat'ing again.
320:     const gitRoot = findGitRoot(cwd)
321:     const canonicalRoot = findCanonicalGitRoot(cwd)
322:     if (gitRoot && canonicalRoot && canonicalRoot !== gitRoot) {
323:       const worktreeSubdir = normalizePathForComparison(
324:         join(gitRoot, '.claude', subdir),
325:       )
326:       const worktreeHasSubdir = projectDirs.some(
327:         dir => normalizePathForComparison(dir) === worktreeSubdir,
328:       )
329:       if (!worktreeHasSubdir) {
330:         const mainClaudeSubdir = join(canonicalRoot, '.claude', subdir)
331:         if (!projectDirs.includes(mainClaudeSubdir)) {
332:           projectDirs.push(mainClaudeSubdir)
333:         }
334:       }
335:     }
336: 
337:     const [managedFiles, userFiles, projectFilesNested] = await Promise.all([
338:       // Always load managed (policy settings)
339:       loadMarkdownFiles(managedDir).then(_ =>
340:         _.map(file => ({
341:           ...file,
342:           baseDir: managedDir,
343:           source: 'policySettings' as const,
344:         })),
345:       ),
346:       // Conditionally load user files
347:       isSettingSourceEnabled('userSettings') &&
348:       !(subdir === 'agents' && isRestrictedToPluginOnly('agents'))
349:         ? loadMarkdownFiles(userDir).then(_ =>
350:             _.map(file => ({
351:               ...file,
352:               baseDir: userDir,
353:               source: 'userSettings' as const,
354:             })),
355:           )
356:         : Promise.resolve([]),
357:       // Conditionally load project files from all directories up to home
358:       isSettingSourceEnabled('projectSettings') &&
359:       !(subdir === 'agents' && isRestrictedToPluginOnly('agents'))
360:         ? Promise.all(
361:             projectDirs.map(projectDir =>
362:               loadMarkdownFiles(projectDir).then(_ =>
363:                 _.map(file => ({
364:                   ...file,
365:                   baseDir: projectDir,
366:                   source: 'projectSettings' as const,
367:                 })),
368:               ),
369:             ),
370:           )
371:         : Promise.resolve([]),
372:     ])
373: 
374:     // Flatten nested project files array
375:     const projectFiles = projectFilesNested.flat()
376: 
377:     // Combine all files with priority: managed > user > project
378:     const allFiles = [...managedFiles, ...userFiles, ...projectFiles]
379: 
380:     // Deduplicate files that resolve to the same physical file (same inode).
381:     // This prevents the same file from appearing multiple times when ~/.claude is
382:     // symlinked to a directory within the project hierarchy, causing the same
383:     // physical file to be discovered through different paths.
384:     const fileIdentities = await Promise.all(
385:       allFiles.map(file => getFileIdentity(file.filePath)),
386:     )
387: 
388:     const seenFileIds = new Map<string, SettingSource>()
389:     const deduplicatedFiles: MarkdownFile[] = []
390: 
391:     for (const [i, file] of allFiles.entries()) {
392:       const fileId = fileIdentities[i] ?? null
393:       if (fileId === null) {
394:         // If we can't identify the file, include it (fail open)
395:         deduplicatedFiles.push(file)
396:         continue
397:       }
398:       const existingSource = seenFileIds.get(fileId)
399:       if (existingSource !== undefined) {
400:         logForDebugging(
401:           `Skipping duplicate file '${file.filePath}' from ${file.source} (same inode already loaded from ${existingSource})`,
402:         )
403:         continue
404:       }
405:       seenFileIds.set(fileId, file.source)
406:       deduplicatedFiles.push(file)
407:     }
408: 
409:     const duplicatesRemoved = allFiles.length - deduplicatedFiles.length
410:     if (duplicatesRemoved > 0) {
411:       logForDebugging(
412:         `Deduplicated ${duplicatesRemoved} files in ${subdir} (same inode via symlinks or hard links)`,
413:       )
414:     }
415: 
416:     logEvent(`tengu_dir_search`, {
417:       durationMs: Date.now() - searchStartTime,
418:       managedFilesFound: managedFiles.length,
419:       userFilesFound: userFiles.length,
420:       projectFilesFound: projectFiles.length,
421:       projectDirsSearched: projectDirs.length,
422:       subdir:
423:         subdir as AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS,
424:     })
425: 
426:     return deduplicatedFiles
427:   },
428:   // Custom resolver creates cache key from both subdir and cwd parameters
429:   (subdir: ClaudeConfigDirectory, cwd: string) => `${subdir}:${cwd}`,
430: )
```
