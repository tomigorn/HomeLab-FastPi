docker network create jenkins

create agent secret with:
openssl rand -hex 32 > ./secrets/agents/agent1.secret
