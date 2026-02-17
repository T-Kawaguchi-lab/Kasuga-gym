from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys


def read_year_month(cfg_path: Path) -> tuple[int, int]:
    """
    config yaml から year/month を抜く。
    行内コメント（例: year: 2026 #対象年）もOK。
    """
    raw = cfg_path.read_text(encoding="utf-8-sig", errors="ignore").lstrip("\ufeff")

    y = re.search(r"(?im)^\s*year\s*:\s*(\d{4})\s*(?:#.*)?$", raw)
    m = re.search(r"(?im)^\s*month\s*:\s*([0-9]{1,2})\s*(?:#.*)?$", raw)

    if not y or not m:
        raise ValueError(f"year/month not found in config: {cfg_path}")

    year = int(y.group(1))
    month = int(m.group(1))
    if not (1 <= month <= 12):
        raise ValueError(f"invalid month: {month}")

    return year, month


def copy_if_needed(src: Path, dst: Path) -> None:
    """
    src -> dst にコピー。
    同一ファイルならスキップ（同じ場所を渡されても安全）。
    """
    if not src.exists():
        raise FileNotFoundError(f"missing: {src}")

    dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        # src と dst が同じファイルなら何もしない
        if dst.exists() and src.resolve() == dst.resolve():
            return
    except Exception:
        # resolve できない環境でも copy2 は安全に動くので無視
        pass

    shutil.copy2(src, dst)


def main() -> None:
    """
    Usage:
      python tools/run_in_docker.py <config_yaml> <json_src_dir> <repo_root>

    Example (old style):
      python /app/tools/run_in_docker.py /app/setting/config.yaml /drive/json /app

    Example (new style: host already copied into /app/data):
      python /app/tools/run_in_docker.py /app/setting/config.yaml /app/data /app
    """
    if len(sys.argv) < 4:
        print("Usage: python tools/run_in_docker.py <config_yaml> <json_src_dir> <repo_root>")
        sys.exit(1)

    cfg = Path(sys.argv[1])
    json_src_dir = Path(sys.argv[2])  # /drive/json or /app/data など
    repo_root = Path(sys.argv[3])     # /app

    year, month = read_year_month(cfg)
    ym = f"{year:04d}-{month:02d}"

    # 保存先: repo_root/data/YYYY-MM
    dest_dir = repo_root / "data" / ym
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 取り込み元:
    #   json_src_dir/preferences.json など
    # もしくは json_src_dir/YYYY-MM/preferences.json の可能性もあるので両方見る
    candidates = [
        json_src_dir,
        json_src_dir / ym,
    ]

    def find_src(filename: str) -> Path:
        for base in candidates:
            p = base / filename
            if p.exists():
                return p
        # どこにも無い場合は、最初の候補のパスでエラー表示
        return candidates[0] / filename

    for name in ["preferences.json", "events.json"]:
        src = find_src(name)
        dst = dest_dir / name
        copy_if_needed(src, dst)

    print(f"[OK] json ready: {dest_dir}")

    # main.py を実行（data-tag を明示して YYYY-MM を確実に使う）
    cmd = [
        "python", "sourcecode/main.py",
        "--config", str(cfg),
        "--data-tag", ym,
    ]
    r = subprocess.run(cmd, cwd=str(repo_root))
    if r.returncode != 0:
        raise SystemExit(r.returncode)

    print("[OK] finished main.py")


if __name__ == "__main__":
    main()
