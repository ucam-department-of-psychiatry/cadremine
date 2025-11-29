#!/usr/bin/env python

import argparse
import codecs
import csv
import os
import sys
import xml.etree.ElementTree as ET


class Converter:
    def convert(self, data_dir: str) -> None:
        sources = ET.Element("sources")
        tree = ET.ElementTree(sources)

        for basename in os.listdir(data_dir):
            filename = os.path.join(data_dir, basename)

            if os.path.isfile(filename):
                pieces = os.path.splitext(filename)
                if pieces[1] == ".csv":
                    self.convert_csv_file(sources, filename)

        ET.indent(tree)

        tree.write(sys.stdout, encoding="unicode")

    def convert_csv_file(self, sources: ET.Element, filename: str) -> None:
        basename = os.path.basename(filename)
        class_name = os.path.splitext(basename)[0]
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

            upper_class_name = class_name.upper()
            columns = [f"{upper_class_name}.{h}" for h in headings]
            columns_str = ",".join(columns)
            ET.SubElement(
                source, "property", name="delimited.columns", value=columns_str
            )


def main() -> None:
    arg_parser = argparse.ArgumentParser(
        description="Convert OMOP data CSV files to Intermine project XML",
    )

    arg_parser.add_argument(
        "data_dir",
        type=str,
        help="Directory containing CSV files",
    )

    args = arg_parser.parse_args()

    converter = Converter()
    converter.convert(args.data_dir)


if __name__ == "__main__":
    main()
