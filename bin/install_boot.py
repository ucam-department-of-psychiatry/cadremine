#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import logging
import os
from subprocess import run
import sys
from typing import Any
from venv import EnvBuilder

log = logging.getLogger(__name__)


@dataclass
class Booter:
    recreate_venv: bool
    verbose: bool

    def __post_init__(self) -> None:
        self.release_dir = os.path.dirname(os.path.realpath(__file__))
        self.docker_images_dir = os.path.join(
            self.release_dir, "docker_images"
        )
        self.python_packages_dir = os.path.join(
            self.release_dir, "python_packages"
        )
        self.venv_dir = os.path.join(self.release_dir, "venv")
        self.venv_python = os.path.join(self.venv_dir, "bin", "python")

        self.pypi_port = 8080

    def boot(self) -> None:
        self.install_local_pypi_server()
        self.run_local_pypi_server()

        if self.recreate_venv or not os.path.exists(self.venv_dir):
            self.create_virtual_environment()
            self.install_requirements()

        self.run_install_script()

    def install_local_pypi_server(self) -> None:
        # No python-on-whales until we have a pypi server
        pypi_tar_file = os.path.join(
            self.docker_images_dir, "pypiserver-v2.4.tar"
        )

        self.run_with_env(["docker", "load", "-i", pypi_tar_file])

    def run_local_pypi_server(self) -> None:
        self.run_with_env(
            [
                "docker",
                "run",
                "-p",
                f"80:{self.pypi_port}",
                "-v",
                f"{self.python_packages_dir}:/data/packages",
                "pypiserver/pypiserver:v2.4",
                "run",
            ]
        )

    def create_virtual_environment(self) -> None:
        builder = EnvBuilder(
            clear=self.recreate_venv, with_pip=True, upgrade_deps=True
        )

        builder.create(self.venv_dir)

    def install_requirements(self) -> None:
        self.run_with_env(
            [
                self.venv_python,
                "-m",
                "pip",
                "install",
                "--extra-index-url",
                f"http://localhost:{self.pypi_port}",
                "-r",
                f"{self.release_dir}/requirements.txt",
            ],
            check=True,
        )

    def run_install_script(self) -> None:
        install_args = [
            self.venv_python,
            f"{self.release_dir}/install.py",
        ]

        if self.verbose:
            install_args.append("--verbose")

        returned_value = self.run_with_env(install_args)
        sys.exit(returned_value.returncode)

    def run_with_env(self, run_args: list[Any]) -> None:
        env = os.environ.copy()

        if self.verbose:
            log.info("Running:")
            log.info(run_args)
        run(run_args, check=True, env=env)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install cadremine",
    )
    parser.add_argument(
        "--recreate_venv",
        action="store_true",
        help="Recreate the installer virtual environment",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Be verbose"
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    booter = Booter(**vars(args))
    booter.boot()


if __name__ == "__main__":
    main()
