#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import logging
import os
import requests
import time

from python_on_whales import DockerClient, DockerException

log = logging.getLogger(__name__)


@dataclass
class Initialiser:
    admin_user: str
    nexus_url: str
    verbose: bool

    def __post_init__(self) -> None:
        self.bin_dir = os.path.dirname(os.path.realpath(__file__))
        self.project_root_dir = os.path.join(self.bin_dir, "..")

        self._docker = None

    @property
    def docker(self) -> DockerClient:
        if self._docker is None:
            compose_files = [
                os.path.join(self.project_root_dir, "docker-compose.yml")
            ]
            self._docker = DockerClient(compose_files=compose_files)

        return self._docker

    def initialise(self) -> None:
        self.get_admin_user_password()
        self.create_proxy_repository(
            "maven-clojars", "https://repo.clojars.org/"
        )
        self.create_proxy_repository(
            "maven-ebi",
            "https://www.ebi.ac.uk/Tools/maven/repos/content/groups/ebi-repo/",
        )
        self.create_proxy_repository(
            "maven-plugins", "https://plugins.gradle.org/m2/"
        )
        self.add_repositories_to_group()

    def get_admin_user_password(self) -> None:
        password_file = "/nexus-data/admin.password"

        timeout_s = 300
        sleep_s = 1

        start_time = time.time()

        while time.time() - start_time < timeout_s:
            try:
                self.admin_user_password = self.docker.compose.execute(
                    "nexus",
                    ["cat", password_file],
                    tty=False,
                )
                log.debug(f"Admin password is {self.admin_user_password}")

                return

            except DockerException:
                time.sleep(sleep_s)
                sleep_s *= 2

        raise TimeoutError("Gave up waiting for the admin password.")

    def create_proxy_repository(self, name: str, url: str) -> None:
        data = {
            "name": name,
            "online": True,
            "storage": {
                "blobStoreName": "default",
                "strictContentTypeValidation": True,
            },
            "proxy": {
                "remoteUrl": url,
                "contentMaxAge": 1440,
                "metadataMaxAge": 1440,
            },
            "negativeCache": {"enabled": True, "timeToLive": 1440},
            "httpClient": {"blocked": False, "autoBlock": True},
            "maven": {"versionPolicy": "RELEASE", "layoutPolicy": "STRICT"},
        }
        response = requests.post(
            f"{self.nexus_url}/service/rest/v1/repositories/maven/proxy",
            json=data,
            auth=(self.admin_user, self.admin_user_password),
        )
        response.raise_for_status()

    def add_repositories_to_group(self) -> None:
        # GET /service/rest/v1/repositories/maven/group/maven-public

        data = {
            "name": "maven-public",
            "online": True,
            "storage": {
                "blobStoreName": "default",
                "strictContentTypeValidation": True,
            },
            "group": {
                "memberNames": [
                    "maven-central",
                    "maven-releases",
                    "maven-snapshots",
                    "maven-clojars",
                    "maven-ebi",
                    "maven-plugins",
                ]
            },
        }

        response = requests.put(
            f"{self.nexus_url}/service/rest/v1/repositories/maven/group/maven-public",  # noqa: E501
            json=data,
            auth=(self.admin_user, self.admin_user_password),
        )
        response.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=("Initialise a Sonatype Nexus Maven repository"),
    )
    parser.add_argument(
        "--admin_user",
        default="admin",
        help="Name of the admin user",
    )
    parser.add_argument(
        "--nexus_url",
        default="http://localhost:8081",
        help="Location of Sonatype Nexus repository",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Be verbose"
    )

    args = parser.parse_args()
    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    initialiser = Initialiser(**vars(args))
    initialiser.initialise()


if __name__ == "__main__":
    main()
