FROM neo4j:5.26-community

ADD --checksum=sha256:509bec192befce6224a7e3bf78a0e6b74aeb8bf61eb7a1e009b7b62e0737900b \
    https://github.com/neo4j-labs/neosemantics/releases/download/5.26.0/neosemantics-5.26.0.jar \
    /var/lib/neo4j/plugins/neosemantics-5.26.0.jar

RUN set -eux; \
    cp /var/lib/neo4j/labs/apoc-*-core.jar /var/lib/neo4j/plugins/; \
    chown -R neo4j:neo4j /var/lib/neo4j/plugins

COPY deploy/neo4j/apoc.conf /var/lib/neo4j/conf/apoc.conf
RUN chown neo4j:neo4j /var/lib/neo4j/conf/apoc.conf
