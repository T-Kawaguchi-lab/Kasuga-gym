from __future__ import annotations

import os
import sys
import shutil
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


def run_allocator(base_dir: Path, config_path: Path, ym: str, use_docker: bool = True) -> SimpleNamespace:
    """
    Run allocator.

    - ローカルPC(Windows等): use_docker=True なら Docker で環境固定して実行
    - Hugging Face Spaces: dockerコマンドが無い/動かないので自動的に local 実行にフォールバック

    Returns an object with:
      - ok: bool (return code == 0)
      - returncode: int
      - lines: List[str]
      - log: str (joined)
    """

    # ----------------------------
    # 0) Spaces判定 / docker存在判定
    # ----------------------------
    in_spaces = bool(os.getenv("SPACE_ID") or os.getenv("HF_SPACE_ID") or os.getenv("SYSTEM") == "spaces")
    docker_path = shutil.which("docker")
    docker_exists = docker_path is not None

    # Spaces では必ずDocker-in-Dockerをしない
    if in_spaces:
        use_docker = False

    # dockerコマンドが無いなら local 実行
    if use_docker and (not docker_exists):
        use_docker = False

    # ----------------------------
    # 1) Docker実行（可能なら）
    # ----------------------------
    if use_docker:
        # 0) Docker ready?
        info = _run_and_capture(["docker", "info"], cwd=base_dir)
        if not info.ok:
            # dockerコマンドはあるが、起動してない/権限不足等 → localへフォールバック
            use_docker = False
        else:
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

            merged_lines = ["[docker info]", *info.lines, "", "[docker build]", *build.lines, "", "[docker run]", *r.lines]
            merged_log = "\n".join(merged_lines)
            return SimpleNamespace(ok=r.ok, returncode=r.returncode, lines=merged_lines, log=merged_log)

    # ----------------------------
    # 2) Local実行（Spaces含む）
    # ----------------------------
    main_py = base_dir / "sourcecode" / "main.py"

    # python は "python" 固定だと環境差が出るので、同一環境の python を使う
    cmd = [
        sys.executable,
        str(main_py),
        "--config",
        str(config_path),
        "--data-tag",
        ym,
        "--out",
        "output",
    ]
    return _run_and_capture(cmd, cwd=base_dir)
