#!/usr/bin/env python

import argparse
import csv
import os
import xml.etree.ElementTree as ET

ROOT_BIN_DIR = os.path.dirname(os.path.realpath(__file__))
PROJECT_ROOT = os.path.join(ROOT_BIN_DIR, "..")
RESOURCES_DIR = os.path.join(PROJECT_ROOT, "dbmodel", "resources")


class OmopTypeException(Exception):
    pass


class Converter:
    def convert(self, csv_file: str) -> None:

        # Write Schema to dbmodel/omop_additions.xml
        classes = ET.Element("classes")
        tree = ET.ElementTree(classes)

        with open(csv_file) as f:
            reader = csv.DictReader(f)
            old_class_name = ""
            im_class = None
            keys = []

            for row in reader:
                class_name = row["cdmTableName"]

                if class_name != old_class_name:
                    im_class = ET.SubElement(classes, "class", name=class_name)

                    if old_class_name:
                        self.write_keys(old_class_name, keys)
                        keys = []

                attribute_name = row["cdmFieldName"].replace('"', "")
                datatype = row["cdmDatatype"].lower()
                im_type = self.get_im_type(
                    class_name, attribute_name, datatype
                )

                ET.SubElement(
                    im_class, "attribute", name=attribute_name, type=im_type
                )

                if row["isPrimaryKey"] == "Yes":
                    keys.append((class_name, attribute_name))

                if row["isForeignKey"] == "Yes":
                    keys.append(
                        (row["fkTableName"], row["fkFieldName"].lower())
                    )

                old_class_name = class_name

        ET.indent(tree)

        xml_filename = os.path.join(RESOURCES_DIR, "omop_additions.xml")
        tree.write(xml_filename, encoding="unicode", xml_declaration=True)

    def write_keys(self, class_name: str, keys: list[str]) -> None:
        filename = os.path.join(RESOURCES_DIR, f"{class_name}_keys.properties")

        unique_keys = list(set(keys))

        with open(filename, "w") as f:
            for table, field in unique_keys:
                f.write(f"{table}.key_primaryidentifer = {field}\n")

    def get_im_type(
        self, class_name: str, attribute_name: str, datatype: str
    ) -> str:
        troublesome_fields = [
            "MEASUREMENT.measurement_date",
            "MEASUREMENT.measurement_datetime",
            "PERSON.birth_datetime",
        ]

        if f"{class_name}.{attribute_name}" in troublesome_fields:
            return "java.lang.String"

        type_map = {
            "bigint": "java.lang.Integer",
            "date": "java.util.Date",
            "datetime": "java.util.Date",
            "float": "float",
            "integer": "java.lang.Integer",
        }

        im_type = type_map.get(datatype)

        if im_type is not None:
            return im_type

        if datatype.startswith("varchar("):
            return "java.lang.String"

        raise OmopTypeException(f"Do not know how to handle type '{datatype}'")


def main() -> None:
    arg_parser = argparse.ArgumentParser(
        description="Convert OMOP schema CSV file to Intermine additions XML",
    )

    arg_parser.add_argument(
        "csv_file",
        type=str,
        help="OMOP CSV file",
    )

    args = arg_parser.parse_args()

    converter = Converter()
    converter.convert(args.csv_file)


if __name__ == "__main__":
    main()
