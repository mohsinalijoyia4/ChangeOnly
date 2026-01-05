import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "changeonly.zip"

EXCLUDE_DIRS = {".venv", "__pycache__", ".git", ".mypy_cache", ".pytest_cache"}
EXCLUDE_FILES = {"changeonly.zip", ".env"}

def should_exclude(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDE_DIRS:
        return True
    if path.name in EXCLUDE_FILES:
        return True
    return False

def main():
    if OUT.exists():
        OUT.unlink()

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for p in ROOT.rglob("*"):
            if p.is_dir():
                continue
            rel = p.relative_to(ROOT)
            if should_exclude(rel):
                continue
            z.write(p, rel)

    print(f"Created: {OUT}")

if __name__ == "__main__":
    main()
