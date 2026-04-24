from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET

from .common import (
    GROUPWISE_EVENTS_NS,
    GROUPWISE_METHODS_NS,
    GROUPWISE_TYPES_NS,
    GROUPWISE_WSDL_NS,
    SOAP,
    WSDL,
    XSD,
    XSD_NS,
    ElementDef,
    FieldDef,
    OperationDef,
    QNameRef,
    TypeDef,
    local_name,
    lower_camel,
    parse_xml,
    resolve_qname,
    upper_camel,
)


class GroupWiseSchemaModel:
    def __init__(self, wsdl_path: Path, base_package: str) -> None:
        self.wsdl_path = wsdl_path
        self.base_package = base_package
        self.global_elements: dict[tuple[str, str], ElementDef] = {}
        self.types: dict[tuple[str, str], TypeDef] = {}
        self.operations: list[OperationDef] = []
        self.synthetic_names: dict[str, set[str]] = defaultdict(set)
        self.port_endpoints: dict[str, str] = {}

    def load(self) -> None:
        self._load_schemas()
        self._resolve_simple_content_inheritance()
        self._load_wsdl()

    def _resolve_simple_content_inheritance(self) -> None:
        for type_def in self.types.values():
            if type_def.kind != "class" or type_def.value_type is None:
                continue
            base_ref = type_def.value_type
            if base_ref.namespace == XSD_NS:
                continue
            base_type = self.types.get(base_ref.key)
            if base_type is None or base_type.kind != "class":
                continue
            type_def.base = base_ref
            type_def.value_type = None

    def package_for_namespace(self, namespace: str) -> str:
        if namespace == GROUPWISE_TYPES_NS:
            return f"{self.base_package}.types"
        if namespace == GROUPWISE_METHODS_NS:
            return f"{self.base_package}.methods"
        if namespace == GROUPWISE_EVENTS_NS:
            return f"{self.base_package}.events"
        if namespace == GROUPWISE_WSDL_NS:
            return f"{self.base_package}.service"
        return f"{self.base_package}.misc"

    def _load_schemas(self) -> None:
        for filename in ("types.xsd", "methods.xsd", "events.xsd"):
            path = self.wsdl_path.parent / filename
            root, namespaces = parse_xml(path)
            target_namespace = root.attrib["targetNamespace"]

            for child in root:
                tag = local_name(child.tag)
                if tag == "element" and child.attrib.get("name") and child.attrib.get("type"):
                    self._parse_global_element(child, namespaces, target_namespace)

            for child in root:
                tag = local_name(child.tag)
                if tag == "simpleType" and child.attrib.get("name"):
                    type_def = self._parse_simple_type(child, namespaces, target_namespace)
                    self._register_type(type_def)

            for child in root:
                tag = local_name(child.tag)
                if tag == "complexType" and child.attrib.get("name"):
                    type_def = self._parse_complex_type(
                        child,
                        namespaces,
                        target_namespace,
                        child.attrib["name"],
                        child.attrib["name"],
                    )
                    self._register_type(type_def)

            for child in root:
                tag = local_name(child.tag)
                if tag == "element" and child.attrib.get("name"):
                    if (target_namespace, child.attrib["name"]) not in self.global_elements:
                        self._parse_global_element(child, namespaces, target_namespace)

    def _register_type(self, type_def: TypeDef) -> None:
        self.types[(type_def.namespace, type_def.name)] = type_def
        self.synthetic_names[type_def.namespace].add(type_def.name)

    def _unique_type_name(self, namespace: str, seed: str) -> str:
        candidate = upper_camel(seed)
        index = 2
        while candidate in self.synthetic_names[namespace]:
            candidate = f"{upper_camel(seed)}{index}"
            index += 1
        self.synthetic_names[namespace].add(candidate)
        return candidate

    def _parse_global_element(self, element: ET.Element, namespaces: dict[str, str], target_namespace: str) -> None:
        name = element.attrib["name"]
        explicit_type = resolve_qname(element.attrib.get("type"), namespaces, target_namespace)
        if explicit_type is not None:
            self.global_elements[(target_namespace, name)] = ElementDef(target_namespace, name, explicit_type)
            return

        complex_type = element.find(f"{XSD}complexType")
        simple_type = element.find(f"{XSD}simpleType")
        generated_name = self._unique_type_name(target_namespace, name)

        if complex_type is not None:
            type_def = self._parse_complex_type(complex_type, namespaces, target_namespace, generated_name, "")
            type_def.root_element_name = name
            self._register_type(type_def)
            self.global_elements[(target_namespace, name)] = ElementDef(
                target_namespace,
                name,
                QNameRef(target_namespace, generated_name),
            )
            return

        if simple_type is not None:
            type_def = self._parse_simple_type(simple_type, namespaces, target_namespace, forced_name=generated_name)
            type_def.root_element_name = name
            type_def.xml_type_name = ""
            self._register_type(type_def)
            self.global_elements[(target_namespace, name)] = ElementDef(
                target_namespace,
                name,
                QNameRef(target_namespace, generated_name),
            )
            return

        raise ValueError(f"Unsupported global element structure for {name}")

    def _parse_simple_type(
        self,
        simple_type: ET.Element,
        namespaces: dict[str, str],
        target_namespace: str,
        forced_name: str | None = None,
    ) -> TypeDef:
        name = forced_name or simple_type.attrib["name"]
        restriction = simple_type.find(f"{XSD}restriction")
        list_node = simple_type.find(f"{XSD}list")

        if restriction is not None:
            base = resolve_qname(restriction.attrib.get("base"), namespaces, target_namespace)
            enum_values = [enum.attrib["value"] for enum in restriction.findall(f"{XSD}enumeration")]
            if enum_values:
                return TypeDef(
                    namespace=target_namespace,
                    name=name,
                    xml_type_name=simple_type.attrib.get("name", name),
                    kind="enum",
                    base=base,
                    enum_values=enum_values,
                )
            return TypeDef(
                namespace=target_namespace,
                name=name,
                xml_type_name=simple_type.attrib.get("name", name),
                kind="alias",
                base=base,
            )

        if list_node is not None:
            item_type = resolve_qname(list_node.attrib["itemType"], namespaces, target_namespace)
            assert item_type is not None
            return TypeDef(
                namespace=target_namespace,
                name=name,
                xml_type_name=simple_type.attrib.get("name", name),
                kind="list",
                value_type=item_type,
            )

        raise ValueError(f"Unsupported simpleType {name}")

    def _parse_complex_type(
        self,
        complex_type: ET.Element,
        namespaces: dict[str, str],
        target_namespace: str,
        type_name: str,
        xml_type_name: str,
    ) -> TypeDef:
        type_def = TypeDef(
            namespace=target_namespace,
            name=type_name,
            xml_type_name=xml_type_name,
            kind="class",
        )

        simple_content = complex_type.find(f"{XSD}simpleContent")
        if simple_content is not None:
            extension = simple_content.find(f"{XSD}extension")
            if extension is None:
                raise ValueError(f"Unsupported simpleContent in {type_name}")
            type_def.value_type = resolve_qname(extension.attrib.get("base"), namespaces, target_namespace)
            type_def.attributes.extend(self._parse_attributes(extension, namespaces, target_namespace))
            return type_def

        complex_content = complex_type.find(f"{XSD}complexContent")
        content_parent = complex_type
        if complex_content is not None:
            extension = complex_content.find(f"{XSD}extension")
            if extension is None:
                raise ValueError(f"Unsupported complexContent in {type_name}")
            type_def.base = resolve_qname(extension.attrib.get("base"), namespaces, target_namespace)
            content_parent = extension

        sequence = content_parent.find(f"{XSD}sequence")
        all_node = content_parent.find(f"{XSD}all")
        if sequence is not None:
            type_def.compositor = "sequence"
            type_def.fields.extend(self._parse_elements(sequence, namespaces, target_namespace, type_name))
        if all_node is not None:
            type_def.compositor = "all"
            type_def.fields.extend(self._parse_elements(all_node, namespaces, target_namespace, type_name))
        type_def.attributes.extend(self._parse_attributes(content_parent, namespaces, target_namespace))
        return type_def

    def _parse_elements(
        self,
        parent: ET.Element,
        namespaces: dict[str, str],
        target_namespace: str,
        owner_name: str,
    ) -> list[FieldDef]:
        fields: list[FieldDef] = []
        for child in parent.findall(f"{XSD}element"):
            ref = resolve_qname(child.attrib.get("ref"), namespaces, target_namespace)
            if ref is not None:
                element_def = self.global_elements.get(ref.key)
                if element_def is None:
                    raise ValueError(f"Missing referenced element {ref.namespace}:{ref.local}")
                xml_name = ref.local
                field_type = element_def.type_ref
                field_namespace = ref.namespace
            else:
                xml_name = child.attrib["name"]
                field_namespace = target_namespace
                explicit_type = resolve_qname(child.attrib.get("type"), namespaces, target_namespace)
                if explicit_type is not None:
                    field_type = explicit_type
                else:
                    nested_complex = child.find(f"{XSD}complexType")
                    nested_simple = child.find(f"{XSD}simpleType")
                    generated_name = self._unique_type_name(target_namespace, f"{owner_name}{upper_camel(xml_name)}")
                    if nested_complex is not None:
                        nested_type = self._parse_complex_type(
                            nested_complex,
                            namespaces,
                            target_namespace,
                            generated_name,
                            generated_name,
                        )
                        self._register_type(nested_type)
                        field_type = QNameRef(target_namespace, generated_name)
                    elif nested_simple is not None:
                        nested_type = self._parse_simple_type(
                            nested_simple,
                            namespaces,
                            target_namespace,
                            forced_name=generated_name,
                        )
                        self._register_type(nested_type)
                        field_type = QNameRef(target_namespace, generated_name)
                    else:
                        raise ValueError(f"Unsupported nested element in {owner_name}.{xml_name}")

            max_occurs = child.attrib.get("maxOccurs", "1")
            repeated = max_occurs == "unbounded" or (max_occurs.isdigit() and int(max_occurs) > 1)
            min_occurs = child.attrib.get("minOccurs", "1")
            optional = min_occurs == "0"
            required = not optional and not repeated
            nillable = child.attrib.get("nillable", "false") in {"1", "true"}

            fields.append(
                FieldDef(
                    xml_name=xml_name,
                    java_name=lower_camel(xml_name),
                    type_ref=field_type,
                    namespace=field_namespace,
                    repeated=repeated,
                    optional=optional,
                    nillable=nillable,
                    required=required,
                    default_value=child.attrib.get("default"),
                )
            )
        return fields

    def _parse_attributes(self, parent: ET.Element, namespaces: dict[str, str], target_namespace: str) -> list[FieldDef]:
        attributes: list[FieldDef] = []
        for child in parent.findall(f"{XSD}attribute"):
            name = child.attrib["name"]
            attr_type = resolve_qname(child.attrib.get("type"), namespaces, target_namespace)
            if attr_type is None:
                raise ValueError(f"Unsupported anonymous attribute on {name}")
            use = child.attrib.get("use", "optional")
            attributes.append(
                FieldDef(
                    xml_name=name,
                    java_name=lower_camel(name),
                    type_ref=attr_type,
                    namespace=target_namespace,
                    attribute=True,
                    optional=use != "required",
                    required=use == "required",
                    default_value=child.attrib.get("default"),
                )
            )
        return attributes

    def _load_wsdl(self) -> None:
        root, namespaces = parse_xml(self.wsdl_path)
        messages: dict[str, QNameRef] = {}
        port_type_ops: dict[tuple[str, str], tuple[QNameRef, QNameRef]] = {}
        binding_to_port_type: dict[str, str] = {}
        binding_actions: dict[tuple[str, str], str] = {}

        for message in root.findall(f"{WSDL}message"):
            name = message.attrib["name"]
            part = message.find(f"{WSDL}part")
            if part is None:
                continue
            element = resolve_qname(part.attrib.get("element"), namespaces, GROUPWISE_WSDL_NS)
            if element is not None:
                messages[name] = element

        for port_type in root.findall(f"{WSDL}portType"):
            port_type_name = port_type.attrib["name"]
            for operation in port_type.findall(f"{WSDL}operation"):
                input_node = operation.find(f"{WSDL}input")
                output_node = operation.find(f"{WSDL}output")
                if input_node is None or output_node is None:
                    continue
                input_message = resolve_qname(input_node.attrib.get("message"), namespaces, GROUPWISE_WSDL_NS)
                output_message = resolve_qname(output_node.attrib.get("message"), namespaces, GROUPWISE_WSDL_NS)
                if input_message is None or output_message is None:
                    continue
                port_type_ops[(port_type_name, operation.attrib["name"])] = (
                    messages[input_message.local],
                    messages[output_message.local],
                )

        for binding in root.findall(f"{WSDL}binding"):
            binding_name = binding.attrib["name"]
            port_type_ref = resolve_qname(binding.attrib.get("type"), namespaces, GROUPWISE_WSDL_NS)
            if port_type_ref is None:
                continue
            binding_to_port_type[binding_name] = port_type_ref.local
            for operation in binding.findall(f"{WSDL}operation"):
                soap_operation = operation.find(f"{SOAP}operation")
                action = soap_operation.attrib.get("soapAction", operation.attrib["name"]) if soap_operation is not None else operation.attrib["name"]
                binding_actions[(binding_name, operation.attrib["name"])] = action

        service = root.find(f"{WSDL}service")
        if service is not None:
            for port in service.findall(f"{WSDL}port"):
                binding_ref = resolve_qname(port.attrib.get("binding"), namespaces, GROUPWISE_WSDL_NS)
                address = port.find(f"{SOAP}address")
                if binding_ref is not None and address is not None:
                    self.port_endpoints[binding_ref.local] = address.attrib.get("location", "")

        for (binding_name, operation_name), action in binding_actions.items():
            port_type_name = binding_to_port_type[binding_name]
            request_element, response_element = port_type_ops[(port_type_name, operation_name)]
            self.operations.append(
                OperationDef(
                    port_type=port_type_name,
                    binding_name=binding_name,
                    name=operation_name,
                    soap_action=action,
                    request_element=request_element,
                    response_element=response_element,
                    endpoint=self.port_endpoints.get(binding_name, ""),
                )
            )

    def subclasses(self) -> dict[tuple[str, str], list[QNameRef]]:
        mapping: dict[tuple[str, str], list[QNameRef]] = defaultdict(list)
        for type_def in self.types.values():
            if type_def.base is not None and type_def.base.namespace != XSD_NS:
                mapping[type_def.base.key].append(QNameRef(type_def.namespace, type_def.name))
        return mapping