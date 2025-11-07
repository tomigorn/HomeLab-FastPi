# Jenkins JDK 21
FROM jenkins/jenkins:latest-jdk21

# Allow timezone to be provided at build/run time
ARG TZ="Europe/Zurich"

USER root

RUN apt-get update && apt-get install -y lsb-release

RUN curl -fsSLo /usr/share/keyrings/docker-archive-keyring.asc \
  https://download.docker.com/linux/debian/gpg

RUN echo "deb [arch=$(dpkg --print-architecture) \
  signed-by=/usr/share/keyrings/docker-archive-keyring.asc] \
  https://download.docker.com/linux/debian \
  $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list

RUN apt-get update && apt-get install -y docker-ce-cli

RUN apt update && apt install tzdata -y

ENV TZ=${TZ}
ENV JAVA_OPTS "-Djenkins.install.runSetupWizard=false ${JAVA_OPTS:-}"

COPY jenkins/plugins.txt /usr/share/jenkins/ref/plugins.txt
USER root
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt || true
USER jenkins