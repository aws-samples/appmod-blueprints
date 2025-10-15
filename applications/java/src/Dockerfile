FROM gradle:7.3.1-jdk17-alpine AS BUILD
WORKDIR /usr/app/
COPY src/ .
RUN gradle build

FROM public.ecr.aws/docker/library/openjdk:11.0.16-jdk
RUN apt-get update && apt-get install -y unzip && apt-get install -y tomcat9 tomcat9-admin libtomcat9-embed-java libtomcat9-java
ENV APP_HOME=/usr/app/
WORKDIR $APP_HOME
RUN mkdir /usr/share/tomcat9/webapps
RUN mkdir /usr/share/tomcat9/conf/
RUN mkdir /usr/share/tomcat9/temp/
RUN mkdir /usr/share/tomcat9/logs
RUN mkdir /usr/share/tomcat9/work
COPY --from=BUILD $APP_HOME/build/libs/*.war /usr/share/tomcat9/webapps/.
WORKDIR /usr/share/tomcat9
RUN cp /usr/share/tomcat9/etc/* /usr/share/tomcat9/conf/.
CMD [ "/usr/share/tomcat9/bin/catalina.sh", "run" ]