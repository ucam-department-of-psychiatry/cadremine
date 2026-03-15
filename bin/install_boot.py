#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import logging
import os
from subprocess import CompletedProcess, run
import sys
from typing import Any
from venv import EnvBuilder

log = logging.getLogger(__name__)


class BootException(Exception):
    pass


@dataclass
class Booter:
    intermine_dir: str
    nexus_host_port: int
    offline: bool
    postgres_host_port: int
    recreate_databases: bool
    recreate_venv: bool
    release_dir: str
    tomcat_host_port: int
    verbose: bool

    pypi_host_port: int = 8080

    def __post_init__(self) -> None:
        self.bin_dir = os.path.dirname(os.path.realpath(__file__))
        self.project_root_dir = os.path.join(self.bin_dir, "..")
        self.venv_dir = os.path.join(self.release_dir, "venv")
        self.venv_python = os.path.join(self.venv_dir, "bin", "python")

    def boot(self) -> None:
        if self.recreate_venv or not os.path.exists(self.venv_dir):
            self.create_virtual_environment()
            self.install_requirements()

        self.run_install_script()

    def create_virtual_environment(self) -> None:
        builder = EnvBuilder(
            clear=self.recreate_venv, with_pip=True, upgrade_deps=True
        )

        builder.create(self.venv_dir)

    def install_requirements(self) -> None:
        install_args = [
            self.venv_python,
            "-m",
            "pip",
            "install",
            "-r",
            f"{self.project_root_dir}/requirements.txt",
        ]

        self.run_with_env(install_args)

    def run_install_script(self) -> None:
        install_args = [
            self.venv_python,
            f"{self.bin_dir}/install.py",
            self.intermine_dir,
            self.release_dir,
            "--nexus_host_port",
            str(self.nexus_host_port),
            "--postgres_host_port",
            str(self.postgres_host_port),
            "--tomcat_host_port",
            str(self.tomcat_host_port),
        ]

        if self.offline:
            install_args.append("--offline")

        if self.recreate_databases:
            install_args.append("--recreate_databases")

        if self.verbose:
            install_args.append("--verbose")

        returned_value = self.run_with_env(install_args, check=False)
        sys.exit(returned_value.returncode)

    def run_with_env(
        self, run_args: list[Any], check: bool = True
    ) -> CompletedProcess[Any]:
        env = os.environ.copy()

        log.debug("Running:")
        log.debug(run_args)
        return run(run_args, check=check, env=env)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install cadremine",
    )
    parser.add_argument(
        "intermine_dir", help="Top level directory containing Intermine"
    )
    parser.add_argument(
        "release_dir",
        help="Top level directory containing files outside of version control",
    )
    parser.add_argument(
        "--recreate_venv",
        action="store_true",
        help="Recreate the installer virtual environment",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Be verbose"
    )
    parser.add_argument(
        "--nexus_host_port",
        type=int,
        default=8081,
        help="Host port to use for the Sonatype Nexus server",
    )
    parser.add_argument(
        "--postgres_host_port",
        type=int,
        default=5432,
        help="Host port to use for the Postgres server",
    )
    parser.add_argument(
        "--tomcat_host_port",
        type=int,
        default=9999,
        help="Host port to use for the Tomcat server",
    )
    parser.add_argument(
        "--recreate_databases",
        action="store_true",
        help="Recreate databases",
    )

    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use offline Maven repositories",
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    booter = Booter(**vars(args))
    booter.boot()


if __name__ == "__main__":
    main()
