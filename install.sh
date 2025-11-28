#!/bin/bash
# NextDNS Blocker - Install

set -e

AUDIT_DIR="$HOME/.local/share/nextdns-audit/logs"

echo ""
echo "  nextdns-blocker install"
echo "  -----------------------"
echo ""

# Ask for install directory
DEFAULT_DIR="$(cd "$(dirname "$0")" && pwd)"
read -p "  install path [$DEFAULT_DIR]: " INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_DIR}"
echo ""

# Check Python 3
echo "  [1/7] python3"
if ! command -v python3 &> /dev/null; then
    sudo yum install -y python3 || sudo apt-get install -y python3
fi

# Check pip
echo "  [2/7] pip"
if ! command -v pip3 &> /dev/null; then
    sudo yum install -y python3-pip || sudo apt-get install -y python3-pip
fi

# Verify directory
echo "  [3/7] directory"
if [ ! -d "$INSTALL_DIR" ]; then
    echo "  error: $INSTALL_DIR not found"
    exit 1
fi
cd "$INSTALL_DIR"

# Install dependencies
echo "  [4/7] dependencies"
pip3 install -r requirements.txt --user --quiet

# Verify config files
echo "  [5/7] config"
if [ ! -f "$INSTALL_DIR/.env" ]; then
    echo "  error: .env not found"
    exit 1
fi

# Check for domains.json OR DOMAINS_URL
source "$INSTALL_DIR/.env"
if [ ! -f "$INSTALL_DIR/domains.json" ] && [ -z "$DOMAINS_URL" ]; then
    echo "  error: domains.json not found and DOMAINS_URL not set"
    echo "         provide either a local domains.json or set DOMAINS_URL in .env"
    exit 1
fi
if [ -n "$DOMAINS_URL" ]; then
    echo "         using remote: $DOMAINS_URL"
elif [ -f "$INSTALL_DIR/domains.json" ]; then
    echo "         using local: domains.json"
fi

# Validate API credentials
echo "  [6/7] validating API"
if [ -z "$NEXTDNS_API_KEY" ] || [ -z "$NEXTDNS_PROFILE_ID" ]; then
    echo "  error: NEXTDNS_API_KEY or NEXTDNS_PROFILE_ID not set in .env"
    exit 1
fi

API_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "X-Api-Key: $NEXTDNS_API_KEY" \
    "https://api.nextdns.io/profiles/$NEXTDNS_PROFILE_ID")

if [ "$API_RESPONSE" != "200" ]; then
    echo "  error: API validation failed (HTTP $API_RESPONSE)"
    echo "         Check your API key and profile ID"
    exit 1
fi
echo "         credentials valid"

# Create directories and set permissions
echo "  [7/7] setup"
mkdir -p "$AUDIT_DIR"
chmod +x nextdns_blocker.py watchdog.py

# Create wrapper scripts
cat > blocker << 'WRAPPER'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/nextdns_blocker.py" "$@"
WRAPPER
chmod +x blocker

cat > watchdog << 'WRAPPER'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
python3 "$SCRIPT_DIR/watchdog.py" "$@"
WRAPPER
chmod +x watchdog

# Setup cron jobs
CRON_SYNC="*/2 * * * * cd $INSTALL_DIR && ./blocker sync >> $AUDIT_DIR/cron.log 2>&1"
CRON_WD="* * * * * cd $INSTALL_DIR && ./watchdog check >> $AUDIT_DIR/wd.log 2>&1"

crontab -l 2>/dev/null | grep -v "blocker" | grep -v "watchdog" | grep -v "nextdns" | crontab - 2>/dev/null || true
(crontab -l 2>/dev/null; echo "$CRON_SYNC"; echo "$CRON_WD") | crontab -

# Run initial sync
echo ""
echo "  syncing..."
./blocker sync || true

# Done
echo ""
echo "  done"
echo ""
echo "  files"
echo "    blocker        main script"
echo "    watchdog       cron protector"
echo "    .env           credentials"
echo ""
echo "  schedule"
echo "    sync           every 2 min"
echo "    watchdog       every 1 min"
echo ""
echo "  commands"
echo "    ./blocker status"
echo "    ./blocker sync"
echo "    ./watchdog status"
echo ""
