#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
from subprocess import CompletedProcess, run
from typing import Any, IO, TypeAlias

_FILE: TypeAlias = None | int | IO[Any]

log = logging.getLogger(__name__)


@dataclass
class Backup:
    backup_dir: str
    postgres_host_port: int
    verbose: bool

    def __post_init__(self) -> None:
        self.psql_host = os.getenv("PSQL_HOST", "localhost")
        self.psql_user = os.getenv("PSQL_USER", "postgres")
        self.psql_pass = os.getenv("PSQL_PWD", "postgres")

    def backup(self) -> None:
        self.ensure_backup_dir_exists()

        databases = [
            "cadremine",
            "items-cadremine",
            "items-mine",
            "mine",
            "userprofile-cadremine",
            "userprofile-mine",
        ]

        for database in databases:
            self.backup_database(database)

    def ensure_backup_dir_exists(self) -> None:
        Path(self.backup_dir).mkdir(parents=True, exist_ok=True)

    def backup_database(self, name: str) -> None:
        log.debug(f"Backing up '{name}'")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(self.backup_dir, f"{name}_{timestamp}.sql.gz")

        with open(filename, "w") as backup:
            self.run_with_env(
                [
                    "pg_dump",
                    "-h",
                    self.psql_host,
                    "-U",
                    self.psql_user,
                    "-d",
                    name,
                    "--compress=9",
                    "-c",  # DROP tables when restoring
                    "-O",  # No owner
                ],
                stdout=backup,
            )

    def run_with_env(
        self,
        run_args: list[Any],
        stdout: _FILE = None,
        stderr: _FILE = None,
        check: bool = True,
    ) -> CompletedProcess[Any]:
        env = os.environ.copy()

        if self.verbose:
            log.info("Running:")
            log.info(run_args)

            for k in sorted(env.keys()):
                v = env[k]
                log.info(f"{k}={v}")

        return run(
            run_args, stdout=stdout, stderr=stderr, check=check, env=env
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backup cadremine",
    )
    parser.add_argument(
        "backup_dir", help="Top level directory containing backups"
    )
    parser.add_argument(
        "--postgres_host_port",
        type=int,
        default=5432,
        help="Host port to use for the Postgres server",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Be verbose"
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    backup = Backup(**vars(args))
    backup.backup()


if __name__ == "__main__":
    main()
