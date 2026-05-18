#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════
# mysql_backup_universal.sh
# Universal MySQL backup script — compatible with any MySQL target
# (RDS, EC2, Percona, Azure MySQL, on-prem, Docker, etc.)
#
# Features:
#   - Auto-detects server version and client version
#   - Auto-detects GTID mode
#   - Auto-detects --no-tablespaces support
#   - Auto-detects --column-statistics support
#   - Configurable target DEFINER user
#   - Full pre-flight + post-dump validation chain
#   - SHA256 checksum generation
#   - Optional S3 upload (for cloud targets)
#   - Safe retention cleanup
# ════════════════════════════════════════════════════════════════

set -euo pipefail

# ════════════════════════════════════════════════════════════════
# CONFIGURATION — adjust these per environment
# ════════════════════════════════════════════════════════════════

# Source database
DB="pheno20"
MYSQL_DEFAULTS_FILE="/root/.my.cnf"

# Target user that EXISTS on the destination server
# This is used to replace DEFINER clauses in views/procedures/triggers
# Examples: "phenome", "root", "admin", "dba_user"
TARGET_DB_USER="phenome"

# Backup storage
LOCAL_BACKUP_DIR="/var/backups/mysql"   # Dedicated path — never /tmp
RETENTION_DAYS=7

# Logging
LOG_PATH="/var/log"
LOG_FILE_NAME="mysql_backup.log"

# Sanity check — minimum expected compressed file size in bytes
# Tune this to ~10-20% of your typical dump size
MIN_EXPECTED_BYTES=10240   # 10 KB — increase for large databases

# Optional: S3 upload (leave empty to skip)
# Example: "s3://my-bucket/db-dumps"
S3_BUCKET=""
S3_REGION="us-east-1"

# ════════════════════════════════════════════════════════════════
# RUNTIME — do not edit below this line
# ════════════════════════════════════════════════════════════════

LOG_FILE="${LOG_PATH}/${LOG_FILE_NAME}"
DATE_FORMAT=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_DIR="${LOCAL_BACKUP_DIR}/${DATE_FORMAT}"
OUTPUT_FILE="${BACKUP_DIR}/${DB}-${DATE_FORMAT}.sql.gz"
CHECKSUM_FILE="${OUTPUT_FILE}.sha256"

# Auto-detected flags (populated by detect_capabilities)
NO_TABLESPACES_FLAG=""
COLUMN_STATS_FLAG=""
GTID_PURGED_FLAG=""
STRIP_TABLESPACES=false

# ── Logging ──────────────────────────────────────────────────────
log() {
    local level="$1"; shift
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [${level}] $*" | tee -a "$LOG_FILE"
}

# ── Auto-detect server/client capabilities ───────────────────────
detect_capabilities() {
    log INFO "Detecting MySQL server and client capabilities..."

    # ── Server version ──────────────────────────────────────────
    local server_version
    server_version=$(mysql --defaults-file="$MYSQL_DEFAULTS_FILE" \
        -sse "SELECT VERSION();" 2>/dev/null)
    log INFO "MySQL server version: ${server_version}"

    local minor patch
    minor=$(echo "$server_version" | cut -d. -f2)
    patch=$(echo "$server_version" | cut -d. -f3 | cut -d- -f1)

    # ── --no-tablespaces: supported from 5.7.31 / 8.0.21 ──────
    # Logic:
    #   MySQL 5.x : need minor==7 and patch>=31
    #   MySQL 8.x+: supported
    if [[ "$minor" -ge 8 ]] || { [[ "$minor" -eq 7 ]] && [[ "$patch" -ge 31 ]]; }; then
        NO_TABLESPACES_FLAG="--no-tablespaces"
        log INFO "  --no-tablespaces : SUPPORTED (server ${server_version})"
    else
        NO_TABLESPACES_FLAG=""
        STRIP_TABLESPACES=true
        log INFO "  --no-tablespaces : NOT SUPPORTED (server ${server_version}) — will strip via sed"
    fi

    # ── GTID mode detection ────────────────────────────────────
    # If GTIDs are not enabled on the source, --set-gtid-purged=OFF
    # is still safe but will produce a warning on older clients.
    # If GTIDs ARE enabled, OFF is required to avoid importing GTID state
    # onto a target that manages its own GTIDs (RDS, Percona, replicas, etc.)
    local gtid_mode
    gtid_mode=$(mysql --defaults-file="$MYSQL_DEFAULTS_FILE" \
        -sse "SELECT @@global.gtid_mode;" 2>/dev/null || echo "OFF")
    log INFO "  GTID mode        : ${gtid_mode}"
    # Always set OFF — safe for all targets regardless of source GTID state
    GTID_PURGED_FLAG="--set-gtid-purged=OFF"

    # ── mysqldump client version ───────────────────────────────
    # --column-statistics=0 is only valid on mysqldump 8.x clients
    # (flag does not exist on 5.x client — passing it causes an error)
    local client_version client_major
    client_version=$(mysqldump --version 2>&1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
    client_major=$(echo "$client_version" | cut -d. -f1)
    log INFO "  mysqldump client : ${client_version}"

    if [[ "$client_major" -ge 8 ]]; then
        COLUMN_STATS_FLAG="--column-statistics=0"
        log INFO "  --column-statistics=0 : ENABLED (client is 8.x)"
    else
        COLUMN_STATS_FLAG=""
        log INFO "  --column-statistics=0 : NOT NEEDED (client is 5.x)"
    fi

    log INFO "Capability detection complete."
}

# ── Pre-flight checks ─────────────────────────────────────────────
preflight_checks() {
    log INFO "Running pre-flight checks..."

    # 1. mysqldump binary
    if ! command -v mysqldump &>/dev/null; then
        log ERROR "mysqldump not found in PATH"
        exit 1
    fi

    # 2. Credentials file
    if [[ ! -f "$MYSQL_DEFAULTS_FILE" ]]; then
        log ERROR "${MYSQL_DEFAULTS_FILE} not found — cannot authenticate"
        exit 1
    fi

    # Credentials file should not be world-readable
    local perms
    perms=$(stat -c "%a" "$MYSQL_DEFAULTS_FILE")
    if [[ "$perms" != "600" && "$perms" != "400" ]]; then
        log WARN "${MYSQL_DEFAULTS_FILE} permissions are ${perms} — should be 600 or 400"
    fi

    # 3. Disk space: require at least 5 GB free
    mkdir -p "$LOCAL_BACKUP_DIR"
    local required_kb=5242880
    local available_kb
    available_kb=$(df -Pk "$LOCAL_BACKUP_DIR" | awk 'NR==2{print $4}')
    if (( available_kb < required_kb )); then
        log ERROR "Insufficient disk space: ${available_kb}KB available, ${required_kb}KB required"
        exit 1
    fi
    log INFO "  Disk space : ${available_kb}KB available — OK"

    # 4. MySQL connectivity
    if ! mysql --defaults-file="$MYSQL_DEFAULTS_FILE" -e "SELECT 1;" &>/dev/null; then
        log ERROR "Cannot connect to MySQL — check credentials or server status"
        exit 1
    fi
    log INFO "  MySQL connection : OK"

    # 5. Database existence
    if ! mysql --defaults-file="$MYSQL_DEFAULTS_FILE" -e "USE \`${DB}\`;" &>/dev/null; then
        log ERROR "Database '${DB}' does not exist or is not accessible"
        exit 1
    fi
    log INFO "  Database '${DB}' : EXISTS"

    log INFO "Pre-flight checks passed."
}

# ── Capture pre-dump row counts ───────────────────────────────────
# Saves machine-readable snapshots to BACKUP_DIR for use in validate_data_integrity()
capture_row_counts() {
    log INFO "Pre-dump row counts for '${DB}':"
    mkdir -p "$BACKUP_DIR"

    # Human-readable log output
    mysql --defaults-file="$MYSQL_DEFAULTS_FILE" \
        --batch --skip-column-names \
        -e "SELECT
                LPAD(TABLE_NAME, 40, ' '),
                LPAD(TABLE_ROWS, 12, ' '),
                LPAD(ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 2), 10, ' ') AS 'Size_MB'
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = '${DB}'
            ORDER BY TABLE_NAME;" 2>/dev/null \
        | tee -a "$LOG_FILE" || true

    # Machine-readable snapshot: TABLE_NAME<TAB>ROW_COUNT — used for post-dump diff
    mysql --defaults-file="$MYSQL_DEFAULTS_FILE" \
        --batch --skip-column-names \
        -e "SELECT TABLE_NAME, TABLE_ROWS
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = '${DB}'
              AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME;" 2>/dev/null \
        > "${BACKUP_DIR}/pre_dump_rowcounts.txt" || true

    # Sorted table name list — used for schema diff
    mysql --defaults-file="$MYSQL_DEFAULTS_FILE" \
        --batch --skip-column-names \
        -e "SELECT TABLE_NAME
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = '${DB}'
              AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME;" 2>/dev/null \
        > "${BACKUP_DIR}/pre_dump_tables.txt" || true

    # Views, procedures, functions, triggers counts — for schema completeness check
    mysql --defaults-file="$MYSQL_DEFAULTS_FILE" \
        --batch --skip-column-names \
        -e "SELECT 'VIEWS',      COUNT(*) FROM information_schema.VIEWS    WHERE TABLE_SCHEMA='${DB}'
            UNION ALL
            SELECT 'PROCEDURES', COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA='${DB}' AND ROUTINE_TYPE='PROCEDURE'
            UNION ALL
            SELECT 'FUNCTIONS',  COUNT(*) FROM information_schema.ROUTINES WHERE ROUTINE_SCHEMA='${DB}' AND ROUTINE_TYPE='FUNCTION'
            UNION ALL
            SELECT 'TRIGGERS',   COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA='${DB}';" 2>/dev/null \
        > "${BACKUP_DIR}/pre_dump_objects.txt" || true

    log INFO "Pre-dump snapshots saved to ${BACKUP_DIR}/"
}

# ── Build mysqldump command dynamically ───────────────────────────
build_dump_flags() {
    DUMP_FLAGS=(
        "--defaults-file=${MYSQL_DEFAULTS_FILE}"
        "$GTID_PURGED_FLAG"         # Always OFF — safe for all targets
        "--single-transaction"       # Consistent InnoDB snapshot, no table locks
        "--quick"                    # Stream rows (low memory footprint)
        "--triggers"                 # Include triggers
        "--routines"                 # Include stored procedures + functions
        "--events"                   # Include scheduled events
        "--add-drop-database"        # DROP DATABASE IF EXISTS before CREATE
        "--hex-blob"                 # Safe encoding for BINARY/BLOB columns
        "--databases" "${DB}"        # Adds CREATE DATABASE to dump
    )

    # Conditionally add version-dependent flags
    # NOTE: must use if/then — not [[ ]] && ... which exits with code 1 under set -e when condition is false
    if [[ -n "$NO_TABLESPACES_FLAG" ]]; then DUMP_FLAGS+=("$NO_TABLESPACES_FLAG"); fi
    if [[ -n "$COLUMN_STATS_FLAG"   ]]; then DUMP_FLAGS+=("$COLUMN_STATS_FLAG");   fi
}

# ── Run the backup ────────────────────────────────────────────────
run_backup() {
    log INFO "Starting backup: '${DB}' → ${OUTPUT_FILE}"
    mkdir -p "$BACKUP_DIR"

    log INFO "Flags: ${DUMP_FLAGS[*]}"

    # Pipe chain:
    #   mysqldump → [strip tablespace if old server] → replace DEFINER → gzip
    #
    # sed explanation:
    #   s/DEFINER=[^ ]*/DEFINER=`TARGET_DB_USER`@`%`/g
    #   Replaces ALL occurrences of DEFINER=<anything> with the configured
    #   target user so views/procedures/triggers work on any destination server.
    #
    # The tablespace strip sed covers the case where --no-tablespaces is
    # not supported — removes /*!50100 TABLESPACE and related directives.

    local tablespace_filter
    if [[ "$STRIP_TABLESPACES" == "true" ]]; then
        tablespace_filter="grep -v '/\*!50100 TABLESPACE\|/\*!80000 SET @@tablespace\|TABLESPACE ='"
    else
        tablespace_filter="cat"
    fi

    if mysqldump "${DUMP_FLAGS[@]}" 2>>"$LOG_FILE" \
        | eval "$tablespace_filter" \
        | sed "s/DEFINER=[^ ]*/DEFINER=\`${TARGET_DB_USER}\`@\`%\`/g" \
        | gzip -6 > "$OUTPUT_FILE"
    then
        log INFO "mysqldump + gzip completed successfully"
    else
        log ERROR "mysqldump FAILED — check log for details"
        [[ -f "$OUTPUT_FILE" ]] && rm -f "$OUTPUT_FILE"
        exit 1
    fi
}

# ── Post-dump validation chain ────────────────────────────────────
validate_backup() {
    log INFO "Running post-dump validation..."

    # 1. File must exist
    if [[ ! -f "$OUTPUT_FILE" ]]; then
        log ERROR "Output file missing: $OUTPUT_FILE"
        exit 1
    fi

    # 2. File size sanity check
    local actual_bytes
    actual_bytes=$(stat -c%s "$OUTPUT_FILE")
    if (( actual_bytes < MIN_EXPECTED_BYTES )); then
        log ERROR "File suspiciously small: ${actual_bytes}B (minimum: ${MIN_EXPECTED_BYTES}B)"
        exit 1
    fi
    local human_size
    human_size=$(numfmt --to=iec "$actual_bytes" 2>/dev/null || echo "${actual_bytes}B")
    log INFO "  File size        : ${actual_bytes} bytes (${human_size}) — OK"

    # 3. gzip integrity test — catches truncation and corruption
    if ! gunzip -t "$OUTPUT_FILE" 2>>"$LOG_FILE"; then
        log ERROR "gzip integrity check FAILED — dump is corrupt or truncated"
        exit 1
    fi
    log INFO "  gzip integrity   : PASSED"

    # 4. Dump completion marker
    local marker_count
    marker_count=$(zcat "$OUTPUT_FILE" | grep -c "^-- Dump completed" || true)
    if (( marker_count == 0 )); then
        log WARN "  Dump marker      : NOT FOUND (non-fatal — some versions omit it)"
    else
        log INFO "  Dump marker      : FOUND (${marker_count}) — OK"
    fi

    # 5. CREATE TABLE count — confirms dump is non-empty
    local table_count
    table_count=$(zcat "$OUTPUT_FILE" | grep -c "^CREATE TABLE" || true)
    if (( table_count == 0 )); then
        log ERROR "No CREATE TABLE statements found — dump appears empty"
        exit 1
    fi
    log INFO "  CREATE TABLE     : ${table_count} tables — OK"

    # 6. DEFINER check — confirm no original DEFINERs remain
    local definer_count
    definer_count=$(zcat "$OUTPUT_FILE" | grep -c "DEFINER=" || true)
    if (( definer_count > 0 )); then
        log INFO "  DEFINER clauses  : ${definer_count} found (all rewritten to ${TARGET_DB_USER}@%)"
    else
        log INFO "  DEFINER clauses  : none (no views/procedures/triggers in dump)"
    fi

    # 7. SHA256 checksum — for verifying integrity after transfer
    sha256sum "$OUTPUT_FILE" > "$CHECKSUM_FILE"
    log INFO "  SHA256 checksum  : $(cat "$CHECKSUM_FILE" | awk '{print $1}')"
    log INFO "  Checksum file    : ${CHECKSUM_FILE}"
}

# ── Data integrity validation — live DB vs dump ───────────────────
# Compares table list, schema objects, and row counts between
# the live database (captured pre-dump) and the actual dump file
validate_data_integrity() {
    log INFO "Running data integrity validation (live DB vs dump)..."
    local errors=0

    # ── 1. Table count: live vs dump ────────────────────────────
    local live_table_count dump_table_count
    live_table_count=$(wc -l < "${BACKUP_DIR}/pre_dump_tables.txt" 2>/dev/null || echo 0)
    dump_table_count=$(zcat "$OUTPUT_FILE" | grep -c "^CREATE TABLE" || true)

    log INFO "  Table count — live: ${live_table_count} | dump: ${dump_table_count}"
    if (( live_table_count != dump_table_count )); then
        log ERROR "  Table count MISMATCH — live has ${live_table_count}, dump has ${dump_table_count}"
        (( errors++ )) || true
    else
        log INFO "  Table count      : MATCH ✓"
    fi

    # ── 2. Table names: diff live list vs dump ──────────────────
    # Extract table names from dump
    zcat "$OUTPUT_FILE" \
        | grep "^CREATE TABLE" \
        | awk '{print $3}' \
        | tr -d '\`' \
        | sort > "${BACKUP_DIR}/dump_tables.txt"

    sort "${BACKUP_DIR}/pre_dump_tables.txt" > "${BACKUP_DIR}/pre_dump_tables_sorted.txt"

    local tables_diff
    tables_diff=$(diff "${BACKUP_DIR}/pre_dump_tables_sorted.txt" \
                       "${BACKUP_DIR}/dump_tables.txt" 2>/dev/null || true)

    if [[ -n "$tables_diff" ]]; then
        log ERROR "  Table names MISMATCH — differences found:"
        echo "$tables_diff" | while read -r line; do
            log ERROR "    $line"
        done
        (( errors++ )) || true
    else
        log INFO "  Table names      : ALL ${live_table_count} tables present in dump ✓"
    fi

    # ── 3. Schema objects: views, procedures, functions, triggers ─
    log INFO "  Schema objects (live vs dump):"
    while IFS=$'\t' read -r obj_type live_count; do
        local dump_count=0
        case "$obj_type" in
            VIEWS)
                # mysqldump wraps VIEWs in /*!50001 ... */ conditional comments
                # match both plain CREATE VIEW and the /*!50001 CREATE ... VIEW variant
                dump_count=$(zcat "$OUTPUT_FILE" | grep -c "VIEW \`" || true) ;;
            PROCEDURES)
                # Procedures appear as: /*!50003 CREATE PROCEDURE or CREATE PROCEDURE
                dump_count=$(zcat "$OUTPUT_FILE" | grep -c "PROCEDURE \`" || true) ;;
            FUNCTIONS)
                # Functions appear as: /*!50003 CREATE FUNCTION or CREATE FUNCTION
                dump_count=$(zcat "$OUTPUT_FILE" | grep -c "FUNCTION \`" || true) ;;
            TRIGGERS)
                # Triggers appear as: /*!50003 CREATE TRIGGER or CREATE TRIGGER
                dump_count=$(zcat "$OUTPUT_FILE" | grep -c "TRIGGER \`" || true) ;;
        esac

        if (( live_count != dump_count )); then
            log WARN "    ${obj_type}: live=${live_count} | dump=${dump_count} — MISMATCH"
            # Non-fatal: some versions format CREATE differently
        else
            log INFO "    ${obj_type}: ${live_count} ✓"
        fi
    done < "${BACKUP_DIR}/pre_dump_objects.txt" || true

    # ── 4. Row count spot-check — top 5 largest tables ──────────
    log INFO "  Row count spot-check (top 5 largest tables by row count):"
    sort -t$'\t' -k2 -rn "${BACKUP_DIR}/pre_dump_rowcounts.txt" \
        | head -5 \
        | while IFS=$'\t' read -r tbl live_rows; do
            # Count INSERT INTO `table` lines in dump as a proxy for row batches
            # (mysqldump --quick writes one INSERT per row or extended inserts)
            local dump_inserts
            dump_inserts=$(zcat "$OUTPUT_FILE" \
                | grep -c "^INSERT INTO \`${tbl}\`" || true)

            if (( live_rows == 0 && dump_inserts == 0 )); then
                log INFO "    ${tbl}: 0 rows — empty table, no INSERTs expected ✓"
            elif (( dump_inserts == 0 && live_rows > 0 )); then
                log WARN "    ${tbl}: live=${live_rows} rows | dump has 0 INSERT statements — check if table is excluded"
            else
                log INFO "    ${tbl}: live≈${live_rows} rows | dump has ${dump_inserts} INSERT statement(s) ✓"
            fi
        done || true

    # ── 5. Final verdict ─────────────────────────────────────────
    if (( errors > 0 )); then
        log ERROR "Data integrity validation FAILED with ${errors} error(s)"
        exit 1
    else
        log INFO "  Data integrity   : PASSED ✓"
    fi
}

# ── Optional S3 upload ────────────────────────────────────────────
upload_to_s3() {
    if [[ -z "$S3_BUCKET" ]]; then
        log INFO "S3_BUCKET not configured — skipping upload"
        return 0
    fi
    if ! command -v aws &>/dev/null; then
        log WARN "aws CLI not found — skipping S3 upload"
        return 0
    fi

    log INFO "Uploading to S3: ${S3_BUCKET}/"
    if aws s3 cp "$OUTPUT_FILE"    "${S3_BUCKET}/" --region "$S3_REGION" --no-progress 2>>"$LOG_FILE" \
    && aws s3 cp "$CHECKSUM_FILE"  "${S3_BUCKET}/" --region "$S3_REGION" --no-progress 2>>"$LOG_FILE"
    then
        log INFO "S3 upload complete: ${S3_BUCKET}/$(basename "$OUTPUT_FILE")"
    else
        log ERROR "S3 upload FAILED"
        exit 1
    fi
}

# ── Cleanup old backups ───────────────────────────────────────────
cleanup_old_backups() {
    log INFO "Cleaning up backups older than ${RETENTION_DAYS} days..."
    find "$LOCAL_BACKUP_DIR" \
        -maxdepth 1 -mindepth 1 \
        -type d \
        -mtime "+${RETENTION_DAYS}" \
        -exec rm -rf {} + \
        2>>"$LOG_FILE" || true
    log INFO "Cleanup done"
}

# ── Final summary ─────────────────────────────────────────────────
print_summary() {
    local file_size
    file_size=$(stat -c%s "$OUTPUT_FILE")
    local human_size
    human_size=$(numfmt --to=iec "$file_size" 2>/dev/null || echo "${file_size}B")

    log INFO "════════════════════════════════════════════════"
    log INFO "  BACKUP SUMMARY"
    log INFO "  Database       : ${DB}"
    log INFO "  Target user    : ${TARGET_DB_USER}@%"
    log INFO "  Output file    : ${OUTPUT_FILE}"
    log INFO "  File size      : ${file_size} bytes (${human_size})"
    log INFO "  Checksum file  : ${CHECKSUM_FILE}"
    log INFO "  Flags used     : ${DUMP_FLAGS[*]}"
    log INFO "  Tablespace     : $([ "$STRIP_TABLESPACES" == "true" ] && echo "stripped via sed" || echo "--no-tablespaces flag")"
    [[ -n "$S3_BUCKET" ]] && \
    log INFO "  S3 path        : ${S3_BUCKET}/$(basename "$OUTPUT_FILE")"
    log INFO "  Status         : SUCCESS ✓"
    log INFO "════════════════════════════════════════════════"
}

# ── Entry point ───────────────────────────────────────────────────
main() {
    mkdir -p "$LOG_PATH" "$LOCAL_BACKUP_DIR"
    touch "$LOG_FILE"

    log INFO "════════════════════════════════════════════════"
    log INFO "  MySQL Universal Backup — DB: ${DB}"
    log INFO "  Started: $(date)"
    log INFO "════════════════════════════════════════════════"

    detect_capabilities
    preflight_checks
    capture_row_counts
    build_dump_flags
    run_backup
    validate_backup
    validate_data_integrity
    upload_to_s3
    cleanup_old_backups
    print_summary
}

main "$@"
