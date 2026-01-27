FROM gradle:7.3.1-jdk17-alpine AS BUILD
WORKDIR /usr/app/
COPY src/build.gradle ./
RUN gradle dependencies --no-daemon || true
COPY src/ .
RUN gradle build --no-daemon

FROM public.ecr.aws/docker/library/openjdk:11.0.16-jdk
RUN apt-get update && apt-get install -y --no-install-recommends tomcat9 tomcat9-admin libtomcat9-embed-java libtomcat9-java && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /usr/share/tomcat9
RUN mkdir -p webapps conf temp logs work && \
    cp /usr/share/tomcat9/etc/* conf/
COPY --from=BUILD /usr/app/build/libs/*.war webapps/
CMD [ "/usr/share/tomcat9/bin/catalina.sh", "run" ]