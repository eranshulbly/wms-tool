#!/usr/bin/env bash
# =============================================================================
# WMS Tool - Deploy Script
# Usage: ./deploy.sh <version> <env>
#   ./deploy.sh 1.2.0 prod        → deploy v1.2.0 to production
#   ./deploy.sh 1.1.0 staging     → deploy v1.1.0 to staging
#   ./deploy.sh 1.0.0 dev         → deploy v1.0.0 to dev (build locally)
# =============================================================================
set -euo pipefail

VERSION=${1:-}
ENV=${2:-prod}

# ---- Validation ----
if [[ -z "$VERSION" ]]; then
    echo "ERROR: Version is required."
    echo "Usage: ./deploy.sh <version> <env>"
    echo "Example: ./deploy.sh 1.2.0 prod"
    exit 1
fi

if [[ ! "$ENV" =~ ^(dev|staging|prod)$ ]]; then
    echo "ERROR: env must be one of: dev, staging, prod"
    exit 1
fi

# ---- Map env → compose override file ----
case "$ENV" in
    dev)     OVERRIDE="docker-compose.dev.yml";     ENV_FILE=".env.dev" ;;
    staging) OVERRIDE="docker-compose.staging.yml"; ENV_FILE=".env.staging" ;;
    prod)    OVERRIDE="docker-compose.prod.yml";    ENV_FILE=".env.prod" ;;
esac

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE not found. Copy .env.example to $ENV_FILE and configure it."
    exit 1
fi

# ---- Load current version (for rollback tracking) ----
PREVIOUS_VERSION=$(grep '^APP_VERSION=' "$ENV_FILE" | cut -d'=' -f2 || echo "unknown")

echo "============================================="
echo "  WMS Tool Deployment"
echo "  Environment : $ENV"
echo "  Version     : $VERSION  (was: $PREVIOUS_VERSION)"
echo "  Env file    : $ENV_FILE"
echo "  Compose     : docker-compose.yml + $OVERRIDE"
echo "============================================="
read -rp "Proceed? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

# ---- Update APP_VERSION in env file ----
if grep -q '^APP_VERSION=' "$ENV_FILE"; then
    sed -i.bak "s/^APP_VERSION=.*/APP_VERSION=$VERSION/" "$ENV_FILE"
else
    echo "APP_VERSION=$VERSION" >> "$ENV_FILE"
fi

# ---- Record deployment history ----
HISTORY_FILE=".deployment_history"
echo "$(date -u +"%Y-%m-%dT%H:%M:%SZ")  $ENV  $VERSION  (was: $PREVIOUS_VERSION)  by: $(git config user.name 2>/dev/null || echo unknown)" >> "$HISTORY_FILE"

# ---- Pull images (skipped for dev which builds locally) ----
if [[ "$ENV" != "dev" ]]; then
    echo ">>> Pulling images for version $VERSION..."
    APP_VERSION="$VERSION" docker-compose -f docker-compose.yml -f "$OVERRIDE" --env-file "$ENV_FILE" pull backend frontend
fi

# ---- Deploy ----
echo ">>> Starting services..."
APP_VERSION="$VERSION" docker-compose -f docker-compose.yml -f "$OVERRIDE" --env-file "$ENV_FILE" up -d

# ---- Health check ----
echo ">>> Waiting for backend health check..."
RETRIES=20
until curl -sf http://localhost:${HEALTH_PORT:-80}/health > /dev/null 2>&1; do
    RETRIES=$((RETRIES - 1))
    if [[ $RETRIES -le 0 ]]; then
        echo "ERROR: Health check failed after deployment. Rolling back to $PREVIOUS_VERSION..."
        sed -i.bak "s/^APP_VERSION=.*/APP_VERSION=$PREVIOUS_VERSION/" "$ENV_FILE"
        APP_VERSION="$PREVIOUS_VERSION" docker-compose -f docker-compose.yml -f "$OVERRIDE" --env-file "$ENV_FILE" up -d
        echo "Rolled back to $PREVIOUS_VERSION."
        exit 1
    fi
    echo "  Waiting... ($RETRIES retries left)"
    sleep 3
done

echo "============================================="
echo "  Deployed successfully: v$VERSION on $ENV"
echo "============================================="
