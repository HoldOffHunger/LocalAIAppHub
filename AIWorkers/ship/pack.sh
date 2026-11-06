#!/bin/bash
# Fumiko (WSL, root): pack a site for prod after warm_site.sh. The named tables from int's database, the warmed pages,
# and int's checksums from before the work, for swap_tables.sh to guard with. Pictures only with --images.
#   bash pack.sh revoltlib.com revoltlib /mnt/d/rl-ship before.txt "Quote TextBody Entry ..." [--images]
set -euo pipefail
site=${1:?domain} db=${2:?database} out=${3:?output folder} before=${4:?int checksums taken before the work} tables=${5:?tables}
mkdir -p "$out"
# shellcheck disable=SC2086
mysqldump --single-transaction --add-drop-table --default-character-set=utf8mb4 "$db" $tables | gzip > "$out/tables.sql.gz"
tar -czf "$out/pages.tgz" -C /root/warm-pages "$site"
[ "${6:-}" = "--images" ] && tar -czf "$out/images.tgz" -C "/srv/ggcms/$site/www" image
cp "$before" "$out/before.txt"
echo "$tables" > "$out/tables.txt"
ls -la "$out"
