import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any


class MinerUClient:
    """Thin wrapper for future MinerU API/CLI integration."""

    def __init__(self, endpoint: str | None = None, cli: str = "mineru") -> None:
        self.endpoint = endpoint
        self.cli = self._resolve_cli(cli)

    def _resolve_cli(self, cli: str) -> str:
        if Path(cli).exists():
            return cli
        found = shutil.which(cli)
        if found:
            return found
        local_venv = Path.cwd() / ".venv" / "bin" / cli
        if local_venv.exists():
            return str(local_venv)
        prefix_venv = Path(sys.prefix) / "bin" / cli
        if prefix_venv.exists():
            return str(prefix_venv)
        return cli

    async def parse(self, input_path: Path, output_dir: Path, options: dict[str, Any] | None = None) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        if not input_path.exists():
            return {
                "status": "missing_input",
                "message": "Input file does not exist, so MinerU was not invoked.",
                "input_path": str(input_path),
                "output_dir": str(output_dir),
                "options": options or {},
            }

        command = [self.cli, "-p", str(input_path), "-o", str(output_dir)]
        if options:
            command.extend(self._build_cli_options(options))
        if self.endpoint:
            command.extend(["--api-url", self.endpoint])

        return await self._run_cli(command, input_path, output_dir, options or {})

    def _build_cli_options(self, options: dict[str, Any]) -> list[str]:
        cli_options: list[str] = []
        option_map = {
            "method": "-m",
            "backend": "-b",
            "lang": "-l",
            "server_url": "-u",
        }
        for key, flag in option_map.items():
            value = options.get(key)
            if value is not None:
                cli_options.extend([flag, str(value)])

        if options.get("start_page") is not None:
            cli_options.extend(["-s", str(options["start_page"])])
        if options.get("end_page") is not None:
            cli_options.extend(["-e", str(options["end_page"])])

        for key, flag in [("formula", "-f"), ("table", "-t")]:
            if key in options:
                cli_options.extend([flag, str(bool(options[key]))])
        if "image_analysis" in options:
            cli_options.extend(["--image-analysis", str(bool(options["image_analysis"]))])

        return cli_options

    async def _run_cli(
        self,
        command: list[str],
        input_path: Path,
        output_dir: Path,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        env = self._build_env(options)
        process = await asyncio.create_subprocess_exec(
            *command,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return {
            "status": "succeeded" if process.returncode == 0 else "failed",
            "returncode": process.returncode,
            "command": command,
            "input_path": str(input_path),
            "output_dir": str(output_dir),
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "options": options,
        }

    def _build_env(self, options: dict[str, Any]) -> dict[str, str]:
        env = os.environ.copy()
        if env.get("MINERU_MODEL_SOURCE"):
            return env

        backend = str(options.get("backend") or "").lower()
        remote_backend = backend in {"vlm-http-client", "hybrid-http-client"} or options.get("server_url")
        if remote_backend or self.endpoint:
            return env

        config_path = Path.home() / "mineru.json"
        if not config_path.exists():
            return env

        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return env

        pipeline_dir = (
            config.get("models-dir", {})
            .get("pipeline")
        )
        if pipeline_dir and Path(str(pipeline_dir)).exists():
            env["MINERU_MODEL_SOURCE"] = "local"

        return env
