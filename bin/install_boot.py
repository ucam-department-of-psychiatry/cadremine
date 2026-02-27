#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import logging
import os
import socket
from subprocess import CompletedProcess, PIPE, Popen, run
import sys
import time
from typing import Any
from venv import EnvBuilder

log = logging.getLogger(__name__)


class BootException(Exception):
    pass


@dataclass
class Booter:
    intermine_dir: str
    recreate_venv: bool
    verbose: bool
    postgres_host_port: int
    pypi_host_port: int
    tomcat_host_port: int
    recreate_databases: bool

    def __post_init__(self) -> None:
        self.bin_dir = os.path.dirname(os.path.realpath(__file__))
        self.project_root_dir = os.path.join(self.bin_dir, "..")
        self.release_dir = os.path.join(self.project_root_dir, "release")
        self.docker_images_dir = os.path.join(
            self.release_dir, "docker_images"
        )
        self.python_packages_dir = os.path.join(
            self.release_dir, "python_packages"
        )
        self.venv_dir = os.path.join(self.release_dir, "venv")
        self.venv_python = os.path.join(self.venv_dir, "bin", "python")

    def boot(self) -> None:
        self.install_local_pypi_server()
        self.run_local_pypi_server()

        if self.recreate_venv or not os.path.exists(self.venv_dir):
            self.create_virtual_environment()
            self.install_requirements()

        self.run_install_script()

    def install_local_pypi_server(self) -> None:
        pypi_tar_file = os.path.join(
            self.docker_images_dir, "pypiserver-v2.4.tar"
        )

        self.run_with_env(["docker", "load", "-i", pypi_tar_file])

    def run_local_pypi_server(self) -> None:
        container_name = "cadre_pypi_server"

        result = self.run_with_env(
            [
                "docker",
                "start",
                container_name,
            ],
            check=False,
        )
        if result.returncode != 0:
            self.run_with_env(
                [
                    "docker",
                    "run",
                    "--name",
                    container_name,
                    "-p",
                    f"{self.pypi_host_port}:8080",
                    "-v",
                    f"{self.python_packages_dir}:/data/packages",
                    "--detach",
                    "pypiserver/pypiserver:v2.4",
                    "run",
                ]
            )
        self.wait_for_port("127.0.0.1", self.pypi_host_port, 60)

    def wait_for_port(
        self, ip_address: str, port: int, timeout_s: float
    ) -> None:
        start_time = time.time()

        while time.time() - start_time < timeout_s:
            try:
                with socket.create_connection((ip_address, port), timeout_s):
                    return

            except OSError:
                time.sleep(1)

        raise TimeoutError("Gave up waiting for port {port} on {ip_address}.")

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
                f"http://localhost:{self.pypi_host_port}",
                "-r",
                f"{self.project_root_dir}/requirements.txt",
            ]
        )

    def run_install_script(self) -> None:
        install_args = [
            self.venv_python,
            f"{self.bin_dir}/install.py",
            self.intermine_dir,
            "--postgres_host_port",
            str(self.postgres_host_port),
            "--tomcat_host_port",
            str(self.tomcat_host_port),
        ]

        if self.recreate_databases:
            install_args.append("--recreate_databases")

        if self.verbose:
            install_args.append("--verbose")

        returned_value = self.run_with_env(install_args, check=False)
        sys.exit(returned_value.returncode)

    def run_with_env(
        self, run_args: list[Any], check=True
    ) -> CompletedProcess[Any]:
        env = os.environ.copy()

        if self.verbose:
            log.info("Running:")
            log.info(run_args)
        return run(run_args, check=check, env=env)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install cadremine",
    )
    parser.add_argument(
        "intermine_dir", help="Top level directory containing Intermine"
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
        "--pypi_host_port",
        type=int,
        default=8080,
        help="Host port to use for the PyPI server",
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

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    booter = Booter(**vars(args))
    booter.boot()


if __name__ == "__main__":
    main()
