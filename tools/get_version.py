"""Affiche la version déclarée dans foulee/__init__.py (utilisé par build.bat et la CI)."""
import re
from pathlib import Path

src = (Path(__file__).resolve().parent.parent / "foulee" / "__init__.py").read_text(encoding="utf-8")
print(re.search(r'__version__\s*=\s*"([^"]+)"', src).group(1))
