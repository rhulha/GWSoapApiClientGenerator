# GroupWise WSDL Tools

`tools/wsdl2java.py` is a custom generator for the WSDL and XSD files in `wsdl/`.
`tools/wsdl2python.py` follows the same parser/model pipeline and emits Python code.

It is intentionally not a general-purpose WSDL compiler.

What it generates:

- JAXB-annotated Java model classes for `types.xsd`, `methods.xsd`, and `events.xsd`
- service interfaces for the two WSDL port types
- Java 14 SOAP clients built on `java.net.http.HttpClient`
- a minimal Gradle project using JAXB as the only external runtime dependency

Usage:

```
python tools/wsdl2java.py --wsdl wsdl/groupwise.wsdl --output generated/groupwise-java14-client
```

The output project will be written to `generated/groupwise-java14-client` by default.

Python generator usage:

```
python tools/wsdl2python.py --wsdl wsdl/groupwise.wsdl --output generated/groupwise-python-client
```

The Python package will be written to `generated/groupwise-python-client` by default.
