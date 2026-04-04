#!/bin/bash
# Restores drafts.db from the eventsnap-backup repo.
#
# Usage:
#   ./restore_db.sh           — restore latest backup
#   ./restore_db.sh <commit>  — restore a specific commit (e.g. abc1234)

set -euo pipefail

DB_PATH="/home/johan/eventsnap/drafts.db"
BACKUP_REPO="/home/johan/eventsnap-backup"
COMMIT="${1:-HEAD}"

echo "Stopping EventSnap service..."
sudo systemctl stop eventsnap

# Pull latest from backup repo
cd "$BACKUP_REPO"
git fetch origin

if [ "$COMMIT" = "HEAD" ]; then
    git checkout main
    git pull
    echo "Restoring latest backup ($(git log -1 --format='%h %s'))..."
else
    echo "Restoring backup at commit $COMMIT..."
    git checkout "$COMMIT" -- drafts.db
fi

# Create a safety copy of the current DB before overwriting
if [ -f "$DB_PATH" ]; then
    cp "$DB_PATH" "${DB_PATH}.before_restore"
    echo "Current database saved as drafts.db.before_restore"
fi

cp "$BACKUP_REPO/drafts.db" "$DB_PATH"

# Update checksum to match restored file
md5sum "$DB_PATH" | awk '{print $1}' > "$BACKUP_REPO/.last_checksum"

echo "Starting EventSnap service..."
sudo systemctl start eventsnap
sleep 2
sudo systemctl is-active eventsnap

echo "Restore complete."
echo ""
echo "To list available backups: cd $BACKUP_REPO && git log --oneline"
