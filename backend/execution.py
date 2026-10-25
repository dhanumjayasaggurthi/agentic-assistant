"""Execution runtime abstraction for agent-authored code.

Development can use local subprocesses. Production should set
RDI_EXECUTION_MODE=docker so every command runs in an ephemeral, constrained
container with the conversation workspace mounted at /workspace.
"""
import asyncio
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List

from .config import get_config


@dataclass
class ExecutionResult:
    command: List[str]
    exit_code: int
    stdout: str
    stderr: str
    mode: str

    @property
    def combined(self) -> str:
        text = (self.stdout or "") + (self.stderr or "")
        return text


def docker_command(workspace: Path, shell_command: str) -> List[str]:
    cfg = get_config().execution
    cmd = [
        "docker", "run", "--rm",
        "--workdir", "/workspace",
        "--mount", f"type=bind,src={workspace.resolve()},dst=/workspace",
        "--memory", f"{max(128, cfg.memory_mb)}m",
        "--cpus", str(max(0.1, cfg.cpus)),
        "--pids-limit", str(max(32, cfg.pids_limit)),
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
    ]
    if not cfg.network_enabled:
        cmd += ["--network", "none"]
    cmd += [cfg.docker_image, "sh", "-lc", shell_command]
    return cmd


async def run_shell(workspace: Path, command: str, timeout: int = None) -> ExecutionResult:
    cfg = get_config().execution
    effective_timeout = min(
        int(timeout or cfg.timeout_seconds),
        max(1, int(cfg.timeout_seconds)),
    )

    if cfg.mode == "docker":
        argv = docker_command(workspace, command)
        cwd = None
    else:
        # Development compatibility only. A cwd is not a security boundary.
        argv = ["sh", "-lc", command]
        cwd = str(workspace)

    loop = asyncio.get_running_loop()

    def _run():
        cp = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
        return ExecutionResult(
            command=argv,
            exit_code=cp.returncode,
            stdout=cp.stdout,
            stderr=cp.stderr,
            mode=cfg.mode,
        )

    try:
        return await loop.run_in_executor(None, _run)
    except subprocess.TimeoutExpired as exc:
        return ExecutionResult(
            command=argv,
            exit_code=124,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=f"Execution timed out after {effective_timeout}s",
            mode=cfg.mode,
        )


async def run_python(workspace: Path, code: str, timeout: int = None) -> ExecutionResult:
    quoted = shlex.quote(code)
    return await run_shell(workspace, f"python -c {quoted}", timeout=timeout)


def execution_status() -> dict:
    cfg = get_config().execution
    return {
        "mode": cfg.mode,
        "isolated": cfg.mode == "docker",
        "docker_image": cfg.docker_image if cfg.mode == "docker" else None,
        "network_enabled": cfg.network_enabled if cfg.mode == "docker" else None,
        "memory_mb": cfg.memory_mb,
        "cpus": cfg.cpus,
        "pids_limit": cfg.pids_limit,
        "timeout_seconds": cfg.timeout_seconds,
        "warning": None if cfg.mode == "docker" else (
            "local execution is for development only; set RDI_EXECUTION_MODE=docker "
            "for a constrained production runner"
        ),
    }
