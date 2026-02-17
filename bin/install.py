#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import socket
from subprocess import CompletedProcess, run
import time
from typing import Any

from python_on_whales import DockerClient

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 60


@dataclass
class Installer:
    verbose: bool
    postgres_host_port: int
    tomcat_host_port: int
    recreate_databases: bool

    def __post_init__(self) -> None:
        self.mine_name = "cadremine"
        self.release_dir = os.path.dirname(os.path.realpath(__file__))
        self.docker_images_dir = os.path.join(
            self.release_dir, "docker_images"
        )
        self.pg_host = "localhost"
        self.psql_user = "postgres"

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
        self.build_databases()
        self.deploy_war_file()

    def load_docker_images(self) -> None:
        for filename in Path(self.docker_images_dir).glob("*.tar"):
            self.docker.load(filename)

    def make_data_dirs(self) -> None:
        for data_dir in [
            "postgres",
            "solr",
            "tomcat",
            "bluegenes_tools",
            "nexus",
        ]:
            full_path = os.path.join(self.release_dir, "data", data_dir)
            Path(full_path).mkdir(parents=True, exist_ok=True)

    def start_containers(self) -> None:
        self.docker.compose.up(detach=True)

        self.wait_for_port("127.0.0.1", self.tomcat_host_port)

        # Not enough on its own as the container stops and restarts
        self.wait_for_port("127.0.0.1", self.postgres_host_port)

        # https://github.com/docker-library/postgres/issues/146
        self.wait_for_postgres()

    def wait_for_postgres(self, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        start_time = time.time()

        while time.time() - start_time < timeout_s:
            returned_value = self.run_psql("SELECT 1", check=False)
            if returned_value.returncode == 0:
                return

            time.sleep(1)

        raise TimeoutError("Gave up waiting for Postgres container.")

    def build_databases(self) -> None:
        self.run_psql(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE pid <> pg_backend_pid();"
        )

        if not self.recreate_databases:
            return

        self.drop_db(self.mine_name)
        self.drop_db(f"items-{self.mine_name}")
        self.drop_db(f"userprofile-{self.mine_name}")

        self.create_db(self.mine_name)
        self.create_db(f"items-{self.mine_name}")
        self.create_db(f"userprofile-{self.mine_name}")

        self.run_psql(
            f'GRANT ALL PRIVILEGES ON DATABASE "{self.mine_name}" to '
            f"{self.psql_user};"
        )
        self.run_psql(
            f'GRANT ALL PRIVILEGES ON DATABASE "items-{self.mine_name}" to '
            f"{self.psql_user};"
        )
        self.run_psql(
            "GRANT ALL PRIVILEGES ON DATABASE "
            f'"userprofile-{self.mine_name}" to {self.psql_user};'
        )

    def drop_db(self, name: str) -> None:
        self.run_postgres("dropdb", ["--if-exists", name])

    def create_db(self, name: str) -> None:
        self.run_postgres("createdb", [name])

    def run_psql(self, sql: str, check: bool = True) -> CompletedProcess[Any]:
        return self.run_postgres("psql", ["-c", sql], check=check)

    def run_postgres(
        self,
        command: str,
        postgres_args: list[Any] = None,
        check: bool = True,
    ) -> CompletedProcess[Any]:
        if postgres_args is None:
            postgres_args = []

        args = [command, "-h", self.pg_host, "-U", self.psql_user]

        return self.run_with_env(args + postgres_args, check=check)

    def deploy_war_file(self) -> None:
        war_file = os.path.join(self.release_dir, "webapp.war")
        webapps_dir = os.path.join("usr", "local", "tomcat", "webapps")
        dest_path = os.path.join(webapps_dir, f"{self.mine_name}.war")

        if self.verbose:
            log.info(f"Copying WAR file to {dest_path} on Tomcat server")

        self.docker.copy(war_file, ("intermine_tomcat", dest_path))

    def wait_for_port(
        self, ip_address: str, port: int, timeout_s: float = DEFAULT_TIMEOUT_S
    ) -> None:
        start_time = time.time()

        while time.time() - start_time < timeout_s:
            try:
                with socket.create_connection((ip_address, port), timeout_s):
                    return

            except OSError:
                time.sleep(1)

        raise TimeoutError("Gave up waiting for port {port} on {ip_address}.")

    def run_with_env(
        self, run_args: list[Any], check: bool = True
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
        type=bool,
        default=False,
        help="Recreate databases",
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
