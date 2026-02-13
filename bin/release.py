#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import glob
import logging
import os
from pathlib import Path
import shutil
from subprocess import run
from typing import Any

from python_on_whales import DockerClient

log = logging.getLogger(__name__)


@dataclass
class Releaser:
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
        self.create_gradle_properties()
        self.create_war_file()
        self.create_release_directories()
        self.copy_files()
        self.save_docker_images()
        self.download_python_packages()
        self.create_archive()

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

    def create_war_file(self) -> None:
        if not Path(self.war_file).exists():
            self.run_gradle([":webapp:war"])

    def run_gradle(self, gradle_args: list[Any]) -> None:
        os.chdir(self.project_root_dir)

        if self.verbose:
            gradle_args.append("--info")

        gradle_args.append("--stacktrace")

        self.run_with_env(["./gradlew"] + gradle_args)

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
            for f in ["docker-compose.yml", ".env"]
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

        for docker_dir in ["postgres", "solr", "tomcat"]:
            src_path = os.path.join(self.project_root_dir, docker_dir)
            dest_path = os.path.join(self.release_dir, docker_dir)
            shutil.copytree(src_path, dest_path, dirs_exist_ok=False)

        dot_gradle_dir = os.path.join(self.release_dir, ".gradle")
        Path(dot_gradle_dir).mkdir(exist_ok=True)
        init_dot_gradle = os.path.join(self.project_root, "init.gradle")
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
        full_prefix = os.path.join(self.archive_dir, "cadremine_full")
        incremental_prefix = os.path.join(
            self.archive_dir, "cadremine_incremental"
        )
        incremental = Path(f"{full_prefix}.1.dar").exists()

        dar_args = ["dar", "-R", self.release_dir, "-z", "-vt"]

        for dir_to_exclude in ["data"]:
            dar_args += [
                "-P",
                dir_to_exclude,
            ]

        prefix = full_prefix
        if incremental:
            dar_args += ["-A", full_prefix]
            prefix = incremental_prefix

        dar_args += ["-c", prefix]

        self.run_with_env(dar_args)

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
