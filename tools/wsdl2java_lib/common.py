from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET


XSD_NS = "http://www.w3.org/2001/XMLSchema"
WSDL_NS = "http://schemas.xmlsoap.org/wsdl/"
SOAP_NS = "http://schemas.xmlsoap.org/wsdl/soap/"

GROUPWISE_WSDL_NS = "http://schemas.novell.com/2005/01/GroupWise/groupwise.wsdl"
GROUPWISE_TYPES_NS = "http://schemas.novell.com/2005/01/GroupWise/types"
GROUPWISE_METHODS_NS = "http://schemas.novell.com/2005/01/GroupWise/methods"
GROUPWISE_EVENTS_NS = "http://schemas.novell.com/2005/01/GroupWise/events"

XSD = f"{{{XSD_NS}}}"
WSDL = f"{{{WSDL_NS}}}"
SOAP = f"{{{SOAP_NS}}}"

JAVA_KEYWORDS = set(keyword.kwlist) | {
    "abstract",
    "assert",
    "boolean",
    "break",
    "byte",
    "case",
    "catch",
    "char",
    "class",
    "const",
    "continue",
    "default",
    "do",
    "double",
    "else",
    "enum",
    "extends",
    "final",
    "finally",
    "float",
    "for",
    "goto",
    "if",
    "implements",
    "import",
    "instanceof",
    "int",
    "interface",
    "long",
    "native",
    "new",
    "package",
    "private",
    "protected",
    "public",
    "return",
    "short",
    "static",
    "strictfp",
    "super",
    "switch",
    "synchronized",
    "this",
    "throw",
    "throws",
    "transient",
    "try",
    "void",
    "volatile",
    "while",
    "record",
    "sealed",
    "permits",
    "yield",
    "var",
}


def local_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def namespace_of(tag: str) -> str | None:
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return None


def parse_xml(path: Path) -> tuple[ET.Element, dict[str, str]]:
    namespaces: dict[str, str] = {}
    for _, item in ET.iterparse(path, events=("start-ns",)):
        prefix, uri = item
        namespaces[prefix or ""] = uri
    root = ET.parse(path).getroot()
    return root, namespaces


@dataclass(frozen=True)
class QNameRef:
    namespace: str
    local: str

    @property
    def key(self) -> tuple[str, str]:
        return self.namespace, self.local


@dataclass
class FieldDef:
    xml_name: str
    java_name: str
    type_ref: QNameRef
    namespace: str
    repeated: bool = False
    optional: bool = False
    nillable: bool = False
    attribute: bool = False
    required: bool = False
    default_value: str | None = None


@dataclass
class TypeDef:
    namespace: str
    name: str
    xml_type_name: str
    kind: str
    base: QNameRef | None = None
    fields: list[FieldDef] = field(default_factory=list)
    attributes: list[FieldDef] = field(default_factory=list)
    enum_values: list[str] = field(default_factory=list)
    value_type: QNameRef | None = None
    root_element_name: str | None = None
    compositor: str = "sequence"


@dataclass
class ElementDef:
    namespace: str
    name: str
    type_ref: QNameRef


@dataclass
class OperationDef:
    port_type: str
    binding_name: str
    name: str
    soap_action: str
    request_element: QNameRef
    response_element: QNameRef
    endpoint: str


def resolve_qname(value: str | None, namespaces: dict[str, str], default_namespace: str | None = None) -> QNameRef | None:
    if not value:
        return None
    if value.startswith("{"):
        return QNameRef(namespace_of(value) or "", local_name(value))
    if ":" in value:
        prefix, local = value.split(":", 1)
        namespace = namespaces[prefix]
        return QNameRef(namespace, local)
    namespace = namespaces.get("", default_namespace or "")
    return QNameRef(namespace, value)


def upper_camel(name: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        candidate = name[0].upper() + name[1:]
    else:
        parts = re.split(r"[^0-9A-Za-z]+", name)
        candidate = "".join(part[:1].upper() + part[1:] for part in parts if part)
    if not candidate:
        candidate = "GeneratedType"
    if candidate[0].isdigit():
        candidate = f"Type{candidate}"
    if candidate.lower() in JAVA_KEYWORDS:
        candidate = f"{candidate}Type"
    return candidate


def lower_camel(name: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        candidate = name[0].lower() + name[1:]
    else:
        parts = re.split(r"[^0-9A-Za-z]+", name)
        candidate = "".join(
            (part[:1].lower() + part[1:]) if index == 0 else (part[:1].upper() + part[1:])
            for index, part in enumerate(part for part in parts if part)
        )
    if not candidate:
        candidate = "value"
    if candidate[0].isdigit():
        candidate = f"value{candidate}"
    if candidate in JAVA_KEYWORDS:
        candidate = f"{candidate}Value"
    return candidate


def enum_constant(name: str) -> str:
    candidate = re.sub(r"[^0-9A-Za-z]+", "_", name).upper()
    if not candidate:
        candidate = "VALUE"
    if candidate[0].isdigit():
        candidate = f"VALUE_{candidate}"
    return candidate


def escape_java(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')