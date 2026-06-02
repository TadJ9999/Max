#!/usr/bin/env bash
# ============================================================================
#  Leo - Max's BUILD console (macOS / Linux). The bash twin of leo-build.ps1:
#  an ASCII poodle + an animated spinner while a build command runs, with the
#  verbose output tucked into a log. On success a happy poodle; on failure a
#  sad poodle + the error tail.
#
#  Usage:  leo-build.sh "<label>" "<logfile>" <command> [args...]
#  Example: leo-build.sh "Building the desktop app" /tmp/max-build.log \
#             npm run tauri build -- --no-bundle
#  Exits with the build command's exit code.
# ============================================================================
set -u

LABEL="${1:-Building}"
LOGFILE="${2:-/tmp/max-build.log}"
shift 2 2>/dev/null || true   # remaining args = the command to run

if [ -t 1 ]; then
  RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; RST=$'\033[0m'
else
  RED=""; GREEN=""; YELLOW=""; DIM=""; RST=""
fi

poodle() {
  local mood="$1" eyes="o.o" mouth="^" tag="Leo is building..." col="$RED"
  case "$mood" in
    happy) eyes="^.^"; mouth="v"; tag="woof! build is done!"; col="$GREEN";;
    sad)   eyes="T.T"; mouth="_"; tag="build hit a snag - see below."; col="$YELLOW";;
  esac
  printf '\n%s     ,_     ,_\n    ( %s )   %s\n     > %s <\n    (__)_(__)%s\n\n' "$col" "$eyes" "$tag" "$mouth" "$RST"
}

printf '\n%s  == LEO - BUILD MODE ====================================%s\n\n' "$RED" "$RST"
poodle work
printf '%s  %s%s\n' "$RED" "$LABEL" "$RST"
printf '%s  %s%s\n' "$DIM" "$(date '+%Y-%m-%d %H:%M:%S')" "$RST"
printf '%s  ----------------------------------------------------------%s\n' "$DIM" "$RST"

# Run the build in the background; capture all output to the log.
( "$@" ) >"$LOGFILE" 2>&1 &
pid=$!

frames=(">(o.o)   " " >(o.o)  " "  >(o.o) " "   >(o.o)" "  >(o.o) " " >(o.o)  ")
i=0; start=$(date +%s)
while kill -0 "$pid" 2>/dev/null; do
  f="${frames[$((i % ${#frames[@]}))]}"
  secs=$(( $(date +%s) - start ))
  printf '\r%s  [%s] working... %ss          %s' "$RED" "$f" "$secs" "$RST"
  i=$((i + 1)); sleep 0.12
done
wait "$pid"; code=$?
printf '\r%*s\r' 72 ''   # erase the spinner line
took=$(( $(date +%s) - start ))

if [ "$code" -eq 0 ]; then
  poodle happy
  printf '%s  [ok] %s - done in %ss%s\n\n' "$GREEN" "$LABEL" "$took" "$RST"
  exit 0
fi

poodle sad
printf '%s  [x] Build failed (exit %s) after %ss. Last lines:%s\n' "$RED" "$code" "$took" "$RST"
printf '%s  ----------------------------------------------------------%s\n' "$DIM" "$RST"
tail -n 25 "$LOGFILE" 2>/dev/null | while IFS= read -r line; do
  printf '%s    %s%s\n' "$DIM" "$line" "$RST"
done
printf '%s  ----------------------------------------------------------%s\n' "$DIM" "$RST"
printf '%s  Full log: %s%s\n\n' "$YELLOW" "$LOGFILE" "$RST"
exit "$code"
