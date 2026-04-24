from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .common import (
    GROUPWISE_TYPES_NS,
    GROUPWISE_WSDL_NS,
    XSD_NS,
    FieldDef,
    QNameRef,
    TypeDef,
    enum_constant,
    escape_java,
    lower_camel,
    upper_camel,
)
from .model import GroupWiseSchemaModel


class JavaEmitter:
    BUILTIN_MAPPINGS = {
        (XSD_NS, "string"): ("String", None),
        (XSD_NS, "boolean"): ("Boolean", None),
        (XSD_NS, "byte"): ("Byte", None),
        (XSD_NS, "int"): ("Integer", None),
        (XSD_NS, "integer"): ("java.math.BigInteger", None),
        (XSD_NS, "decimal"): ("java.math.BigDecimal", None),
        (XSD_NS, "unsignedInt"): ("Long", None),
        (XSD_NS, "unsignedShort"): ("Integer", None),
        (XSD_NS, "unsignedByte"): ("Short", None),
        (XSD_NS, "long"): ("Long", None),
        (XSD_NS, "short"): ("Short", None),
        (XSD_NS, "float"): ("Float", None),
        (XSD_NS, "double"): ("Double", None),
        (XSD_NS, "base64Binary"): ("byte[]", None),
        (XSD_NS, "hexBinary"): ("byte[]", None),
        (XSD_NS, "anyURI"): ("String", None),
        (XSD_NS, "language"): ("String", None),
        (XSD_NS, "token"): ("String", None),
        (XSD_NS, "normalizedString"): ("String", None),
        (XSD_NS, "date"): ("java.time.LocalDate", "LocalDateXmlAdapter"),
        (XSD_NS, "dateTime"): ("java.time.OffsetDateTime", "OffsetDateTimeXmlAdapter"),
        (XSD_NS, "duration"): ("java.time.Duration", "DurationXmlAdapter"),
    }

    def __init__(self, model: GroupWiseSchemaModel, output_dir: Path) -> None:
        self.model = model
        self.output_dir = output_dir
        self.base_package = model.base_package
        self.runtime_package = f"{self.base_package}.soap"
        self.subclasses = model.subclasses()

    def emit(self) -> None:
        self._write_project_files()
        self._write_runtime()
        self._write_model_packages()
        self._write_service_layer()

    def _write_project_files(self) -> None:
        self._write_text(
            self.output_dir / "settings.gradle",
            "rootProject.name = 'groupwise-java14-client'\n",
        )

        build_gradle = """
plugins {
    id 'java-library'
}

group = 'com.novell.groupwise'
version = '1.0.0-SNAPSHOT'

repositories {
    mavenCentral()
}

java {
    sourceCompatibility = JavaVersion.VERSION_14
    targetCompatibility = JavaVersion.VERSION_14
    withSourcesJar()
    withJavadocJar()
}

dependencies {
    api 'javax.xml.bind:jaxb-api:2.3.1'
    runtimeOnly 'org.glassfish.jaxb:jaxb-runtime:2.3.8'
}

tasks.withType(JavaCompile).configureEach {
    options.encoding = 'UTF-8'
}

tasks.named('javadoc').configure {
    options.addStringOption('Xdoclint:none', '-quiet')
    failOnError = false
}

tasks.register('fatJar', Jar) {
    group = 'build'
    description = 'Builds a self-contained JAR with all runtime dependencies (JAXB) bundled.'
    archiveClassifier = 'all'
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
    dependsOn configurations.runtimeClasspath
    from sourceSets.main.output
    from {
        configurations.runtimeClasspath.findAll { it.name.endsWith('.jar') }.collect { zipTree(it) }
    }
    exclude 'META-INF/*.SF', 'META-INF/*.DSA', 'META-INF/*.RSA', 'module-info.class'
}

tasks.register('runConnectionTest', JavaExec) {
    group = 'verification'
    description = 'Run com.novell.groupwise.test.ConnectionTest against a GroupWise SOAP endpoint.'
    dependsOn 'testClasses'
    classpath = sourceSets.test.runtimeClasspath
    mainClass = 'com.novell.groupwise.test.ConnectionTest'
    if (project.hasProperty('testArgs')) {
        args project.testArgs.split(' ')
    }
    standardOutput = System.out
    errorOutput = System.err
}
""".strip() + "\n"
        self._write_text(self.output_dir / "build.gradle", build_gradle)

    def _write_runtime(self) -> None:
        runtime_dir = self._package_dir(self.runtime_package)

        self._write_text(runtime_dir / "RequestContext.java", self._request_context_java())
        self._write_text(runtime_dir / "SoapFaultException.java", self._soap_fault_exception_java())
        self._write_text(runtime_dir / "SoapHttpClient.java", self._soap_http_client_java())
        self._write_text(
            runtime_dir / "LocalDateXmlAdapter.java",
            self._adapter_java("LocalDateXmlAdapter", "java.time.LocalDate", "LocalDate.parse(value)", "value.toString()"),
        )
        self._write_text(
            runtime_dir / "OffsetDateTimeXmlAdapter.java",
            self._adapter_java(
                "OffsetDateTimeXmlAdapter",
                "java.time.OffsetDateTime",
                "OffsetDateTime.parse(value)",
                "value.toString()",
            ),
        )
        self._write_text(
            runtime_dir / "DurationXmlAdapter.java",
            self._adapter_java("DurationXmlAdapter", "java.time.Duration", "Duration.parse(value)", "value.toString()"),
        )

    def _write_model_packages(self) -> None:
        namespaces = sorted({type_def.namespace for type_def in self.model.types.values() if type_def.namespace != GROUPWISE_WSDL_NS})
        for namespace in namespaces:
            package_name = self.model.package_for_namespace(namespace)
            package_dir = self._package_dir(package_name)
            self._write_text(package_dir / "package-info.java", self._package_info_java(package_name, namespace))

            for type_def in sorted(
                [item for item in self.model.types.values() if item.namespace == namespace],
                key=lambda item: item.name,
            ):
                self._write_text(package_dir / f"{type_def.name}.java", self._type_java(type_def))

    def _write_service_layer(self) -> None:
        service_package = f"{self.base_package}.service"
        service_dir = self._package_dir(service_package)
        self._write_text(service_dir / "GroupWisePort.java", self._service_interface_java("GroupWisePortType", "GroupWisePort"))
        self._write_text(service_dir / "GroupWiseEventsPort.java", self._service_interface_java("GroupWiseEventsPortType", "GroupWiseEventsPort"))
        self._write_text(service_dir / "GroupWiseClient.java", self._client_java("GroupWisePortType", "GroupWisePort", "GroupWiseClient"))
        self._write_text(
            service_dir / "GroupWiseEventsClient.java",
            self._client_java("GroupWiseEventsPortType", "GroupWiseEventsPort", "GroupWiseEventsClient"),
        )
        self._write_text(service_dir / "GeneratedJaxbContext.java", self._jaxb_context_java())

    def _package_dir(self, package_name: str) -> Path:
        package_path = Path("src/main/java") / Path(*package_name.split("."))
        directory = self.output_dir / package_path
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _type_java(self, type_def: TypeDef) -> str:
        package_name = self.model.package_for_namespace(type_def.namespace)
        imports: set[str] = set()
        lines: list[str] = [f"package {package_name};", ""]

        body: list[str] = []
        annotations: list[str] = ["@XmlAccessorType(XmlAccessType.FIELD)"]

        if type_def.kind == "enum":
            imports.update({"javax.xml.bind.annotation.XmlEnum", "javax.xml.bind.annotation.XmlEnumValue", "javax.xml.bind.annotation.XmlType"})
            annotations = [self._xml_type_annotation(type_def, []), "@XmlEnum"]
            body.append(f"public enum {type_def.name} {{")
            enum_lines = []
            for value in type_def.enum_values:
                enum_lines.append(f"    @XmlEnumValue(\"{escape_java(value)}\")\n    {enum_constant(value)}(\"{escape_java(value)}\")")
            body.append(",\n".join(enum_lines) + ";\n")
            body.append("    private final String value;\n")
            body.append(f"    {type_def.name}(String value) {{\n        this.value = value;\n    }}\n")
            body.append("    public String value() {\n        return value;\n    }\n")
            body.append(f"    public static {type_def.name} fromValue(String value) {{\n")
            body.append(f"        for (var candidate : {type_def.name}.values()) {{\n            if (candidate.value.equals(value)) {{\n                return candidate;\n            }}\n        }}\n")
            body.append("        throw new IllegalArgumentException(\"Unknown enum value: \" + value);\n    }\n")
            body.append("}\n")
            lines.extend(self._render_imports(imports))
            lines.extend(annotations)
            lines.extend(body)
            return "\n".join(lines)

        imports.update(
            {
                "javax.xml.bind.annotation.XmlAccessType",
                "javax.xml.bind.annotation.XmlAccessorType",
                "javax.xml.bind.annotation.XmlAttribute",
                "javax.xml.bind.annotation.XmlElement",
                "javax.xml.bind.annotation.XmlRootElement",
                "javax.xml.bind.annotation.XmlType",
            }
        )

        if type_def.kind == "list":
            imports.update(
                {
                    "java.util.ArrayList",
                    "java.util.List",
                    "javax.xml.bind.annotation.XmlList",
                    "javax.xml.bind.annotation.XmlValue",
                }
            )
            value_type = self._java_type(type_def.value_type, package_name, imports)
            annotations.append(self._xml_type_annotation(type_def, []))
            if type_def.root_element_name:
                annotations.append(self._xml_root_annotation(type_def))
            body.append(f"public class {type_def.name} {{")
            body.append("    @XmlValue\n    @XmlList")
            body.append(f"    private List<{value_type}> value = new ArrayList<>();\n")
            body.append(f"    public List<{value_type}> getValue() {{\n        return value;\n    }}\n")
            body.append(f"    public {type_def.name} setValue(List<{value_type}> value) {{\n        this.value = value;\n        return this;\n    }}\n")
            body.append("}\n")
            lines.extend(self._render_imports(imports))
            lines.extend(annotations)
            lines.extend(body)
            return "\n".join(lines)

        prop_order = [field.java_name for field in type_def.fields]
        annotations.append(self._xml_type_annotation(type_def, prop_order))
        if type_def.root_element_name:
            annotations.append(self._xml_root_annotation(type_def))
        subclasses = self.subclasses.get((type_def.namespace, type_def.name), [])
        if subclasses:
            imports.add("javax.xml.bind.annotation.XmlSeeAlso")
            targets = ", ".join(f"{self._java_type(ref, package_name, imports)}.class" for ref in sorted(subclasses, key=lambda item: item.local))
            annotations.append(f"@XmlSeeAlso({{{targets}}})")

        extends_clause = ""
        if type_def.base is not None and type_def.base.namespace != XSD_NS:
            extends_clause = f" extends {self._java_type(type_def.base, package_name, imports)}"

        body.append(f"public class {type_def.name}{extends_clause} {{")

        if type_def.value_type is not None:
            imports.add("javax.xml.bind.annotation.XmlValue")
            body.append(
                self._field_declaration(
                    FieldDef(
                        xml_name="value",
                        java_name="value",
                        type_ref=type_def.value_type,
                        namespace=type_def.namespace,
                    ),
                    package_name,
                    imports,
                    xml_value=True,
                )
            )

        for field_def in type_def.fields:
            body.append(self._field_declaration(field_def, package_name, imports))

        for field_def in type_def.attributes:
            body.append(self._field_declaration(field_def, package_name, imports))

        all_fields = []
        if type_def.value_type is not None:
            all_fields.append(("value", type_def.value_type, False))
        all_fields.extend((field.java_name, field.type_ref, field.repeated) for field in type_def.fields + type_def.attributes)

        for java_name, type_ref, repeated in all_fields:
            java_type = self._java_type(type_ref, package_name, imports)
            if repeated:
                body.append(
                    f"    public java.util.List<{java_type}> get{upper_camel(java_name)}() {{\n"
                    f"        if ({java_name} == null) {{\n"
                    f"            {java_name} = new java.util.ArrayList<>();\n"
                    f"        }}\n"
                    f"        return {java_name};\n"
                    f"    }}\n"
                )
                body.append(
                    f"    public {type_def.name} set{upper_camel(java_name)}(java.util.List<{java_type}> {java_name}) {{\n"
                    f"        this.{java_name} = {java_name};\n"
                    f"        return this;\n"
                    f"    }}\n"
                )
                continue
            body.append(f"    public {java_type} get{upper_camel(java_name)}() {{\n        return {java_name};\n    }}\n")
            body.append(
                f"    public {type_def.name} set{upper_camel(java_name)}({java_type} {java_name}) {{\n"
                f"        this.{java_name} = {java_name};\n"
                f"        return this;\n"
                f"    }}\n"
            )

        body.append("}\n")
        lines.extend(self._render_imports(imports))
        lines.extend(annotations)
        lines.extend(body)
        return "\n".join(lines)

    def _field_declaration(
        self,
        field_def: FieldDef,
        package_name: str,
        imports: set[str],
        xml_value: bool = False,
    ) -> str:
        parts: list[str] = []
        adapter = self._adapter_for(field_def.type_ref)
        if adapter is not None:
            imports.add("javax.xml.bind.annotation.adapters.XmlJavaTypeAdapter")
            imports.add(f"{self.runtime_package}.{adapter}")
            parts.append(f"    @XmlJavaTypeAdapter({adapter}.class)")

        java_type = self._java_type(field_def.type_ref, package_name, imports)
        if field_def.repeated:
            imports.update({"java.util.ArrayList", "java.util.List"})
            java_type = f"List<{java_type}>"

        if xml_value:
            parts.append("    @XmlValue")
        elif field_def.attribute:
            annotation = f"    @XmlAttribute(name = \"{field_def.xml_name}\""
            if field_def.required:
                annotation += ", required = true"
            annotation += ")"
            parts.append(annotation)
        else:
            annotation = f"    @XmlElement(name = \"{field_def.xml_name}\""
            if field_def.namespace:
                annotation += f", namespace = \"{field_def.namespace}\""
            if field_def.nillable:
                annotation += ", nillable = true"
            if field_def.required and not field_def.repeated:
                annotation += ", required = true"
            annotation += ")"
            parts.append(annotation)

        initializer = ""
        if field_def.repeated:
            initializer = " = new ArrayList<>()"
        parts.append(f"    private {java_type} {field_def.java_name}{initializer};\n")
        return "\n".join(parts)

    def _adapter_for(self, type_ref: QNameRef) -> str | None:
        resolved = self._resolve_alias(type_ref)
        mapping = self.BUILTIN_MAPPINGS.get(resolved.key)
        return None if mapping is None else mapping[1]

    def _java_type(self, type_ref: QNameRef | None, current_package: str, imports: set[str]) -> str:
        if type_ref is None:
            return "Object"
        resolved = self._resolve_alias(type_ref)
        builtin = self.BUILTIN_MAPPINGS.get(resolved.key)
        if builtin is not None:
            java_type = builtin[0]
            if "." in java_type:
                imports.add(java_type)
                return java_type.rsplit(".", 1)[1]
            return java_type

        package_name = self.model.package_for_namespace(resolved.namespace)
        simple_name = resolved.local
        if package_name != current_package:
            imports.add(f"{package_name}.{simple_name}")
        return simple_name

    def _resolve_alias(self, type_ref: QNameRef) -> QNameRef:
        current = type_ref
        while current.namespace != XSD_NS:
            type_def = self.model.types.get(current.key)
            if type_def is None or type_def.kind != "alias" or type_def.base is None:
                return current
            current = type_def.base
        return current

    def _xml_type_annotation(self, type_def: TypeDef, prop_order: list[str]) -> str:
        parts = [f"name = \"{type_def.xml_type_name}\"", f"namespace = \"{type_def.namespace}\""]
        if prop_order:
            order = ", ".join(f'\"{item}\"' for item in prop_order)
            parts.append(f"propOrder = {{{order}}}")
        return f"@XmlType({', '.join(parts)})"

    def _xml_root_annotation(self, type_def: TypeDef) -> str:
        return f"@XmlRootElement(name = \"{type_def.root_element_name}\", namespace = \"{type_def.namespace}\")"

    def _package_info_java(self, package_name: str, namespace: str) -> str:
        return (
            "@javax.xml.bind.annotation.XmlSchema(\n"
            f"    namespace = \"{namespace}\",\n"
            "    elementFormDefault = javax.xml.bind.annotation.XmlNsForm.QUALIFIED\n"
            ")\n"
            f"package {package_name};\n"
        )

    def _service_interface_java(self, port_type_name: str, interface_name: str) -> str:
        operations = [operation for operation in self.model.operations if operation.port_type == port_type_name]
        imports = {
            "java.io.IOException",
            f"{self.runtime_package}.RequestContext",
            f"{self.runtime_package}.SoapFaultException",
        }
        methods: list[str] = []

        for operation in operations:
            request_type = self._java_class_for_element(operation.request_element)
            response_type = self._java_class_for_element(operation.response_element)
            imports.add(request_type[0])
            imports.add(response_type[0])
            methods.append(
                f"    {response_type[1]} {lower_camel(operation.name)}({request_type[1]} request, RequestContext context)"
                " throws IOException, InterruptedException, SoapFaultException;"
            )

        lines = [f"package {self.base_package}.service;", ""]
        lines.extend(self._render_imports(imports))
        lines.append(f"public interface {interface_name} {{")
        lines.extend(methods)
        lines.append("}\n")
        return "\n".join(lines)

    def _client_java(self, port_type_name: str, interface_name: str, class_name: str) -> str:
        operations = [operation for operation in self.model.operations if operation.port_type == port_type_name]
        imports = {
            "java.io.IOException",
            "java.net.URI",
            f"{self.runtime_package}.RequestContext",
            f"{self.runtime_package}.SoapFaultException",
            f"{self.runtime_package}.SoapHttpClient",
        }

        default_endpoint = next((operation.endpoint for operation in operations if operation.endpoint), "http://localhost:8080")
        lines = [f"package {self.base_package}.service;", ""]

        methods: list[str] = []
        for operation in operations:
            request_type = self._java_class_for_element(operation.request_element)
            response_type = self._java_class_for_element(operation.response_element)
            imports.add(request_type[0])
            imports.add(response_type[0])
            methods.append(
                f"    @Override\n"
                f"    public {response_type[1]} {lower_camel(operation.name)}({request_type[1]} request, RequestContext context)"
                " throws IOException, InterruptedException, SoapFaultException {\n"
                f"        return invoke(\"{escape_java(operation.soap_action)}\", request, {response_type[1]}.class, context);\n"
                "    }\n"
            )

        lines.extend(self._render_imports(imports))
        lines.append(f"public final class {class_name} extends SoapHttpClient implements {interface_name} {{")
        lines.append(f"    public static final URI DEFAULT_ENDPOINT = URI.create(\"{escape_java(default_endpoint)}\");\n")
        lines.append(f"    public {class_name}() {{\n        this(DEFAULT_ENDPOINT);\n    }}\n")
        lines.append(f"    public {class_name}(URI endpoint) {{\n        super(endpoint, GeneratedJaxbContext.create());\n    }}\n")
        lines.extend(methods)
        lines.append("}\n")
        return "\n".join(lines)

    def _jaxb_context_java(self) -> str:
        imports = {"javax.xml.bind.JAXBContext", "javax.xml.bind.JAXBException"}
        class_refs: list[str] = []
        for type_def in sorted(self.model.types.values(), key=lambda item: (self.model.package_for_namespace(item.namespace), item.name)):
            package_name = self.model.package_for_namespace(type_def.namespace)
            imports.add(f"{package_name}.{type_def.name}")
            class_refs.append(f"            {type_def.name}.class")

        lines = [f"package {self.base_package}.service;", ""]
        lines.extend(self._render_imports(imports))
        lines.append("public final class GeneratedJaxbContext {")
        lines.append("    private GeneratedJaxbContext() {\n    }\n")
        lines.append("    public static JAXBContext create() {\n")
        lines.append("        try {\n")
        lines.append("            return JAXBContext.newInstance(\n")
        lines.append(",\n".join(class_refs))
        lines.append("\n            );\n")
        lines.append("        } catch (JAXBException exception) {\n")
        lines.append("            throw new IllegalStateException(\"Unable to initialize JAXBContext\", exception);\n")
        lines.append("        }\n    }\n")
        lines.append("}\n")
        return "\n".join(lines)

    def _java_class_for_element(self, element_ref: QNameRef) -> tuple[str, str]:
        element = self.model.global_elements[element_ref.key]
        package_name = self.model.package_for_namespace(element.type_ref.namespace)
        return f"{package_name}.{element.type_ref.local}", element.type_ref.local

    def _request_context_java(self) -> str:
        return f"""package {self.runtime_package};

import java.util.Objects;

public final class RequestContext {{
    private static final RequestContext EMPTY = new RequestContext(null, null);

    private final String sessionId;
    private final Boolean gwTrace;

    private RequestContext(String sessionId, Boolean gwTrace) {{
        this.sessionId = sessionId;
        this.gwTrace = gwTrace;
    }}

    public static RequestContext empty() {{
        return EMPTY;
    }}

    public static RequestContext of(String sessionId) {{
        return new RequestContext(Objects.requireNonNull(sessionId, "sessionId"), null);
    }}

    public RequestContext withSessionId(String sessionId) {{
        return new RequestContext(sessionId, gwTrace);
    }}

    public RequestContext withGwTrace(Boolean gwTrace) {{
        return new RequestContext(sessionId, gwTrace);
    }}

    public String getSessionId() {{
        return sessionId;
    }}

    public Boolean getGwTrace() {{
        return gwTrace;
    }}
}}
"""

    def _soap_fault_exception_java(self) -> str:
        return f"""package {self.runtime_package};

import java.io.IOException;

public final class SoapFaultException extends IOException {{
    private final String faultCode;
    private final String faultString;
    private final String detail;

    public SoapFaultException(String faultCode, String faultString, String detail) {{
        super(faultCode + ": " + faultString);
        this.faultCode = faultCode;
        this.faultString = faultString;
        this.detail = detail;
    }}

    public String getFaultCode() {{
        return faultCode;
    }}

    public String getFaultString() {{
        return faultString;
    }}

    public String getDetail() {{
        return detail;
    }}
}}
"""

    def _adapter_java(self, class_name: str, target_type: str, parse_expression: str, print_expression: str) -> str:
        simple_type = target_type.rsplit(".", 1)[1]
        return f"""package {self.runtime_package};

import javax.xml.bind.annotation.adapters.XmlAdapter;
import {target_type};

public final class {class_name} extends XmlAdapter<String, {simple_type}> {{
    @Override
    public {simple_type} unmarshal(String value) {{
        if (value == null || value.isBlank()) {{
            return null;
        }}
        return {parse_expression};
    }}

    @Override
    public String marshal({simple_type} value) {{
        if (value == null) {{
            return null;
        }}
        return {print_expression};
    }}
}}
"""

    def _soap_http_client_java(self) -> str:
        return f"""package {self.runtime_package};

import java.io.IOException;
import java.io.StringReader;
import java.io.StringWriter;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import javax.xml.XMLConstants;
import javax.xml.bind.JAXBContext;
import javax.xml.bind.JAXBElement;
import javax.xml.bind.JAXBException;
import javax.xml.bind.Marshaller;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Element;
import org.xml.sax.InputSource;

public abstract class SoapHttpClient {{
    private static final String SOAP_ENVELOPE_NS = "http://schemas.xmlsoap.org/soap/envelope/";
    private static final String TYPES_NS = "{GROUPWISE_TYPES_NS}";

    private final URI endpoint;
    private final HttpClient httpClient;
    private final JAXBContext jaxbContext;

    protected SoapHttpClient(URI endpoint, JAXBContext jaxbContext) {{
        this(endpoint, HttpClient.newBuilder().build(), jaxbContext);
    }}

    protected SoapHttpClient(URI endpoint, HttpClient httpClient, JAXBContext jaxbContext) {{
        this.endpoint = endpoint;
        this.httpClient = httpClient;
        this.jaxbContext = jaxbContext;
    }}

    protected <T> T invoke(String soapAction, Object request, Class<T> responseType, RequestContext context)
            throws IOException, InterruptedException, SoapFaultException {{
        try {{
            var payload = envelope(marshal(request), context == null ? RequestContext.empty() : context);
            var httpRequest = HttpRequest.newBuilder(endpoint)
                    .header("Content-Type", "text/xml; charset=UTF-8")
                    .header("SOAPAction", soapAction)
                    .POST(HttpRequest.BodyPublishers.ofString(payload))
                    .build();

            var response = httpClient.send(httpRequest, HttpResponse.BodyHandlers.ofString());
            return unmarshalBody(response.body(), responseType);
        }} catch (JAXBException exception) {{
            throw new IOException("SOAP marshalling failed", exception);
        }}
    }}

    private String marshal(Object request) throws JAXBException {{
        var marshaller = jaxbContext.createMarshaller();
        marshaller.setProperty(Marshaller.JAXB_FRAGMENT, Boolean.TRUE);
        var writer = new StringWriter();
        marshaller.marshal(request, writer);
        return writer.toString();
    }}

    private <T> T unmarshalBody(String xml, Class<T> responseType) throws IOException, JAXBException, SoapFaultException {{
        var factory = DocumentBuilderFactory.newInstance();
        factory.setNamespaceAware(true);
        try {{
            factory.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
            var document = factory.newDocumentBuilder().parse(new InputSource(new StringReader(xml)));
            var body = firstChild(document.getDocumentElement(), "Body");
            var payload = firstElement(body);
            if (payload == null) {{
                throw new IOException("SOAP response body is empty");
            }}
            if ("Fault".equals(payload.getLocalName())) {{
                throw soapFault(payload);
            }}
            var unmarshaller = jaxbContext.createUnmarshaller();
            JAXBElement<T> result = unmarshaller.unmarshal(payload, responseType);
            return result.getValue();
        }} catch (SoapFaultException exception) {{
            throw exception;
        }} catch (Exception exception) {{
            throw new IOException("SOAP response parsing failed", exception);
        }}
    }}

    private SoapFaultException soapFault(Element fault) {{
        return new SoapFaultException(
                text(firstChild(fault, "faultcode")),
                text(firstChild(fault, "faultstring")),
                text(firstChild(fault, "detail"))
        );
    }}

    private String envelope(String bodyXml, RequestContext context) {{
        var builder = new StringBuilder(256 + bodyXml.length());
        builder.append("<?xml version=\\\"1.0\\\" encoding=\\\"UTF-8\\\"?>");
        builder.append("<soapenv:Envelope xmlns:soapenv=\\\"").append(SOAP_ENVELOPE_NS)
            .append("\\\" xmlns:typ=\\\"").append(TYPES_NS).append("\\\">");
        builder.append("<soapenv:Header>");
        if (context.getSessionId() != null && !context.getSessionId().isBlank()) {{
            builder.append("<typ:session>").append(escape(context.getSessionId())).append("</typ:session>");
        }}
        if (context.getGwTrace() != null) {{
            builder.append("<typ:gwTrace>").append(context.getGwTrace()).append("</typ:gwTrace>");
        }}
        builder.append("</soapenv:Header>");
        builder.append("<soapenv:Body>").append(bodyXml).append("</soapenv:Body>");
        builder.append("</soapenv:Envelope>");
        return builder.toString();
    }}

    private String escape(String value) {{
        return value
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\\\"", "&quot;")
                .replace("'", "&apos;");
    }}

    private Element firstChild(Element parent, String localName) {{
        if (parent == null) {{
            return null;
        }}
        var children = parent.getChildNodes();
        for (var index = 0; index < children.getLength(); index++) {{
            var node = children.item(index);
            if (node instanceof Element) {{
                var element = (Element) node;
                if (localName.equals(element.getLocalName())) {{
                    return element;
                }}
            }}
        }}
        return null;
    }}

    private Element firstElement(Element parent) {{
        if (parent == null) {{
            return null;
        }}
        var children = parent.getChildNodes();
        for (var index = 0; index < children.getLength(); index++) {{
            var node = children.item(index);
            if (node instanceof Element) {{
                return (Element) node;
            }}
        }}
        return null;
    }}

    private String text(Element element) {{
        return element == null ? null : element.getTextContent();
    }}
}}
"""

    def _render_imports(self, imports: Iterable[str]) -> list[str]:
        rendered = [f"import {item};" for item in sorted(imports)]
        return rendered + ([""] if rendered else [])


def write_readme(path: Path) -> None:
    content = """# GroupWise wsdl2java Generator

This repository now contains a Python generator specialized for the WSDL and XSD files in `wsdl/`.

It is intentionally not a general-purpose WSDL compiler.

What it generates:

- JAXB-annotated Java model classes for `types.xsd`, `methods.xsd`, and `events.xsd`
- service interfaces for the two WSDL port types
- Java 14 SOAP clients built on `java.net.http.HttpClient`
- a minimal Gradle project using JAXB as the only external runtime dependency

Usage:

```powershell
c:/Work/Bergt/GWSOAP/GWWS2/.venv/Scripts/python.exe tools/wsdl2java.py --wsdl wsdl/groupwise.wsdl --output generated/groupwise-java14-client
```

The output project will be written to `generated/groupwise-java14-client` by default.
"""
    path.write_text(content, encoding="utf-8")