#!/bin/bash
# Deployment script for Telegram IPTV Bot Ultra Pro
# This script builds and deploys the bot using Docker Compose

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Starting deployment of Telegram IPTV Bot...${NC}"

# Check if .env exists, if not copy from .env.example
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        echo -e "${YELLOW}.env not found, copying from .env.example${NC}"
        cp .env.example .env
        echo -e "${RED}Please edit .env with your configuration before proceeding!${NC}"
        exit 1
    else
        echo -e "${RED}Error: .env.example not found!${NC}"
        exit 1
    fi
fi

# Build and start containers
echo -e "${YELLOW}Building Docker image...${NC}"
docker-compose build

echo -e "${YELLOW}Starting services...${NC}"
docker-compose up -d

echo -e "${GREEN}Deployment completed!${NC}"
echo -e "${YELLOW}To view logs: docker-compose logs -f${NC}"
echo -e "${YELLOW}To stop: docker-compose down${NC}"