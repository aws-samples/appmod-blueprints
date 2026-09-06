FROM gradle:7.3.1-jdk17-alpine AS BUILD
WORKDIR /usr/app/
COPY src/build.gradle ./
RUN gradle dependencies --no-daemon || true
COPY src/ .
RUN gradle build --no-daemon

# Runtime: official Tomcat 9 + JDK 11 image (public ECR mirror).
# Replaces the previous `apt-get install tomcat9` on the deprecated
# openjdk:11.0.16-jdk (Debian bullseye) base. That approach 404s when the
# bullseye-security mirror purges the old point-release .debs still referenced
# by tomcat9's strict-versioned dependencies (libsystemd0, libavahi-common-data,
# libtomcat9-embed-java) — and `apt-get update` does NOT fix it (the index lists
# a version whose .deb is already gone from the pool). The official Tomcat image
# ships a consistent Tomcat 9 + JDK 11 and needs no apt at all.
FROM public.ecr.aws/docker/library/tomcat:9-jdk11
COPY --from=BUILD /usr/app/build/libs/*.war /usr/local/tomcat/webapps/
# CMD inherited from the base image: catalina.sh run (CATALINA_HOME=/usr/local/tomcat)