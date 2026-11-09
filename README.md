# properties-validator-cli

Validate .properties files, fail CI on a bad line.

[![CI](https://github.com/haiderstudio/properties-validator-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/properties-validator-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`properties_validator` reads a Java-style `.properties` file and
checks every line is a valid `key=value` or `key:value` entry, and
reports every problem with the file, the line number, and the
exact reason. It exits 1 when any problem is found, so it can
fail a CI run. A clean file exits 0.

- A bad `.properties` line breaks the Java, Android, or Spring
  app that reads it at startup, with a cryptic error. This tool
  catches the break before the file ships, and points at the
  exact line.
- Every problem is reported, not just the first: a file with a
  duplicate key *and* a bad escape lists both.
- Checks: a line with no `=` or `:` separator, an empty key, a
  key that appears twice in one file, a bad escape (`\w` is not
  a real escape), a unicode escape that is not followed by 4
  hex digits (`\u00e` is cut short), and a line that ends with
  a lone backslash.
- Keys are case-sensitive, the way the format reads them —
  `Port` and `port` are different keys. A key written with an
  escaped space (`my\ key`) counts as the same key as the same
  words with a plain space.
- Lines starting with `#` or `!` are comments, and blank lines
  are skipped. Leading whitespace before a key is fine.
- A line ending in a backslash continues onto the next line,
  with the next line's leading whitespace dropped — even if
  the next line looks like a comment.
- A file that is not valid UTF-8, or that contains a null byte,
  is reported as a problem — neither can be a real
  `.properties` file.
- A line with no `=` or `:` is a problem, even though Java
  itself would read a whitespace-separated line as a key with
  a value. This tool wants every entry to use an explicit
  separator, so a typo that drops the `=` is caught instead
  of silently becoming a different entry.
- A file given directly on the command line is always checked,
  whatever its name. A folder is walked for `.properties`
  files, recursively by default (`--no-recursive` stops at
  the top level). `.git` folders are never walked, and
  directory links are never followed. `--exclude` skips files
  and folders by name pattern.
- `--json` prints the result as JSON (the human-readable
  lines go to standard error), and `--stdin` checks one
  `.properties` file read from standard input.

## Who it is for

Anyone who ships `.properties` files — Java and Android
developers, Spring teams, and anyone who keeps app settings
in version control and has ever stared at a startup crash
that turned out to be one bad line in a settings file.

## What it does NOT do

- It does not check whether a value is *right* — a valid file
  can still hold a wrong port number. Checking values against
  a schema is a different job.
- It does not convert or rewrite anything. It is report-only,
  and it never touches the network.
- It does not check any other format. INI is repo #54's
  ini-validator-cli, TOML is repo #36's toml-validator-cli —
  `.properties` is a different format.

## How this differs

- typestack/class-validator (11,852 stars) is decorator-based
  property validation for TypeScript classes. It validates
  object properties in code, not `.properties` files.
- SvenTiigi/ValidatedPropertyKit (977 stars) validates
  properties with Swift property wrappers. Same name, a
  different job.
- adopted-ember-addons/ember-cp-validations (437 stars) and
  eivindfjeldstad/validate (234 stars) are Ember and
  JavaScript property validators. Neither reads a
  `.properties` file.
- apple/pkl (11,567 stars) is a configuration language with
  its own validation. A whole language is not a file checker
  you run in CI.
- There is no exact-name rival: a GitHub search for
  `"properties-validator-cli"` returns 0 results, and a search
  for `"properties file checker"` returns 0 results (checked
  Nov 8, 2026).

## Install

Python 3.10 or newer, nothing else to install.

```sh
git clone https://github.com/haiderstudio/properties-validator-cli.git
cd properties-validator-cli
```

## Usage

Check one file:

```sh
python3 src/properties_validator.py examples/good.properties
```

```text
OK — 1 file(s) checked, all .properties files are valid.
```

Check a broken file:

```sh
python3 src/properties_validator.py examples/bad.properties
```

```text
examples/bad.properties:2: line has no '=' or ':' separator
examples/bad.properties:3: key name is empty
examples/bad.properties:5: key 'port' already exists
examples/bad.properties:6: bad escape '\w' in the value
examples/bad.properties:7: unicode escape is not followed by 4 hex digits in the value
Checked 1 file(s), 5 problem(s) in 1 file(s).
```

The exit code is 1, so a CI run fails.

Check a whole folder:

```sh
python3 src/properties_validator.py examples
```

```text
examples/bad.properties:2: line has no '=' or ':' separator
examples/bad.properties:3: key name is empty
examples/bad.properties:5: key 'port' already exists
examples/bad.properties:6: bad escape '\w' in the value
examples/bad.properties:7: unicode escape is not followed by 4 hex digits in the value
examples/configs/app.properties:4: key 'app.name' already exists
Checked 4 file(s), 6 problem(s) in 2 file(s).
```

Check one file from standard input:

```sh
printf 'app.name = MyApp\nport = 8080\n' | python3 src/properties_validator.py --stdin
```

```text
OK — 1 file(s) checked, all .properties files are valid.
```

Machine-readable output:

```sh
python3 src/properties_validator.py examples/configs/app.properties --json
```

```json
{
  "files_checked": 1,
  "problems": [
    {
      "file": "examples/configs/app.properties",
      "line": 4,
      "reason": "key 'app.name' already exists"
    }
  ],
  "files_with_problems": 1
}
```

## Examples

- `examples/good.properties` — a clean settings file: both
  separators, an empty value, an escaped space in a key, a
  unicode escape, and a continued line. Passes.
- `examples/bad.properties` — five problems in one file: a
  line with no separator, an empty key, a duplicate key, a
  bad escape, and a cut-short unicode escape. Fails with
  exit 1.
- `examples/messages.properties` — a clean messages file
  with both comment styles and a non-English unicode escape.
  Passes.
- `examples/configs/app.properties` — one duplicate key, in
  a subfolder. Fails with exit 1.
- `sh examples/run-example.sh` runs the checker on the whole
  `examples/` folder. Its output is in
  `examples/sample-output.md`.

## How it is tested

```sh
python3 tests/test_properties_validator.py
```

The tests cover: every problem type with exact line numbers,
valid files that must pass (both separators, empty values,
comments in both styles, escaped spaces and separators in
keys, valid unicode escapes, continued lines, keys that
differ only by case passing, duplicate keys with escaped
spaces failing), folder walking (`.properties` only, `.git`
skipped, `--no-recursive`, `--exclude`, direct file with any
name, dedupe), `--stdin`, `--json`, exit codes 0/1/2,
non-UTF-8 and null-byte files, an empty folder, input files
left unchanged, and the bundled examples (the sample output
is compared byte-for-byte against a fresh run, and every
code block in this README is compared against a real run).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The
`.properties` rules it checks are the rules of the Java
`.properties` format, with one deliberate stricter choice:
a line with no `=` or `:` is a problem here, so a dropped
separator is caught instead of silently changing the entry.
The idea of validating config files is a common one; the
code, the wording, and the tests are original.
