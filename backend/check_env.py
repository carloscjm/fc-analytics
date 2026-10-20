"""Confere o ambiente da máquina para o FC Analytics.

Uso: python check_env.py
Mostra versão do Python, GPU NVIDIA (via nvidia-smi), Node.js e Ollama.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys


def run(cmd: list[str]) -> str | None:
    exe = shutil.which(cmd[0])
    if exe is None:
        return None
    try:
        out = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (out.stdout or out.stderr).strip() or None


def main() -> int:
    ok = True
    print(f"Sistema: {platform.system()} {platform.release()}")

    py = sys.version_info
    py_ok = (3, 10) <= (py.major, py.minor) <= (3, 12)
    print(f"Python: {platform.python_version()} {'OK' if py_ok else '(recomendado 3.11 ou 3.12)'}")
    ok &= py_ok

    gpu = run(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"])
    print(f"GPU NVIDIA: {gpu or 'não encontrada (instale o driver NVIDIA mais recente)'}")
    ok &= gpu is not None

    try:
        import torch

        cuda = torch.cuda.is_available()
        detail = torch.cuda.get_device_name(0) if cuda else "sem CUDA (vai rodar na CPU)"
        print(f"PyTorch: {torch.__version__} | {detail}")
        ok &= cuda or gpu is None
    except ImportError:
        print("PyTorch: não instalado (rode o instalar.bat)")
        ok = False

    node = run(["node", "--version"])
    print(f"Node.js: {node or 'não encontrado'}")
    ok &= node is not None

    ollama = run(["ollama", "--version"])
    print(f"Ollama: {ollama or 'não encontrado'}")
    ok &= ollama is not None

    print("\nTudo pronto." if ok else "\nFalta algum item acima.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
