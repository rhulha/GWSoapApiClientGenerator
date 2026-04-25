from __future__ import annotations

import keyword
import re
from pathlib import Path

from wsdl2java_lib.common import (
    GROUPWISE_EVENTS_NS,
    GROUPWISE_METHODS_NS,
    GROUPWISE_TYPES_NS,
    GROUPWISE_WSDL_NS,
    XSD_NS,
    FieldDef,
    QNameRef,
    TypeDef,
    lower_camel,
    upper_camel,
)
from wsdl2java_lib.model import GroupWiseSchemaModel


# ---------------------------------------------------------------------------
# Name helpers
# ---------------------------------------------------------------------------

def to_snake(camel: str) -> str:
    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", camel)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()
    if keyword.iskeyword(s2):
        s2 += "_"
    return s2


def _enum_member(value: str) -> str:
    candidate = re.sub(r"[^0-9A-Za-z]+", "_", value).upper()
    if not candidate:
        candidate = "VALUE"
    if candidate[0].isdigit():
        candidate = f"VALUE_{candidate}"
    return candidate


# ---------------------------------------------------------------------------
# PythonEmitter
# ---------------------------------------------------------------------------

class PythonEmitter:
    # (XSD qname key) -> (python type name, serialization strategy)
    BUILTIN: dict[tuple[str, str], tuple[str, str]] = {
        (XSD_NS, "string"):           ("str",      "str"),
        (XSD_NS, "boolean"):          ("bool",     "bool"),
        (XSD_NS, "byte"):             ("int",      "int"),
        (XSD_NS, "int"):              ("int",      "int"),
        (XSD_NS, "integer"):          ("int",      "int"),
        (XSD_NS, "decimal"):          ("Decimal",  "decimal"),
        (XSD_NS, "unsignedInt"):      ("int",      "int"),
        (XSD_NS, "unsignedShort"):    ("int",      "int"),
        (XSD_NS, "unsignedByte"):     ("int",      "int"),
        (XSD_NS, "long"):             ("int",      "int"),
        (XSD_NS, "short"):            ("int",      "int"),
        (XSD_NS, "float"):            ("float",    "float"),
        (XSD_NS, "double"):           ("float",    "float"),
        (XSD_NS, "base64Binary"):     ("bytes",    "b64"),
        (XSD_NS, "hexBinary"):        ("bytes",    "hex"),
        (XSD_NS, "anyURI"):           ("str",      "str"),
        (XSD_NS, "language"):         ("str",      "str"),
        (XSD_NS, "token"):            ("str",      "str"),
        (XSD_NS, "normalizedString"): ("str",      "str"),
        (XSD_NS, "date"):             ("date",     "date"),
        (XSD_NS, "dateTime"):         ("datetime", "datetime"),
        (XSD_NS, "duration"):         ("timedelta","duration"),
    }

    def __init__(self, model: GroupWiseSchemaModel, output_dir: Path) -> None:
        self.model = model
        self.output_dir = output_dir
        self._pkg_root = output_dir / "groupwise"

    # ------------------------------------------------------------------
    # Top-level emit
    # ------------------------------------------------------------------

    def emit(self) -> None:
        self._write_utils()
        self._write_runtime()
        self._write_model_packages()
        self._write_service_layer()
        self._write_project_files()

    # ------------------------------------------------------------------
    # Namespace / module helpers
    # ------------------------------------------------------------------

    def _module_for_ns(self, namespace: str) -> str:
        if namespace == GROUPWISE_TYPES_NS:
            return "groupwise.types"
        if namespace == GROUPWISE_METHODS_NS:
            return "groupwise.methods"
        if namespace == GROUPWISE_EVENTS_NS:
            return "groupwise.events"
        if namespace == GROUPWISE_WSDL_NS:
            return "groupwise.service"
        return "groupwise.misc"

    def _subdir_for_ns(self, namespace: str) -> Path:
        module = self._module_for_ns(namespace)
        subpkg = module.split(".", 1)[1]  # strip "groupwise."
        return self._pkg_root / subpkg

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def _write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    # ------------------------------------------------------------------
    # Utilities module
    # ------------------------------------------------------------------

    def _write_utils(self) -> None:
        self._write(self._pkg_root / "_utils.py", _UTILS_PY)

    # ------------------------------------------------------------------
    # Runtime (soap package)
    # ------------------------------------------------------------------

    def _write_runtime(self) -> None:
        soap_dir = self._pkg_root / "soap"
        soap_dir.mkdir(parents=True, exist_ok=True)
        self._write(soap_dir / "__init__.py", "")
        self._write(soap_dir / "request_context.py", self._request_context_py())
        self._write(soap_dir / "exceptions.py", self._exceptions_py())
        self._write(soap_dir / "soap_client.py", self._soap_client_py())

    # ------------------------------------------------------------------
    # Model packages
    # ------------------------------------------------------------------

    def _write_model_packages(self) -> None:
        namespaces = sorted({
            td.namespace
            for td in self.model.types.values()
            if td.namespace != GROUPWISE_WSDL_NS
        })
        for ns in namespaces:
            subdir = self._subdir_for_ns(ns)
            subdir.mkdir(parents=True, exist_ok=True)

            types_in_ns = sorted(
                [td for td in self.model.types.values() if td.namespace == ns],
                key=lambda td: td.name,
            )
            for type_def in types_in_ns:
                content = self._type_python(type_def)
                self._write(subdir / f"{type_def.name}.py", content)

            init_lines = ["from __future__ import annotations\n"]
            for type_def in types_in_ns:
                init_lines.append(f"from .{type_def.name} import {type_def.name}")
            init_lines.append("")
            self._write(subdir / "__init__.py", "\n".join(init_lines))

        # top-level groupwise/__init__.py
        self._write(self._pkg_root / "__init__.py", "")

    # ------------------------------------------------------------------
    # Service layer
    # ------------------------------------------------------------------

    def _write_service_layer(self) -> None:
        svc_dir = self._pkg_root / "service"
        svc_dir.mkdir(parents=True, exist_ok=True)
        self._write(svc_dir / "__init__.py", "")
        self._write(
            svc_dir / "groupwise_client.py",
            self._client_py("GroupWisePortType", "GroupWiseClient"),
        )
        self._write(
            svc_dir / "groupwise_events_client.py",
            self._client_py("GroupWiseEventsPortType", "GroupWiseEventsClient"),
        )

    # ------------------------------------------------------------------
    # Project files
    # ------------------------------------------------------------------

    def _write_project_files(self) -> None:
        self._write(
            self.output_dir / "requirements.txt",
            "# No mandatory runtime dependencies.\n"
            "# Install 'requests' if you prefer it over urllib:\n"
            "# requests>=2.28\n",
        )

    # ------------------------------------------------------------------
    # Type generation dispatch
    # ------------------------------------------------------------------

    def _type_python(self, type_def: TypeDef) -> str:
        if type_def.kind == "enum":
            return self._enum_python(type_def)
        if type_def.kind == "alias":
            return self._alias_python(type_def)
        if type_def.kind == "list":
            return self._list_python(type_def)
        return self._class_python(type_def)

    # ------------------------------------------------------------------
    # Enum
    # ------------------------------------------------------------------

    def _enum_python(self, type_def: TypeDef) -> str:
        lines = [
            "from __future__ import annotations\n",
            "from enum import Enum\n",
            "",
            f"class {type_def.name}(str, Enum):",
        ]
        for value in type_def.enum_values:
            lines.append(f"    {_enum_member(value)} = {value!r}")
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Alias (XSD restriction without enum values)
    # ------------------------------------------------------------------

    def _alias_python(self, type_def: TypeDef) -> str:
        resolved = self._resolve_alias(QNameRef(type_def.namespace, type_def.name))
        py_type, _ = self._builtin_for(resolved) or (type_def.name, "str")
        lines = [
            "from __future__ import annotations\n",
            f"{type_def.name} = {py_type}",
            "",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # List type (xsd:list)
    # ------------------------------------------------------------------

    def _list_python(self, type_def: TypeDef) -> str:
        assert type_def.value_type is not None
        resolved = self._resolve_alias(type_def.value_type)
        builtin = self._builtin_for(resolved)
        imports: set[str] = set()
        if builtin:
            item_py_type, strategy = builtin
            self._add_type_import(imports, item_py_type, strategy)
        else:
            item_py_type = resolved.local
            item_module = self._module_for_ns(resolved.namespace)
            imports.add(f"from {item_module}.{item_py_type} import {item_py_type}")

        parse_item = self._deserialize_text("_v", item_py_type, strategy if builtin else "obj", resolved)
        serial_item = self._serialize_value("_v", item_py_type, strategy if builtin else "obj")

        lines = [
            "from __future__ import annotations\n",
            "import xml.etree.ElementTree as ET",
            "from dataclasses import dataclass, field as _field",
        ]
        lines += sorted(imports)
        lines += [
            "",
            f"_NS = {type_def.namespace!r}",
            "",
            "@dataclass",
            f"class {type_def.name}:",
            f"    value: list[{item_py_type}] = _field(default_factory=list)",
            "",
            "    def to_xml(self, parent: ET.Element | None = None, tag: str | None = None) -> ET.Element:",
            "        _tag = tag or f'{{{_NS}}}" + type_def.name + "'",
            "        _el = ET.SubElement(parent, _tag) if parent is not None else ET.Element(_tag)",
            "        self._write_fields(_el)",
            "        return _el",
            "",
            "    def _write_fields(self, _el: ET.Element) -> None:",
            f"        _el.text = ' '.join({serial_item} for _v in self.value)",
            "",
            "    @classmethod",
            "    def _parse_fields(cls, _el: ET.Element) -> dict:",
            f"        return {{'value': [{parse_item} for _v in (_el.text or '').split() if _v]}}",
            "",
            "    @classmethod",
            f"    def from_xml(cls, _el: ET.Element) -> {type_def.name}:",
            "        return cls(**cls._parse_fields(_el))",
            "",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Class type
    # ------------------------------------------------------------------

    def _class_python(self, type_def: TypeDef) -> str:
        ns = type_def.namespace
        imports: set[str] = {
            "import xml.etree.ElementTree as ET",
            "from dataclasses import dataclass",
        }

        has_list_field = any(
            f.repeated for f in (type_def.fields + type_def.attributes)
        )
        if has_list_field:
            imports.add("from dataclasses import field as _field")

        # Resolve base class (Python)
        base_py: str | None = None
        has_gw_base = (
            type_def.base is not None
            and type_def.base.namespace != XSD_NS
        )
        if has_gw_base:
            assert type_def.base is not None
            base_py = type_def.base.local
            base_module = self._module_for_ns(type_def.base.namespace)
            # Base class MUST be imported at module level (used in class definition)
            imports.add(f"from {base_module}.{base_py} import {base_py}")

        # Collect field declarations, _write_fields, _parse_fields
        field_decls: list[str] = []
        write_lines: list[str] = []
        parse_lines: list[str] = []

        # value_type (simpleContent text node)
        if type_def.value_type is not None:
            vt_resolved = self._resolve_alias(type_def.value_type)
            vt_builtin = self._builtin_for(vt_resolved)
            if vt_builtin:
                vt_py, vt_strat = vt_builtin
                self._add_type_import(imports, vt_py, vt_strat)
                vt_lazy = None
            else:
                vt_py = vt_resolved.local
                vt_strat = "obj"
                vt_module = self._module_for_ns(vt_resolved.namespace)
                vt_lazy = f"from {vt_module}.{vt_py} import {vt_py}"
            field_decls.append(f"    value: {vt_py} | None = None")
            write_lines += self._emit_value_type_write(vt_py, vt_strat, vt_resolved)
            parse_lines += self._emit_value_type_parse(vt_py, vt_strat, vt_resolved, vt_lazy)

        # Regular element fields
        for fd in type_def.fields:
            py_name = to_snake(fd.java_name)
            resolved = self._resolve_alias(fd.type_ref)
            builtin = self._builtin_for(resolved)
            if builtin:
                py_type, strategy = builtin
                self._add_type_import(imports, py_type, strategy)
                is_enum = False
                lazy_import = None
            else:
                py_type = resolved.local
                strategy = "obj"
                field_module = self._module_for_ns(resolved.namespace)
                td = self.model.types.get(resolved.key)
                is_enum = td is not None and td.kind == "enum"
                # Use lazy import inside _parse_fields to break potential circular imports
                lazy_import = f"from {field_module}.{py_type} import {py_type}"

            if fd.repeated:
                imports.add("from dataclasses import field as _field")
                field_decls.append(f"    {py_name}: list[{py_type}] = _field(default_factory=list)")
                write_lines += self._emit_repeated_write(py_name, fd, py_type, strategy, is_enum, ns)
                parse_lines += self._emit_repeated_parse(py_name, fd, py_type, strategy, is_enum, ns, lazy_import)
            else:
                field_decls.append(f"    {py_name}: {py_type} | None = None")
                write_lines += self._emit_element_write(py_name, fd, py_type, strategy, is_enum, ns)
                parse_lines += self._emit_element_parse(py_name, fd, py_type, strategy, is_enum, ns, lazy_import)

        # Attribute fields
        for fd in type_def.attributes:
            py_name = to_snake(fd.java_name)
            resolved = self._resolve_alias(fd.type_ref)
            builtin = self._builtin_for(resolved)
            if builtin:
                py_type, strategy = builtin
                self._add_type_import(imports, py_type, strategy)
                is_enum = False
                lazy_import = None
            else:
                py_type = resolved.local
                strategy = "obj"
                field_module = self._module_for_ns(resolved.namespace)
                td = self.model.types.get(resolved.key)
                is_enum = td is not None and td.kind == "enum"
                lazy_import = f"from {field_module}.{py_type} import {py_type}"

            field_decls.append(f"    {py_name}: {py_type} | None = None")
            write_lines += self._emit_attr_write(py_name, fd, py_type, strategy, is_enum)
            parse_lines += self._emit_attr_parse(py_name, fd, py_type, strategy, is_enum, lazy_import)

        # --- Assemble file ---
        lines = ["from __future__ import annotations\n"]
        lines += sorted(imports)
        lines += ["", f"_NS = {ns!r}", ""]

        class_line = f"class {type_def.name}"
        if base_py:
            class_line += f"({base_py})"
        lines += ["@dataclass", class_line + ":"]

        if not field_decls:
            lines.append("    pass")
        else:
            lines += field_decls

        xml_name = type_def.root_element_name or type_def.xml_type_name or type_def.name
        lines += [
            "",
            "    def to_xml(self, parent: ET.Element | None = None, tag: str | None = None) -> ET.Element:",
            "        _tag = tag or f'{{{_NS}}}" + xml_name + "'",
            "        _el = ET.SubElement(parent, _tag) if parent is not None else ET.Element(_tag)",
            "        self._write_fields(_el)",
            "        return _el",
            "",
            "    def _write_fields(self, _el: ET.Element) -> None:",
        ]
        if has_gw_base:
            lines.append("        super()._write_fields(_el)")
        if write_lines:
            lines += write_lines
        elif not has_gw_base:
            lines.append("        pass")

        lines += [
            "",
            "    @classmethod",
            "    def _parse_fields(cls, _el: ET.Element) -> dict:",
        ]
        if has_gw_base:
            lines.append("        _f: dict = super()._parse_fields(_el)")
        else:
            lines.append("        _f: dict = {}")
        if parse_lines:
            lines += parse_lines
        lines.append("        return _f")

        if not has_gw_base:
            lines += [
                "",
                "    @classmethod",
                f"    def from_xml(cls, _el: ET.Element) -> {type_def.name}:",
                "        return cls(**cls._parse_fields(_el))",
            ]

        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Field emission helpers
    # ------------------------------------------------------------------

    def _emit_element_write(
        self, py_name: str, fd: FieldDef, py_type: str, strategy: str, is_enum: bool, default_ns: str
    ) -> list[str]:
        tag = self._field_tag(fd, default_ns)
        lines = [f"        if self.{py_name} is not None:"]
        lines.append(f"            _c = ET.SubElement(_el, {tag})")
        if strategy == "obj" and not is_enum:
            lines[-1] = f"            self.{py_name}.to_xml(_el, {tag})"
            lines.pop(0)
            lines.insert(0, f"        if self.{py_name} is not None:")
        elif is_enum:
            lines.append(f"            _c.text = self.{py_name}.value")
        else:
            serial = self._serialize_value(f"self.{py_name}", py_type, strategy)
            lines.append(f"            _c.text = {serial}")
        return lines

    def _emit_element_parse(
        self, py_name: str, fd: FieldDef, py_type: str, strategy: str, is_enum: bool,
        default_ns: str, lazy_import: str | None = None
    ) -> list[str]:
        tag = self._field_tag(fd, default_ns)
        lines = [f"        _c = _el.find({tag})"]
        lines.append("        if _c is not None:")
        if strategy == "obj" and not is_enum:
            if lazy_import:
                lines.append(f"            {lazy_import}")
            lines.append(f"            _f[{py_name!r}] = {py_type}.from_xml(_c)")
        elif is_enum:
            if lazy_import:
                lines.append(f"            {lazy_import}")
            lines.append(f"            if _c.text is not None:")
            lines.append(f"                _f[{py_name!r}] = {py_type}(_c.text)")
        else:
            deser = self._deserialize_text("_c.text", py_type, strategy, QNameRef("", ""))
            lines.append(f"            if _c.text is not None:")
            lines.append(f"                _f[{py_name!r}] = {deser}")
        return lines

    def _emit_repeated_write(
        self, py_name: str, fd: FieldDef, py_type: str, strategy: str, is_enum: bool, default_ns: str
    ) -> list[str]:
        tag = self._field_tag(fd, default_ns)
        if strategy == "obj" and not is_enum:
            return [f"        for _v in self.{py_name}:", f"            _v.to_xml(_el, {tag})"]
        serial = self._serialize_value("_v", py_type, strategy)
        return [
            f"        for _v in self.{py_name}:",
            f"            _c = ET.SubElement(_el, {tag})",
            f"            _c.text = {serial}",
        ]

    def _emit_repeated_parse(
        self, py_name: str, fd: FieldDef, py_type: str, strategy: str, is_enum: bool,
        default_ns: str, lazy_import: str | None = None
    ) -> list[str]:
        tag = self._field_tag(fd, default_ns)
        lines: list[str] = []
        if lazy_import:
            lines.append(f"        {lazy_import}")
        if strategy == "obj" and not is_enum:
            lines.append(f"        _f[{py_name!r}] = [{py_type}.from_xml(_c) for _c in _el.findall({tag})]")
        elif is_enum:
            lines.append(f"        _f[{py_name!r}] = [{py_type}(_c.text) for _c in _el.findall({tag}) if _c.text]")
        else:
            deser = self._deserialize_text("_c.text", py_type, strategy, QNameRef("", ""))
            lines.append(f"        _f[{py_name!r}] = [{deser} for _c in _el.findall({tag}) if _c.text is not None]")
        return lines

    def _emit_attr_write(
        self, py_name: str, fd: FieldDef, py_type: str, strategy: str, is_enum: bool
    ) -> list[str]:
        serial = (
            f"self.{py_name}.value" if is_enum
            else self._serialize_value(f"self.{py_name}", py_type, strategy)
        )
        return [
            f"        if self.{py_name} is not None:",
            f"            _el.set({fd.xml_name!r}, {serial})",
        ]

    def _emit_attr_parse(
        self, py_name: str, fd: FieldDef, py_type: str, strategy: str, is_enum: bool,
        lazy_import: str | None = None
    ) -> list[str]:
        lines = [f"        _v = _el.get({fd.xml_name!r})"]
        lines.append("        if _v is not None:")
        if is_enum:
            if lazy_import:
                lines.append(f"            {lazy_import}")
            lines.append(f"            _f[{py_name!r}] = {py_type}(_v)")
        else:
            deser = self._deserialize_text("_v", py_type, strategy, QNameRef("", ""))
            lines.append(f"            _f[{py_name!r}] = {deser}")
        return lines

    def _emit_value_type_write(self, py_type: str, strategy: str, resolved: QNameRef) -> list[str]:
        serial = self._serialize_value("self.value", py_type, strategy)
        return [
            "        if self.value is not None:",
            f"            _el.text = {serial}",
        ]

    def _emit_value_type_parse(
        self, py_type: str, strategy: str, resolved: QNameRef, lazy_import: str | None = None
    ) -> list[str]:
        lines = ["        if _el.text is not None:"]
        if lazy_import and strategy == "obj":
            lines.append(f"            {lazy_import}")
        deser = self._deserialize_text("_el.text", py_type, strategy, resolved)
        lines.append(f"            _f['value'] = {deser}")
        return lines

    # ------------------------------------------------------------------
    # Serialize / deserialize expressions
    # ------------------------------------------------------------------

    def _serialize_value(self, var: str, py_type: str, strategy: str) -> str:
        if strategy == "str":
            return var
        if strategy == "bool":
            return f"('true' if {var} else 'false')"
        if strategy in ("int", "float", "decimal"):
            return f"str({var})"
        if strategy == "date":
            return f"{var}.isoformat()"
        if strategy == "datetime":
            return f"{var}.isoformat()"
        if strategy == "duration":
            return f"_iso_duration({var})"
        if strategy == "b64":
            return f"_b64enc({var})"
        if strategy == "hex":
            return f"{var}.hex()"
        return f"str({var})"

    def _deserialize_text(self, text_expr: str, py_type: str, strategy: str, resolved: QNameRef) -> str:
        if strategy == "str":
            return text_expr
        if strategy == "bool":
            return f"(({text_expr}) or '').lower() in ('true', '1')"
        if strategy == "int":
            return f"int({text_expr})"
        if strategy in ("float", "decimal"):
            return f"{py_type}({text_expr})"
        if strategy == "date":
            return f"date.fromisoformat({text_expr})"
        if strategy == "datetime":
            return f"datetime.fromisoformat({text_expr})"
        if strategy == "duration":
            return f"_parse_duration({text_expr})"
        if strategy == "b64":
            return f"_b64dec({text_expr})"
        if strategy == "hex":
            return f"bytes.fromhex({text_expr})"
        return text_expr

    # ------------------------------------------------------------------
    # Type resolution helpers
    # ------------------------------------------------------------------

    def _resolve_alias(self, ref: QNameRef) -> QNameRef:
        current = ref
        while current.namespace != XSD_NS:
            td = self.model.types.get(current.key)
            if td is None or td.kind != "alias" or td.base is None:
                return current
            current = td.base
        return current

    def _builtin_for(self, resolved: QNameRef) -> tuple[str, str] | None:
        return self.BUILTIN.get(resolved.key)

    def _add_type_import(self, imports: set[str], py_type: str, strategy: str) -> None:
        if py_type == "Decimal":
            imports.add("from decimal import Decimal")
        elif py_type == "date":
            imports.add("from datetime import date")
        elif py_type == "datetime":
            imports.add("from datetime import datetime")
        elif py_type == "timedelta":
            imports.add("from datetime import timedelta")
            imports.add("from groupwise._utils import iso_duration as _iso_duration, parse_duration as _parse_duration")
        if strategy == "b64":
            imports.add("from groupwise._utils import b64enc as _b64enc, b64dec as _b64dec")
        elif strategy == "hex":
            pass  # bytes.fromhex / .hex() are builtins

    def _field_tag(self, fd: FieldDef, default_ns: str) -> str:
        ns = fd.namespace or default_ns
        if ns:
            if ns == default_ns:
                return "f'{{{_NS}}}" + fd.xml_name + "'"
            return f"f'{{{{{ns}}}}}{fd.xml_name}'"
        return repr(fd.xml_name)

    # ------------------------------------------------------------------
    # Service client
    # ------------------------------------------------------------------

    def _client_py(self, port_type_name: str, class_name: str) -> str:
        operations = [op for op in self.model.operations if op.port_type == port_type_name]
        default_endpoint = next((op.endpoint for op in operations if op.endpoint), "http://localhost:8080")

        fixed_imports: list[str] = [
            "from groupwise.soap.soap_client import SoapClient",
            "from groupwise.soap.request_context import RequestContext",
            "from groupwise.soap.exceptions import SoapFaultException",
        ]
        wildcard_modules: set[str] = set()
        method_lines: list[str] = []

        for op in operations:
            req_elem = self.model.global_elements[op.request_element.key]
            resp_elem = self.model.global_elements[op.response_element.key]
            req_type = req_elem.type_ref.local
            resp_type = resp_elem.type_ref.local
            req_module = self._module_for_ns(req_elem.type_ref.namespace)
            resp_module = self._module_for_ns(resp_elem.type_ref.namespace)
            wildcard_modules.add(req_module)
            wildcard_modules.add(resp_module)
            method_name = to_snake(lower_camel(op.name))
            if method_name.endswith('_request'):
                method_name = method_name[:-8]
            method_lines += [
                f"    def {method_name}(self, request: {req_type}, context: RequestContext | None = None) -> {resp_type}:",
                f"        _el = self._invoke({op.soap_action!r}, request, context)",
                f"        return {resp_type}.from_xml(_el)",
                "",
            ]

        lines = ["from __future__ import annotations\n"]
        lines = ["from __future__ import annotations\n"]
        lines += fixed_imports
        lines += sorted(f"from {m} import *" for m in wildcard_modules)
        lines += [
            "",
            f"DEFAULT_ENDPOINT = {default_endpoint!r}",
            "",
            f"class {class_name}(SoapClient):",
            f"    def __init__(self, endpoint: str = DEFAULT_ENDPOINT) -> None:",
            "        super().__init__(endpoint)",
            "",
        ]
        lines += method_lines
        lines.append("")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Runtime file content
    # ------------------------------------------------------------------

    def _request_context_py(self) -> str:
        return """\
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RequestContext:
    session_id: str | None = None
    gw_trace: bool | None = None
"""

    def _exceptions_py(self) -> str:
        return """\
from __future__ import annotations


class SoapFaultException(Exception):
    def __init__(self, fault_code: str, fault_string: str, detail: str | None = None) -> None:
        super().__init__(f"{fault_code}: {fault_string}")
        self.fault_code = fault_code
        self.fault_string = fault_string
        self.detail = detail
"""

    def _soap_client_py(self) -> str:
        # pre-compute tags as literals so the outer f-string doesn't need
        # to escape namespace variable references inside the generated code
        soap_ns = "http://schemas.xmlsoap.org/soap/envelope/"
        types_ns = GROUPWISE_TYPES_NS
        body_tag = "{" + soap_ns + "}Body"
        return f"""\
from __future__ import annotations

import urllib.request
import urllib.error
import xml.etree.ElementTree as ET

from .request_context import RequestContext
from .exceptions import SoapFaultException

_SOAP_NS = {soap_ns!r}
_TYPES_NS = {types_ns!r}


class SoapClient:
    def __init__(self, endpoint: str) -> None:
        self._endpoint = endpoint

    def _invoke(self, soap_action: str, request_obj: object, context: RequestContext | None) -> ET.Element:
        ctx = context or RequestContext()
        request_el = request_obj.to_xml()  # type: ignore[attr-defined]
        body_xml = ET.tostring(request_el, encoding="unicode")
        envelope = self._build_envelope(body_xml, ctx)

        req = urllib.request.Request(
            self._endpoint,
            data=envelope.encode("utf-8"),
            headers={{
                "Content-Type": "text/xml; charset=UTF-8",
                "SOAPAction": soap_action,
            }},
        )
        try:
            with urllib.request.urlopen(req) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()

        doc = ET.fromstring(raw)
        body = doc.find({body_tag!r})
        if body is None:
            raise ValueError("SOAP response is missing a Body element")
        payload = next(iter(body), None)
        if payload is None:
            raise ValueError("SOAP Body is empty")
        local = payload.tag.split("}}", 1)[-1] if "}}" in payload.tag else payload.tag
        if local == "Fault":
            raise self._parse_fault(payload)
        return payload

    @staticmethod
    def _parse_fault(fault: ET.Element) -> SoapFaultException:
        def _text(tag: str) -> str | None:
            el = fault.find(tag)
            return el.text if el is not None else None
        return SoapFaultException(
            _text("faultcode") or "",
            _text("faultstring") or "",
            _text("detail"),
        )

    @staticmethod
    def _escape(value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )

    def _build_envelope(self, body_xml: str, ctx: RequestContext) -> str:
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<soapenv:Envelope xmlns:soapenv="' + _SOAP_NS + '" xmlns:typ="' + _TYPES_NS + '">',
            "<soapenv:Header>",
        ]
        if ctx.session_id:
            parts.append("<typ:session>" + self._escape(ctx.session_id) + "</typ:session>")
        if ctx.gw_trace is not None:
            parts.append("<typ:gwTrace>" + ("true" if ctx.gw_trace else "false") + "</typ:gwTrace>")
        parts += [
            "</soapenv:Header>",
            "<soapenv:Body>" + body_xml + "</soapenv:Body>",
            "</soapenv:Envelope>",
        ]
        return "".join(parts)
"""


# ---------------------------------------------------------------------------
# Utilities module (written verbatim into the output package)
# ---------------------------------------------------------------------------

_UTILS_PY = """\
from __future__ import annotations

import base64
import re
from datetime import timedelta


def b64enc(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64dec(s: str) -> bytes:
    return base64.b64decode(s)


def iso_duration(td: timedelta) -> str:
    total = int(td.total_seconds())
    sign = "-" if total < 0 else ""
    total = abs(total)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    return f"{sign}P{days}DT{hours}H{minutes}M{seconds}S"


def parse_duration(s: str) -> timedelta:
    m = re.fullmatch(
        r"(-?)P(?:(\\d+)Y)?(?:(\\d+)M)?(?:(\\d+)D)?"
        r"(?:T(?:(\\d+)H)?(?:(\\d+)M)?(?:(\\d+(?:\\.\\d+)?)S)?)?",
        s,
    )
    if not m:
        raise ValueError(f"Invalid ISO 8601 duration: {s!r}")
    sign = -1 if m.group(1) == "-" else 1
    years = int(m.group(2) or 0)
    months = int(m.group(3) or 0)
    days = int(m.group(4) or 0)
    hours = int(m.group(5) or 0)
    minutes = int(m.group(6) or 0)
    seconds = float(m.group(7) or 0)
    total_days = years * 365 + months * 30 + days
    return sign * timedelta(days=total_days, hours=hours, minutes=minutes, seconds=seconds)
"""


# ---------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------

def write_readme(path: Path) -> None:
    content = """\
# GroupWise Python Client

Auto-generated Python package for the GroupWise WSDL/XSD schemas.

## Package layout

```
groupwise/
  _utils.py              helper functions (base64, ISO 8601 duration)
  types/                 XSD types namespace classes
  methods/               XSD methods namespace classes
  events/                XSD events namespace classes
  soap/
    request_context.py   RequestContext dataclass
    exceptions.py        SoapFaultException
    soap_client.py       Base SOAP/HTTP client
  service/
    groupwise_client.py        GroupWise main service client
    groupwise_events_client.py GroupWise events service client
```

## Usage

```python
from groupwise.service.groupwise_client import GroupWiseClient
from groupwise.methods.LoginRequest import LoginRequest
from groupwise.soap.request_context import RequestContext

client = GroupWiseClient("https://your-server/soap")
req = LoginRequest()
# populate req fields ...
response = client.login(req)
```

## Regenerate

```powershell
python tools/wsdl2python.py --wsdl wsdl/groupwise.wsdl --output generated/groupwise-python-client
```
"""
    path.write_text(content, encoding="utf-8")
