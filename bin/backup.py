#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
from subprocess import CompletedProcess, run
import time
from typing import Any, IO, TypeAlias

_FILE: TypeAlias = None | int | IO[Any]

log = logging.getLogger(__name__)


@dataclass
class Backup:
    backup_dir: str
    days_to_keep: int
    dry_run: bool
    postgres_host_port: int
    verbose: bool

    def __post_init__(self) -> None:
        self.psql_host = os.getenv("PSQL_HOST", "localhost")
        self.psql_user = os.getenv("PSQL_USER", "postgres")
        self.psql_pass = os.getenv("PSQL_PWD", "postgres")
        current_time = time.time()
        seconds_per_day = 60 * 60 * 24
        self.delete_before_time = (
            current_time - self.days_to_keep * seconds_per_day
        )

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

        self.remove_old_backups()

    def ensure_backup_dir_exists(self) -> None:
        Path(self.backup_dir).mkdir(parents=True, exist_ok=True)

    def backup_database(self, database_name: str) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(
            self.backup_dir, f"{database_name}_{timestamp}.sql.gz"
        )

        if self.dry_run:
            log.info(f"Would backup '{database_name}' to {filename}")
        else:
            self.write_to_file(database_name, filename)

    def write_to_file(self, database_name: str, filename: str) -> None:
        log.debug(f"Backing up '{database_name}' to '{filename}'...")

        with open(filename, "w") as backup:
            self.run_with_env(
                [
                    "pg_dump",
                    "-h",
                    self.psql_host,
                    "-U",
                    self.psql_user,
                    "-d",
                    database_name,
                    "--compress=9",
                    "-c",  # DROP tables when restoring
                    "-O",  # No owner
                ],
                stdout=backup,
            )

    def remove_old_backups(self) -> None:
        backups = os.listdir(self.backup_dir)

        for backup in backups:
            full_path = os.path.join(self.backup_dir, backup)
            if self.should_delete(full_path):
                if self.dry_run:
                    log.info(f"Would remove {full_path}")
                else:
                    log.debug(f"Removing {full_path}...")
                    os.remove(full_path)

    def should_delete(self, full_path: str) -> bool:
        filename_matches = full_path.endswith(".sql.gz")
        file_time = os.stat(full_path).st_mtime
        old_enough = file_time < self.delete_before_time

        if filename_matches and old_enough:
            return True

        log.debug(f"Skipping {full_path}")

        return False

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
        "--days_to_keep",
        type=int,
        default=30,
        help="Number of days to keep backups",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Don't create or delete anything",
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
