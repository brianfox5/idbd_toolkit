"""Write an anonymized copy of this repository for double-blind review.

Copies every file git would publish (tracked, or untracked but not ignored) into
an output folder, replacing the author's identifying details. The original
repository is not modified.

    python scripts/anonymize.py ../idbd-toolkit-anonymous
    python scripts/anonymize.py OUT --also "Example University" --also "jdoe"

Identity comes from ``pyproject.toml`` (author name and email) plus any ``--also``
terms. Afterwards the script lists remaining mentions of the author's surname —
typically third-person citations of their prior work, which blind-review rules
usually allow — so you can decide on each one.

Then publish the copy anonymously, e.g. via https://anonymous.4open.science
(which mirrors a GitHub repository with identifying details removed) or a neutral
account.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANON_NAME = "Anonymous Author"
ANON_EMAIL = "anonymous@example.org"
ANON_INSTITUTION = "Anonymous Institution"


def publishable_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return sorted(set(out.splitlines()))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out", type=Path, help="output folder (must not exist)")
    parser.add_argument("--also", action="append", default=[],
                        help="another identifying term to replace (repeatable)")
    args = parser.parse_args(argv)
    if args.out.exists():
        sys.exit(f"{args.out} already exists; choose a new folder")

    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    author = meta["project"]["authors"][0]
    name, email = author["name"], author.get("email", "")
    given, _, family = name.rpartition(" ")
    replacements: list[tuple[re.Pattern[str], str]] = [
        (re.compile(re.escape(email), re.I), ANON_EMAIL),
        (re.compile(re.escape(name)), ANON_NAME),
    ] + [(re.compile(re.escape(t), re.I), "anonymous") for t in args.also if t]
    if "@" in email:  # e.g. jdoe@example.edu -> also the user id "jdoe"
        replacements.append((re.compile(r"\b" + re.escape(email.split("@")[0]) + r"\b", re.I),
                             "anonymous"))

    # Structured fields, only in the files that hold them.
    per_file = {
        "CITATION.cff": [(re.compile(r"(family-names:\s*)" + re.escape(family)), r"\1Anonymous"),
                         (re.compile(r"(given-names:\s*)" + re.escape(given)), r"\1Author"),
                         (re.compile(r"(affiliation:\s*).+"), r"\1" + ANON_INSTITUTION)],
        "NOTICE": [(re.compile(r"(Copyright \d{4} ).+"), r"\1The Authors")],
    }
    this_script = Path(__file__).resolve().relative_to(ROOT).as_posix()

    changed, leftovers = [], []
    for rel in publishable_files():
        src, dst = ROOT / rel, args.out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = src.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copy2(src, dst)  # binary: copied as is
            continue
        new = text
        if rel != this_script:  # leave this tool's own source intact
            for pattern, repl in replacements + per_file.get(rel, []):
                new = pattern.sub(repl, new)
        dst.write_text(new, encoding="utf-8")
        shutil.copymode(src, dst)
        if new != text:
            changed.append(rel)
        for i, line in enumerate(new.splitlines(), 1):
            if re.search(r"\b" + re.escape(family) + r"\b", line):
                leftovers.append(f"  {rel}:{i}: {line.strip()[:110]}")

    print(f"wrote {len(publishable_files())} files to {args.out}")
    print(f"identifying details replaced in {len(changed)}: " + ", ".join(changed))
    if leftovers:
        print(f"\nremaining mentions of '{family}' (review each — third-person "
              f"citations are usually fine):")
        print("\n".join(leftovers[:60]))
        if len(leftovers) > 60:
            print(f"  … and {len(leftovers) - 60} more")


if __name__ == "__main__":
    main()
