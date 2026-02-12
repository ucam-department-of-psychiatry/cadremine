#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import logging
import os
from pathlib import Path
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
        self.docker_images_dir = os.path.join(
            self.release_dir, "docker_images"
        )

        self._docker = None

    @property
    def docker(self) -> DockerClient:
        if self._docker is None:
            compose_files = [
                os.path.join(self.release_dir, "docker-compose.yml")
            ]
            self._docker = DockerClient(compose_files=compose_files)

        return self._docker

    def install(self) -> None:
        self.load_docker_images()
        self.make_data_dirs()
        self.start_containers()

    def load_docker_images(self) -> None:
        for filename in Path(self.docker_images_dir).glob("*.tar"):
            self.docker.load(filename)

    def make_data_dirs(self) -> None:
        for data_dir in ["postgres", "solr", "tomcat", "bluegenes_tools"]:
            full_path = os.path.join(self.release_dir, "data", data_dir)
            Path(full_path).mkdir(parents=True, exist_ok=True)

    def start_containers(self) -> None:
        self.docker.compose.up(detach=True)

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
