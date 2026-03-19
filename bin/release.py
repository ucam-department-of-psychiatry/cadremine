#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
import shutil
from subprocess import CompletedProcess, PIPE, run
from typing import Any, IO, Optional, TypeAlias
import urllib.request

from python_on_whales import DockerClient

_FILE: TypeAlias = None | int | IO[Any]

log = logging.getLogger(__name__)


@dataclass
class Releaser:
    bluegenes_dir: str
    intermine_dir: str
    verbose: bool

    # TODO: Sync with docker-compose.yml
    bluegenes_version: str = "intermine/bluegenes:1.4.6-rc2"
    bundle_tag: str = "last_release_bundle"
    cadremine_git_branch: str = "main"
    gradle_zip_url: str = (
        "https://services.gradle.org/distributions/gradle-4.9-bin.zip"
    )
    intermine_git_branch: str = "eclipse-setup"

    def __post_init__(self) -> None:
        self.bin_dir = os.path.dirname(os.path.realpath(__file__))
        self.project_root_dir = os.path.join(self.bin_dir, "..")
        self.release_dir = os.path.join(self.project_root_dir, "release")
        self.archive_dir = os.path.join(self.project_root_dir, "archive")
        self.data_dir = os.path.join(self.project_root_dir, "data")
        self.nexus_data_dir = os.path.join(self.data_dir, "nexus")
        self.base_requirements_file = os.path.join(
            self.project_root_dir, "base_requirements.txt"
        )
        self.requirements_file = os.path.join(
            self.project_root_dir, "requirements.txt"
        )
        self.gradle_release_dir = os.path.join(self.release_dir, "gradle")
        self.nexus_release_dir = os.path.join(self.release_dir, "nexus")

        self._docker = None

    @property
    def docker(self) -> DockerClient:
        if self._docker is None:
            self._docker = DockerClient()

        return self._docker

    def release(self) -> None:
        self.create_release_directories()
        self.download_gradle_zip()
        self.copy_nexus_data_volume()
        self.create_bluegenes_image()
        self.create_intermine_bundle()
        self.create_cadremine_bundle()
        self.create_archive()

    def create_release_directories(self) -> None:
        Path(self.data_dir).mkdir(exist_ok=True)

        Path(self.release_dir).mkdir(exist_ok=True)
        Path(self.gradle_release_dir).mkdir(exist_ok=True)
        Path(self.nexus_release_dir).mkdir(exist_ok=True)

    def create_intermine_bundle(self) -> None:
        self.create_git_bundle(
            self.intermine_dir, "intermine", self.intermine_git_branch
        )

    def create_cadremine_bundle(self) -> None:
        self.create_git_bundle(
            self.project_root_dir, "cadremine", self.cadremine_git_branch
        )

    def create_git_bundle(
        self, project_dir: str, name: str, branch: str
    ) -> None:
        filename = os.path.join(self.release_dir, f"{name}.bundle")
        if not os.path.exists(filename):
            ref = branch
        else:
            if not self.repository_has_changed(project_dir, branch):
                print(f"Repository {name} has not changed")
                return

            ref = f"{self.bundle_tag}..{branch}"

        os.chdir(project_dir)

        self.run_with_env(["git", "bundle", "create", filename, ref])
        self.run_with_env(["git", "tag", "-f", self.bundle_tag, branch])

    def repository_has_changed(self, project_dir: str, branch: str) -> bool:
        os.chdir(project_dir)
        tag_commit = self.get_git_commit_id(self.bundle_tag)
        branch_commit = self.get_git_commit_id(branch)

        return tag_commit != branch_commit

    def get_git_commit_id(self, ref: str) -> str:
        return self.run_with_env(
            ["git", "rev-parse", "--verify", ref], stdout=PIPE
        ).stdout.decode("utf-8")

    def download_gradle_zip(self) -> None:
        zip_file = self.gradle_zip_url.rsplit("/", 1)[-1]
        path = os.path.join(self.gradle_release_dir, zip_file)
        if not os.path.exists(path):
            urllib.request.urlretrieve(self.gradle_zip_url, path)

    def copy_nexus_data_volume(self) -> None:
        shutil.copytree(
            self.nexus_data_dir,
            self.nexus_release_dir,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".userPrefs"),
        )

    def create_bluegenes_image(self) -> None:
        docker_images_dir = os.path.join(self.release_dir, "docker_images")
        Path(docker_images_dir).mkdir(exist_ok=True)

        image = self.bluegenes_version
        filename = image.split("/")[-1].replace(":", "-")
        path = os.path.join(docker_images_dir, f"{filename}.tar")

        # TODO: Will not save newer images that match the version
        # if already saved
        if not os.path.exists(path):
            os.chdir(self.bluegenes_dir)
            self.run_with_env(["lein", "uberjar"])
            self.docker.build(self.bluegenes_dir, tags=self.bluegenes_version)
            self.docker.save(image, path)

    def create_archive(self) -> None:
        Path(self.archive_dir).mkdir(exist_ok=True)
        current_prefix, previous_prefix = (
            self.get_current_and_previous_archives()
        )

        previous_args = []
        if previous_prefix:
            log.info(f"Creating incremental archive from {previous_prefix}")
            previous_args = ["-A", previous_prefix]
        else:
            log.info("Creating full archive")

        dar_args = (
            [
                "dar",
                "-c",
                current_prefix,
                "-z",
                "-vt",
                "-w",
            ]
            + previous_args
            + [
                "-R",
                self.release_dir,
            ]
        )

        for dir_to_exclude in ["data"]:
            dar_args += [
                "-P",
                dir_to_exclude,
            ]

        self.run_with_env(dar_args)

    def get_current_and_previous_archives(self) -> tuple[str, Optional[str]]:
        full_prefix = os.path.join(self.archive_dir, "cadremine_full")
        # full comes alphabetically before incremental
        archives = sorted(os.listdir(self.archive_dir))

        if len(archives) == 0:
            return full_prefix, None

        most_recent = archives[-1]
        # strip .1.dar
        most_recent_prefix = most_recent[:-6]
        previous_prefix = os.path.join(self.archive_dir, most_recent_prefix)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        incremental_prefix = os.path.join(
            self.archive_dir, f"cadremine_incremental_{timestamp}"
        )
        return incremental_prefix, previous_prefix

    def run_with_env(
        self,
        run_args: list[Any],
        stdout: _FILE = None,
        stderr: _FILE = None,
    ) -> CompletedProcess[bytes]:
        env = os.environ.copy()

        if self.verbose:
            log.info("Running:")
            log.info(run_args)

        return run(run_args, check=True, env=env, stdout=stdout, stderr=stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Release cadremine",
    )
    parser.add_argument(
        "intermine_dir", help="Top level directory containing Intermine"
    )
    parser.add_argument(
        "bluegenes_dir", help="Top level directory containing Bluegenes"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Be verbose"
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    releaser = Releaser(**vars(args))
    releaser.release()


if __name__ == "__main__":
    main()
