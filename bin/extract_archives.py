#!/usr/bin/env python3
import argparse
from dataclasses import dataclass
import logging
import os
from pathlib import Path
from subprocess import CompletedProcess, run
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class Extractor:
    archive_dir: str
    release_dir: str
    verbose: bool

    def extract(self):
        Path(self.release_dir).mkdir(exist_ok=True)
        archives = sorted(os.listdir(self.archive_dir))

        for archive in archives:
            # strip .1.dar
            prefix = archive[:-6]

            full_path = os.path.join(self.archive_dir, prefix)
            dar_args = [
                "dar",
                "-x",
                full_path,
                "-R",
                self.release_dir,
                "-w",
            ]
            self.run_with_env(dar_args)

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
        description="Extract DAR archives for cadremine",
    )
    parser.add_argument("archive_dir", help="Directory containing archives")
    parser.add_argument("release_dir", help="Directory containing release")

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Be verbose"
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    extractor = Extractor(**vars(args))
    extractor.extract()


if __name__ == "__main__":
    main()
