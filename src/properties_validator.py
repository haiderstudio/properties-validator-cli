"""properties-validator-cli: check .properties files parse cleanly, fail CI on a bad line.

Reads one or more Java-style .properties files (or folders of
them), checks every line is a valid key=value or key:value entry,
and reports every problem with file, line number, and reason.
Report-only: it never rewrites a file. Exit 0 when every file is
clean, 1 when any problem is found, 2 for a usage error.
"""

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

__version__ = "1.0.0"

PROPERTIES_EXTENSIONS = {".properties"}

# A backslash may escape these characters. Anything else after a
# backslash is a bad escape. \uXXXX is handled separately.
VALID_ESCAPES = set("tnrf\\'\" #!:= \t")
HEX_DIGITS = set("0123456789abcdefABCDEF")


class Problem:
    """One problem in one file: path, line number, plain reason."""

    def __init__(self, path, line, reason):
        self.path = path
        self.line = line
        self.reason = reason

    def text(self):
        return f"{self.path}:{self.line}: {self.reason}"

    def as_dict(self):
        return {"file": self.path, "line": self.line, "reason": self.reason}


def _count_trailing_backslashes(line):
    count = 0
    for char in reversed(line):
        if char == "\\":
            count += 1
        else:
            break
    return count


def _join_logical_lines(text):
    """Fold backslash continuations into logical lines.

    A line ending in an odd number of backslashes continues onto
    the next line; the leading whitespace of the next line is
    dropped. Returns a list of (first line number, logical line).
    """
    raw_lines = text.splitlines()
    logical = []
    index = 0
    while index < len(raw_lines):
        lineno = index + 1
        line = raw_lines[index]
        while (_count_trailing_backslashes(line) % 2 == 1
               and index + 1 < len(raw_lines)):
            line = line[:-1]
            index += 1
            line += raw_lines[index].lstrip(" \t\f")
        logical.append((lineno, line))
        index += 1
    return logical


def _check_escapes(segment, label, lineno, problems, where):
    """Check the escapes in one key or value segment.

    Reports the first bad escape on the line, if any. Returns
    True when the segment is clean.
    """
    index = 0
    while index < len(segment):
        if segment[index] != "\\":
            index += 1
            continue
        if index + 1 >= len(segment):
            problems.append(Problem(
                label, lineno,
                f"line ends with a lone backslash in the {where}"))
            return False
        nxt = segment[index + 1]
        if nxt == "u":
            digits = segment[index + 2:index + 6]
            if len(digits) < 4 or any(c not in HEX_DIGITS for c in digits):
                problems.append(Problem(
                    label, lineno,
                    "unicode escape is not followed by 4 hex digits "
                    f"in the {where}"))
                return False
            index += 6
            continue
        if nxt not in VALID_ESCAPES:
            problems.append(Problem(
                label, lineno,
                f"bad escape '\\{nxt}' in the {where}"))
            return False
        index += 2
    return True


def _unescape(text):
    """Turn the escape sequences in text into plain characters.

    Used only to compare keys, so `my\\ key` and `my key` count
    as the same key.
    """
    out = []
    index = 0
    while index < len(text):
        if text[index] != "\\" or index + 1 >= len(text):
            out.append(text[index])
            index += 1
            continue
        nxt = text[index + 1]
        if nxt == "u" and len(text) >= index + 6:
            out.append(chr(int(text[index + 2:index + 6], 16)))
            index += 6
            continue
        out.append({"t": "\t", "n": "\n", "r": "\r", "f": "\f"}.get(nxt, nxt))
        index += 2
    return "".join(out)


def _find_separator(line):
    """Find the key/value separator in a logical line.

    Returns (key_end, value_start) where key_end is the index just
    past the key and value_start is the index where the value
    starts, or None when the line has no '=' or ':' separator.
    The first unescaped '=' or ':' wins. Whitespace before it is
    part of the gap, not part of the key.
    """
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\":
            index += 2
            continue
        if char in "=:":
            value_start = index + 1
            while (value_start < len(line)
                   and line[value_start] in " \t\f"):
                value_start += 1
            return index, value_start
        index += 1
    return None


def scan_text(text, label):
    """Check one .properties document (as text) and return problems.

    A line is blank, a comment (# or !, after leading whitespace),
    or a key=value / key:value entry. Anything else is a problem.
    Every problem is reported, not just the first. Keys are
    case-sensitive: `Port` and `port` are different keys.
    """
    problems = []
    seen_keys = set()

    for lineno, line in _join_logical_lines(text):
        stripped = line.strip(" \t\f")
        if not stripped:
            continue
        if stripped[0] in "#!":
            continue
        # Leading whitespace before a key is fine; it is skipped.
        found = _find_separator(line)
        if found is None:
            problems.append(Problem(
                label, lineno,
                "line has no '=' or ':' separator"))
            continue
        key_end, value_start = found
        raw_key = line[:key_end].strip(" \t\f")
        if raw_key == "":
            problems.append(Problem(label, lineno, "key name is empty"))
            continue
        value = line[value_start:]
        _check_escapes(raw_key, label, lineno, problems, "key")
        _check_escapes(value, label, lineno, problems, "value")
        key = _unescape(raw_key)
        if key in seen_keys:
            problems.append(Problem(
                label, lineno, f"key '{raw_key}' already exists"))
        else:
            seen_keys.add(key)
    return problems


def check_file(path):
    """Check one file on disk.

    Returns (problems, error). problems is a list of Problem; error is
    a message string when the file cannot be read at all, else None.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        return None, f"cannot read {path}: {exc.strerror or exc}"
    if b"\x00" in raw:
        line = raw[:raw.index(b"\x00")].count(b"\n") + 1
        return [Problem(str(path), line,
            "file contains a null byte, it is not a text file")], None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = raw[:exc.start].count(b"\n") + 1
        return [Problem(str(path), line,
            "file is not valid UTF-8")], None
    return scan_text(text, str(path)), None


def collect(paths, recursive=True, exclude=()):
    """Expand files and folders into a sorted list of .properties files.

    A file given directly is always checked, whatever its name. A
    folder is walked for .properties files. .git folders are never
    walked, and directory links are never followed.
    """
    found = []
    seen = set()
    for given in paths:
        path = Path(given)
        if path.is_file():
            if path not in seen:
                seen.add(path)
                found.append(path)
        elif path.is_dir():
            for root, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = [d for d in dirs
                           if d != ".git"
                           and not any(fnmatch.fnmatch(d, pat)
                                       for pat in exclude)]
                if not recursive:
                    dirs[:] = []
                for name in files:
                    if any(fnmatch.fnmatch(name, pat) for pat in exclude):
                        continue
                    candidate = Path(root) / name
                    if candidate.suffix.lower() in PROPERTIES_EXTENSIONS:
                        if candidate not in seen:
                            seen.add(candidate)
                            found.append(candidate)
        else:
            raise FileNotFoundError(given)
    return sorted(found, key=str)


def check_paths(paths, recursive=True, exclude=()):
    """Check every file found under paths. Returns (problems, checked)."""
    problems = []
    try:
        files = collect(paths, recursive, exclude)
    except FileNotFoundError as exc:
        return None, None, f"no such file or folder: {exc}"
    for path in files:
        file_problems, error = check_file(path)
        if error is not None:
            return None, None, error
        problems.extend(file_problems)
    return problems, len(files), None


def format_report(problems, checked):
    """Human-readable report lines and the summary line."""
    lines = [problem.text() for problem in problems]
    bad_files = len({problem.path for problem in problems})
    if problems:
        summary = (f"Checked {checked} file(s), {len(problems)} "
                   f"problem(s) in {bad_files} file(s).")
    else:
        summary = (f"OK — {checked} file(s) checked, "
                   "all .properties files are valid.")
    return lines, summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="properties-validator-cli",
        description="Validate .properties files, fail CI on a bad line.")
    parser.add_argument("paths", nargs="*",
                        help=".properties files or folders to check")
    parser.add_argument("--stdin", action="store_true",
                        help="check one .properties file read from "
                        "standard input")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON "
                        "(human-readable lines go to standard error)")
    parser.add_argument("--no-recursive", action="store_true",
                        help="do not walk into subfolders")
    parser.add_argument("--exclude", action="append", default=[],
                        metavar="PATTERN",
                        help="skip files and folders whose name matches "
                        "PATTERN (repeatable)")
    parser.add_argument("--version", action="version",
                        version=f"properties-validator-cli {__version__}")
    args = parser.parse_args(argv)

    if not args.paths and not args.stdin:
        parser.error("give at least one file or folder, or --stdin")

    problems = []
    checked = 0
    if args.stdin:
        text = sys.stdin.read()
        problems.extend(scan_text(text, "<stdin>"))
        checked += 1
    if args.paths:
        found, count, error = check_paths(
            args.paths, not args.no_recursive, args.exclude)
        if error is not None:
            print(error, file=sys.stderr)
            return 2
        problems.extend(found)
        checked += count

    lines, summary = format_report(problems, checked)
    if args.json:
        for line in lines:
            print(line, file=sys.stderr)
        print(json.dumps({
            "files_checked": checked,
            "problems": [problem.as_dict() for problem in problems],
            "files_with_problems": len({p.path for p in problems}),
        }, indent=2))
    else:
        for line in lines:
            print(line)
        print(summary)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
