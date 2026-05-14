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

EXIT_FAILURE = -1


class BootException(Exception):
    pass


@dataclass
class Booter:
    intermine_dir: str
    nexus_host_port: int
    offline: bool
    omop_data_dir: str
    omop_schema_file: str
    postgres_host_port: int
    recreate_databases: bool
    recreate_venv: bool
    release_dir: str
    tomcat_host: str
    verbose: bool

    pypi_host_port: int = 8080

    def __post_init__(self) -> None:
        self.bin_dir = os.path.dirname(os.path.realpath(__file__))
        self.project_root_dir = os.path.join(self.bin_dir, "..")
        self.venv_dir = os.path.join(self.release_dir, "venv")
        self.venv_python = os.path.join(self.venv_dir, "bin", "python")

    def boot(self) -> None:
        self.check_release_dir_exists()
        if self.recreate_venv or not os.path.exists(self.venv_dir):
            self.create_virtual_environment()
            self.install_requirements()

        self.run_install_script()

    def check_release_dir_exists(self) -> None:
        if not os.path.exists(self.release_dir):
            print(f"The directory {self.release_dir} does not exist")
            sys.exit(EXIT_FAILURE)

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
            self.omop_schema_file,
            self.omop_data_dir,
            "--nexus_host_port",
            str(self.nexus_host_port),
            "--postgres_host_port",
            str(self.postgres_host_port),
            "--tomcat_host",
            self.tomcat_host,
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
        "omop_schema_file",
        type=str,
        help="OMOP CDM Schema CSV file",
    )
    parser.add_argument(
        "omop_data_dir", type=str, help="Directory containing csv files"
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
        "--tomcat_host",
        type=str,
        default="localhost",
        help="Host where Tomcat is running under Docker",
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
