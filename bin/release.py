#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
from datetime import datetime
import glob
import logging
import os
from pathlib import Path
import shutil
from subprocess import run
from typing import Any, Optional

from python_on_whales import DockerClient

log = logging.getLogger(__name__)


@dataclass
class Releaser:
    environment: str
    intermine_dir: str
    verbose: bool

    def __post_init__(self) -> None:
        self.bin_dir = os.path.dirname(os.path.realpath(__file__))
        self.project_root_dir = os.path.join(self.bin_dir, "..")
        self.release_dir = os.path.join(self.project_root_dir, "release")
        self.archive_dir = os.path.join(self.project_root_dir, "archive")
        self.requirements_file = os.path.join(
            self.project_root_dir, "requirements.txt"
        )
        self.python_packages_dir = os.path.join(
            self.release_dir, "python_packages"
        )
        self.war_file = os.path.join(
            self.project_root_dir, "webapp", "build", "libs", "webapp.war"
        )

        self._docker = None

    @property
    def docker(self) -> DockerClient:
        if self._docker is None:
            self._docker = DockerClient()

        return self._docker

    def release(self) -> None:
        self.create_release_directories()
        self.copy_files()
        self.save_docker_images()
        self.download_python_packages()
        self.create_archive()

    def create_release_directories(self) -> None:
        Path(self.release_dir).mkdir(exist_ok=True)
        Path(self.python_packages_dir).mkdir(exist_ok=True)

    def copy_files(self) -> None:
        install_scripts = [
            os.path.join(self.bin_dir, f)
            for f in ["install_boot.py", "install.py"]
        ]

        top_level_files = [
            os.path.join(self.project_root_dir, f)
            for f in ["docker-compose.yml", ".env", "gradle.properties,in", "gradlew", "build.gradle"]
        ]

        all_files = (
            [
                self.war_file,
                self.requirements_file,
            ]
            + install_scripts
            + top_level_files
        )

        for filename in all_files:
            shutil.copy(filename, self.release_dir)

        for top_level_dir in ["postgres", "solr", "tomcat", "gradle"]:
            src_path = os.path.join(self.project_root_dir, top_level_dir)
            dest_path = os.path.join(self.release_dir, top_level_dir)
            shutil.copytree(src_path, dest_path, dirs_exist_ok=True)

        dot_gradle_dir = os.path.join(self.release_dir, ".gradle")
        Path(dot_gradle_dir).mkdir(exist_ok=True)
        init_dot_gradle = os.path.join(self.project_root_dir, "init.gradle")
        shutil.copy(init_dot_gradle, dot_gradle_dir)

    def save_docker_images(self) -> None:
        docker_images_dir = os.path.join(self.release_dir, "docker_images")
        Path(docker_images_dir).mkdir(exist_ok=True)

        images = [
            "intermine/bluegenes:1.4.5-dx",
            "postgres:14",
            "pypiserver/pypiserver:v2.4",
            "sonatype/nexus3:3.89.1",
            "solr:8.11-slim",
            "tomcat:9-jre8-temurin-jammy",
        ]

        self.docker.pull(images)

        for image in images:
            filename = image.split("/")[-1].replace(":", "-")
            path = os.path.join(docker_images_dir, f"{filename}.tar")

            # TODO: Will not save newer images that match the version
            # if already saved
            if not os.path.exists(path):
                self.docker.save(image, path)

    def download_python_packages(self) -> None:
        self.run_with_env(
            [
                "python3",
                "-m",
                "pip",
                "download",
                "-r",
                self.requirements_file,
                "--dest",
                self.python_packages_dir,
            ]
        )

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
        "environment", help="Environment to deploy to e.g. dev, docker"
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
