from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List
from types import SimpleNamespace


IMAGE_NAME = "kasuga-gym:latest"


def _run_and_capture(cmd: list[str], cwd: Path) -> SimpleNamespace:
    """Run a command and capture stdout/stderr merged."""
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    lines: List[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line.rstrip("\n"))
    proc.wait()

    lines.append(f"\n[exit code] {proc.returncode}")
    log = "\n".join(lines)
    return SimpleNamespace(ok=(proc.returncode == 0), returncode=proc.returncode, lines=lines, log=log)


def run_allocator(base_dir: Path, config_path: Path, ym: str, use_docker: bool = True):
    """Run allocator.

    Default is to run via Docker (to avoid local NumPy/Windows encoding issues).

    Returns an object with:
      - ok: bool (return code == 0)
      - returncode: int
      - lines: List[str]
      - log: str (joined)
    """

    if use_docker:
        # 0) Docker ready?
        info = _run_and_capture(["docker", "info"], cwd=base_dir)
        if not info.ok:
            return SimpleNamespace(
                ok=False,
                returncode=info.returncode,
                lines=info.lines,
                log="Docker が起動していません（Docker Desktop を起動してください）\n\n" + info.log,
            )

        # 1) build image (cached if unchanged)
        build = _run_and_capture(["docker", "build", "-t", IMAGE_NAME, "."], cwd=base_dir)
        if not build.ok:
            return build

        # 2) run in container
        try:
            rel_cfg = config_path.resolve().relative_to(base_dir.resolve()).as_posix()
        except Exception:
            rel_cfg = config_path.name

        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{str(base_dir)}:/app",
            IMAGE_NAME,
            "python",
            "/app/tools/run_in_docker.py",
            f"/app/{rel_cfg}",
            "/app/data",
            "/app",
        ]
        r = _run_and_capture(cmd, cwd=base_dir)

        merged_lines = ["[docker build]", *build.lines, "", "[docker run]", *r.lines]
        merged_log = "\n".join(merged_lines)
        return SimpleNamespace(ok=r.ok, returncode=r.returncode, lines=merged_lines, log=merged_log)

    # --- Local run (fallback) ---
    main_py = base_dir / "sourcecode" / "main.py"
    cmd = [
        "python",
        str(main_py),
        "--config",
        str(config_path),
        "--data-tag",
        ym,
        "--out",
        "output",
    ]
    return _run_and_capture(cmd, cwd=base_dir)
