#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import logging
import os
from subprocess import run
from typing import Any

from python_on_whales import DockerClient

log = logging.getLogger(__name__)


@dataclass
class Installer:
    verbose: bool
    mine_name: str = "cadremine"

    def __post_init__(self) -> None:
        self.release_dir = os.path.dirname(os.path.realpath(__file__))
        self._docker = None

    @property
    def docker(self) -> DockerClient:
        if self._docker is None:
            self._docker = DockerClient()

        return self._docker

    def install(self) -> None:
        self.setup_docker_registry()

    def setup_docker_registry(self) -> None:
        pass

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
        "--verbose", "-v", action="store_true", help="Be verbose"
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    installer_args = dict(
        verbose=args.verbose,
    )

    installer = Installer(**installer_args)
    installer.install()


if __name__ == "__main__":
    main()
