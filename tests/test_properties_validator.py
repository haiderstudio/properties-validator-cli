"""Tests for properties-validator-cli. Standard library only."""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "properties_validator.py"

sys.path.insert(0, str(ROOT / "src"))
import properties_validator as pv  # noqa: E402


def scan(text):
    return [(p.line, p.reason) for p in pv.scan_text(text, "test.properties")]


def run_cli(*args, stdin_text=None):
    result = subprocess.run(
        [sys.executable, str(SRC), *args],
        input=stdin_text, capture_output=True, text=True, cwd=ROOT)
    return result


class TestProblemTypes(unittest.TestCase):
    def test_line_with_no_separator(self):
        problems = scan("host example.com\n")
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0][0], 1)
        self.assertIn("no '=' or ':' separator", problems[0][1])

    def test_empty_key_equals(self):
        problems = scan("= no key here\n")
        self.assertEqual(problems, [(1, "key name is empty")])

    def test_empty_key_colon(self):
        problems = scan(": no key here\n")
        self.assertEqual(problems, [(1, "key name is empty")])

    def test_duplicate_key(self):
        problems = scan("port = 8080\nport = 9090\n")
        self.assertEqual(problems,
                         [(2, "key 'port' already exists")])

    def test_duplicate_key_different_separator(self):
        problems = scan("port = 8080\nport: 9090\n")
        self.assertEqual(problems,
                         [(2, "key 'port' already exists")])

    def test_duplicate_key_escaped_space(self):
        problems = scan("my\\ key = 1\nmy key = 2\n")
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0][0], 2)
        self.assertIn("already exists", problems[0][1])

    def test_bad_escape_in_value(self):
        problems = scan("path = C:\\windows\\system\n")
        self.assertEqual(problems,
                         [(1, "bad escape '\\w' in the value")])

    def test_bad_escape_in_key(self):
        problems = scan("my\\qkey = 1\n")
        self.assertEqual(problems,
                         [(1, "bad escape '\\q' in the key")])

    def test_unicode_escape_too_short(self):
        problems = scan("greeting = caf\\u00e\n")
        self.assertEqual(problems, [(1, "unicode escape is not followed "
                                        "by 4 hex digits in the value")])

    def test_unicode_escape_non_hex(self):
        problems = scan("greeting = caf\\u00xz\n")
        self.assertEqual(problems, [(1, "unicode escape is not followed "
                                        "by 4 hex digits in the value")])

    def test_unicode_escape_in_key(self):
        problems = scan("caf\\u00e = 1\n")
        self.assertEqual(problems, [(1, "unicode escape is not followed "
                                        "by 4 hex digits in the key")])

    def test_lone_backslash_last_line(self):
        problems = scan("key = value\\\n")
        self.assertEqual(problems, [(1, "line ends with a lone backslash "
                                        "in the value")])

    def test_bad_file_reports_every_problem(self):
        problems = scan((ROOT / "examples" / "bad.properties").read_text())
        self.assertEqual([p[0] for p in problems], [2, 3, 5, 6, 7])
        self.assertEqual(len(problems), 5)


class TestValidFiles(unittest.TestCase):
    def test_both_separators(self):
        self.assertEqual(scan("a = 1\nb: 2\n"), [])

    def test_empty_value(self):
        self.assertEqual(scan("empty =\n"), [])
        self.assertEqual(scan("empty:\n"), [])

    def test_comments_and_blanks(self):
        text = "# hash comment\n! bang comment\n\n   # indented comment\nkey = 1\n"
        self.assertEqual(scan(text), [])

    def test_leading_whitespace_before_key(self):
        self.assertEqual(scan("   key = 1\n"), [])

    def test_keys_are_case_sensitive(self):
        self.assertEqual(scan("Port = 8080\nport = 9090\n"), [])

    def test_escaped_space_in_key(self):
        self.assertEqual(scan("my\\ key = spaced\n"), [])

    def test_escaped_separators_in_key(self):
        self.assertEqual(scan("key\\:with\\:colons = 1\n"), [])
        self.assertEqual(scan("key\\=with\\=equals = 1\n"), [])

    def test_valid_unicode_escape(self):
        self.assertEqual(scan("greeting = caf\\u00e9\n"), [])

    def test_valid_escapes(self):
        self.assertEqual(scan("a = tab\\there\n"), [])
        self.assertEqual(scan("a = new\\nline\n"), [])
        self.assertEqual(scan("a = back\\\\slash\n"), [])
        self.assertEqual(scan("a = \\'quoted\\'\n"), [])

    def test_continuation(self):
        text = "long.value = first part \\\n    second part\n"
        self.assertEqual(scan(text), [])

    def test_continuation_joins_comment_line(self):
        # After a continuation backslash the next line is part of
        # the value, even if it looks like a comment.
        text = "key = one \\\n# not a comment\n"
        self.assertEqual(scan(text), [])

    def test_escaped_backslash_at_end_is_not_continuation(self):
        self.assertEqual(scan("path = C:\\\\\n"), [])

    def test_value_may_contain_separator(self):
        self.assertEqual(scan("url = http://example.com:8080/x\n"), [])

    def test_good_examples_pass(self):
        for name in ("good.properties", "messages.properties"):
            text = (ROOT / "examples" / name).read_text()
            self.assertEqual(scan(text), [], name)


class TestFilesAndFolders(unittest.TestCase):
    def test_check_file_good(self):
        problems, error = pv.check_file(ROOT / "examples" / "good.properties")
        self.assertIsNone(error)
        self.assertEqual(problems, [])

    def test_check_file_missing(self):
        problems, error = pv.check_file(ROOT / "examples" / "nope.properties")
        self.assertIsNone(problems)
        self.assertIn("cannot read", error)

    def test_check_file_not_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.properties"
            path.write_bytes(b"key = caf\xff\n")
            problems, error = pv.check_file(path)
            self.assertIsNone(error)
            self.assertEqual(len(problems), 1)
            self.assertIn("not valid UTF-8", problems[0].reason)

    def test_check_file_null_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.properties"
            path.write_bytes(b"key = 1\n\x00\n")
            problems, error = pv.check_file(path)
            self.assertIsNone(error)
            self.assertEqual(len(problems), 1)
            self.assertIn("null byte", problems[0].reason)

    def test_folder_walk_finds_properties_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.properties").write_text("a = 1\n")
            (root / "b.txt").write_text("not a key\n")
            (root / "sub").mkdir()
            (root / "sub" / "c.properties").write_text("c = 1\n")
            found = pv.collect([str(root)])
            self.assertEqual([p.name for p in found],
                             ["a.properties", "c.properties"])

    def test_folder_walk_skips_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git = root / ".git"
            git.mkdir()
            (git / "hooks.properties").write_text("bad line\n")
            (root / "a.properties").write_text("a = 1\n")
            found = pv.collect([str(root)])
            self.assertEqual([p.name for p in found], ["a.properties"])

    def test_no_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.properties").write_text("a = 1\n")
            (root / "sub").mkdir()
            (root / "sub" / "b.properties").write_text("b = 1\n")
            found = pv.collect([str(root)], recursive=False)
            self.assertEqual([p.name for p in found], ["a.properties"])

    def test_exclude_pattern(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.properties").write_text("a = 1\n")
            (root / "skip.properties").write_text("b = 1\n")
            found = pv.collect([str(root)], exclude=["skip*"])
            self.assertEqual([p.name for p in found], ["a.properties"])

    def test_direct_file_any_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weird-name"
            path.write_text("bad line\n")
            found = pv.collect([str(path)])
            self.assertEqual(found, [path])

    def test_dedupe(self):
        path = ROOT / "examples" / "good.properties"
        found = pv.collect([str(path), str(path)])
        self.assertEqual(found, [path])

    def test_missing_path(self):
        problems, checked, error = pv.check_paths(["/no/such/path"])
        self.assertIsNone(problems)
        self.assertIsNone(checked)
        self.assertIn("no such file or folder", error)

    def test_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems, checked, error = pv.check_paths([tmp])
            self.assertIsNone(error)
            self.assertEqual(problems, [])
            self.assertEqual(checked, 0)


class TestCli(unittest.TestCase):
    def test_good_file_exit_0(self):
        result = run_cli("examples/good.properties")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(),
                         "OK — 1 file(s) checked, all .properties files are valid.")

    def test_bad_file_exit_1(self):
        result = run_cli("examples/bad.properties")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Checked 1 file(s), 5 problem(s) in 1 file(s).",
                      result.stdout)

    def test_folder_exit_1(self):
        result = run_cli("examples")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Checked 4 file(s), 6 problem(s) in 2 file(s).",
                      result.stdout)

    def test_stdin_clean(self):
        result = run_cli("--stdin", stdin_text="app.name = MyApp\n")
        self.assertEqual(result.returncode, 0)
        self.assertIn("all .properties files are valid.", result.stdout)

    def test_stdin_bad(self):
        result = run_cli("--stdin", stdin_text="no separator here\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("<stdin>:1: line has no '=' or ':' separator",
                      result.stdout)

    def test_json_output(self):
        result = run_cli("examples/configs/app.properties", "--json")
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertEqual(data["files_checked"], 1)
        self.assertEqual(data["files_with_problems"], 1)
        self.assertEqual(len(data["problems"]), 1)
        self.assertEqual(data["problems"][0]["line"], 4)
        self.assertIn("already exists", data["problems"][0]["reason"])
        self.assertIn("key 'app.name' already exists", result.stderr)

    def test_no_args_exit_2(self):
        result = run_cli()
        self.assertEqual(result.returncode, 2)

    def test_missing_path_exit_2(self):
        result = run_cli("/no/such/path")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no such file or folder", result.stderr)

    def test_version(self):
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("properties-validator-cli 1.0.0", result.stdout)

    def test_input_files_unchanged(self):
        before = {}
        for path in (ROOT / "examples").rglob("*"):
            if path.is_file():
                before[path] = path.read_bytes()
        run_cli("examples")
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content, path)


class TestExamplesAndReadme(unittest.TestCase):
    def test_run_example_matches_sample_output(self):
        result = subprocess.run(["sh", "examples/run-example.sh"],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0)
        sample = (ROOT / "examples" / "sample-output.md").read_text()
        block = sample.split("```text\n")[1].split("\n```")[0]
        self.assertEqual(result.stdout.rstrip("\n"), block.rstrip("\n"))

    def test_readme_text_blocks_match_real_output(self):
        readme = (ROOT / "README.md").read_text()
        blocks = re.findall(r"```text\n(.*?)```", readme, re.S)
        # The README has 4 ```text blocks: good, bad, folder, stdin.
        self.assertEqual(len(blocks), 4)
        cases = [
            (["examples/good.properties"], None),
            (["examples/bad.properties"], None),
            (["examples"], None),
            (["--stdin"], "app.name = MyApp\nport = 8080\n"),
        ]
        for block, (args, stdin_text) in zip(blocks, cases):
            result = run_cli(*args, stdin_text=stdin_text)
            self.assertEqual(result.stdout.rstrip("\n"),
                             block.rstrip("\n"), args)

    def test_readme_json_block_matches_real_output(self):
        readme = (ROOT / "README.md").read_text()
        blocks = re.findall(r"```json\n(.*?)```", readme, re.S)
        self.assertEqual(len(blocks), 1)
        result = run_cli("examples/configs/app.properties", "--json")
        self.assertEqual(result.stdout.rstrip("\n"),
                         blocks[0].rstrip("\n"))


class TestHygiene(unittest.TestCase):
    def test_no_placeholder_or_secret_words(self):
        banned = ["TODO", "FIXME", "coming soon", "lorem ipsum",
                  "api_key"]
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT)
            if ".git" in rel.parts or "__pycache__" in rel.parts or \
                    rel.parts[0] == "tests":
                continue
            text = path.read_text(errors="ignore")
            for word in banned:
                if word in text:
                    hits.append(f"{rel}: {word}")
        self.assertEqual(hits, [])

    def test_no_absolute_paths(self):
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT)
            if ".git" in rel.parts or "__pycache__" in rel.parts or \
                    rel.parts[0] == "tests":
                continue
            if "/home/hatch" in path.read_text(errors="ignore"):
                hits.append(str(rel))
        self.assertEqual(hits, [])

    def test_gitignore_lists_env_first(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_no_yaml_import(self):
        for path in (ROOT / "src").rglob("*.py"):
            self.assertNotIn("import yaml", path.read_text())
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
        self.assertNotIn("yaml", ci)


if __name__ == "__main__":
    unittest.main()
