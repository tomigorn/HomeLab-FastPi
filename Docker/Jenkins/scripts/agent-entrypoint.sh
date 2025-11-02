#!/bin/bash
set -e

if [ -f "/run/secrets/agent1_secret" ]; then
  AGENT_SECRET=$(cat /run/secrets/agent1_secret)
else
  echo "ERROR: agent secret file not found!"
  exit 1
fi

exec java -jar /usr/share/jenkins/agent.jar \
  -url "${JENKINS_URL}" \
  -name "${JENKINS_AGENT_NAME}" \
  -secret "$AGENT_SECRET" \
  -workDir "$JENKINS_AGENT_WORKDIR" \
  -webSocket
