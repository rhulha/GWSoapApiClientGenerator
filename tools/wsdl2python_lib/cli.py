from __future__ import annotations

import argparse
from pathlib import Path

from .emitter import PythonEmitter, write_readme
from wsdl2java_lib.model import GroupWiseSchemaModel


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Python sources for the GroupWise WSDL set")
    parser.add_argument("--wsdl", default="wsdl/groupwise.wsdl", help="Path to the root GroupWise WSDL file")
    parser.add_argument("--output", default="generated/groupwise-python-client", help="Output directory for the generated Python package")
    args = parser.parse_args()

    wsdl_path = Path(args.wsdl).resolve()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    model = GroupWiseSchemaModel(wsdl_path, "com.novell.groupwise")
    model.load()

    emitter = PythonEmitter(model, output_dir)
    emitter.emit()
    write_readme(output_dir / "README.md")

    print(f"Generated Python package at {output_dir}")
