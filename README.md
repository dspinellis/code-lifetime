# git-hot

`git-hot` is a Git extension that reports how ``hot'' (often-changing)
the current lines or files in a repository are.
It derives line lifetime and churn information from Git history,
then highlights files and lines that have changed often or recently.

Install the package and run it as either:

```sh
git hot
git-hot
```

The package installs two commands:

- `git-hot`, the Git extension command; [manual page](https://dspinellis.github.io/manview/?src=https%3A%2F%2Fraw.githubusercontent.com%2Fdspinellis%2Fgit-hot%2Frefs%2Fheads%2Fmaster%2Fgit-hot.1&name=git-hot&link=https%3A%2F%2Fgithub.com%2Fdspinellis%2Fgit-hot).
- `daglp`, a helper, written in Rust, used to compute the longest path
  through the Git commit DAG; [manual page](https://dspinellis.github.io/manview/?src=https%3A%2F%2Fraw.githubusercontent.com%2Fdspinellis%2Fgit-hot%2Frefs%2Fheads%2Fmaster%2Fdaglp.1&name=daglp&link=https%3A%2F%2Fgithub.com%2Fdspinellis%2Fgit-hot).


## Installation

For an isolated command installation:

```sh
uv tool install git-hot
```

For installation in an active virtual environment:

```sh
uv pip install git-hot
```

With `pip`:

```sh
python -m pip install git-hot
```

After installation, ensure the installation's script directory is on `PATH` so
Git can find `git-hot` and you can invoke it as `git hot`.

## Usage

Show hot files in the current repository:

```sh
git hot
```

Show hot files at a specific revision:

```sh
git hot HEAD
```

Show line-level churn for one file:

```sh
git hot -- src/main.py
```

Show line ages and birth commits for one file:

```sh
git hot -q --format '{days(age)} {hash[:7]} {line}' -- src/main.py
```

Reconstruct all source files with churn prefixes below a directory:

```sh
git hot --dir hot-tree HEAD
```

## Output

Without a path, `git hot` prints one line per current source file, sorted by
path.  The default columns are:

- maximum live-line churn in the file
- median changed-line lifetime in days
- median live-line age in days
- repository path

With a path, `git hot` prints the reconstructed contents of that file.  By
default each line is preceded by its churn count.

Use `--color always` or `--color never` to control color output.  Automatic
coloring can rank lines by `churn`, `age`, or `lifetime`:

```sh
git hot --color always --color-domain age -- src/main.py
```

## Formatting

Use `--format` to customize file or line output with a restricted Python
f-string expression.  The available fields depend on whether repository-wide
file metrics or selected-path line output is being produced.

Examples:

```sh
git hot --format '{max(churn):5d} {days(median(line_age)):5d} {path}'
git hot --format '{days(age)} {hash[:7]} {line}' -- src/main.py
```

Common helpers include `days`, `max`, `min`, `median`, `mean`,
`quartile_rank`, `color`, and `color_reset`.

For the complete list of format fields and options, see:

```sh
man git-hot
```

or read the [git-hot manual page](https://dspinellis.github.io/manview/?src=https%3A%2F%2Fraw.githubusercontent.com%2Fdspinellis%2Fgit-hot%2Frefs%2Fheads%2Fmaster%2Fgit-hot.1&name=git-hot&link=https%3A%2F%2Fgithub.com%2Fdspinellis%2Fgit-hot).

## Requirements

`git-hot` expects to run inside a Git repository.
Alternatively, the Git repository can be passed to the `git` command
using the `--git-dir` option.
Internally, it invokes Git commands such
as `git log`, `git show`, and `git diff`, and uses rename and copy detection.

Binary files and deleted files are skipped in file-metric output.

## Installing From Source

Building from source requires Python 3.10 or later and a Rust toolchain with
`rustc`, because `daglp` is compiled during installation.

```sh
uv sync --group dev
uv pip install -e .
uv run python -m unittest discover -s . -p 'test*.py'
uv run --group dev ruff check .
```

Build a source distribution locally with:

```sh
uv build --sdist
```

Platform wheels are built in CI through `cibuildwheel`.

## Research Tools

This repository also contains research-oriented source tools used for
fine-grained code lifetime analysis, including `lifetime.py`, `difflog.sh`,
`tokenize.pl`, and the top-level `daglp.rs`.  They are kept in source form for
reproducibility and experimentation, but the installable package exposes only
`git-hot` and `daglp`.

For historical and research context, see `lifetime-tools.md`.

## License

`git-hot` is distributed under the Apache License 2.0.  See `LICENSE`.
