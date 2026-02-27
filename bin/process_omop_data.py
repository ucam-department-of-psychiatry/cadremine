#!/usr/bin/env python

import argparse
import codecs
import csv
from dataclasses import dataclass, field
import os
import xml.etree.ElementTree as ET


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
    unique_name: str = None


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

    def __eq__(self, other: object):
        if not isinstance(other, Key):
            return False

        if self.class_name != other.class_name:
            return False

        return self.attribute_name == other.attribute_name

    def __hash__(self):
        return hash((self.class_name, self.attribute_name))


@dataclass
class Processor:
    omop_schema_file: str
    data_dir: str

    def __post_init__(self) -> None:
        root_bin_dir = os.path.dirname(os.path.realpath(__file__))
        self.project_root_dir = os.path.join(root_bin_dir, "..")
        self.resources_dir = os.path.join(
            self.project_root_dir, "dbmodel", "resources"
        )
        self.keys: dict(str, Key) = {}
        self.omop_classes: dict[str, OmopClass] = {}
        self.column_dict: dict[str, dict[str, str]] = {}
        self.supported_classes = [
            "Condition",
            "Measurement",
            "Observation",
            "Person",
            "ProcedureOccurrence",
        ]

    def process(self) -> None:
        self.read_schema()
        self.write_additions_xml()
        self.write_all_keys_properties()
        self.write_project_xml()

    def read_schema(self) -> None:
        with open(self.omop_schema_file) as f:
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
                collection.unique_name = f"{prefix}{collection.class_name}"

                unique_names.append(collection.unique_name)

            unique = sorted(list(set(unique_names))) == sorted(unique_names)
            prefix_chars += 1

    def write_all_keys_properties(self) -> None:
        for class_name, keys in self.keys.items():
            self.write_keys_properties(class_name, keys)

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

    def write_project_xml(self) -> None:
        project = ET.Element("project", type="bio")
        ET.SubElement(
            project, "property", name="target.model", value="genomic"
        )
        ET.SubElement(
            project, "property", name="common.os.prefix", value="common"
        )
        sources = ET.SubElement(project, "sources")
        tree = ET.ElementTree(project)

        for basename in os.listdir(self.data_dir):
            filename = os.path.join(self.data_dir, basename)

            if os.path.isfile(filename):
                pieces = os.path.splitext(filename)
                if pieces[1] == ".csv":
                    self.convert_data_csv_file(sources, filename)

        ET.indent(tree)

        xml_filename = os.path.join(self.project_root_dir, "project.xml")
        tree.write(xml_filename, encoding="unicode", xml_declaration=True)

    def convert_data_csv_file(
        self, sources: ET.Element, filename: str
    ) -> None:
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
        ET.SubElement(source, "property", name="src.data.dir", location="data")
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


def main() -> None:
    arg_parser = argparse.ArgumentParser(
        description=(
            "Create Intermine data model files "
            "from OMOP schema and CSV files"
        ),
    )

    arg_parser.add_argument(
        "omop_schema_file",
        type=str,
        help="OMOP CDM Schema CSV file",
    )

    arg_parser.add_argument(
        "data_dir",
        type=str,
        help="Directory containing data CSV files",
    )

    args = arg_parser.parse_args()

    processor = Processor(**vars(args))
    processor.process()


if __name__ == "__main__":
    main()
