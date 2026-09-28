#!/bin/bash
set -e

# ==============================================================================
# ISRO SIH26170 Container Bootstrap Entrypoint
# ==============================================================================

echo "=========================================================="
echo "  ISRO SIH26170 Semiconductor Screening & Analytics"
echo "  Container Bootstrap & Service Initializer"
echo "=========================================================="

python scripts/bootstrap.py "$@"
