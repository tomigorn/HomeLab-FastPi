# OpenNebula — Private Cloud for Self-Service VM Provisioning

> Job interview homework assignment: research, design, and demonstrate OpenNebula as a private IaaS cloud platform for an academic institution.

---

## Table of Contents

- [What is OpenNebula?](#what-is-opennebula)
- [Why OpenNebula?](#why-opennebula)
- [Architecture](#architecture)
- [Deployment Plan](#deployment-plan)
- [User & Access Management](#user--access-management)
- [VM Lifecycle](#vm-lifecycle)
- [Homelab Demo](#homelab-demo)
- [Deliverables Checklist](#deliverables-checklist)

---

## What is OpenNebula?

OpenNebula is an open-source **IaaS (Infrastructure-as-a-Service)** cloud management platform. It abstracts bare-metal hypervisor nodes into a unified compute pool and provides a self-service portal, REST API, and CLI so that end users can provision virtual machines on demand — without IT involvement for every request.

It sits one layer above the hypervisor:

```
Users (web UI / API / CLI)
         ↓
   OpenNebula Front-End
         ↓
KVM Hypervisor Nodes (bare metal)
```

The target use case here: an institution with **10 physical KVM servers** wants to give students and researchers a self-service way to spin up Linux VMs using their existing directory (LDAP/AD) credentials.

---

## Why OpenNebula?

| | OpenNebula | OpenStack | Apache CloudStack <br><br> (was an alternative) |
|---|---|---|---|
| Complexity | Low | Very High | Medium |
| KVM support | Native | Native | Good |
| Small team ops | ✅ | ❌ | ⚠️ |
| LDAP/AD auth | Built-in | via Keystone | Built-in |
| Self-service UI | Sunstone | Horizon | Built-in |

OpenNebula was **probably** chosen because it is significantly easier to deploy and operate than OpenStack/CloudStack for a small-to-medium infrastructure team, while still providing all required features: multi-tenancy, LDAP integration, quotas, and a clean self-service portal.

---

## Architecture

### Component Overview

```
                        ┌─────────────────────────────────┐
                        │         LDAP / AD Server        │
                        │   (existing directory service)  │
                        └──────────────┬──────────────────┘
                                       │ auth
                        ┌──────────────▼──────────────────┐
                        │     OpenNebula Front-End        │
                        │  oned · Sunstone UI · oneauth   │
                        │  MariaDB · OneFlow · FireEdge   │
                        └──┬──────────────────────────┬───┘
                           │  management network      │
          ┌────────────────┼──────────────────────────┼────────────────┐
          │                │                          │                │
  ┌───────▼──────┐  ┌──────▼───────┐           ┌──────▼───────┐  ...   │
  │  KVM Host 1  │  │  KVM Host 2  │           │  KVM Host N  │        │
  │  (libvirt)   │  │  (libvirt)   │           │  (libvirt)   │        │
  └──────┬───────┘  └──────┬───────┘           └──────┬───────┘        │
         │                 │                          │                │
         └─────────────────┴──────────────────────────┘                │
                           │  VM data network (VLANs / bridges)        │
                           │                                           │
              ┌────────────▼────────────────────────────┐              │
              │          Shared Storage                 │              │
              │  (NFS / Ceph / local datastores)        │              │
              └─────────────────────────────────────────┘              │
```

### Key Components

| Component | Role |
|---|---|
| **Front-End** | Runs `oned` (the OpenNebula daemon), Sunstone web UI, scheduler, and auth drivers. One dedicated node. |
| **KVM Hosts** | Hypervisor nodes managed by libvirt. OpenNebula deploys VMs here via SSH. |
| **Datastores** | Image datastore (stores base images), System datastore (running VM disk images). Can be NFS, Ceph, or local. |
| **Virtual Networks** | OpenNebula manages bridge/VLAN networking on the hosts. Each VM Template defines which network to attach to. |
| **Sunstone** | Browser-based self-service portal for end users and admins. |
| **FireEdge** | Modern Next.js-based UI, ships with OpenNebula 6+. Replaces Sunstone long-term. |
| **OneFlow** | Orchestrates multi-VM services (e.g. web tier + DB tier as a single deployable unit). |

### Sunstone vs. FireEdge

OpenNebula ships with two web UIs. Both can run simultaneously — they serve the same backend, so switching between them requires no data migration.

| | Sunstone | FireEdge |
|---|---|---|
| Tech stack | Ruby / Sinatra | Next.js (React) |
| Ships since | OpenNebula 2.x | OpenNebula 6.0 |
| Status | Maintenance mode | Actively developed, long-term replacement |
| VNC / SPICE console | ✅ via noVNC | ✅ via Guacamole |
| Look & feel | Functional, dated | Modern, responsive |
| Feature parity | Complete | Nearly complete (catching up) |
| Default port | 9869 | 2616 |

**Recommendation:** install both, use FireEdge as the primary UI. Sunstone is a useful fallback if a FireEdge feature is missing or during troubleshooting. OpenNebula's own documentation positions FireEdge as the future; Sunstone will eventually be removed. If you only can install one, go with FireEdge.

---

## Deployment Plan

### Prerequisites

- One dedicated **Front-End** machine (can be a VM): 4+ cores, 8GB+ RAM, 50GB disk
- 10 **KVM hypervisor nodes** with libvirt installed and SSH key access from the Front-End
- Shared storage accessible by all hosts (NFS is simplest; Ceph for production)
- Network connectivity between all nodes on a management network

### Step-by-Step

**1. Install OpenNebula Front-End**

There are two ways to deploy the Front-End. **Docker Compose is the preferred approach** for production and for anything committed to Git: the entire configuration is in versioned files, upgrades are a one-line image tag bump, and rollbacks are a `git revert` away. The bare-metal install is simpler for a quick local test but leaves no audit trail and is harder to reproduce.

> ⚠️ Docker only applies to the **Front-End**. KVM hypervisor nodes always run directly on the host OS — KVM requires hardware virtualisation access that containers cannot provide.

---

*Option A — Docker Compose (recommended)*

```yaml
# docker-compose.yaml
# Secrets are read from a .env file in the same directory — never commit .env to Git
services:
  db:
    image: mariadb:10.11
    restart: unless-stopped
    environment:
      MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASSWORD}   # .env / vault
      MYSQL_DATABASE: opennebula
      MYSQL_USER: ${DB_USER}                     # permanent service account used by oned internally
      MYSQL_PASSWORD: ${DB_PASSWORD}             # .env / vault
    volumes:
      - db_data:/var/lib/mysql

  opennebula:
    image: opennebula/opennebula:6.10
    restart: unless-stopped
    depends_on:
      - db
    ports:
      - "9869:9869"   # Sunstone UI
      - "2616:2616"   # FireEdge UI
      - "2633:2633"   # oned API
    volumes:
      - one_data:/var/lib/one
      - ./config:/etc/one          # versioned config files live here
    environment:
      ONE_DB_BACKEND: mysql
      ONE_DB_HOST: db
      ONE_DB_USER: ${DB_USER}       # must match MYSQL_USER above
      ONE_DB_PASSWD: ${DB_PASSWORD} # .env / vault
      ONE_DB_NAME: opennebula

volumes:
  db_data:
  one_data:
```

```bash
# .env (gitignored — never commit this file)
DB_ROOT_PASSWORD=changeme
DB_USER=oneadmin
DB_PASSWORD=changeme
```

```bash
echo ".env" >> .gitignore
docker compose up -d
docker compose logs -f opennebula   # watch until "oned is running"
```

> **Note on the DB user vs. OpenNebula users:** `DB_USER` is an internal service account — `oned` uses it to read/write its own database and it stays active permanently. It has nothing to do with end-user login. LDAP/AD replaces OpenNebula's *authentication layer* for human users; the database service account is separate.

Committing `docker-compose.yaml`, `.gitignore`, and the `./config/` directory to Git gives you full change history for every configuration tweak.

---

*Option B — Direct OS install*

```bash
# Add OpenNebula repo (Ubuntu 22.04 / 24.04)
wget -q -O- https://downloads.opennebula.io/repo/repo2.key | apt-key add -
echo "deb https://downloads.opennebula.io/repo/6.10/Ubuntu/22.04 stable opennebula" \
  > /etc/apt/sources.list.d/opennebula.list

apt update && apt install -y opennebula opennebula-sunstone opennebula-fireedge \
  opennebula-gate opennebula-flow mariadb-server

# Initialize DB
mysql -u root < /usr/share/one/sh/create_db.sql

systemctl enable --now opennebula opennebula-sunstone opennebula-fireedge
```

**2. Generate SSH key on the Front-End**

OpenNebula's `oned` daemon connects to KVM hosts as the `oneadmin` user over SSH. Generate a dedicated keypair on the Front-End:

```bash
# Run on the Front-End, as oneadmin (home is /var/lib/one)
# -C sets a comment embedded in the public key — visible in authorized_keys on every host,
# making it easy to audit which key came from where.
# Convention used here: user@source-host -> target (describes direction of trust)
sudo -u oneadmin ssh-keygen -t ed25519 -f /var/lib/one/.ssh/id_ed25519 -N "" \
  -C "oneadmin@opennebula-frontend -> kvm-nodes"

# Harden permissions — SSH will refuse to use keys if these are too open
chmod 700 /var/lib/one/.ssh
chmod 600 /var/lib/one/.ssh/id_ed25519        # private key: owner read/write only
chmod 644 /var/lib/one/.ssh/id_ed25519.pub    # public key: world-readable is fine
```

The **private key** (`id_ed25519`) never leaves the Front-End. The **public key** (`id_ed25519.pub`) is what gets copied to each KVM host.

We could also do one key per host and name them accordingly with the hardware chassis naming scheme in the server rack, so for instance id_ed25519_kvm-node-01

**3. Prepare KVM Hosts**

> KVM hosts **must run directly on the OS** — KVM requires direct access to `/dev/kvm` (hardware virtualisation), which containers cannot provide. In production, all of these steps would be managed with **Ansible** for reproducibility.

```bash
# On each hypervisor node
apt install -y qemu-kvm libvirt-daemon-system bridge-utils

# Create the oneadmin user with the same UID as on the Front-End
useradd -u 9869 -g 9869 -m -s /bin/bash oneadmin
passwd -l oneadmin   # lock password — SSH key is the only allowed auth method

# Create the .ssh directory and authorized_keys file
mkdir -p /var/lib/one/.ssh
# Paste the contents of /var/lib/one/.ssh/id_ed25519.pub from the Front-End here:
echo "ssh-ed25519 AAAA..." >> /var/lib/one/.ssh/authorized_keys

# Harden permissions — sshd will ignore authorized_keys if these are wrong
chmod 700 /var/lib/one/.ssh
chmod 600 /var/lib/one/.ssh/authorized_keys
chown -R oneadmin:oneadmin /var/lib/one/.ssh
```

Verify the connection from the Front-End before registering hosts:

```bash
# On the Front-End, as oneadmin
ssh -i /var/lib/one/.ssh/id_ed25519 oneadmin@kvm-node-01 hostname
```

**3. Register Hosts in OpenNebula**

```bash
# On the Front-End, as oneadmin
onehost create kvm-node-01 --im kvm --vm kvm
onehost create kvm-node-02 --im kvm --vm kvm
# ... repeat for all 10 nodes

onehost list   # verify all show MONITORED
```

**4. Configure Storage**

```bash
# Create an NFS-backed image datastore
cat > image-ds.conf <<EOF
NAME   = "nfs-images"
DS_MAD = fs
TM_MAD = shared
TYPE   = IMAGE_DS
EOF

onedatastore create image-ds.conf
```

**5. Upload a Base Image**

```bash
# Download an Ubuntu 24.04 cloud image
wget https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img

oneimage create --name "Ubuntu-24.04" \
  --path noble-server-cloudimg-amd64.img \
  --driver qcow2 \
  --datastore nfs-images
```

**6. Create a VM Template**

```bash
cat > student-template.conf <<EOF
NAME   = "Student-Ubuntu-24.04"
CPU    = 2
MEMORY = 4096
DISK   = [ IMAGE = "Ubuntu-24.04", SIZE = 20480 ]
NIC    = [ NETWORK = "student-net" ]
CONTEXT = [
  NETWORK = YES,
  SSH_PUBLIC_KEY = "$USER[SSH_PUBLIC_KEY]"
]
EOF

onetemplate create student-template.conf
onetemplate chmod student-template +604   # make readable by all users
```

**7. Set Quotas per User Group**

```bash
onegroup quota students <<EOF
VM = [ VMS = 3, CPU = 6, MEMORY = 12288 ]
EOF
```

---

## User & Access Management

### How it works

OpenNebula supports **LDAP / Active Directory authentication** natively via the `oneauth` driver. Users authenticate with their existing directory credentials — no separate OpenNebula account needed.

> **LDAP** is a protocol; **Active Directory** is Microsoft's directory service that *speaks* LDAP. OpenNebula's auth driver works with both, but the configuration differs slightly — mainly in field names and how the bind account works.

### Configuration for Active Directory

AD does not allow anonymous queries, so a read-only **service account** is required for OpenNebula to search the directory.

`/etc/one/auth/ldap_auth.conf`:

```yaml
server:
  host: ad.example.org
  port: 636
  encryption: :simple_tls                        # use LDAPS (port 636); for plain LDAP use :plain on 389
  base: "DC=example,DC=org"
  # Service account — read-only AD user for directory lookups (store password in vault, not here)
  user: "CN=svc-opennebula,CN=Users,DC=example,DC=org"
  pass: "service-account-password"
  user_field: sAMAccountName                     # AD uses sAMAccountName, not uid
  group_field: memberOf
  auth_method: :simple

group_mapping:
  - group_dn: "CN=students,OU=Groups,DC=example,DC=org"
    one_group: "students"
  - group_dn: "CN=researchers,OU=Groups,DC=example,DC=org"
    one_group: "researchers"
```

### (optional) Configuration for plain OpenLDAP

For a standard OpenLDAP server (e.g. in a homelab demo), anonymous binds are usually allowed and field names follow POSIX conventions:

```yaml
server:
  host: ldap.example.org
  port: 636
  base: "ou=users,dc=example,dc=org"
  user_field: uid                                # OpenLDAP uses uid
  group_field: memberOf
  auth_method: :simple

group_mapping:
  - group_dn: "cn=students,ou=groups,dc=example,dc=org"
    one_group: "students"
  - group_dn: "cn=researchers,ou=groups,dc=example,dc=org"
    one_group: "researchers"
```

Enable LDAP auth in `/etc/one/oned.conf` (same for both AD and OpenLDAP):

```
AUTH_MAD = [ executable = "one_auth_mad", authn = "ldap,server_cipher,server_x509,x509,ssh,plain" ]
```

### Roles & Permissions

OpenNebula uses a **User → Group → ACL** model:

| Role | Can do |
|---|---|
| `student` | Instantiate templates from the shared catalog, manage own VMs, upload SSH key |
| `researcher` | All of above + create custom templates, manage own images |
| `group-admin` | Manage users within their group, set group-level quotas |
| `admin` | Full access to all resources and configuration |

```bash
# Create the students group
onegroup create students

# Assign ACL: students can instantiate (use) templates
oneacl create "@students USE TEMPLATE/* #0"

# Assign quota to the group
onegroup quota students < quota.conf
```

---

## VM Lifecycle

From a student's perspective, the flow is:

```
1. Log in to Sunstone/FireEdge with LDAP credentials
2. Browse the shared template catalog
3. Click "Instantiate" → optionally set a name / add SSH key
4. VM is scheduled to a KVM host automatically
5. VM boots, cloud-init runs (network config, SSH key injection)
6. Student SSHes in or uses the built-in VNC/SPICE console
7. When done: suspend, snapshot, or terminate
```

### Contextualization (cloud-init)

OpenNebula injects configuration into the VM at boot via a **context ISO**. This handles:

- Network interface configuration
- SSH public key injection from the user's profile
- Custom startup scripts
- Hostname, DNS, NTP

This means students get a fully configured, accessible VM without any manual OS setup.

---