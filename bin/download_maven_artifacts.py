#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import glob
import logging
import os
from pathlib import Path
import re
from subprocess import CompletedProcess, PIPE, run
from typing import Any, Generator, IO, TypeAlias

log = logging.getLogger(__name__)

_FILE: TypeAlias = None | int | IO[Any]


@dataclass
class Downloader:
    intermine_dir: str
    nexus_urls: str
    verbose: bool

    def __post_init__(self) -> None:
        self.bin_dir = os.path.dirname(os.path.realpath(__file__))
        self.project_root_dir = os.path.join(self.bin_dir, "..")
        self.release_dir = os.path.join(self.project_root_dir, "release")
        self.artifacts_file = os.path.join(
            self.project_root_dir, "maven_artifacts.txt"
        )
        self.dependencies: list[str] = []

    def download(self) -> None:
        if not os.path.exists(self.artifacts_file):
            self.create_artifact_list()
        self.download_artifacts()

    def create_artifact_list(self) -> None:
        self.find_all_dependencies(self.intermine_dir)
        self.find_all_dependencies(self.project_root_dir)
        self.write_artifact_list()

    def find_all_dependencies(self, project_dir: str) -> None:
        log.info(f"Finding dependencies in {project_dir}")
        for matching_file in glob.glob(
            "**/gradlew",
            root_dir=project_dir,
            recursive=True,
        ):
            gradlew = os.path.join(project_dir, matching_file)
            log.info(f"    Found {gradlew}")
            for project in self.get_projects(gradlew):
                log.info(f"        Found {project}")
                self.find_dependencies(gradlew, project)

    def get_projects(self, gradlew: str) -> Generator[str, None, None]:
        gradlew_dir = Path(gradlew).parent
        os.chdir(gradlew_dir)

        output = self.run_with_env(
            ["./gradlew", "-q", "projects"], stdout=PIPE
        )
        lines = output.stdout.decode("utf-8").splitlines()
        regex = r"^[+\-\\]+ Project '(.+)'$"

        for line in lines:
            log.info(line)
            m = re.match(regex, line)
            if m is not None:
                yield m.group(1)

    def find_dependencies(self, gradlew: str, project: str) -> None:
        gradlew_dir = Path(gradlew).parent
        os.chdir(gradlew_dir)

        output = self.run_with_env(
            ["./gradlew", "-q", f"{project}:dependencies"], stdout=PIPE
        )
        lines = output.stdout.decode("utf-8").splitlines()
        regex = r"^.+ (.+):(.+):(.+?)(?: \(.\))?$"

        for line in lines:
            log.info(line)
            m = re.match(regex, line)
            if m is not None:
                group = m.group(1)
                module = m.group(2)
                version = m.group(3)

                if "->" not in version:
                    self.dependencies.append(f"{group}:{module}:{version}")

    def write_artifact_list(self) -> None:
        unique_dependencies = sorted(set(self.dependencies))

        with open(self.artifacts_file, "w") as f:
            for dependency in unique_dependencies:
                f.write(f"{dependency}\n")

    def download_artifacts(self) -> None:
        failed_artifacts = []

        with open(self.artifacts_file) as f:
            for line in f:
                artifact = line.strip()
                returned_value = self.run_with_env(
                    [
                        "mvn",
                        "dependency:get",
                        f"-DremoteRepositories={self.nexus_urls}",
                        f"-Dartifact={artifact}",
                        "-Dtransitive=true",
                        "-Dos.detected.classifier=linux-x86_64",
                    ],
                    check=False,
                )
                if returned_value.returncode != 0:
                    failed_artifacts.append(artifact)

        if failed_artifacts:
            log.info("Failed to download these artifacts:")

        for artifact in failed_artifacts:
            log.info(artifact)

    def run_with_env(
        self,
        run_args: list[Any],
        stdout: _FILE = None,
        stderr: _FILE = None,
        check: bool = True,
    ) -> CompletedProcess[Any]:
        env = os.environ.copy()

        log.debug("Running:")
        log.debug(run_args)

        return run(
            run_args, stdout=stdout, stderr=stderr, check=check, env=env
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Download artifacts from Maven Central to local repository"
        ),
    )
    parser.add_argument(
        "intermine_dir", help="Top level directory containing Intermine"
    )
    # Typically set this to http://localhost:8081/repository/maven-public and
    # in the Nexus UI, configure proxy repositories as group members of
    # maven-public:
    # https://repo.clojars.org/ (Might not be needed Bluegenes?)
    # https://www.ebi.ac.uk/Tools/maven/repos/content/groups/ebi-repo/
    # https://plugins.gradle.org/m2/
    parser.add_argument(
        "nexus_urls",
        help="Location of Sonatype Nexus repositories, comma separated",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Be verbose"
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    downloader = Downloader(**vars(args))
    downloader.download()


if __name__ == "__main__":
    main()
