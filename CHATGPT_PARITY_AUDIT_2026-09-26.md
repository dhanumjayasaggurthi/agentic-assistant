# ChatGPT-parity engineering audit — 2026-09-26

Scope: direct code review of `feature_review`. This assessment intentionally does not use the repository's narrative/report documents as evidence.

## Executive diagnosis

The application already has strong raw ingredients: multiple premium model gateways, a WebSocket UI, persistent conversations, an agent loop, workspace tools, image generation, and artifact creation. The main problem was not model quality. The problem was **capability orchestration**.

The UI exposed premium models as if they were interchangeable, while the backend had materially different integration paths for chat, reasoning, Codex, images, Bedrock, and Vertex. Several user-visible features were also only approximations of the requested action. This produced the impression that a premium model was "weak" when, in reality, the request was being routed through a constrained path or the required source artifact/tool was never supplied to the model.

## Root causes found in code

### 1. Premium model selection did not imply premium agent execution

- Codex was explicitly replaced by `gpt-4o-global` inside the coding agent when Agent mode was used.
- o-series integration did not attach function tools.
- Vertex's current integration performed plain generation rather than tool-calling orchestration.
- Capability rules were duplicated between frontend and backend and did not describe the actual runtime integration.

Effect: users could select a premium specialist model and reasonably expect it to drive files/tools, but a different model or non-tool path actually performed the work.

### 2. Image "edit" and "vary" were not image editing

The frontend's edit action sent a text message such as `Edit image X: ...` with an empty attachment list. The source image itself was not sent to an image-edit endpoint.

The "vary x4" action sent a text generation request, while the backend only generated one image.

Effect: the model could not preserve the source image because it never received the source image as an edit input.

### 3. Tool/action requests depended on a manual Agent-mode switch

Normal Chat mode never escalated an explicit implementation or workspace request to the agent. This differs from ChatGPT-style interaction, where the user primarily states intent and the runtime chooses tools when necessary.

Effect: users could ask Chat to create/edit/run something and receive prose instead of an executed action.

### 4. Context growth degraded long conversations

Historical attachments were repeatedly re-injected into prompts. Images could be resent as large base64 payloads and documents could be reintroduced repeatedly. The coding agent also fed potentially large tool output back into subsequent model calls.

Effect: prompt size grew rapidly, signal-to-noise degraded, latency increased, and model behavior became less consistent.

### 5. Coding edits were coarse-grained

The workspace exposed whole-file write/overwrite but no precise patch primitive.

Effect: the agent was encouraged to rewrite large files for small changes, increasing regression risk and token use.

### 6. Attached images were saved but the coding agent could not truly inspect them

Agent mode converted an attached image into a workspace path and textual marker, but there was no vision tool for the agent to inspect that file.

Effect: image-oriented coding/design tasks could silently become text-only reasoning tasks.

### 7. Codex existed but was not used as a code specialist inside the agent

There was a valid Codex Responses API path, but the tool loop did not delegate hard coding work to it. Instead, Codex selection caused a fallback.

Effect: the system owned a premium specialist but did not compose it with the tool-capable orchestration layer.

### 8. Stop control did not stop server-side work

The UI stop button only displayed a message saying the run would continue.

Effect: perceived loss of control and wasted model/tool execution.

### 9. Reconnect ordering contradicted the intended protocol

The WebSocket client sent `resume` and then immediately flushed queued user actions instead of waiting for `resume_ok`.

Effect: new activity could interleave with replayed events after a disconnect.

### 10. Image provider URLs were not normalized for the existing UI

The frontend image handler rendered base64 payloads. Provider code could return a URL instead.

Effect: a successful image provider response could exist but not be rendered/persisted consistently.

## Architecture implemented on the parity branch

### Capability-aware model routing

A central `backend/model_capabilities.py` now distinguishes:
- tool-capable orchestrators
- vision-capable models
- image-generation models
- image-edit models
- reasoning specialists
- Codex/code specialists

Agent mode preserves the selected model when the current integration supports tools. Specialist/non-tool integration paths are paired with a tool-capable premium orchestrator instead of pretending every model has identical capabilities.

### Orchestrator + specialist pattern

The agent now has a `delegate_code` tool. A tool-capable model owns planning, permissions, file state, and execution; GPT-5.3 Codex can be called as a specialist for difficult code generation/debugging.

This is intentionally different from "pick one model and hope it does everything."

### Real image editing

A dedicated `edit_image` WebSocket path now passes the actual image bytes into the Azure image edit provider. Variations are generated from the original image, with support for up to four outputs.

Generated/edited outputs are persisted into the conversation workspace and artifact registry.

### Automatic tool escalation

Chat requests with explicit action intent (edit, implement, run tests, create an artifact, inspect attachments, current web research, etc.) can automatically promote into an agent run. Normal informational chat remains lightweight.

### Better context engineering

- chat history budget reduced
- prior images are referenced instead of repeatedly resending base64
- prior document attachment text is capped
- coding-agent conversation context is bounded
- tool result feedback to the model is bounded
- file reads can request specific line ranges

### Precise code editing and validation primitives

New agent tools:
- `patch_file` — exact targeted replacement
- `inspect_image` — vision analysis of workspace images
- `delegate_code` — Codex specialist consultation

The system prompt now instructs the agent to inspect first, patch narrowly, validate changes, and treat tool failures as failures rather than success.

### True cancellation

Running streams now retain their task handle and the client can send a real `stop` event. Agent cancellation is persisted as `cancelled` in the run record.

### Reconnect ordering fix

Queued user actions are flushed only after `resume_ok`, preserving replay order.

## Deliberate non-goals / remaining gaps

These changes materially improve capability orchestration, but they do **not** make this application identical to ChatGPT.

1. **Execution isolation remains process-level, not a hardened container sandbox.**
   `run_bash` and `run_python` use subprocesses with the workspace as the working directory, but a working directory is not a security boundary. Production code execution should move to an ephemeral container/microVM service with filesystem, network, CPU, memory, and syscall controls.

2. **The agent's tool-calling model turns are non-streaming.**
   User-facing tool activity is streamed, but each model planning turn waits for a complete tool-call response. True streaming tool calls would further improve perceived latency.

3. **Uploads are still content-heavy.**
   The browser receives extracted attachment content/base64 and sends it through the WebSocket. The next architecture step is attachment IDs/object references plus server-side selective retrieval instead of moving large content through the client.

4. **Model catalog is still static.**
   The UI lists known marketplace models rather than discovering runtime model/deployment capabilities from the gateway. A production control plane should expose a live capability registry.

5. **Provider-specific tool support must be integration-tested.**
   The code contains a GPT-5 chat-completions tool path, but actual behavior depends on the J&J gateway/deployment configuration. The branch makes capability decisions explicit so failed qualification can be corrected in one place.

6. **Web research is basic.**
   Current agent web search is DuckDuckGo HTML + page crawl, not a high-recall search/retrieval service with source ranking and citations.

## Recommended next production phase

1. Add live provider/deployment capability probes and hide/label unavailable features.
2. Move code execution to isolated ephemeral runners.
3. Replace attachment payloads with server-side file handles + selective extraction/retrieval.
4. Add model/tool evals:
   - coding task success
   - edit fidelity
   - tool selection accuracy
   - multi-turn context retention
   - hallucinated tool completion
   - cancellation/reconnect correctness
5. Add tracing for model route, fallback/specialist delegation, token usage, tool latency, failures, and retries.
6. Add a small golden-suite regression test for common user journeys:
   - "fix this code and run tests"
   - "edit this image"
   - "create four variations"
   - "build a PPT from these images"
   - "analyze attached code/archive"
   - disconnect/reconnect during an agent run

## Product principle

Do not optimize for the number of premium models exposed in a dropdown. Optimize for **the right model + the right tools + the right context + reliable execution + verification**. That is the difference between a model marketplace UI and a dependable AI workbench.
