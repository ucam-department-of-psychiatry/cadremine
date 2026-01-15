#!/usr/bin/env python

import argparse
from dataclasses import dataclass
import logging
import os
from subprocess import run
from typing import Any

log = logging.getLogger(__name__)

BIN_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_ROOT_DIR = os.path.join(BIN_DIR, "..")


@dataclass
class Initialiser:
    mine_name: str = "cadremine"
    pg_host: str = "localhost"
    psql_user: str = "postgres"
    psql_pass: str = "postgres"

    def initialise(self) -> None:
        self.initialise_databases()
        self.run_project_build_script()
        self.build_user_db()
        self.build_war_file()

    def initialise_databases(self) -> None:
        log.info("Connect and create Postgres databases")
        self.run_psql(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE pid <> pg_backend_pid();"
        )

        log.info("Database is now available ...")
        log.info("Reset databases and roles")
        self.drop_db(self.mine_name)
        self.drop_db(f"items-{self.mine_name}")
        self.drop_db(f"userprofile-{self.mine_name}")

        log.info("Creating postgres database tables and roles..")
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

    def run_project_build_script(self) -> None:
        os.chdir(PROJECT_ROOT_DIR)
        self.run_with_env(["./project_build", "-b", "localhost", "cadremine"])

    def build_user_db(self) -> None:
        self.run_gradle(["buildUserDB"])

    def build_war_file(self) -> None:
        self.run_gradle([":webapp:war"])

    def run_gradle(self, gradle_args: list[Any]) -> None:
        os.chdir(PROJECT_ROOT_DIR)
        self.run_with_env(["./gradlew"] + gradle_args + ["--stacktrace"])

    def drop_db(self, name: str) -> None:
        self.run_postgres("dropdb", ["--if-exists", name])

    def create_db(self, name: str) -> None:
        self.run_postgres("createdb", [name])

    def run_psql(self, sql: str) -> None:
        self.run_postgres("psql", ["-c", sql])

    def run_postgres(
        self, command: str, postgres_args: list[Any] = None
    ) -> None:
        if postgres_args is None:
            postgres_args = []

        self.run_with_env(
            ["sudo", "-E", "-u", self.psql_user, command, "-h", self.pg_host]
            + postgres_args,
        )

    def run_with_env(self, run_args: list[Any]) -> None:
        env = os.environ.copy()
        env["PGPASSWORD"] = self.psql_pass

        run(run_args, check=True, env=env)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Initialise cadremine",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Be verbose"
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    initialiser = Initialiser()
    initialiser.initialise()


if __name__ == "__main__":
    main()
