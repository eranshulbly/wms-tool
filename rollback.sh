#!/usr/bin/env bash
# =============================================================================
# WMS Tool - Rollback Script
# Usage: ./rollback.sh <env>
#   Rolls back to the previous version recorded in .deployment_history
#   Or specify a version: ./rollback.sh prod 1.0.0
# =============================================================================
set -euo pipefail

ENV=${1:-prod}
TARGET_VERSION=${2:-}   # optional: explicit version to roll back to

if [[ ! "$ENV" =~ ^(dev|staging|prod)$ ]]; then
    echo "ERROR: env must be: dev | staging | prod"
    exit 1
fi

HISTORY_FILE=".deployment_history"
if [[ ! -f "$HISTORY_FILE" ]]; then
    echo "ERROR: No deployment history found. Cannot auto-rollback."
    echo "Specify version manually: ./rollback.sh $ENV <version>"
    exit 1
fi

# ---- Find the previous version for this environment ----
if [[ -z "$TARGET_VERSION" ]]; then
    # Get the second-to-last entry for this environment
    CURRENT_LINE=$(grep "  $ENV  " "$HISTORY_FILE" | tail -1)
    CURRENT_VERSION=$(echo "$CURRENT_LINE" | awk '{print $3}')

    PREVIOUS_LINE=$(grep "  $ENV  " "$HISTORY_FILE" | tail -2 | head -1)
    TARGET_VERSION=$(echo "$PREVIOUS_LINE" | awk '{print $3}')

    if [[ -z "$TARGET_VERSION" || "$TARGET_VERSION" == "$CURRENT_VERSION" ]]; then
        echo "ERROR: Could not find a previous version to roll back to for env '$ENV'."
        echo "Deployment history for $ENV:"
        grep "  $ENV  " "$HISTORY_FILE" || echo "  (none)"
        exit 1
    fi
fi

echo "============================================="
echo "  WMS Tool Rollback"
echo "  Environment : $ENV"
echo "  Target      : v$TARGET_VERSION"
echo "============================================="
read -rp "Proceed with rollback? [y/N] " confirm
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 0; }

# Delegate to deploy.sh
./deploy.sh "$TARGET_VERSION" "$ENV"
