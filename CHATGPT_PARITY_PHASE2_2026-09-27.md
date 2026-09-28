# ChatGPT parity phase 2 — 2026-09-27

This phase continues the code-first parity work from `feature/chatgpt-parity-2026-09-26`.

## Implemented

### 1. Execution isolation boundary

Agent `run_bash` and `run_python` now route through `backend/execution.py`.

Development remains compatible with:

```
RDI_EXECUTION_MODE=local
```

Production should use:

```
RDI_EXECUTION_MODE=docker
RDI_EXECUTION_IMAGE=python:3.12-slim
RDI_EXECUTION_NETWORK=false
RDI_EXECUTION_MEMORY_MB=1024
RDI_EXECUTION_CPUS=1.0
RDI_EXECUTION_PIDS=128
RDI_EXECUTION_TIMEOUT=60
```

Docker execution uses an ephemeral container with:
- conversation workspace mounted at `/workspace`
- network disabled by default
- memory/CPU/PID constraints
- all Linux capabilities dropped
- `no-new-privileges`
- automatic container removal

Local mode is retained only for developer compatibility and is surfaced as non-isolated in provider/runtime status.

### 2. Attachment handles instead of browser round-tripping file contents

Uploads now:
1. persist original bytes server-side under the authenticated user's workspace
2. extract bounded text once where applicable
3. create an owner-bound attachment record
4. return a lightweight attachment ID + metadata to the browser

The browser no longer receives PDF/DOCX/ZIP extracted text or uploaded image base64 solely to send it back through WebSocket chat payloads.

At model time the server:
- validates attachment ownership
- hydrates extracted text only when needed
- loads image bytes only when needed
- binds pre-conversation uploads to the newly created conversation
- materializes original attached files into `workspace/uploads/` for agent editing

Legacy inline attachments remain readable for backward compatibility.

### 3. Runtime model capability registry

`GET /models/catalog` exposes the backend-owned model registry with:
- provider
- tier/group/display name
- tool capability
- vision capability
- reasoning/specialist role
- image generation/edit capability
- current provider availability

The frontend consumes this registry and marks models whose provider is not configured as offline instead of presenting every marketplace label as equally executable.

### 4. Streaming Azure agent turns

Azure tool-capable agent planning/final turns now use streaming chat completions while function-call deltas are accumulated server-side.

This improves perceived latency while preserving the existing agent loop and permission model.

### 5. Structured privacy-safe telemetry

The backend emits JSON telemetry for:
- selected vs orchestrator model route
- specialist delegation state
- agent tool completion/success/duration
- run completion/latency/step count/output size

Prompts, responses, file contents, attachment text and credentials are deliberately excluded.

### 6. Regression coverage

Phase-two tests cover:
- runtime provider/model availability
- specialist/tool capability semantics
- lightweight attachment handle preservation
- Docker runner constraints

CI also asserts the architecture wiring directly.

## Remaining production work

1. Replace Docker CLI execution with a dedicated remote runner service or Kubernetes Job/microVM execution plane if multi-tenant untrusted code execution is required.
2. Add object storage for large uploads/artifacts rather than node-local workspace storage.
3. Add retention, malware scanning, content-type verification and enterprise DLP hooks for uploads.
4. Add provider-side live deployment probing where the enterprise gateway exposes a supported discovery API.
5. Export structured telemetry to the organization's OTEL collector and define SLO dashboards.
6. Add full browser E2E tests for upload → agent edit → validation → artifact download and disconnect/resume.
7. Add representative model/tool eval datasets and promotion thresholds before declaring parity.

## Design principle

The runtime now treats the product as an AI workbench rather than a model dropdown:

```
intent
  -> capability routing
  -> orchestrator
  -> specialists/tools
  -> bounded context
  -> isolated execution
  -> verification
  -> artifact
  -> telemetry
```

The next quality gains should come from eval-driven reliability and production hardening, not from exposing more model names.
