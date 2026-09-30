#!/usr/bin/env python3

import argparse
import configparser
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
    config_file: str
    drop_databases: bool
    recreate_venv: bool
    verbose: bool

    pypi_host_port: int = 8080

    def __post_init__(self) -> None:
        self.bin_dir = os.path.dirname(os.path.realpath(__file__))
        self.project_root_dir = os.path.join(self.bin_dir, "..")
        self.venv_dir: str

    def boot(self) -> None:
        self.read_config()
        self.venv_python = os.path.join(self.venv_dir, "bin", "python")
        if self.recreate_venv or not os.path.exists(self.venv_dir):
            self.create_virtual_environment()
            self.install_requirements()

        self.run_install_script()

    def read_config(self) -> None:
        config = configparser.ConfigParser()
        config.read_file(open(self.config_file))

        common = config["common"]

        self.venv_dir = common["venv_dir"]

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
            self.config_file,
        ]

        if self.drop_databases:
            install_args.append("--drop_databases")

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
        description="Install Intermine for CADRE",
    )
    parser.add_argument(
        "config_file",
        help="Configuration file (INI format)",
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
        "--drop_databases",
        action="store_true",
        help="Drop ALL databases",
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    booter = Booter(**vars(args))
    booter.boot()


if __name__ == "__main__":
    main()
