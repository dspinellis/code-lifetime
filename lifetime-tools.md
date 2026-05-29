# Tools for tracking the lifetime of code lines and tokens
The tools in this repository allow the precise tracking of when a specific
code line or token is modified or removed.
They have been used for conducting the studies described in the
following paper.

Diomidis Spinellis, Panos Louridas, and Maria Kechagia.
Software evolution: The lifetime of fine-grained elements.
_PeerJ Computer Science_, 7:e372, February 2021.
[doi:10.7717/peerj-cs.372](https://dx.doi.org/10.7717/peerj-cs.372)

This is the paper's abstract.

A model regarding the lifetime of individual source code lines or tokens can
estimate maintenance effort,
guide preventive maintenance, and,
more broadly,
identify factors that can improve the efficiency of software development.
We present methods and tools that allow tracking of
each line's or token's birth and death.
Through them, we analyze 3.3 billion source code element lifetime events
in 89 revision control repositories.
Statistical analysis shows that code lines are durable,
with a median lifespan of about 2.3 years,
and that young lines are more likely to be modified or deleted,
following a Weibull distribution
with the associated hazard rate decreasing over time.
This behavior appears to be independent from specific characteristics
of lines or tokens, as we could not determine factors that
influence significantly their longevity across projects.
The programming language,
and developer tenure and experience were not
found to be significantly correlated with line or token longevity,
while project size and project age showed only a slight correlation.

The following sections describe the tools included in this repository.

## Installation as a package

The project is distributed as a Python package named `git-hot`, with the import
package named `git_hot`.
Installing it provides the `git-hot` Git extension command and the
platform-native Rust `daglp` executable.
Git can invoke `git-hot` as `git hot` when the installation's script directory
is on `PATH`.

For an isolated command installation, use `uv tool`:

```
uv tool install git-hot
```

For installation in an active virtual environment:

```
uv pip install git-hot
```

The equivalent `pip` commands are:

```
python -m pip install git-hot
python -m pip install --user git-hot
```

Use a virtual environment, `uv tool install`, `pipx`, or a user installation
unless you deliberately manage packages in the system Python.  On systems
following PEP 668, the system Python may reject global pip installs; prefer the
operating system package manager or an isolated environment instead.

## Installation from source

Building or installing from source requires Python 3.10 or later and a Rust
toolchain with `rustc`, because the package build compiles `daglp` from
`src/git_hot/daglp.rs`.  The recommended project workflow uses
[`uv`](https://docs.astral.sh/uv/), while the package remains standards-based
and can still be installed by `pip`.

For a project-local virtual environment:

```
uv venv
uv pip install .
```

For development, use an editable install with the test and lint tools
installed in the same environment:

```
uv sync --group dev
uv pip install -e .
uv run python -m unittest discover -s . -p 'test*.py'
uv run ruff check .
```

For a user installation, which avoids writing into the system Python:

```
uv tool install .
```

`uv tool install` installs commands into uv's tool directory, typically
`~/.local/bin` on Unix-like systems.  Ensure that directory is on `PATH`.
For a classic pip user install, `python -m pip install --user .` also works.

For a global installation from source, prefer a distribution package or an
administrator-managed environment.  If a global pip installation is appropriate
for the machine, run it explicitly through the intended interpreter:

```
python -m pip install .
```

## Distribution

Build a source distribution locally with:

```
uv build --sdist
```

The generated artifact is written below `dist/`.
Do not upload a locally built Linux wheel such as
`git_hot-0.1-py3-none-linux_x86_64.whl` to PyPI; PyPI rejects the local
`linux_x86_64` platform tag.  Release wheels are built separately through
`cibuildwheel`, which produces PyPI-accepted platform wheels such as
`manylinux`, Windows, and macOS wheels.

Before publishing a release, run:

```
uv run --group dev ruff check .
uv run python -m unittest discover -s . -p 'test*.py'
uv build --sdist
```

To verify an installation from the source checkout in an isolated environment:

```
uv venv /tmp/git-hot-smoke
uv pip install --python /tmp/git-hot-smoke/bin/python .
/tmp/git-hot-smoke/bin/git-hot --help
/tmp/git-hot-smoke/bin/daglp < /dev/null
```

The CI workflow builds and uploads separate wheels through `cibuildwheel` for
Linux x86_64, Linux aarch64, Windows AMD64, and macOS arm64.  Each wheel
contains the single `daglp` executable compiled for that platform.  Published
GitHub releases also publish the source distribution and built wheels to PyPI
using trusted publishing.

The repository also contains research-oriented source tools, including
`lifetime.py`, `difflog.sh`, `tokenize.pl`, and the original top-level
`daglp.rs`.  These are kept in source form for reproducibility and further
experimentation, but they are not installed by the `git-hot` package.

## lifetime
The _lifetime_ tool parses the output of successive _git diff_ runs and,
for every changed or deleted line, outputs a record containing the timestamps
of the line's creation and deletion.
Input can be supplied on its standard input or as files specified as arguments.
To monitor progress in long repositories it also outputs on its standard error
the SHA hash of each commit being processed.
When all commits have been processed it outputs the creation timestamps of
all remaining lines followed by `alive NA`.

### Example run

```
git log -M -m --pretty=tformat:'commit %H %ct' --topo-order --reverse -U0 |
lifetime.pl
1516281718 1597482365
1514636783 1597482365
1591563588 1598358198
1601804488 1601809923
1601809923 1601810093
1601810093 1601821073
1601809923 1602450156
1601804488 1603903274
1601804488 1603903274
1601821073 1603903274
1601821073 1603903274
1525764676 alive NA
1587747980 alive NA
1587747980 alive NA
1587747980 alive NA
1586362490 alive NA
1586362490 alive NA

```

The tool's operation can be modified through the following command-line
arguments.
```
-c      Output in "compressed" format: commit, followed by birthday of deaths
-d      Report the LoC delta
-D opts Debug as specified by the letters in opts
        C Show commit set changes
        D Show diff headers
        E Show diff extended headers
        H Show each commit SHA, timestamp header
        L Show LoC change processing
        P Show push to change set operations
        R Reconstruct the repository contents from its log
        @ Show range headers
        S Show results of splicing operations
        u Run unit tests
-e SHA  End processing after the specified (full) SHA commit hash
-E      Redirect (debugging) output to stderr
-f      List current files preceded by max line churn, median changed-line
        lifetime, and median line age (rounded integer days)
-g file Create a growth file with line count of live lines at every commit
-h      Print usage information and exit
-l      Associate with each line details about its composition
-q      Quiet; do not output commit and timestamp on normal processing
-s      Report only changes in source code files (based on their suffix)
-t      Show tokens with lifetime
```

## daglp
The _daglp_ program simplifies Git commit history into a linear graph
with the most commits, using a [graph longest path algorithm](https://en.wikipedia.org/wiki/Longest_path_problem#Acyclic_graphs_and_critical_paths).
Given as input a topologically sorted list of each commit's parents,
it will output the longest path of the directed acyclic graph from the
beginning (the oldest commit) to the end (the newest one).
The input is expected to come from a command such as
`git log --topo-order --pretty=format:'%H %at %P'`.
The output is a set of "SHA identifier" lines.

### Example run

```
$ git log --topo-order --pretty=format:'%H %at %P' | daglp
13af1997c687bb4462f97ab512e51e8c072a2858 1370686723
d8e85967adc0b188a49117b5db4f10cc6c7c36cb 1370688578
27a8ec806f16ae66a7eaa8563220f600c99b9ab9 1370688605
222f60c28228e189c0986f8c4e86cc5a07e69bfa 1370688896
a0759fa8d6838170e4b693d26d6edb5e0463c1d0 1370689181
```

## difflog
The _difflog_ tool produces a Git repository's log of changes
in unified diff format.
The processed commits are obtained through history simplification using _daglp_.
The output is roughly the equivalent of running,
as required by the _lifetime_ tool:

```
git -c diff.renameLimit=30000 log -m -M -C --pretty=tformat:'commit %H %at' --topo-order --reverse -U0
```

However, the former command [has been known to produce incorrect results](http://stackoverflow.com/questions/38839595/how-can-i-obtain-with-git-log-a-series-of-patches-that-can-be-auto-applied), which _difflog_ corrects.
Any command line options are passed as arguments to _git diff_.

## tokenize
The _tokenize_ tool is used to convert the source code commits of a Git
repository into equivalent ones containing one token per line, as e.g. proposed
by [cregit](https://github.com/cregit/cregit) and
[used on the Linux kernel](https://github.com/dmgerman/linux-token-bfg).
The new repository can then be used for performing token-level diffs.

The tool supports code written in Java, C, C#, C++, PHP, and Python,
as recognized by each file's suffix.
The tool expects the separate
[tokenizer](https://github.com/dspinellis/tokenizer) tool to be installed
and available in its execution path.
It is invoked with a Git repository directory and branch name as
argument.
Its output is suitable for feeding into _git fast-input_.
Each line in the new repository contains the token 's type
(KW for keyword,
NUM for number,
ID for identifier, and
TOK for all other tokens),
followed by the actual token.

### Example run
```
$ git init tokenized-repo
$ tokenize.pl repo main  | (cd tokenized-repo ; git fast-import)

/usr/lib/git-core/git-fast-import statistics:
---------------------------------------------------------------------
Alloc'd objects:       5000
Total objects:          494 (        91 duplicates                  )
      blobs  :          243 (        87 duplicates        234 deltas of        237 attempts)
      trees  :          141 (         4 duplicates        138 deltas of        138 attempts)
      commits:          110 (         0 duplicates          0 deltas of          0 attempts)
      tags   :            0 (         0 duplicates          0 deltas of          0 attempts)
Total branches:           1 (         1 loads     )
      marks:           1024 (       440 unique    )
      atoms:             54
Memory total:          2344 KiB
       pools:          2110 KiB
     objects:           234 KiB
---------------------------------------------------------------------
pack_report: getpagesize()            =       4096
pack_report: core.packedGitWindowSize = 1073741824
pack_report: core.packedGitLimit      = 35184372088832
pack_report: pack_used_ctr            =         25
pack_report: pack_mmap_calls          =         10
pack_report: pack_open_windows        =          1 /          1
pack_report: pack_mapped              =     237444 /     237444
---------------------------------------------------------------------
$ cd tokenized-repo
$ git show
commit 1004d9ad8074c774dfe60f8d0527d3eefd20a003 (HEAD -> master)
Author: Diomidis Spinellis <dds@aueb.gr>
Date:   Fri Feb 8 15:34:17 2019 +0200

    Handle numbers representing infinity

    Issue: #10

diff --git a/src/TokenId.cpp b/src/TokenId.cpp
index 35b8296..511e57a 100644
--- a/src/TokenId.cpp
+++ b/src/TokenId.cpp
@@ -37,6 +37,18 @@ KW constexpr
 KW int
 ID TokenId
 TOK ::
+ID NUMBER_INFINITE
+TOK ;
+KW constexpr
+KW int
+ID TokenId
+TOK ::
+ID NUMBER_NAN
+TOK ;
+KW constexpr
+KW int
+ID TokenId
+TOK ::
 ID NUMBER_END
 TOK ;
 KW constexpr
```
