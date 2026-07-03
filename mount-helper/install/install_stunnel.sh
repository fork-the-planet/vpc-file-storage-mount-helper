#!/bin/bash
set -euo pipefail

INSTALL="install"
UNINSTALL="uninstall"
CONF_FILE=/etc/ibmshare/share.conf
VERBOSE=false

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PACKAGES_BASE="${SCRIPT_DIR}/packages"

ACTION="$INSTALL"

# -------- ARG PARSING --------
for arg in "$@"; do
    case "$arg" in
        install|uninstall)
            ACTION="$arg"
            ;;
        --verbose|-v)
            VERBOSE=true
            ;;
        *)
            echo "Invalid argument: $arg use either install or uninstall"
            exit 1
            ;;
    esac
done

# -------- VALIDATE ACTION --------
if [[ "$ACTION" != "$INSTALL" && "$ACTION" != "$UNINSTALL" ]]; then
    echo "Error: use 'install' or 'uninstall'"
    exit 1
fi

if [ ! -f /etc/os-release ]; then
        echo "/etc/os-release missing. Cannot determine os type."
        exit 1
fi

store_kv() {
    local k="$1"
    local v="$2"
    sudo mkdir -p "$(dirname "$CONF_FILE")"
    sudo touch "$CONF_FILE"
    sudo sed -i.bak "/^${k}=*/d" "$CONF_FILE"
    echo "${k}=${v}" | sudo tee -a "$CONF_FILE" >/dev/null
}

store_arch_env() {
    store_kv ARCH_ENV "$(uname -m)"
}
store_stunnel_env() {
    store_kv STUNNEL_ENV "${STUNNEL_ENV:-}"
}

store_trusted_ca_file_name() {
    store_kv TRUSTED_ROOT_CACERT "$*"
}

# -------- LOGGING --------
log() {
    if [ "$VERBOSE" = true ]; then
        echo "[INFO] $*"
    fi
}

# -------- HELPERS --------
is_ppc () {
    uname -m | grep -iq "ppc"
}

verify_stunnel_installed() {
    if ! command -v stunnel >/dev/null 2>&1; then
        echo "Error: stunnel installation failed - stunnel command not found"
        exit 1
    fi
    log "stunnel successfully installed and verified"
}

# -------- CONFIG --------
if [[ "$ACTION" == "$INSTALL" && ! -f "$CONF_FILE" ]]; then
    log "Initializing share.conf"
    sudo mkdir -p /etc/ibmshare
    sudo cp "$SCRIPT_DIR/share.conf" "$CONF_FILE"
fi

if [[ "$ACTION" == "$UNINSTALL" ]]; then
    log "Removing share.conf"
    sudo rm -f "$CONF_FILE" || true
fi

# -------- CERT --------
create_stunnel_cert_if_installed() {
    if command -v stunnel >/dev/null 2>&1 && [ -d /etc/stunnel ]; then
        log "Creating stunnel test certificate"
        DRY_RUN="false"
        if [ "$DRY_RUN" = true ]; then
            echo "[DRY-RUN] create /etc/stunnel/allca.pem"
        else
            sudo cat <<EOF > /etc/stunnel/allca.pem
-----BEGIN CERTIFICATE-----
MIIFdTCCA12gAwIBAgIUdNDeiuIBYhInN5rrT+FZPmE5vy4wDQYJKoZIhvcNAQEL
BQAwSjELMAkGA1UEBhMCVVMxDjAMBgNVBAgMBVRleGFzMQ8wDQYDVQQHDAZEYWxs
YXMxDDAKBgNVBAoMA0lCTTEMMAoGA1UEAwwDSUJNMB4XDTI1MDUwMTE0NDkxNVoX
DTM1MDQyOTE0NDkxNVowSjELMAkGA1UEBhMCVVMxDjAMBgNVBAgMBVRleGFzMQ8w
DQYDVQQHDAZEYWxsYXMxDDAKBgNVBAoMA0lCTTEMMAoGA1UEAwwDSUJNMIICIjAN
BgkqhkiG9w0BAQEFAAOCAg8AMIICCgKCAgEA4xgsAao3qQc6btAw2fwue/YK7/qm
XmLX+F7ATfqJwnDgshGOSii6LBBa9QHLPL59WLHbz/M3YBk4YJ8MTOAZTH48UyS0
3epYSIpeoE/8wtoGtQoIhhEftNSsPYNixFsDPPyRSR2dvXVJrZZtkwdxrp4M8aAc
wD3hBqCNI2FFPb8d1/OICCweHevz3BvGzAT8HdDo9j8vjH2BSFqm99cyk5iKMdO9
p0LCNPN/uLybNScyzB7aeNRQPHaNEMU5JVHtV+sYrDAeanAmHnMbRnQw8QBOIC3N
jyvB1IAV5Ny884Nb0pZWSWzwXCr3oB6S4YI/O6jQIBhBgG+27R9jWVfgoiS7ezqT
Grc7/n50PdLEMUqyJ6lijzvearACanObnXi6xJup18DYv7aCLwNQn2I7C3KNs7lr
DaFLEEl0xjj/u6ruDYCxe70aGJC2g4s36chvu6BoSaSpl2yU9a1XrfNGfxoVcXvZ
Bwhx+zsWlH3sdIa85lqwvjFg9kh2+JLkAA+7KgINwGeNF8+a05tBbC5N9xOXjOJu
Ok/CCMJ8chQZoJj1JqrKezUZElTG0qJNqVlKyEzJ3boLTAOT6mGurna3ajR5Zijd
7Y8m298ecozO3+WnQtLJQY5jMHJBQjG3l8qfaUybeDSllmypDiOHfS9hn7F85sGh
bupFEHIYP2Y4+UcCAwEAAaNTMFEwHQYDVR0OBBYEFJnWw/hcYcbsRbcSWivW8893
M9TMMB8GA1UdIwQYMBaAFJnWw/hcYcbsRbcSWivW8893M9TMMA8GA1UdEwEB/wQF
MAMBAf8wDQYJKoZIhvcNAQELBQADggIBALhVdmERupJERDAxa8tjv9NyPdLmWKvX
DG4EN9qeuh7lXnTw97tuaAFglXmp//nbqJ1pSUdaTflUnc1bGEiOkRKHfeVEsvbH
AtvFkLWi7CEg/A6ulJ+RgZynssdZ5D5Y+cLw2JhaiDxNf+yikcnn5q0BXpiZCqA6
a0ylPmoDKn1pC2c5s95f7yehXBNDxJw+Lxdec8kKKeNk23HcLei/AoKaKzJQK2Q0
aCFgWdxofvky1h2csCjQN2EJAAp1v0BDBX/GvIkD4dXA9YI8sIeF/ZWv2gxFJNeY
guqcBWTPNwpKNflmz+TqQOB9rNdGDh0WQAQLLeeccOb16hlr86YbDfrjikQFrfcx
KIq9Jj15vsIEmLNavIAANjWOGn/8gNTttyHMYitSAecpqX0VY0/Qe3s0fmMhwJgl
PSEK8nYssZ/7WVpV0RE8qyo0t4M01kl8NXUlWuyZ3vt+Wgz8xYMMvL2b9M7q6ysm
M76z0t8anU9C7BTX8C7THFHid/LRS/1UlvuJKkQYsUgxac+OFcrw32NiZ5QTJ8Z8
0iurNNAwqiVuEKwccwv+dO1qXTQDMf7YmeAwv4iSzG/l4M7F/xBTZEY2MeRjrLQl
62hMSc0o/OkBYCF6O3tXupXJs/5weBNZqcLizEu076XZ4pBhgKXpmJgqfHLRAcwN
6sIG86suxYkB
-----END CERTIFICATE-----
EOF
        fi
    fi
}

# -------- DIRS --------
setup_stunnel_directories() {
    log "enter setup_stunnel_directories"
    sudo mkdir -p /var/run/stunnel4 /etc/stunnel /var/log/stunnel
    sudo chmod 744 /var/run/stunnel4 /etc/stunnel /var/log/stunnel
    log "exit setup_stunnel_directories"
}

cleanup_dirs() {
    sudo rm -rf /var/run/stunnel4 /etc/stunnel
}

# -------- INSTALL --------
install_stunnel_ubuntu_debian() {
    . /etc/os-release

    log "enter install_stunnel_ubuntu_debian"
    if is_ppc; then
        sudo apt-get update
        sudo apt-get install -y stunnel4
    else
        PKG_DIR="${PACKAGES_BASE}/${ID}/${VERSION_ID}"
        if ls "$PKG_DIR"/stunnel*.deb >/dev/null 2>&1; then
            sudo apt-get -y install "$PKG_DIR"/stunnel*.deb
        else
            sudo apt-get install -y stunnel4
        fi
    fi

    verify_stunnel_installed
    setup_stunnel_directories
    create_stunnel_cert_if_installed
    store_trusted_ca_file_name "/etc/ssl/certs/ca-certificates.crt"
    store_stunnel_env
    store_arch_env
    log "exit install_stunnel_ubuntu_debian"
}

install_stunnel_rhel_centos_rocky() {
    . /etc/os-release

    log "enter install_stunnel_rhel_centos_rocky"
    if is_ppc; then
        if command -v dnf >/dev/null; then
            sudo dnf install -y stunnel
        else
            sudo yum install -y stunnel
        fi
    else
        PKG_DIR="${PACKAGES_BASE}/${ID}/${VERSION_ID}"
        if ls "$PKG_DIR"/stunnel*.rpm >/dev/null 2>&1; then
            if command -v dnf >/dev/null; then
                sudo dnf -y install --disablerepo='*'  --setopt=install_weak_deps=False "$PKG_DIR"/stunnel*.rpm
            else
                sudo yum -y install --disablerepo='*' --nogpgcheck "$PKG_DIR"/stunnel*.rpm
            fi
        else
            if command -v dnf >/dev/null; then
                sudo dnf install -y stunnel
            else
                sudo yum install -y stunnel
            fi
        fi
    fi

    verify_stunnel_installed
    setup_stunnel_directories
    create_stunnel_cert_if_installed
    store_trusted_ca_file_name "/etc/pki/tls/certs/ca-bundle.crt"
    store_stunnel_env
    store_arch_env
    log "exit install_stunnel_rhel_centos_rocky"
}

install_stunnel_suse() {
    . /etc/os-release

    log "enter install_stunnel_suse"

    if is_ppc; then
        sudo zypper install -y stunnel
    else
        PKG_DIR="${PACKAGES_BASE}/${ID}/${VERSION_ID}"
        if ls "$PKG_DIR"/stunnel*.rpm >/dev/null 2>&1; then
            sudo zypper install -y "$PKG_DIR"/stunnel*.rpm
        else
            sudo zypper install -y stunnel
        fi
    fi

    verify_stunnel_installed
    setup_stunnel_directories
    create_stunnel_cert_if_installed
    store_trusted_ca_file_name "/etc/ssl/ca-bundle.pem"
    store_stunnel_env
    store_arch_env
    log "exit install_stunnel_suse"
}

install_stunnel_rhcos() {
    . /etc/os-release

    log "enter install_stunnel_rhcos"
    if is_ppc; then
        sudo rpm-ostree install -y --idempotent stunnel
    else
        RPM_PATTERN="${PACKAGES_BASE}/rhel/${VERSION_ID}/stunnel*.rpm"
        if ls "$RPM_PATTERN" >/dev/null 2>&1; then
            sudo rpm-ostree install -y --idempotent "$(ls "$RPM_PATTERN" | head -1)"
        else
            sudo rpm-ostree install -y --idempotent stunnel
        fi
    fi
    verify_stunnel_installed
    setup_stunnel_directories
    create_stunnel_cert_if_installed
    store_trusted_ca_file_name "/etc/ssl/certs/ca-certificates.crt"
    store_stunnel_env
    store_arch_env

    echo ""
    echo "=================================================="
    echo "stunnel installation staged successfully."
    echo "Reboot REQUIRED to activate changes."
    echo "=================================================="
    echo ""

    log "exit install_stunnel_rhcos"
}
# -------- UNINSTALL --------
uninstall_stunnel_ubuntu_debian() {

    log "entering uninstall_stunnel_ubuntu_debian"
    sudo apt-get remove --purge -y stunnel4 || true
    cleanup_dirs
    log "completed uninstall_stunnel_ubuntu_debian"
}

uninstall_stunnel_rhel_centos_rocky() {
    log "entering uninstall_stunnel_rhel_centos_rocky"
    if command -v dnf >/dev/null; then
        sudo dnf remove -y stunnel || true
    else
        sudo yum remove -y stunnel || true
    fi
    cleanup_dirs
    log "completed uninstall_stunnel_rhel_centos_rocky"
}

uninstall_stunnel_rhcos() {
    log "entering uninstall_stunnel_rhcos"
    sudo rpm-ostree uninstall stunnel || true
    log "completed uninstall_stunnel_rhcos"
}

uninstall_stunnel_suse() {
    log "entering uninstall_stunnel_suse"
    sudo zypper remove -y stunnel || true
    cleanup_dirs
    log "completed uninstall_stunnel_suse"
}

# -------- MAIN --------
main() {
    . /etc/os-release

    if [[ "$ID" == "rhcos" ]] || [[ "${VARIANT_ID:-}" == *"coreos"* ]]; then
        OS_TYPE="rhcos"
    else
        OS_TYPE="$ID"
    fi

    if [[ "$ACTION" == "$INSTALL" ]]; then
        case "$OS_TYPE" in
            ubuntu|debian) install_stunnel_ubuntu_debian ;;
            centos|rhel|rocky) install_stunnel_rhel_centos_rocky ;;
            rhcos) install_stunnel_rhcos ;;
            suse|sles) install_stunnel_suse ;;
            *) echo "Unsupported OS: $ID"; exit 1 ;;
        esac
    else
        case "$OS_TYPE" in
            ubuntu|debian) uninstall_stunnel_ubuntu_debian ;;
            centos|rhel|rocky) uninstall_stunnel_rhel_centos_rocky ;;
            rhcos) uninstall_stunnel_rhcos ;;
            suse|sles) uninstall_stunnel_suse ;;
            *) echo "Unsupported OS: $ID"; exit 1 ;;
        esac
    fi
}

main
