"""Single-file installer for ROMULUS (creates venv + installs CLI)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from shutil import which


def _venv_python(venv_path: Path) -> Path:
    if os.name == "nt":
        return venv_path / "Scripts" / "python.exe"
    return venv_path / "bin" / "python"


def _activation_hint(venv_path: Path) -> str:
    if os.name == "nt":
        return f"{venv_path}\\Scripts\\activate"
    return f"source {venv_path}/bin/activate"


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install ROMULUS in a local venv.")
    parser.add_argument("--venv", default=".venv", help="Path for virtualenv (default: .venv)")
    parser.add_argument("--ml", action="store_true", help="Install ML extras (xgboost)")
    parser.add_argument("--pipx", action="store_true", help="Install globally with pipx (no venv)")
    parser.add_argument("--upgrade-pip", action="store_true", help="Upgrade pip before install")
    args = parser.parse_args()

    if sys.version_info < (3, 11):
        print("Error: Python 3.11+ is required to install ROMULUS.")
        sys.exit(1)

    repo_root = Path(__file__).resolve().parent

    if args.pipx:
        if which("pipx") is None:
            print("Error: pipx is not installed. Install with: python -m pip install --user pipx")
            sys.exit(1)
        spec = ".[ml]" if args.ml else "."
        print("Installing ROMULUS with pipx ...")
        _run(["pipx", "install", spec])
        print("\nInstall complete.")
        print("Run:")
        print("  romulus --help")
        return

    venv_path = repo_root / args.venv
    venv_python = _venv_python(venv_path)

    if not venv_path.exists():
        print(f"Creating venv at {venv_path} ...")
        _run([sys.executable, "-m", "venv", str(venv_path)])

    if not venv_python.exists():
        print(f"Error: venv python not found at {venv_python}")
        sys.exit(1)

    if args.upgrade_pip:
        print("Upgrading pip ...")
        _run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])

    extras = "[ml]" if args.ml else ""
    print("Installing ROMULUS ...")
    _run([str(venv_python), "-m", "pip", "install", "-e", f".{extras}"])

    print("\nInstall complete.")
    print(f"Activate venv:\n  {_activation_hint(Path(args.venv))}")
    print("Next commands:")
    print("  romulus --help")
    print("  romulus init")


if __name__ == "__main__":
    main()
