from __future__ import annotations

import argparse
from pathlib import Path

from .emitter import JavaEmitter, write_readme
from .model import GroupWiseSchemaModel


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Java 14 sources for the GroupWise WSDL set")
    parser.add_argument("--wsdl", default="wsdl/groupwise.wsdl", help="Path to the root GroupWise WSDL file")
    parser.add_argument("--output", default="generated/groupwise-java14-client", help="Output directory for the generated Gradle project")
    parser.add_argument("--base-package", default="com.novell.groupwise", help="Base Java package")
    args = parser.parse_args()

    wsdl_path = Path(args.wsdl).resolve()
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    model = GroupWiseSchemaModel(wsdl_path, args.base_package)
    model.load()

    emitter = JavaEmitter(model, output_dir)
    emitter.emit()
    write_readme(output_dir / "README.md")

    print(f"Generated Java project at {output_dir}")