# Traefik Wake-on-Demand Setup

## Overview
This setup implements intelligent power management for your homelab:
- **FastPi (Raspberry Pi)**: Runs 24/7 with Traefik proxy + Node-RED + WOL API
- **Beefy Server**: Sleeps when idle, wakes automatically when accessed

## Architecture Flow
1. User requests service (e.g., `http://service.fastpi.local`)
2. Traefik intercepts via `wake-on-demand` middleware
3. Node-RED checks if beefy server is awake (health check)
4. If sleeping: sends WOL packet, waits up to 60s for wake
5. Once awake: Traefik forwards request to actual service

## Setup Steps

### 1. Configure Your Environment
```bash
cp .env.example .env
# Edit .env with your timezone and settings
```

### 2. Find Your Beefy Server's MAC Address
On the beefy server, run:
```bash
ip link show | grep -A1 "eth0\|enp"
# Look for the MAC address (format: aa:bb:cc:dd:ee:ff)
```

### 3. Update Configuration
Edit these files with your actual values:

**dynamic.yaml**: Update the IP address and service details
**node-red/flow.json**: Replace `AA:BB:CC:DD:EE:FF` with your actual MAC
**scripts/enhanced-hibernate.sh**: Adjust hibernation logic if needed

### 4. Set Up SSH Key Authentication
Ensure your Pi can SSH to beefy server without password:
```bash
ssh-copy-id buntu@192.168.1.102
# Test: ssh buntu@192.168.1.102 'echo "SSH works"'
```

### 5. Configure Beefy Server for WOL
On your beefy server:
```bash
# Enable WOL in network settings
sudo ethtool -s eth0 wol g

# Make it persistent (add to /etc/systemd/system/wol.service)
sudo systemctl enable wol.service
```

### 6. Deploy Services on Beefy Server
Your beefy server needs a health endpoint. Example Docker service:
```yaml
services:
  your-service:
    image: your-app
    ports:
      - "8080:8080"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 10s
```

### 7. Start the Stack
```bash
docker-compose up -d
```

### 8. Configure Hibernation (Optional)
Add a cron job on the Pi to automatically hibernate the beefy server:
```bash
# Run every hour, hibernate if idle for 2+ hours
0 * * * * /home/pi/Projects/Docker/Traefik/scripts/enhanced-hibernate.sh
```

## Testing

### Test WOL API
```bash
curl -X POST http://localhost:5000/wol \
  -H "Content-Type: application/json" \
  -d '{"mac":"AA:BB:CC:DD:EE:FF"}'
```

### Test Wake-on-Demand
```bash
# This should wake the server if sleeping
curl -v http://service.fastpi.local
```

### Check Traefik Dashboard
Visit: http://fastpi.local:8080

## Troubleshooting

### Common Issues:
1. **WOL doesn't work**: Check if beefy server's BIOS/UEFI has WOL enabled
2. **SSH fails**: Verify key authentication works manually
3. **Health check fails**: Ensure your service exposes `/health` endpoint
4. **Timeout issues**: Increase `WAKE_TIMEOUT` in .env

### Logs:
```bash
# Traefik logs
docker-compose logs traefik

# Node-RED flows debug
docker-compose logs nodered

# WOL API logs  
docker-compose logs wol-api
```

## Customization

### Add More Services
1. Add entries to `dynamic.yaml`
2. Create corresponding health checks
3. Update Node-RED flow if needed

### Change Wake Timeout
Edit `WAKE_TIMEOUT` in `.env` file

### Different Hibernation Logic
Modify `scripts/enhanced-hibernate.sh` to check different conditions
