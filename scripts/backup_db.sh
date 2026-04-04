#!/bin/bash
# Backs up drafts.db to the private eventsnap-backup repo.
# Only runs when the database has changed since the last backup.

set -euo pipefail

DB_PATH="/home/johan/eventsnap/drafts.db"
BACKUP_REPO="/home/johan/eventsnap-backup"
CHECKSUM_FILE="$BACKUP_REPO/.last_checksum"

# Compute current checksum
CURRENT=$(md5sum "$DB_PATH" | awk '{print $1}')
PREVIOUS=$(cat "$CHECKSUM_FILE" 2>/dev/null || echo "")

if [ "$CURRENT" = "$PREVIOUS" ]; then
    echo "$(date '+%Y-%m-%d %H:%M') No changes detected, skipping backup."
    exit 0
fi

echo "$(date '+%Y-%m-%d %H:%M') Database changed, starting backup..."

# Copy DB and update checksum
cp "$DB_PATH" "$BACKUP_REPO/drafts.db"
echo "$CURRENT" > "$CHECKSUM_FILE"

# Commit and push
cd "$BACKUP_REPO"
git add drafts.db .last_checksum
git commit -m "Backup $(date '+%Y-%m-%d %H:%M')"
git push

echo "$(date '+%Y-%m-%d %H:%M') Backup complete."
