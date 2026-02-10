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
class Releaser:
    intermine_dir: str
    verbose: bool
    mine_name: str = "cadremine"

    def release(self) -> None:
        self.create_gradle_properties()
        self.run_gradle([":webapp:war"])

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

    def run_gradle(self, gradle_args: list[Any]) -> None:
        os.chdir(PROJECT_ROOT_DIR)

        if self.verbose:
            gradle_args.append("--info")

        gradle_args.append("--stacktrace")

        self.run_with_env(["./gradlew"] + gradle_args)

    def run_with_env(self, run_args: list[Any]) -> None:
        env = os.environ.copy()

        if self.verbose:
            log.info("Running:")
            log.info(run_args)
        run(run_args, check=True, env=env)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Release cadremine",
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
        "--verbose", "-v", action="store_true", help="Be verbose"
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    releaser_args = dict(
        intermine_dir=args.intermine_dir,
        verbose=args.verbose,
    )

    releaser = Releaser(**releaser_args)
    releaser.release()


if __name__ == "__main__":
    main()
