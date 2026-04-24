gradle compileTestJava
gradle runConnectionTest
 gradle jar produces build/libs/groupwise-java14-client-1.0.0-SNAPSHOT.jar (~424 KB).

 The JAR contains only the library classes — it does not bundle JAXB. Consumers need javax.xml.bind:jaxb-api:2.3.1 on their compile classpath and org.glassfish.jaxb:jaxb-runtime:2.3.8 at runtime (that's what the Gradle dependencies block declares).

All four artifacts built in build/libs/:

Task	File	Size	Contents
gradle jar	...-SNAPSHOT.jar	~424 KB	Library classes only
gradle sourcesJar	...-SNAPSHOT-sources.jar	~269 KB	Generated .java sources
gradle javadocJar	...-SNAPSHOT-javadoc.jar	~1.7 MB	Javadoc HTML
gradle fatJar	...-SNAPSHOT-all.jar	~1.7 MB	Self-contained — includes JAXB
Build all at once with gradle build fatJar.

javadoc is set to Xdoclint:none and failOnError=false — the generated code has no doc comments so strict doclint would fail. fatJar excludes JAR signature files so the bundled JAXB doesn't cause a "SHA-256 digest mismatch" when run.