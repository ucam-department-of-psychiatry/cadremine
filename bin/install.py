#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import glob
import logging
import os
from pathlib import Path
import shutil
import socket
from subprocess import CompletedProcess, PIPE, run
import sys
import time
from typing import Any

from python_on_whales import DockerClient

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 60
EXIT_FAILURE = -1


@dataclass
class Installer:
    intermine_dir: str
    postgres_host_port: int
    recreate_databases: bool
    release_dir: str
    tomcat_host_port: int
    verbose: bool

    environment: str = "dev"
    mine_name: str = "cadremine"
    major_java_version: int = 1
    minor_java_version: int = 8

    def __post_init__(self) -> None:
        self.bin_dir = os.path.dirname(os.path.realpath(__file__))
        self.project_root_dir = os.path.join(self.bin_dir, "..")
        self.data_dir = os.path.join(self.project_root_dir, "data")
        self.nexus_data_dir = os.path.join(self.data_dir, "nexus")
        self.gradle_dir = os.path.join(self.release_dir, "gradle")

        self.psql_host = os.getenv("PSQL_HOST", "localhost")
        self.psql_user = os.getenv("PSQL_USER", "postgres")
        self.psql_pass = os.getenv("PSQL_PWD", "postgres")

        self._docker = None

    @property
    def docker(self) -> DockerClient:
        if self._docker is None:
            compose_files = [
                os.path.join(self.project_root_dir, "docker-compose.yml")
            ]
            self._docker = DockerClient(compose_files=compose_files)

        return self._docker

    def install(self) -> None:
        self.check_java_version()
        self.make_data_dirs()
        self.stop_containers()
        self.copy_nexus_data_volume()
        self.start_containers()
        self.build_databases()
        self.create_gradle_properties()
        self.copy_gradle_zip()
        self.install_intermine()
        self.run_gradle(["clean"])
        self.run_gradle(["buildDB"])
        self.run_gradle(["integrate"])
        self.run_gradle(["buildUserDB"])
        self.run_gradle([":webapp:war"])

    def check_java_version(self) -> None:
        java_home = self.get_java_home()
        java_executable = os.path.join(java_home, "bin", "java")
        output = self.run_with_env([java_executable, "-version"], stderr=PIPE)
        lines = output.stderr.decode("utf-8").splitlines()
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

    def get_java_home(self) -> str:
        return self.getenv_or_exit("JAVA_HOME")

    def getenv_or_exit(self, name: str) -> str:
        value = os.getenv(name)
        if value is None:
            print(f"{name} is not defined")
            sys.exit(EXIT_FAILURE)

        return value

    def make_data_dirs(self) -> None:
        for subdir in [
            "postgres",
            "solr",
            "tomcat",
            "bluegenes_tools",
            "nexus",
        ]:
            full_path = os.path.join(self.data_dir, subdir)
            Path(full_path).mkdir(parents=True, exist_ok=True)

    def copy_nexus_data_volume(self) -> None:
        src_dir = os.path.join(self.release_dir, "nexus")

        shutil.copytree(
            src_dir, self.nexus_data_dir, dirs_exist_ok=True
        )

    def start_containers(self) -> None:
        self.docker.compose.up(detach=True)

        self.wait_for_port("127.0.0.1", self.tomcat_host_port)

        # Not enough on its own as the container stops and restarts
        self.wait_for_port("127.0.0.1", self.postgres_host_port)

        # https://github.com/docker-library/postgres/issues/146
        self.wait_for_postgres()

    def stop_containers(self) -> None:
        self.docker.compose.down(volumes=True)

    def wait_for_postgres(self, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        start_time = time.time()

        while time.time() - start_time < timeout_s:
            returned_value = self.run_with_env(
                ["pg_isready", "-h", "127.0.0.1"], check=False
            )
            if returned_value.returncode == 0:
                return

            time.sleep(1)

        raise TimeoutError("Gave up waiting for Postgres container.")

    def build_databases(self) -> None:
        self.run_psql(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE pid <> pg_backend_pid();"
        )

        if not self.recreate_databases:
            return

        self.drop_db(self.mine_name)
        self.drop_db(f"items-{self.mine_name}")
        self.drop_db(f"userprofile-{self.mine_name}")

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

    def drop_db(self, name: str) -> None:
        self.run_postgres("dropdb", ["--if-exists", name])

    def create_db(self, name: str) -> None:
        self.run_postgres("createdb", [name])

    def run_psql(self, sql: str, check: bool = True) -> CompletedProcess[Any]:
        return self.run_postgres("psql", ["-c", sql], check=check)

    def run_postgres(
        self,
        command: str,
        postgres_args: list[Any] = None,
        check: bool = True,
    ) -> CompletedProcess[Any]:
        if postgres_args is None:
            postgres_args = []

        args = [command, "-h", self.psql_host, "-U", self.psql_user]

        return self.run_with_env(args + postgres_args, check=check)

    def create_gradle_properties(self) -> None:
        # See also config/lib/install_intermine.py in intermine project
        replacement_dict = {
            "im_checkout": self.intermine_dir,
            "im_environment": self.environment,
        }

        for gradle_properties_in in glob.glob(
            "**/gradle.properties.in",
            root_dir=self.project_root_dir,
            recursive=True,
        ):
            in_file = os.path.join(self.project_root_dir, gradle_properties_in)
            out_file = in_file[:-3]
            with open(out_file, "w") as f_out:
                f_out.write(
                    "# FILE AUTOMATICALLY GENERATED FROM "
                    f"{gradle_properties_in}. DO NOT EDIT!\n"
                )
                with open(in_file) as f_in:
                    for line in f_in:
                        for key, value in replacement_dict.items():
                            line = line.replace(f"@@{key}@@", value)
                        f_out.write(line)

            print(f"Written {out_file}")

    def copy_gradle_zip(self) -> None:
        gradle_wrapper_dir = os.path.join(
            self.project_root_dir,
            "gradle",
            "wrapper",
        )

        cadremine_gradle_wrapper_properties = os.path.join(
            gradle_wrapper_dir,
            "gradle-wrapper.properties",
        )

        zip_path = None
        for zip_file in glob.glob(os.path.join(self.gradle_dir, "*.zip")):
            zip_path = os.path.join(self.gradle_dir, zip_file)

        if zip_path is None:
            print(f"Could not find Gradle zip file in {self.gradle_dir}")
            sys.exit(EXIT_FAILURE)

        shutil.copy(zip_path, gradle_wrapper_dir)

        for gradle_wrapper_properties in glob.glob(
            "**/gradle-wrapper.properties",
            root_dir=self.intermine_dir,
            recursive=True,
        ):
            properties_file = os.path.join(
                self.intermine_dir, gradle_wrapper_properties
            )
            properties_dir = os.path.dirname(properties_file)
            shutil.copy(cadremine_gradle_wrapper_properties, properties_dir)
            shutil.copy(zip_path, properties_dir)

    def install_intermine(self) -> None:
        os.environ["PSQL_HOST"] = self.psql_host
        os.environ["PSQL_USER"] = self.psql_user
        os.environ["PSQL_PWD"] = self.psql_pass

        self.run_with_env(
            [
                os.path.join(
                    self.intermine_dir, "config", "lib", "install_intermine.py"
                )
            ]
        )

    def run_gradle(self, gradle_args: list[Any]) -> None:
        os.chdir(self.project_root_dir)

        if self.verbose:
            gradle_args.append("--info")

        gradle_args.append("--stacktrace")

        self.run_with_env(["./gradlew"] + gradle_args)

    def deploy_war_file(self) -> None:
        war_file = os.path.join(
            self.project_root_dir, "webapp", "build", "libs", "webapp.war"
        )
        webapps_dir = os.path.join("usr", "local", "tomcat", "webapps")
        dest_path = os.path.join(webapps_dir, f"{self.mine_name}.war")

        if self.verbose:
            log.info(f"Copying WAR file to {dest_path} on Tomcat server")

        self.docker.copy(war_file, ("intermine_tomcat", dest_path))

    def wait_for_port(
        self, ip_address: str, port: int, timeout_s: float = DEFAULT_TIMEOUT_S
    ) -> None:
        start_time = time.time()

        while time.time() - start_time < timeout_s:
            try:
                with socket.create_connection((ip_address, port), timeout_s):
                    return

            except OSError:
                time.sleep(1)

        raise TimeoutError("Gave up waiting for port {port} on {ip_address}.")

    def run_with_env(
        self, run_args: list[Any], stdout=None, stderr=None, check: bool = True
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
        description="Install cadremine",
    )
    parser.add_argument(
        "intermine_dir", help="Top level directory containing Intermine"
    )
    parser.add_argument(
        "release_dir",
        help="Top level directory containing files outside of version control",
    )
    parser.add_argument(
        "--postgres_host_port",
        type=int,
        default=5432,
        help="Host port to use for the Postgres server",
    )
    parser.add_argument(
        "--tomcat_host_port",
        type=int,
        default=9999,
        help="Host port to use for the Tomcat server",
    )
    parser.add_argument(
        "--recreate_databases",
        action="store_true",
        help="Recreate databases",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Be verbose"
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    installer = Installer(**vars(args))
    installer.install()


if __name__ == "__main__":
    main()
