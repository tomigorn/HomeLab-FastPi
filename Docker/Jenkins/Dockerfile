FROM jenkins/jenkins:lts

USER root

# Copy plugin list and install plugins non-interactively
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

# Copy Configuration as Code and init scripts into the image
COPY casc_configs /var/jenkins_home/casc_configs
COPY init.groovy.d /usr/share/jenkins/ref/init.groovy.d

# Fix ownership
RUN chown -R jenkins:jenkins /var/jenkins_home /usr/share/jenkins/ref/init.groovy.d

USER jenkins

# Image ready to run; Jenkins will read JCasC from CASC_JENKINS_CONFIG env var
