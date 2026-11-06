#!/bin/bash
# Every table's checksum in one database, one "table checksum" per line. Run on int and prod and diff: content tables
# that match mean the two are twins, and only logs, users and sessions should differ.
#   bash checksum.sh revoltlib > int.txt
set -euo pipefail
db=${1:?database}
tables=$(mysql -N -B "$db" -e "SHOW TABLES" | tr '\n' ',' | sed 's/,$//; s/,/`,`/g')
mysql -N -B "$db" -e "CHECKSUM TABLE \`$tables\`" | sed "s/^$db\.//"
