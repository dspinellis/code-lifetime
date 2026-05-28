"""Build helpers for the git-hot package."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from setuptools import setup
from setuptools.command.bdist_wheel import bdist_wheel
from setuptools.command.install_scripts import install_scripts


def build_daglp(output: Path) -> None:
    """Build the Rust daglp command at the specified path."""
    rustc = shutil.which("rustc")
    if rustc is None:
        raise RuntimeError("rustc is required to build the daglp executable")

    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(
        [
            rustc,
            "--edition=2021",
            "-C",
            "opt-level=3",
            "src/git_hot/daglp.rs",
            "-o",
            str(output),
        ]
    )


class InstallScripts(install_scripts):
    """Install the compiled daglp executable beside Python console scripts."""

    def run(self) -> None:
        super().run()
        exe_name = "daglp.exe" if os.name == "nt" else "daglp"
        self._daglp_output = Path(self.install_dir) / exe_name
        build_daglp(self._daglp_output)

    def get_outputs(self) -> list[str]:
        outputs = super().get_outputs()
        daglp_output = getattr(self, "_daglp_output", None)
        if daglp_output is not None:
            outputs.append(str(daglp_output))
        return outputs


class BdistWheel(bdist_wheel):
    """Mark wheels as platform-specific because they include daglp."""

    def finalize_options(self) -> None:
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self) -> tuple[str, str, str]:
        _python, _abi, platform = super().get_tag()
        return "py3", "none", platform


setup(cmdclass={"install_scripts": InstallScripts, "bdist_wheel": BdistWheel})
