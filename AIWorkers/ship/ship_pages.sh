#!/bin/bash
# Prod: lay a bundle's warmed pages (and pictures, if it has them) over the live site with no empty-cache gap. Pages
# Fumiko didn't render this time -- deleted entries -- are older than the marker and go.
#   bash ship_pages.sh /mnt/nyc01/rl-ship revoltlib.com
set -euo pipefail
ship=${1:?bundle folder} site=${2:?domain}
cache=/mnt/nyc01/ggcms_cache/pages
cd "$ship"
if [ -f images.tgz ]; then
	tar -xzf images.tgz -C "/srv/ggcms/$site/www"
	chown -R www-data:root "/srv/ggcms/$site/www/image"
	chmod -R u+rwX,go+rX "/srv/ggcms/$site/www/image"
fi
gzip -t pages.tgz
touch marker
sleep 1
tar -xzmf pages.tgz -C "$cache"
chown -R www-data:www-data "$cache/$site"
removed=$(find "$cache/$site" -type f \( -name '*.html' -o -name '*.html.gz' \) ! -newer marker -print -delete | wc -l)
echo "pages: $(find "$cache/$site" -name '*.html' | wc -l) html, $removed stale removed"
