#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import socket
from subprocess import run
import time
from typing import Any

from python_on_whales import DockerClient

log = logging.getLogger(__name__)


@dataclass
class Installer:
    verbose: bool
    tomcat_host_port: int

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

        self.wait_for_port("127.0.0.1", self.tomcat_host_port, 60)

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
        "--tomcat_host_port",
        type=int,
        default=9999,
        help="Host port to use for the Tomcat server",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Be verbose"
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    installer = Installer(**vars(args))
    installer.install()


if __name__ == "__main__":
    main()
