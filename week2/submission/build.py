#!/usr/bin/env python3
"""Render a submission HTML page to a one-page PDF with headless Chrome.

    python3 build.py --html w2-ex1.html --name "Full Name" \
        --img correct=shot-correct.png --img refusal=shot-refusal.png

Each --img KEY=PATH replaces the placeholder __SHOT_KEY__ in the HTML with the
image, inlined as a data URI. __FULL_NAME__ and __REPO_URL__ are replaced from
--name and --repo.

Chrome lives on the Windows side of WSL and cannot read \\wsl$ paths reliably,
so everything is staged into a Windows temp folder first and the finished PDF
is copied back.
"""

import argparse
import base64
import mimetypes
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHROME = Path("/mnt/c/Program Files/Google/Chrome/Application/chrome.exe")
STAGE = Path("/mnt/c/Users/Public/w2build")
STAGE_WIN = r"C:\Users\Public\w2build"

MISSING = (
    '<div class="missing">screenshot missing<br>'
    "<small>pass --img {key}=path/to/shot.png</small></div>"
)


def embed(path: str) -> str:
    """Inline the image as a data URI so the staged HTML has no dependencies."""
    source = Path(path).expanduser()
    if not source.is_absolute():
        source = HERE / source
    if not source.is_file():
        sys.exit(f"No such screenshot: {source}")
    mime = mimetypes.guess_type(source.name)[0] or "image/png"
    data = base64.b64encode(source.read_bytes()).decode()
    return f'<img src="data:{mime};base64,{data}" alt="">'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", default="w2-ex1.html")
    parser.add_argument("--name", default="__FULL_NAME__")
    parser.add_argument("--repo", default="https://github.com/MartiTarres14/curs-llm")
    parser.add_argument(
        "--img",
        action="append",
        default=[],
        metavar="KEY=PATH",
        help="replace __SHOT_KEY__ with this image; repeatable",
    )
    parser.add_argument("--out", help="defaults to the HTML name with .pdf")
    args = parser.parse_args()

    if not CHROME.is_file():
        sys.exit(f"Chrome not found at {CHROME}")

    page = HERE / args.html
    if not page.is_file():
        sys.exit(f"No such page: {page}")

    html = page.read_text(encoding="utf-8")

    # Inline any local stylesheet: only page.html is staged for Chrome, so a
    # <link> would silently resolve to nothing and the page would print unstyled.
    def inline_css(match: re.Match) -> str:
        sheet = HERE / match.group(1)
        if not sheet.is_file():
            sys.exit(f"No such stylesheet: {sheet}")
        return f"<style>\n{sheet.read_text(encoding='utf-8')}\n</style>"

    html = re.sub(
        r'<link[^>]+href="([^"]+\.css)"[^>]*>', inline_css, html
    )

    html = html.replace("__FULL_NAME__", args.name)
    html = html.replace("__REPO_URL__", args.repo)

    for pair in args.img:
        if "=" not in pair:
            sys.exit(f"--img needs KEY=PATH, got {pair!r}")
        key, _, path = pair.partition("=")
        html = html.replace(f"__SHOT_{key.strip().upper()}__", embed(path))

    # Anything still unfilled becomes a visible placeholder rather than raw text.
    html = re.sub(
        r"__SHOT_([A-Z0-9_]+)__",
        lambda m: MISSING.format(key=m.group(1).lower()),
        html,
    )

    shutil.rmtree(STAGE, ignore_errors=True)
    STAGE.mkdir(parents=True)
    (STAGE / "page.html").write_text(html, encoding="utf-8")

    result = subprocess.run(
        [
            str(CHROME),
            "--headless",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={STAGE_WIN}\\out.pdf",
            f"{STAGE_WIN}\\page.html",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    produced = STAGE / "out.pdf"
    if not produced.is_file():
        sys.exit(f"Chrome produced no PDF.\n{result.stdout}\n{result.stderr}")

    out = Path(args.out).expanduser() if args.out else page.with_suffix(".pdf")
    shutil.copyfile(produced, out)
    print(f"{out}  ({produced.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
