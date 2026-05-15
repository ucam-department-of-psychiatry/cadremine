#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import glob
import logging
import os
from subprocess import CompletedProcess, PIPE, run
import sys
from typing import Any, IO, TypeAlias

log = logging.getLogger(__name__)

_FILE: TypeAlias = None | int | IO[Any]

EXIT_FAILURE = -1


@dataclass
class Builder:
    central_url: str
    clojars_url: str
    ebi_url: str
    init_only: bool
    intermine_dir: str
    gradle_distribution_url: str
    plugins_url: str
    verbose: bool
    with_sudo: bool
    build_environment: str = "dev"
    mine_name: str = "cadremine"
    major_java_version: int = 1
    minor_java_version: int = 8
    war_environment: str = "dev"

    def __post_init__(self) -> None:
        self.psql_host = os.getenv("PSQL_HOST", "localhost")
        self.psql_user = os.getenv("PSQL_USER", "postgres")
        self.psql_pass = os.getenv("PSQL_PWD", "postgres")

    def build(self) -> None:
        self.bin_dir = os.path.dirname(os.path.realpath(__file__))
        self.project_root_dir = os.path.join(self.bin_dir, "..")

        self.check_java_version()
        self.create_gradle_properties()
        self.create_gradle_wrapper_properties()
        self.build_databases()

        if not self.init_only:
            self.run_gradle(["clean"])
            self.run_gradle(["buildDB"])
            self.run_gradle(["integrate"])
            self.run_gradle(["buildUserDB"])
            self.run_gradle([":webapp:war"])

    def check_java_version(self) -> None:
        output = self.run_with_env(
            ["java", "-version"], stderr=PIPE
        ).stderr.decode("utf-8")

        lines = output.splitlines()
        version_elements = lines[0].split()
        version_string = version_elements[2].replace('"', "")
        version_number_elements = version_string.split(".")

        major_version = int(version_number_elements[0])
        minor_version = int(version_number_elements[1])

        if (
            major_version != self.major_java_version
            and minor_version != self.minor_java_version
        ):
            print(major_version, minor_version)
            print(
                f"Java version is {version_string} and must be"
                f"{self.major_java_version}.{self.minor_java_version}"
            )
            sys.exit(EXIT_FAILURE)

    def create_gradle_wrapper_properties(self) -> None:
        replacement_dict = {
            "im_gradle_distribution_url": self.gradle_distribution_url,
        }

        self.create_properties("gradle-wrapper.properties", replacement_dict)

    def create_gradle_properties(self) -> None:
        # See also config/lib/install_intermine.py in intermine project
        replacement_dict = {
            "im_build_environment": self.build_environment,
            "im_checkout": self.intermine_dir,
            "im_central_url": self.central_url,
            "im_clojars_url": self.clojars_url,
            "im_ebi_url": self.ebi_url,
            "im_plugins_url": self.plugins_url,
            "im_war_environment": self.war_environment,
        }
        self.create_properties("gradle.properties", replacement_dict)

    def create_properties(
        self, filename: str, replacement_dict: dict[str, Any]
    ) -> None:
        for gradle_properties_in in glob.glob(
            f"**/{filename}.in",
            root_dir=self.project_root_dir,
            recursive=True,
        ):
            path_in = os.path.join(self.project_root_dir, gradle_properties_in)
            path_out = path_in[:-3]
            with open(path_out, "w") as f_out:
                f_out.write(
                    "# FILE AUTOMATICALLY GENERATED FROM "
                    f"{gradle_properties_in}. DO NOT EDIT!\n"
                )
                with open(path_in) as f_in:
                    for line in f_in:
                        for key, value in replacement_dict.items():
                            line = line.replace(f"@@{key}@@", value)
                        f_out.write(line)

            print(f"Written {path_out}")

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

    def run_gradle(self, gradle_args: list[Any]) -> None:
        os.chdir(self.project_root_dir)

        if self.verbose:
            gradle_args.append("--info")

        gradle_args.append("--stacktrace")

        self.run_with_env(["./gradlew"] + gradle_args)

    def drop_db(self, name: str) -> None:
        self.run_postgres("dropdb", ["--if-exists", name])

    def create_db(self, name: str) -> None:
        self.run_postgres("createdb", [name])

    def run_psql(self, sql: str) -> None:
        self.run_postgres("psql", ["-c", sql])

    def run_postgres(
        self, command: str, postgres_args: list[Any] | None = None
    ) -> None:
        if postgres_args is None:
            postgres_args = []

        args = [command, "-h", self.psql_host]

        if self.with_sudo:
            args = ["sudo", "-E", "-u", self.psql_user] + args

        self.run_with_env(args + postgres_args)

    def run_with_env(
        self,
        run_args: list[Any],
        stdout: _FILE = None,
        stderr: _FILE = None,
    ) -> CompletedProcess[Any]:
        env = os.environ.copy()
        env["PGPASSWORD"] = self.psql_pass

        if self.verbose:
            log.info("Running:")
            log.info(run_args)
        return run(run_args, check=True, env=env, stdout=stdout, stderr=stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build CADRE",
    )
    parser.add_argument(
        "intermine_dir", help="Top level directory containing Intermine"
    )
    parser.add_argument(
        "--gradle_distribution_url",
        default="https://services.gradle.org/distributions/gradle-4.9-bin.zip",
        help="URL of Gradle plugins Maven repository",
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
        "--central_url",
        default="https://repo1.maven.org/maven2/",
        help="URL of Maven Central repository",
    )

    parser.add_argument(
        "--clojars_url",
        default="https://clojars.org/repo",
        help="URL of Clojars Maven repository",
    )

    parser.add_argument(
        "--ebi_url",
        default=(
            "https://www.ebi.ac.uk/Tools/maven/repos/content/groups/ebi-repo/"
        ),
        help="URL of EMBL-EBI Maven repository",
    )

    parser.add_argument(
        "--plugins_url",
        default="https://plugins.gradle.org/m2/",
        help="URL of Gradle plugins Maven repository",
    )

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Be verbose"
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    builder = Builder(**vars(args))
    builder.build()


if __name__ == "__main__":
    main()
