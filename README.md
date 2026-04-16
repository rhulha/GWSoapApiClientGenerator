# GroupWise WSDL Tools

`tools/wsdl2java.py` is a custom generator for the WSDL and XSD files in `wsdl/`.

It generates a Java 14 Gradle project with:

- JAXB model classes for the imported schemas
- interfaces for the two WSDL port types
- `HttpClient`-based SOAP clients

Run it like this:

```powershell
c:/Work/Bergt/GWSOAP/GWWS2/.venv/Scripts/python.exe tools/wsdl2java.py --wsdl wsdl/groupwise.wsdl --output generated/groupwise-java14-client
```