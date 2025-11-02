FROM jenkins/jenkins:lts

USER root

# ---------------------------------------------------------
# 🧩 1. Install Docker CLI inside the Jenkins container
# ---------------------------------------------------------
RUN apt-get update && \
    apt-get install -y ca-certificates curl gnupg lsb-release && \
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
      https://download.docker.com/linux/debian \
      $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" \
      > /etc/apt/sources.list.d/docker.list && \
    apt-get update && apt-get install -y docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------
# 🧩 1b. Add Jenkins user to Docker group
#
# find out the GID of the host machine's docker group and add jenkins user to that group
# $ ls -l /var/run/docker.sock
# srw-rw---- 1 root docker 0 Oct 20 09:15 /var/run/docker.sock
# $ getent group docker 
# docker:x:991:pi
# ---------------------------------------------------------
RUN groupadd -g 991 docker || true
RUN usermod -aG docker jenkins

# ---------------------------------------------------------
# 🧩 2. Install Jenkins plugins from list
# ---------------------------------------------------------
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

# ---------------------------------------------------------
# 🧩 3. Copy Configuration as Code and init scripts
# ---------------------------------------------------------
COPY casc_configs /var/jenkins_home/casc_configs
COPY init.groovy.d /usr/share/jenkins/ref/init.groovy.d

# ---------------------------------------------------------
# 🧩 4. Fix ownership
# ---------------------------------------------------------
RUN chown -R jenkins:jenkins /var/jenkins_home /usr/share/jenkins/ref/init.groovy.d

USER jenkins

# Image ready to run; Jenkins will read JCasC from CASC_JENKINS_CONFIG env var
