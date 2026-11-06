#!/bin/bash
# Fumiko (WSL, root): render every page of one site from int's database into a fresh /root/warm-pages/<site>. Run it
# after the work and before pack.sh: the warm also fills the stats tables pack.sh ships.
#   bash warm_site.sh revoltlib.com
set -euo pipefail
site=${1:?domain}
root=/root/warm-pages
rm -rf "${root:?}/${site:?}"
start=$(date +%s)
GGCMS_PAGE_CACHE_ROOT=$root php8.1 /usr/lib/ggcms/cli/scripts/internal/page_cache/warm_page_cache.php --domain=$site --jobs=16 --quiet
echo "warm done in $(( $(date +%s) - start ))s"
echo "html: $(find "$root/$site" -type f -name '*.html' | wc -l), files: $(find "$root/$site" -type f | wc -l), $(du -sh "$root/$site" | cut -f1)"
echo "localhost/port leaks: $(grep -rlE 'localhost|127\.0\.0\.1|:8000|:8443|domain=' --include='*.html' "$root/$site" | wc -l)"
echo "PHP errors: $(grep -rlE 'Fatal error|Warning:</b>|Uncaught|Notice:</b>' --include='*.html' "$root/$site" | wc -l)"
