#!/bin/bash
# Prod: swap a shipped bundle's tables in, as RevoltLib's quotes went live on 24 Oct 2026.
#  1. Guard: every shipped content table must still match int's checksum from before the work, or it stops. Stats
#     tables (*RecordStats) are caches the warm rebuilt, so they aren't guarded.
#  2. Backup: a dump of exactly what is about to be replaced, in the site's backup folder.
#  3. The bundle loads into <db>_incoming beside the live tables and swaps in with one atomic RENAME; the old tables
#     stay in <db>_before_ship as the instant undo. Visitors never see a half-loaded table.
#   bash swap_tables.sh /mnt/nyc01/rl-ship revoltlib revoltlib.com
set -euo pipefail
ship=${1:?bundle folder} db=${2:?database} site=${3:?domain}
cd "$ship"
gzip -t tables.sql.gz
tables=$(cat tables.txt)
for t in $tables; do
	case "$t" in *RecordStats) continue ;; esac
	want=$(awk -v t="$t" '$1 == t {print $2}' before.txt | tr -d '\r')
	have=$(mysql -N -B "$db" -e "CHECKSUM TABLE \`$t\`" | awk '{print $2}')
	[ -n "$want" ] && [ "$want" = "$have" ] || { echo "STOP: prod's $t changed since int's copy ($have, expected $want)"; exit 1; }
done
echo "guard: prod's tables match int's starting point"
backup=/mnt/nyc01/ggcms_sql_backups/$site
mkdir -p "$backup"
# shellcheck disable=SC2086
mysqldump --single-transaction --set-gtid-purged=OFF "$db" $tables | gzip > "$backup/before-ship-$(date +%Y%m%d-%H%M%S).sql.gz"
mysql -e "DROP DATABASE IF EXISTS ${db}_incoming; CREATE DATABASE ${db}_incoming; DROP DATABASE IF EXISTS ${db}_before_ship; CREATE DATABASE ${db}_before_ship"
gunzip -c tables.sql.gz | mysql "${db}_incoming"
renames=""
for t in $tables; do renames="$renames \`$db\`.\`$t\` TO \`${db}_before_ship\`.\`$t\`, \`${db}_incoming\`.\`$t\` TO \`$db\`.\`$t\`,"; done
mysql -e "RENAME TABLE ${renames%,}"
mysql -e "DROP DATABASE ${db}_incoming"
echo "swapped: $tables (old tables in ${db}_before_ship)"
