#!/usr/bin/env python3

import argparse
import codecs
import csv
from dataclasses import dataclass, field
import glob
import logging
import os
from pathlib import Path
import shutil
import socket
from subprocess import CompletedProcess, PIPE, run
import sys
import time
from typing import Any, IO, TypeAlias
import xml.etree.ElementTree as ET

from python_on_whales import DockerClient

from constants import BLUEGENES_IMAGE

_FILE: TypeAlias = None | int | IO[Any]

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 60
EXIT_FAILURE = -1


class OmopTypeException(Exception):
    pass


@dataclass
class Attribute:
    name: str
    attribute_type: str


@dataclass
class Reference:
    name: str
    referenced_type: str


@dataclass
class Collection:
    attribute_name: str
    referenced_type: str
    class_name: str
    unique_name: str | None = None


@dataclass
class OmopClass:
    name: str
    attributes: list[Attribute] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    collections: list[Collection] = field(default_factory=list)


@dataclass
class Key:
    class_name: str
    attribute_name: str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Key):
            return False

        if self.class_name != other.class_name:
            return False

        return self.attribute_name == other.attribute_name

    def __hash__(self) -> int:
        return hash((self.class_name, self.attribute_name))


@dataclass
class Installer:
    bluegenes_default_service_domain: str
    central_url: str
    clojars_url: str
    docker_images_dir: str
    drop_databases: bool
    ebi_url: str
    gradle_dir: str
    gradle_distribution_url: str
    intermine_dir: str
    nexus_host_port: int
    offline: bool
    offline_url: str
    omop_data_dir: str
    omop_schema_file: str
    plugins_url: str
    postgres_host_port: int
    superuser_account: str
    superuser_initial_password: str
    verbose: bool

    build_environment: str = "dev"
    war_environment: str = "docker"
    major_java_version: int = 1
    minor_java_version: int = 8

    def __post_init__(self) -> None:
        self.bin_dir = os.path.dirname(os.path.realpath(__file__))
        self.project_root_dir = os.path.join(self.bin_dir, "..")
        self.data_dir = os.path.join(self.project_root_dir, "data")
        self.m2_settings_xml = os.path.join(
            self.project_root_dir, "settings.xml"
        )
        self.psql_host = os.getenv("PSQL_HOST", "localhost")
        self.psql_user = os.getenv("PSQL_USER", "postgres")
        self.psql_pass = os.getenv("PSQL_PWD", "postgres")

        self.resources_dir = os.path.join(
            self.project_root_dir, "dbmodel", "resources"
        )
        self.keys: dict[str, list[Key]] = {}
        self.omop_classes: dict[str, OmopClass] = {}
        self.column_dict: dict[str, dict[str, str]] = {}
        self.supported_classes = [
            "ConditionOccurrence",
            "Measurement",
            "Observation",
            "Person",
            "ProcedureOccurrence",
        ]
        self.mine_names = self.read_mine_names()

        self._docker: DockerClient | None = None

    def read_mine_names(self) -> list[str]:
        mines_file = os.path.join(self.project_root_dir, "mines.txt")

        mines = []

        with open(mines_file) as f:
            for mine in f:
                mine = mine.strip()

                if mine and not mine.startswith("#"):
                    mines.append(mine)

        return mines

    @property
    def docker(self) -> DockerClient:
        if self._docker is None:
            compose_files: list[str | Path] = []

            for file_in in glob.glob(
                "docker-compose*.yml",
                root_dir=self.project_root_dir,
                recursive=False,
            ):
                compose_files.append(
                    os.path.join(self.project_root_dir, file_in)
                )

            self._docker = DockerClient(compose_files=compose_files)

        return self._docker

    def install(self) -> None:
        self.set_environment_variables()
        self.check_java_version()
        self.create_docker_compose_files()
        self.load_docker_images()
        self.make_data_dirs()
        self.start_containers()

        self.read_schema()
        self.write_additions_xml()
        self.write_all_keys_properties()

        self.create_gradle_properties()
        self.create_gradle_wrapper_properties()

        if self.offline:
            self.copy_all_gradle_zip()
        self.copy_m2_settings()
        self.install_intermine()

        for mine_name in self.mine_names:
            os.environ["MINE_NAME"] = mine_name
            created = self.build_databases(mine_name)
            self.create_mine_properties(mine_name)
            self.write_project_xml(mine_name)
            if created:
                self.run_gradle(["clean"])
                self.run_gradle(["buildDB"])
                self.run_gradle(["integrate"])
                self.run_gradle(["buildUserDB"])
            self.run_gradle([":webapp:war"])
            self.deploy_war_file(mine_name)
            self.rename_project_xml(mine_name)

    def set_environment_variables(self) -> None:
        os.environ.update(
            MINE_NAMES=" ".join(self.mine_names),
            PSQL_HOST=self.psql_host,
            PSQL_PWD=self.psql_pass,
            PSQL_USER=self.psql_user,
        )

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
                f"Java version is {version_string} and must be "
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

    def create_docker_compose_files(self) -> None:
        docker_compose_template = os.path.join(
            self.project_root_dir, "docker-compose-bluegenes.yml.in"
        )

        bluegenes_host_port = 55000

        for mine_name in self.mine_names:
            docker_compose_file = os.path.join(
                self.project_root_dir, f"docker-compose-{mine_name}.yml"
            )
            if not os.path.exists(docker_compose_file):
                replacement_dict = {
                    "bluegenes_default_service_domain": self.bluegenes_default_service_domain,  # noqa: E501
                    "bluegenes_host_port": bluegenes_host_port,
                    "bluegenes_image": BLUEGENES_IMAGE,
                    "mine_name": mine_name,
                }

                self.search_replace_file(
                    docker_compose_template,
                    docker_compose_file,
                    replacement_dict,
                )

            bluegenes_host_port += 1

    def load_docker_images(self) -> None:
        for filename in Path(self.docker_images_dir).glob("*.tar"):
            self.docker.load(filename)

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

    def start_containers(self) -> None:
        self.docker.compose.up(detach=True)

        self.wait_for_port("127.0.0.1", self.nexus_host_port)

        # Not enough on its own as the container stops and restarts
        self.wait_for_port("127.0.0.1", self.postgres_host_port)

        # https://github.com/docker-library/postgres/issues/146
        self.wait_for_postgres()

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

    def build_databases(self, mine_name: str) -> bool:
        # Terminate idle sessions and free up connections
        self.run_psql(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE pid <> pg_backend_pid();"
        )

        created = any(
            [
                self.build_database(d)
                for d in [
                    mine_name,
                    f"items-{mine_name}",
                    f"userprofile-{mine_name}",
                ]
            ]
        )

        return created

    def build_database(self, database_name: str) -> bool:
        if self.drop_databases or not self.database_exists(database_name):
            self.drop_db(database_name)
            self.create_db(database_name)
            self.run_psql(
                "GRANT ALL PRIVILEGES ON DATABASE "
                f'"{database_name}" to {self.psql_user};'
            )

            return True

        return False

    def database_exists(self, database_name: str) -> bool:
        output = self.run_psql(
            "SELECT 1 FROM pg_catalog.pg_database "
            f"WHERE datname='{database_name}'; ",
            postgres_args=["-XtA"],
            stdout=PIPE,
        )

        lines = output.stdout.decode("utf-8").splitlines()

        return bool(lines) and lines[0] == "1"

    def drop_db(self, name: str) -> None:
        self.run_postgres("dropdb", ["--if-exists", name])

    def create_db(self, name: str) -> None:
        self.run_postgres("createdb", [name])

    def run_psql(
        self,
        sql: str,
        postgres_args: list[Any] | None = None,
        stdout: _FILE = None,
        stderr: _FILE = None,
        check: bool = True,
    ) -> CompletedProcess[Any]:
        if postgres_args is None:
            postgres_args = []

        return self.run_postgres(
            "psql",
            ["-c", sql] + postgres_args,
            stdout=stdout,
            stderr=stderr,
            check=check,
        )

    def run_postgres(
        self,
        command: str,
        postgres_args: list[Any] | None = None,
        stdout: _FILE = None,
        stderr: _FILE = None,
        check: bool = True,
    ) -> CompletedProcess[Any]:
        if postgres_args is None:
            postgres_args = []

        args = [command, "-h", self.psql_host, "-U", self.psql_user]

        return self.run_with_env(
            args + postgres_args, stdout=stdout, stderr=stderr, check=check
        )

    def create_gradle_properties(self) -> None:
        # See also config/lib/install_intermine.py in intermine project
        replacement_dict = {
            "im_checkout": self.intermine_dir,
            "im_build_environment": self.build_environment,
            "im_central_url": self.central_url,
            "im_clojars_url": self.clojars_url,
            "im_ebi_url": self.ebi_url,
            "im_plugins_url": self.plugins_url,
            "im_war_environment": self.war_environment,
        }

        self.replace_all_properties(
            "gradle.properties.in", "gradle.properties", replacement_dict
        )

    def create_gradle_wrapper_properties(self) -> None:
        replacement_dict = {
            "im_gradle_distribution_url": self.gradle_distribution_url,
        }

        self.replace_all_properties(
            "gradle-wrapper.properties.in",
            "gradle-wrapper.properties",
            replacement_dict,
        )

    def create_mine_properties(self, mine_name: str) -> None:
        self.create_mine_build_environment_properties(mine_name)
        self.create_mine_war_environment_properties(mine_name)

    def create_mine_build_environment_properties(self, mine_name: str) -> None:
        replacement_dict = {
            "im_server_name": "localhost",
            "im_mine_name": mine_name,
            "im_mine_title": mine_name.title(),
        }
        self.replace_all_properties(
            "cadremine.properties.in",
            f"{mine_name}-{self.build_environment}.properties",
            replacement_dict,
        )

    def create_mine_war_environment_properties(self, mine_name: str) -> None:
        replacement_dict = {
            "im_server_name": "postgres",
            "im_mine_name": mine_name,
            "im_mine_title": mine_name.title(),
            "im_superuser_account": self.superuser_account,
            "im_superuser_initial_password": self.superuser_initial_password,
        }
        self.replace_all_properties(
            "cadremine.properties.in",
            f"{mine_name}-{self.war_environment}.properties",
            replacement_dict,
        )

    def replace_all_properties(
        self,
        template_in: str,
        filename_out: str,
        replacement_dict: dict[str, Any],
    ) -> None:
        for file_in in glob.glob(
            f"**/{template_in}", root_dir=self.project_root_dir, recursive=True
        ):
            path_in = os.path.join(self.project_root_dir, file_in)
            path_out = path_in.replace(template_in, filename_out)

            self.search_replace_file(path_in, path_out, replacement_dict)

    def search_replace_file(
        self, path_in: str, path_out: str, replacement_dict: dict[str, Any]
    ) -> None:
        with open(path_out, "w") as f_out:
            f_out.write(
                "# FILE AUTOMATICALLY GENERATED FROM "
                f"{path_in}. DO NOT EDIT!\n"
            )
            with open(path_in) as f_in:
                for line in f_in:
                    for key, value in replacement_dict.items():
                        line = line.replace(f"@@{key}@@", str(value))
                    f_out.write(line)

            print(f"Written {path_out}")

    def copy_all_gradle_zip(self) -> None:
        self.copy_gradle_zip(os.path.join(self.project_root_dir))

        project_dirs = [
            "bio",
            "bio/postprocess",
            "bio/postprocess-test",
            "bio/sources",
            "intermine",
            "plugin",
            "testmine",
        ]

        for project_dir in project_dirs:
            self.copy_gradle_zip(os.path.join(self.intermine_dir, project_dir))

    def copy_m2_settings(self) -> None:
        m2_dir = os.path.join(Path.home(), ".m2")
        Path(m2_dir).mkdir(parents=True, exist_ok=True)
        shutil.copy(self.m2_settings_xml, m2_dir)

    def copy_gradle_zip(self, project_dir: str) -> None:
        if not os.path.exists(self.gradle_dir):
            print(f"Directory {self.gradle_dir} does not exist")
            sys.exit(EXIT_FAILURE)

        zip_path = None
        for zip_file in glob.glob(os.path.join(self.gradle_dir, "*.zip")):
            zip_path = os.path.join(self.gradle_dir, zip_file)

        if zip_path is None:
            print(f"Could not find Gradle zip file in {self.gradle_dir}")
            sys.exit(EXIT_FAILURE)

        gradle_wrapper_dir = os.path.join(project_dir, "gradle", "wrapper")

        shutil.copy(zip_path, gradle_wrapper_dir)

    def install_intermine(self) -> None:
        install_args = [
            os.path.join(
                self.intermine_dir,
                "config",
                "lib",
                "install_intermine.py",
            ),
        ]

        if self.offline:
            install_args.append("--offline")

        self.run_with_env(install_args)

    def read_schema(self) -> None:
        with open(self.omop_schema_file, encoding="iso-8859-1") as f:
            reader = csv.DictReader(f)

            for row in reader:
                class_name = self.camelize(row["cdmTableName"])
                cdm_field_name = row["cdmFieldName"].replace('"', "")
                datatype = row["cdmDatatype"].lower()
                foreign_class_name = self.camelize(row["fkTableName"])
                is_primary_key = row["isPrimaryKey"] == "Yes"
                foreign_key_field_name = self.lower_camelize(
                    row["fkFieldName"]
                )

                is_foreign_key = (
                    row["isForeignKey"] == "Yes"
                    and foreign_class_name in self.supported_classes
                )

                omop_class = self.omop_classes.setdefault(
                    class_name, OmopClass(name=class_name)
                )
                attribute_name = self.lower_camelize(cdm_field_name)
                java_type = self.get_java_type(datatype)
                if is_primary_key:
                    self.keys.setdefault(class_name, []).append(
                        Key(
                            class_name=class_name,
                            attribute_name=attribute_name,
                        )
                    )

                if is_foreign_key:
                    self.keys.setdefault(class_name, []).append(
                        Key(
                            class_name=foreign_class_name,
                            attribute_name=foreign_key_field_name,
                        )
                    )
                    omop_class.references.append(
                        Reference(
                            name=attribute_name,
                            referenced_type=foreign_class_name,
                        )
                    )
                    foreign_omop_class = self.omop_classes.setdefault(
                        foreign_class_name, OmopClass(name=foreign_class_name)
                    )
                    foreign_omop_class.collections.append(
                        Collection(
                            attribute_name=attribute_name,
                            class_name=class_name,
                            referenced_type=class_name,
                        )
                    )
                    self.column_dict.setdefault(class_name, {})[
                        cdm_field_name
                    ] = f"{foreign_class_name}.{foreign_key_field_name}"
                else:
                    omop_class.attributes.append(
                        Attribute(
                            name=attribute_name, attribute_type=java_type
                        )
                    )
                    self.column_dict.setdefault(class_name, {})[
                        cdm_field_name
                    ] = f"{class_name}.{attribute_name}"

    def write_additions_xml(self) -> None:
        # Write Schema to dbmodel/omop_additions.xml
        classes_element = ET.Element("classes")
        tree = ET.ElementTree(classes_element)

        for class_name, omop_class in self.omop_classes.items():
            class_element = ET.SubElement(
                classes_element, "class", name=class_name
            )
            class_element.set("is-interface", "true")
            self.write_attributes(class_element, omop_class)
            self.write_references(class_element, omop_class)
            self.write_collections(class_element, omop_class)

        ET.indent(tree)

        xml_filename = os.path.join(self.resources_dir, "omop_additions.xml")
        tree.write(xml_filename, encoding="unicode", xml_declaration=True)

    def write_attributes(
        self, class_element: ET.Element, omop_class: OmopClass
    ) -> None:
        for attribute in omop_class.attributes:
            ET.SubElement(
                class_element,
                "attribute",
                name=attribute.name,
                type=attribute.attribute_type,
            )

    def write_references(
        self, class_element: ET.Element, omop_class: OmopClass
    ) -> None:
        for reference in omop_class.references:
            reference_element = ET.SubElement(
                class_element,
                "reference",
                name=reference.name,
            )

            reference_element.set("referenced-type", reference.referenced_type)

    def write_collections(
        self, class_element: ET.Element, omop_class: OmopClass
    ) -> None:
        self.ensure_collection_names_unique(omop_class)

        for collection in omop_class.collections:
            assert collection.unique_name is not None

            collection_element = ET.SubElement(
                class_element,
                "collection",
                name=self.plural(collection.unique_name),
            )
            collection_element.set(
                "referenced-type", collection.referenced_type
            )

    def ensure_collection_names_unique(self, omop_class: OmopClass) -> None:
        unique = False
        prefix_chars = 0

        while not unique:
            unique_names = []
            for collection in omop_class.collections:
                prefix = collection.attribute_name[:prefix_chars]

                unique_name = f"{prefix}{collection.class_name}"
                collection.unique_name = (
                    unique_name[0].lower() + unique_name[1:]
                )
                unique_names.append(collection.unique_name)

            unique = sorted(list(set(unique_names))) == sorted(unique_names)
            prefix_chars += 1

    def write_all_keys_properties(self) -> None:
        all_keys: list[Key] = []

        for class_name, keys in self.keys.items():
            self.write_keys_properties(class_name, keys)
            all_keys += keys

        self.write_keys_properties("intermine-items-xml-file", all_keys)

    def write_keys_properties(self, class_name: str, keys: list[Key]) -> None:
        filename = os.path.join(
            self.resources_dir, f"{class_name}_keys.properties"
        )

        unique_keys = list(set(keys))
        unique_keys.sort(key=lambda k: k.class_name)

        with open(filename, "w") as f:
            for key in unique_keys:
                class_name = key.class_name
                attribute_name = key.attribute_name
                f.write(
                    f"{class_name}.key_primaryidentifer = {attribute_name}\n"
                )

    def write_project_xml(self, mine_name: str) -> None:
        project = ET.Element("project", type="bio")
        ET.SubElement(
            project, "property", name="target.model", value="genomic"
        )
        ET.SubElement(
            project, "property", name="common.os.prefix", value="common"
        )
        sources = ET.SubElement(project, "sources")
        tree = ET.ElementTree(project)

        mine_data_dir = os.path.join(self.omop_data_dir, mine_name)

        for basename in os.listdir(mine_data_dir):
            filename = os.path.join(mine_data_dir, basename)

            if os.path.isfile(filename):
                pieces = os.path.splitext(filename)
                if pieces[1] == ".csv":
                    self.convert_data_csv_file(sources, filename)
                elif pieces[1] == ".xml":
                    self.convert_data_items_xml_file(sources, filename)

        ET.indent(tree)

        xml_filename = os.path.join(self.project_root_dir, "project.xml")
        tree.write(xml_filename, encoding="unicode", xml_declaration=True)

    def convert_data_csv_file(
        self, sources: ET.Element, filename: str
    ) -> None:
        mine_data_dir = os.path.dirname(filename)
        basename = os.path.basename(filename)

        class_name = self.camelize(os.path.splitext(basename)[0])
        source = ET.SubElement(
            sources, "source", name=class_name, type="delimited"
        )

        ET.SubElement(
            source,
            "property",
            name="delimited.dataSourceName",
            value=class_name,
        )
        title = class_name.replace("_", " ").capitalize()
        ET.SubElement(
            source, "property", name="delimited.dataSetTitle", value=title
        )
        ET.SubElement(
            source, "property", name="delimited.hasHeader", value="true"
        )
        ET.SubElement(
            source, "property", name="delimited.separator", value="comma"
        )
        ET.SubElement(
            source,
            "property",
            name="src.data.dir",
            location=mine_data_dir,
        )
        ET.SubElement(
            source, "property", name="delimited.includes", value=basename
        )

        with codecs.open(filename, encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            headings = next(reader)

            columns = [self.column_dict[class_name][h] for h in headings]
            columns_str = ",".join(columns)
            ET.SubElement(
                source, "property", name="delimited.columns", value=columns_str
            )

    def convert_data_items_xml_file(
        self, sources: ET.Element, filename: str
    ) -> None:
        source = ET.SubElement(
            sources,
            "source",
            type="intermine-items-xml-file",
            name="intermine-items-xml-file",
        )
        ET.SubElement(
            source,
            "property",
            name="src.data.file",
            location=filename,
        )

    def get_java_type(self, datatype: str) -> str:
        type_map = {
            "bigint": "java.lang.Long",
            "date": "java.util.Date",
            "datetime": "java.util.Date",
            "float": "java.lang.Float",
            "integer": "java.lang.Integer",
        }

        java_type = type_map.get(datatype)

        if java_type is not None:
            return java_type

        if datatype.startswith("varchar("):
            return "java.lang.String"

        raise OmopTypeException(f"Do not know how to handle type '{datatype}'")

    def lower_camelize(self, word: str) -> str:
        if not word:
            return word

        camelized = self.camelize(word)
        return camelized[0].lower() + camelized[1:]

    def camelize(self, word: str) -> str:
        return word.replace("_", " ").title().replace(" ", "")

    def plural(self, word: str) -> str:
        return f"{word}s"

    def run_gradle(self, gradle_args: list[Any]) -> None:
        os.chdir(self.project_root_dir)

        if self.verbose:
            gradle_args.append("--info")

        gradle_args += [
            "-Dorg.gradle.jvmargs=-Xmx4g",
            "--max-workers=4",
            "--no-daemon",
            "--stacktrace",
        ]

        self.run_with_env(["./gradlew"] + gradle_args)

    def deploy_war_file(self, mine_name: str) -> None:
        war_file = os.path.join(
            self.project_root_dir, "webapp", "build", "libs", "webapp.war"
        )
        webapps_dir = os.path.join("usr", "local", "tomcat", "webapps")
        dest_path = os.path.join(webapps_dir, f"{mine_name}.war")

        if self.verbose:
            log.info(f"Copying WAR file to {dest_path} on Tomcat server")

        self.docker.copy(war_file, ("intermine_tomcat", dest_path))

    def rename_project_xml(self, mine_name: str) -> None:
        xml_filename = os.path.join(self.project_root_dir, "project.xml")

        os.rename(xml_filename, f"{xml_filename}.{mine_name}")

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

        return run(
            run_args, stdout=stdout, stderr=stderr, check=check, env=env
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Install Intermine for CADRE",
    )
    parser.add_argument(
        "intermine_dir", help="Top level directory containing Intermine"
    )
    parser.add_argument(
        "docker_images_dir",
        help="Directory containing local Docker images e.g. dev Bluegenes",
    )
    parser.add_argument(
        "omop_schema_file",
        type=str,
        help="OMOP CDM Schema CSV file",
    )
    parser.add_argument(
        "omop_data_dir",
        type=str,
        help="Top level directory containing csv files",
    )
    parser.add_argument(
        "bluegenes_default_service_domain",
        type=str,
        help=(
            "Location of the Intermine Tomcat server "
            "as seen from the Bluegenes frontend"
        ),
    )
    parser.add_argument(
        "superuser_account",
        type=str,
        help="Account name for the superuser for all Intermines",
    )
    parser.add_argument(
        "superuser_initial_password",
        type=str,
        help="Initial password for the superuser for all Intermines",
    )
    parser.add_argument(
        "--gradle_dir",
        help="Directory containing Gradle zip (for offline use)",
    )
    parser.add_argument(
        "--nexus_host_port",
        type=int,
        default=8081,
        help="Host port to use for the Sonatype Nexus server",
    )
    parser.add_argument(
        "--postgres_host_port",
        type=int,
        default=5432,
        help="Host port to use for the Postgres server",
    )
    parser.add_argument(
        "--drop_databases",
        action="store_true",
        help="Drop ALL databases",
    )

    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use offline Maven repositories and local Gradle",
    )

    parser.add_argument(
        "--offline_url",
        default="http://localhost:8081/repository/maven-public/",
        help="URL of offline Maven repository",
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

    parser.add_argument(
        "--gradle_distribution_url",
        default="https://services.gradle.org/distributions/gradle-4.9-bin.zip",
        help="URL of Gradle plugins Maven repository",
    )

    args = parser.parse_args()

    if args.offline:
        args.central_url = args.offline_url
        args.clojars_url = args.offline_url
        args.ebi_url = args.offline_url
        args.plugins_url = args.offline_url

        gradle_zip = args.gradle_distribution_url.rsplit("/", 1)[-1]
        args.gradle_distribution_url = gradle_zip

    log_level = logging.DEBUG if args.verbose else logging.INFO

    logging.basicConfig(level=log_level)

    installer = Installer(**vars(args))
    installer.install()


if __name__ == "__main__":
    main()
