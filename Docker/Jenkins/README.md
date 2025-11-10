create agent secret with:
openssl rand -hex 32 > ./secrets/agents/agent1.secret

# create the deploy user with a home dir and bash shell, without adding sudo
sudo adduser --gecos "" --disabled-password deploy

# (optional) set a password if you need interactive login: not required for key-based auth
# sudo passwd deploy

# Create .ssh and set correct permissions
sudo mkdir -p /home/deploy/.ssh
sudo chown deploy:deploy /home/deploy/.ssh
sudo chmod 700 /home/deploy/.ssh

# Add the deploy user to the docker group so it can run docker without sudo
sudo usermod -aG docker deploy

# If you want a dedicated OS group to control SSH access, create one and add the user:
# (only do this if you will also adjust sshd_config to allow the group)
sudo groupadd -f deploy-ssh
sudo usermod -aG deploy-ssh deploy