#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import glob
import logging
import os
from subprocess import run
from typing import Any

log = logging.getLogger(__name__)

BIN_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_ROOT_DIR = os.path.join(BIN_DIR, "..")


@dataclass
class Builder:
    init_only: bool
    intermine_dir: str
    with_sudo: bool
    mine_name: str = "cadremine"
    pg_host: str = "localhost"
    psql_user: str = "postgres"
    psql_pass: str = "postgres"

    def build(self) -> None:
        self.create_gradle_properties()
        self.build_databases()

        if not self.init_only:
            self.build_user_db()
            self.build_war_file()

    def create_gradle_properties(self) -> None:
        # See also config/lib/install_intermine.py in intermine project
        bin_dir = os.path.dirname(os.path.realpath(__file__))
        root_dir = os.path.join(bin_dir, "..")

        for gradle_properties_in in glob.glob(
            "**/gradle.properties.in", root_dir=root_dir, recursive=True
        ):
            in_file = os.path.join(root_dir, gradle_properties_in)
            out_file = in_file[:-3]
            with open(out_file, "w") as f_out:
                f_out.write(
                    "# FILE AUTOMATICALLY GENERATED FROM "
                    f"{gradle_properties_in}. DO NOT EDIT!\n"
                )
                with open(in_file) as f_in:
                    for line in f_in:
                        f_out.write(
                            line.replace("@@im_checkout@@", self.intermine_dir)
                        )

            print(f"Written {out_file}")

    def build_databases(self) -> None:
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

        args = [command, "-h", self.pg_host]

        if self.with_sudo:
            args = ["sudo", "-E", "-u", self.psql_user] + args

        self.run_with_env(args + postgres_args)

    def run_with_env(self, run_args: list[Any]) -> None:
        env = os.environ.copy()
        env["PGPASSWORD"] = self.psql_pass

        run(run_args, check=True, env=env)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build cadremine",
    )
    parser.add_argument(
        "intermine_dir", help="Top level directory containing Intermine"
    )
    parser.add_argument(
        "--init_only",
        action="store_true",
        help="Initialise only, don't build",
        default=False,
    )
    parser.add_argument(
        "--with_sudo",
        action="store_true",
        help="Use sudo when executing Postgres commands",
        default=False,
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Be verbose"
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    builder = Builder(
        intermine_dir=args.intermine_dir,
        init_only=args.init_only,
        with_sudo=args.with_sudo,
    )
    builder.build()


if __name__ == "__main__":
    main()
