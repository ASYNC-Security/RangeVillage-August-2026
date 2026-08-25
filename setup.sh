#!/usr/bin/env bash
# Prepare Kali/Debian for the RV Engineering Bug Bounty Workflow workshop.
set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_BIN="$HOME/.local/bin"

info() { printf '[INFO] %s\n' "$*"; }
ok()   { printf '[OK] %s\n' "$*"; }
fail() { printf '[FAIL] %s\n' "$*" >&2; exit 1; }

[[ -f /etc/debian_version ]] || fail "This setup script supports Kali/Debian-based Linux."

info "Installing system packages"
sudo apt update
sudo apt install -y \
  build-essential \
  ca-certificates \
  curl \
  coreutils \
  g++ \
  git \
  jq \
  libsqlite3-dev \
  make \
  pkg-config \
  python3 \
  sqlite3 \
  unzip

info "Installing the current Node.js LTS release"
curl -fsSL https://deb.nodesource.com/setup_lts.x -o /tmp/nodesource_setup.sh
sudo -E bash /tmp/nodesource_setup.sh
sudo apt install -y nodejs
hash -r
ok "Node.js $(node --version)"
ok "npm $(npm --version)"

info "Installing n8n"
sudo npm install -g --ignore-scripts=false n8n@latest
hash -r

# Install the SQLite dependency declared by n8n when present.
GLOBAL_NPM_ROOT="$(npm root -g)"
N8N_PACKAGE_JSON="$GLOBAL_NPM_ROOT/n8n/package.json"
[[ -f "$N8N_PACKAGE_JSON" ]] || fail "Could not find the installed n8n package"
N8N_SQLITE_SPEC="$(node - "$N8N_PACKAGE_JSON" <<'NODE'
const pkg = require(process.argv[2]);
process.stdout.write(pkg.dependencies?.sqlite3 || '');
NODE
)"
if [[ -n "$N8N_SQLITE_SPEC" ]]; then
  info "Installing n8n SQLite dependency"
  sudo npm install -g --ignore-scripts=false "sqlite3@$N8N_SQLITE_SPEC"
fi

info "Checking n8n startup"
SMOKE_DIR="$(mktemp -d)"
SMOKE_LOG="$(mktemp)"
read -r SMOKE_PORT SMOKE_BROKER_PORT SMOKE_RUNNER_HEALTH_PORT < <(python3 - <<'PYPORT'
import socket
sockets = []
ports = []
for _ in range(3):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sockets.append(sock)
    ports.append(str(sock.getsockname()[1]))
print(" ".join(ports))
for sock in sockets:
    sock.close()
PYPORT
)
set +e
N8N_USER_FOLDER="$SMOKE_DIR" \
N8N_PORT="$SMOKE_PORT" \
N8N_RUNNERS_BROKER_PORT="$SMOKE_BROKER_PORT" \
N8N_RUNNERS_LAUNCHER_HEALTH_CHECK_PORT="$SMOKE_RUNNER_HEALTH_PORT" \
N8N_RUNNERS_TASK_BROKER_URI="http://127.0.0.1:$SMOKE_BROKER_PORT" \
N8N_DIAGNOSTICS_ENABLED=false \
NODES_EXCLUDE='["n8n-nodes-base.localFileTrigger"]' \
timeout --kill-after=5s 30s n8n start >"$SMOKE_LOG" 2>&1
set -e
if grep -q "Editor is now accessible via:" "$SMOKE_LOG"; then
  ok "n8n startup check passed"
else
  cat "$SMOKE_LOG" >&2
  rm -rf "$SMOKE_DIR" "$SMOKE_LOG"
  fail "n8n did not start successfully"
fi
rm -rf "$SMOKE_DIR" "$SMOKE_LOG"

mkdir -p "$LOCAL_BIN"
export PATH="$LOCAL_BIN:$PATH"

install_pdtm() {
  local machine asset_arch api_url release_json download_url temp_dir pdtm_binary
  machine="$(uname -m)"
  case "$machine" in
    x86_64|amd64) asset_arch="amd64" ;;
    aarch64|arm64) asset_arch="arm64" ;;
    *) fail "Unsupported CPU architecture for automatic PDTM install: $machine" ;;
  esac

  api_url="https://api.github.com/repos/projectdiscovery/pdtm/releases/latest"
  release_json="$(curl -fsSL "$api_url")"
  download_url="$(jq -r --arg arch "$asset_arch" \
    '.assets[] | select(.name | test("_linux_" + $arch + "\\.zip$")) | .browser_download_url' \
    <<<"$release_json" | head -n1)"

  [[ -n "$download_url" && "$download_url" != "null" ]] || fail "Could not find the PDTM Linux $asset_arch release asset"

  info "Installing PDTM"
  temp_dir="$(mktemp -d)"
  curl -fsSL "$download_url" -o "$temp_dir/pdtm.zip"
  unzip -q "$temp_dir/pdtm.zip" -d "$temp_dir"
  pdtm_binary="$(find "$temp_dir" -type f -name pdtm | head -n1)"
  [[ -n "$pdtm_binary" ]] || fail "PDTM binary was not found in the release archive"
  install -m 0755 "$pdtm_binary" "$LOCAL_BIN/pdtm"
  rm -rf "$temp_dir"

  ok "PDTM installed"
}

install_pdtm

info "Installing/updating ProjectDiscovery tools"
install_tools=()
update_tools=()
for tool_name in subfinder httpx katana nuclei; do
  if [[ -x "$LOCAL_BIN/$tool_name" ]]; then
    update_tools+=("$tool_name")
  else
    install_tools+=("$tool_name")
  fi
done

if ((${#install_tools[@]})); then
  install_list="$(IFS=,; echo "${install_tools[*]}")"
  pdtm -i "$install_list" -bp "$LOCAL_BIN"
fi

if ((${#update_tools[@]})); then
  update_list="$(IFS=,; echo "${update_tools[*]}")"
  pdtm -u "$update_list" -bp "$LOCAL_BIN"
fi

if ! grep -q 'HOME/.local/bin' "$HOME/.bashrc" 2>/dev/null; then
  printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.bashrc"
fi

info "Updating Nuclei templates"
nuclei -update-templates || true

chmod +x "$PROJECT_DIR/setup.sh" "$PROJECT_DIR"/scripts/*.sh "$PROJECT_DIR"/scripts/*.py
mkdir -p "$PROJECT_DIR/output" "$PROJECT_DIR/results"

info "Checking commands"
for command_name in node npm n8n python3 base64 pdtm subfinder httpx katana nuclei; do
  command -v "$command_name" >/dev/null 2>&1 || fail "$command_name was not found"
  ok "$command_name found"
done

info "Checking workshop CLI compatibility"
require_flag() {
  local tool_name="$1"
  local flag_name="$2"
  local help_text
  help_text="$($tool_name -h 2>&1 || true)"
  grep -Fq -- "$flag_name" <<<"$help_text" || fail "$tool_name does not provide required flag $flag_name"
}

for flag_name in -dL -silent -o; do require_flag subfinder "$flag_name"; done
for flag_name in -l -silent -no-stdin -rate-limit -o; do require_flag httpx "$flag_name"; done
for flag_name in -list -silent -depth -js-crawl -field-scope -max-domain-pages -rate-limit -output; do require_flag katana "$flag_name"; done
for flag_name in -list -tags -severity -exclude-tags -no-stdin -rate-limit -timeout -retries -omit-raw -omit-template -jsonl-export; do require_flag nuclei "$flag_name"; done
ok "Workshop CLI compatibility check passed"

printf '\n'
ok "Workshop setup complete"
printf 'Start n8n from the repository folder with:\n\n'
printf '  cd %q\n' "$PROJECT_DIR"
printf '  NODES_EXCLUDE='"'"'["n8n-nodes-base.localFileTrigger"]'"'"' n8n start\n\n'
printf 'Then open: http://localhost:5678\n'
printf 'Use only targets you are authorised to test.\n'
