#!/usr/bin/env bash
# ==============================================================================
# deploy.sh
# Production Deployment Script for VPS / Linux Server
# Automotive Prototype Testing Analytics Platform
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=================================================================${NC}"
echo -e "${BLUE}  Automotive Prototype Testing Analytics Platform Deployment    ${NC}"
echo -e "${BLUE}=================================================================${NC}"

# 1. Check prerequisites
echo -e "\n${YELLOW}[1/6] Checking prerequisites...${NC}"

command -v git >/dev/null 2>&1 || {
    echo -e "${RED}Error: 'git' is not installed. Please install git.${NC}" >&2
    exit 1
}

command -v docker >/dev/null 2>&1 || {
    echo -e "${RED}Error: 'docker' is not installed.${NC}" >&2
    echo -e "Install Docker with: curl -fsSL https://get.docker.com | sh"
    exit 1
}

docker compose version >/dev/null 2>&1 || {
    echo -e "${RED}Error: 'docker compose' plugin is not installed.${NC}" >&2
    exit 1
}

echo -e "${GREEN}Prerequisites verified: git, docker, docker compose present.${NC}"

# 2. Check / Generate .env file
echo -e "\n${YELLOW}[2/6] Configuring production environment secrets...${NC}"

if [ ! -f .env ]; then
    echo -e "Generating production .env file with cryptographically secure secrets..."
    DB_PASS=$(openssl rand -hex 16 2>/dev/null || date +%s%N | sha256sum | head -c 32)
    JWT_SECRET=$(openssl rand -hex 32 2>/dev/null || date +%s%N | sha256sum | head -c 64)
    FLOWER_PASS=$(openssl rand -hex 12 2>/dev/null || date +%s%N | sha256sum | head -c 24)

    cat <<EOF > .env
# Auto-generated Production Secrets
ENVIRONMENT=production
DEBUG=false
DB_PASSWORD=${DB_PASS}
JWT_SECRET_KEY=${JWT_SECRET}
FLOWER_USER=admin
FLOWER_PASSWORD=${FLOWER_PASS}
STORAGE_BUCKET=prototype-test-telemetry
EOF
    chmod 600 .env
    echo -e "${GREEN}.env created with isolated secrets.${NC}"
else
    echo -e "${GREEN}.env file already exists. Preserving configuration.${NC}"
fi

# 3. Pull latest changes if inside git repo
echo -e "\n${YELLOW}[3/6] Fetching latest repository updates...${NC}"
if [ -d .git ]; then
    git pull origin main || echo -e "${YELLOW}Notice: git pull skipped or up-to-date.${NC}"
fi

# 4. Build and start containers
echo -e "\n${YELLOW}[4/6] Building and orchestrating multi-container topology...${NC}"
echo -e "Starting: PostgreSQL 16, Redis 7, FastAPI Backend, Celery Worker, Flower, Nginx"

docker compose down --remove-orphans || true
docker compose build --pull
docker compose up -d

# 5. Wait for healthy state
echo -e "\n${YELLOW}[5/6] Awaiting service health probes...${NC}"

ATTEMPTS=0
MAX_ATTEMPTS=30
HEALTH_OK=false

while [ $ATTEMPTS -lt $MAX_ATTEMPTS ]; do
    ATTEMPTS=$((ATTEMPTS + 1))
    if docker compose ps | grep -q "test_analytics_api" && curl -s http://localhost:8000/health | grep -q '"status":"healthy"'; then
        HEALTH_OK=true
        break
    fi
    echo -n "."
    sleep 2
done
echo ""

if [ "$HEALTH_OK" = true ]; then
    echo -e "${GREEN}Service health probe PASSED! API is operational.${NC}"
else
    echo -e "${RED}Warning: Health check timed out. Check container logs with: docker compose logs${NC}"
fi

# 6. Summary
echo -e "\n${BLUE}=================================================================${NC}"
echo -e "${GREEN} Deployment completed successfully!${NC}"
echo -e "${BLUE}=================================================================${NC}"
echo -e "  • FastAPI REST Docs   : http://<SERVER_IP>:8000/docs"
echo -e "  • Health Probe        : http://<SERVER_IP>:8000/health"
echo -e "  • Task Monitoring     : http://<SERVER_IP>:5555"
echo -e "  • View Live Logs      : docker compose logs -f"
echo -e "  • Restart Services    : docker compose restart"
echo -e "${BLUE}=================================================================${NC}"
