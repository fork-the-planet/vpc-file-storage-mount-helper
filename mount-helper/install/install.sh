#!/bin/bash
#
# Copyright (c) IBM Corp. 2023. All Rights Reserved.
# Project name: VPC File Storage Mount Helper
# This project is licensed under the MIT License, see LICENSE file in the root directory.


INSTALL_ARG="$1"
INSTALL_MOUNT_OPTION_ARG="$2"
STUNNEL_ENABLED=false
CONF_FILE=/etc/ibmcloud/share.conf

APP_NAME="IBM Mount Share Helper"
SCRIPT_NAME="mount.ibmshare"
SBIN_SCRIPT="/sbin/$SCRIPT_NAME"
MIN_PYTHON3_VERSION=3.4
MIN_STRONGSWAN_VERSION=5.4
NA="NOT_SUPPORTED"
APT="apt-get -y install"
YUM="yum install -y"
ZYP="zypper install -y"
LINUX_INSTALL_APP=""
INSTALL_APP="Unknown"
NAME=$(grep -oP '(?<=^NAME=).+' /etc/os-release | tr -d '"')
VERSION=$(grep -oP '(?<=^VERSION_ID=).+' /etc/os-release | tr -d '"')
ARCH="uname -m"
MAJOR_VERSION=${VERSION%.*}
INSTALLED_PACKAGE_LIST="/etc/pre_installed_packages.txt"
DOWNLOADED_RHEL_PACKAGE_PATH="packages/rhel/$VERSION"

#              Name              Min Version    Install
LINUX_UBUNTU=("Ubuntu"           "18"           "$APT")
LINUX_DEBIAN=("Debian GNU/Linux" "11"           "$APT")
LINUX_CENTOS=("CentOS Stream"     "9"            "$YUM")
LINUX_ROCKY=("Rocky Linux"       "8"            "$YUM")
LINUX_FEDORA=("Fedora Linux"     $NA            $NA)
LINUX_SUSE=("SLES"               "12"           "$ZYP")
LINUX_RED_HAT=("Red Hat Enterprise Linux" "7" "$YUM")

declare -A region_map=(
    ["dal"]="us-south"
    ["us-south"]="us-south"
    ["lon"]="eu-gb"
    ["eu-gb"]="eu-gb"
    ["fra"]="eu-de"
    ["eu-de"]="eu-de"
    ["syd"]="au-syd"
    ["au-syd"]="au-syd"
    ["tok"]="jp-tok"
    ["jp-tok"]="jp-tok"
    ["osa"]="jp-osa"
    ["jp-osa"]="jp-osa"
    ["wdc"]="us-east"
    ["us-east"]="us-east"
    ["mad"]="eu-es"
    ["eu-es"]="eu-es"
    ["tor"]="ca-tor"
    ["ca-tor"]="ca-tor"
    ["sao"]="br-sao"
    ["br-sao"]="br-sao"
    ["par"]="eu-fr2"
    ["eu-fr2"]="eu-fr2"
    ["ca-mon"]="ca-mon"
    ["in-che"]="in-che"
    ["in-mum"]="in-mum"
    )


not_for_ppc () {
    echo $@ is not needed for PPC architechture since Ipsec is not supported. Silently ignoring.
    # Make sure to return 0
    return 0
}

log () {
    echo "$1"
}

ipsec_not_required () {
    [[ -n "${DO_NOT_INSTALL_IPSEC+is_set}" ]]
    return $?
}

is_ppc () {
    uname -m | grep -iq "ppc"
    return $?
}

reject_ipsec () {
    is_ppc || ipsec_not_required
    return $?
}

exit_err () {
    log "Install failed: $1"
    exit -1
}

exit_ok () {
    echo
    echo "$APP_NAME: $1."
    exit 0
}

check_linux_version () {
    MIN_VER=$1
    if [ "$MIN_VER" == "$NA" ]; then
        exit_err "IbmMountHelper Install not supported $NAME"
        return 0
    fi;

    if version_less_than $VERSION $MIN_VER; then
        exit_err "Can only install on $NAME version $MIN_VER or greater. Current version:$VERSION"
    fi;
    log "Linux($NAME) Version($VERSION) distro"
}

check_tls_supported_linux_verion() {
    if { is_linux LINUX_UBUNTU &&  [[ "$VERSION" == 24.04 ]]; } || { is_linux LINUX_RED_HAT && [[ "$VERSION" == 9.4 ]]; } || { is_linux LINUX_ROCKY && [[ "$VERSION" == 9.4 ]]; }; then
        log "Linux($NAME) Version($VERSION) supports TLS"
    else
        exit_err "TLS is not supported on this OS version"
    fi
}

is_linux () {
    eval 'ARRAY=( "${'"$1"'[@]}" )'
    local _NAME=${ARRAY[0]}
    local _MIN_VER=${ARRAY[1]}

    if [[ "$NAME" == "$_NAME"* ]]; then
        check_linux_version $_MIN_VER
        log "Linux version supported - $NAME ($VERSION)"
        set_install_app "${ARRAY[2]}"
        return 0
    fi;
    return 1
}

command_not_exist () {
    type -p $1 &>/dev/null
    if [ 0 -eq $? ]; then
        return 1
    fi;
    return 0
}

command_exist () {
    type -p $1 &>/dev/null ;
}

check_result () {
  code="$?"
  if [ $code != "0" ]; then
    exit_err "$1 ExitCode($code)"
  fi;
}

version_less_than() {
    ans="$(printf '%s\n%s\n' "$1" "$2" | sort -t '.' -k 1,1 -k 2,2 -k 3,3 -k 4,4 -g | head -n 1)"
    if [ "$ans" == "$2" ]; then
        return 1
    fi;
    return 0
}

set_install_app() {
    LINUX_INSTALL_APP="$1"
    array=($LINUX_INSTALL_APP)
    INSTALL_APP=${array[0]}
    if command_not_exist "$INSTALL_APP"; then
        exit_err "Missing install app: $INSTALL_APP"
    fi;
    echo "Using install app: $INSTALL_APP"
}

_remove_apps() {

    apps=($@)
    reject_ipsec || $SBIN_SCRIPT -TEARDOWN_APP
    for ((i=${#apps[@]}-1; i>=0; i--)); do
        app="${apps[$i]}"
        log "Removing package $app"

        # Condition to check if app name consists of mount.ibmshare
        if [[ "$app" == *"mount.ibmshare"* ]]; then
            app="mount.ibmshare"
        fi

        if ( is_linux LINUX_UBUNTU || is_linux LINUX_DEBIAN ); then
            # Skip uninstallation in case /etc/pre_installed_packages.txt is missing in system
            if [ ! -f "$INSTALLED_PACKAGE_LIST" ]; then
                log "Skipping uninstallation of packages as file '$INSTALLED_PACKAGE_LIST' is missing..."
                exit -1
            fi
            # Read preInstalled packages from system
            if grep -q "^$app" $INSTALLED_PACKAGE_LIST ; then
                log "Skipping package $app for uninstallation as it was pre-installed on the system"
                continue 2
            fi
            apt-get purge -y --no-auto-remove "$app"
        elif ( is_linux LINUX_RED_HAT || is_linux LINUX_CENTOS ); then
            if [ -d "$DOWNLOADED_RHEL_PACKAGE_PATH" ]; then
                # Skip uninstallation in case /etc/pre_installed_packages.txt is missing in system
                if [ ! -f "$INSTALLED_PACKAGE_LIST" ]; then
                    log "Skipping uninstallation of packages as file '$INSTALLED_PACKAGE_LIST' is missing..."
                    exit -1
                fi
                # Read preInstalled packages from system
                if grep -q "^$app" $INSTALLED_PACKAGE_LIST ; then
                    log "Skipping package $app for uninstallation as it was pre-installed on the system"
                    continue 3
                fi
                rpm -e --allmatches --nodeps "$app"
            else
                rpm -e --allmatches --nodeps "$app"
            fi
        else
            if [ "$INSTALL_APP" == "apt-get" ]; then
                apt-get purge -y --auto-remove "$app"
            elif [ "$INSTALL_APP" == "zypper" ]; then
                zypper remove -y --clean-deps "$app"
            else
                eval "$INSTALL_APP remove -y $app"
            fi
        fi
    done
}

extract_version() {
    ver=$1
    python3 -c "import re; m=re.findall(r'[0-9]+\.[0-9]+\.?[0-9]*', '$ver'); print(m[0] if len(m)>0 else '' )"

}

check_available_version() {
    app=$1
    min_ver=$2
    if [ "$INSTALL_APP" == "apt-get" ]; then
        cmd="apt show  "$app"  2>/dev/null  | grep -i \"Version:\""
    elif [ "$INSTALL_APP" == "zypper" ]; then
        cmd="zypper info "$app" | grep \"Version\""
    else
        cmd="yum info "$app" | grep -i version"
    fi

    app_ver=$(eval "$cmd")
    app_ver=$(extract_version "$app_ver")

    if [[ "$app_ver" == "" ]]; then
        exit_err "Package not available: $app"
    fi
    if version_less_than $app_ver $min_ver; then
        exit_err "Package($app) - Available Version($app_ver) - Min Version($min_ver)"
    fi
    echo "Package($app) - Available Version($app_ver) - Min Version($min_ver)"
}

setup_strongswan_restart_service() {

    # Define the systemd service unit content
    SERVICE_UNIT_CONTENT="[Unit]
    Description=Restart StrongSwan service and log the event
    After=network.target multi-user.target

    [Service]
    Type=oneshot
    ExecStart=/bin/bash -c 'systemctl restart strongswan && echo \"$(date) - StrongSwan service restarted by systemd service\" >> /var/log/restart-strongswan.log'
    RemainAfterExit=true

    [Install]
    WantedBy=multi-user.target
    "

    # Check if systemd and systemctl is available
    if [ "$(ps -p 1 -o comm=)" = "systemd" ] && systemctl > /dev/null 2>&1; then
        # Create the systemd service unit file
        echo "$SERVICE_UNIT_CONTENT" | sudo tee /etc/systemd/system/restart-strongswan.service

        # Reload systemd configuration
        sudo systemctl daemon-reload

        # Enable and start the service
        sudo systemctl enable restart-strongswan.service
        sudo systemctl start restart-strongswan.service

        echo "StrongSwan restart service installed and enabled via systemd."
    fi
}

remove_strongswan_restart_service() {

    # Check if systemd is available
    if [ "$(ps -p 1 -o comm=)" = "systemd" ] && systemctl > /dev/null 2>&1; then
        # Stop the service if it is running
        sudo systemctl stop restart-strongswan.service

        # Disable the service
        sudo systemctl disable restart-strongswan.service

        # Remove the service unit file
        sudo rm /etc/systemd/system/restart-strongswan.service

        # Reload systemd configuration
        sudo systemctl daemon-reload

        echo "StrongSwan restart service removed."
    fi
}


_install_app() {
    PACKAGE_NAME=$1
    log "Installing package $PACKAGE_NAME"
    # Install the package with specific conditions for mount.ibmshare* packages
    if [[ $PACKAGE_NAME == mount.ibmshare* ]]; then
        if [ "$LINUX_INSTALL_APP" == "$YUM" ]; then
            eval "yum install -y $PACKAGE_NAME --nogpgcheck"
        elif [ "$LINUX_INSTALL_APP" == "$APT" ]; then
            eval "apt-get --allow-unauthenticated -y install $PACKAGE_NAME"
        elif [ "$LINUX_INSTALL_APP" == "$ZYP" ]; then
            eval "zypper --no-gpg-checks install -y $PACKAGE_NAME"
        fi
    else
        eval "$LINUX_INSTALL_APP $PACKAGE_NAME"
    fi
    check_result "Problem installing package: $PACKAGE_NAME"
    log "Updating package $PACKAGE_NAME"
    # Update the package
    if [ "$LINUX_INSTALL_APP" == "$YUM" ]; then
        eval "yum update -y $PACKAGE_NAME"
    elif [ "$LINUX_INSTALL_APP" == "$APT" ]; then
        eval "apt-get install --only-upgrade -y $PACKAGE_NAME"
    elif [ "$LINUX_INSTALL_APP" == "$ZYP" ]; then
        eval "zypper update -y $(basename $PACKAGE_NAME .rpm)"
    fi
}

_install_apps() {
    apps=($@)

    if ( is_linux LINUX_UBUNTU || is_linux LINUX_DEBIAN ) && [[ "$INSTALL_ARG" != "--update" && "$INSTALL_ARG" != "--update-stage" ]]; then
        # Storing all the packages which come by default on the system. This will be used in uninstalltion case.
        dpkg -l | grep '^ii' | awk '{print $2}' > $INSTALLED_PACKAGE_LIST

    elif ( is_linux LINUX_RED_HAT || is_linux LINUX_CENTOS ) && [[ "$INSTALL_ARG" != "--update" && "$INSTALL_ARG" != "--update-stage" ]]; then
        rpm -qa --queryformat '%{NAME}\n' > $INSTALLED_PACKAGE_LIST

    fi

    for app in "${apps[@]}"; do
        if [[ (( "$INSTALL_ARG" == "--update" || "$INSTALL_ARG" == "--update-stage" )) && $app != "mount.ibmshare"* ]]; then
            continue
        fi
        if grep -q -i "strongswan" <<< "$app" && ! is_linux LINUX_UBUNTU && ! is_linux LINUX_RED_HAT; then
            check_available_version "$app" $MIN_STRONGSWAN_VERSION
        fi

        if is_linux LINUX_UBUNTU && ([[ ! "$ARCH" = *"s390x"* ]]); then
            # Read preInstalled packages from system
            if [[ $app != *"python"* && $(grep -q "^$app" $INSTALLED_PACKAGE_LIST; echo $?) -eq 0 ]] ; then
                log "Skipping package $app for installation as it is pre-installed on the system"
                continue
            fi
            log "Installing package $app"
            if [[ $app == "mount.ibmshare"* || $app == *"python"* ]]; then
                dpkg --force-all -i "$app"
                continue
            fi
            PACKAGE_DIR="packages/ubuntu/$VERSION"
            dpkg --force-all -i "$PACKAGE_DIR/$app"*
        elif is_linux LINUX_DEBIAN ; then
            # Read preInstalled packages from system
            if [[ $app != *"python"* && $(grep -q "^$app" $INSTALLED_PACKAGE_LIST; echo $?) -eq 0 ]] ; then
                log "Skipping package $app for installation as it is pre-installed on the system"
                continue
            fi
            log "Installing package $app"
            if [[ $app == *"nfs-common"* ]]; then
                _install_app "$app"
                sudo systemctl enable --now nfs-client.target
                continue
            fi
            if [[ $app == "mount.ibmshare"* || $app == *"python"* ]]; then
                dpkg --force-all -i "$app"
                continue
            else
                _install_app "$app"
            fi
        elif  is_linux LINUX_RED_HAT && ([[ -d "$DOWNLOADED_RHEL_PACKAGE_PATH" ]]); then
            # Read preInstalled packages from system
            if [[ $app != *"python"* && $(grep -q "^$app" $INSTALLED_PACKAGE_LIST; echo $?) -eq 0 ]] ; then
                log "Skipping package $app for installation as it is pre-installed on the system"
                continue
            fi
            log "Installing package $app"
            if [[ $app == mount.ibmshare* ]]; then
                if [[ "$INSTALL_ARG" == "--update" || "$INSTALL_ARG" == "--update-stage" ]]; then
                    rpm -U "$app" --force --nodeps --nodigest --nosignature
                else
                    rpm -i "$app" --force --nodeps --nodigest --nosignature
                fi
            continue
            fi
            if [[ $app == *"python"* ]]; then
                rpm -i "$app" --force --nodeps
                continue
            fi
            PACKAGE_DIR="packages/rhel/$VERSION"
            rpm -i "$PACKAGE_DIR/$app"* --force --nodeps
        elif  is_linux LINUX_CENTOS ; then
            # Read preInstalled packages from system
            if [[ $app != *"python"* && $(grep -q "^$app" $INSTALLED_PACKAGE_LIST; echo $?) -eq 0 ]] ; then
                log "Skipping package $app for installation as it is pre-installed on the system"
                continue
            fi
            log "Installing package $app"
            if [[ $app == mount.ibmshare* ]]; then
                if [[ "$INSTALL_ARG" == "--update" || "$INSTALL_ARG" == "--update-stage" ]]; then
                    rpm -U "$app" --force --nodeps --nodigest --nosignature
                else
                    rpm -i "$app" --force --nodeps --nodigest --nosignature
                fi
            continue
            fi
            if [[ $app == *"python"* ]]; then
                rpm -i "$app" --force --nodeps
                continue
            fi
            _install_app "$app"
        else
            _install_app "$app"
        fi
    done
}

install_apps() {

    if [ "$INSTALL_ARG" == "--uninstall" ]; then
        _remove_apps "$@"
        reject_ipsec ||  remove_strongswan_restart_service
        if is_linux LINUX_SUSE; then
           reject_ipsec ||  sudo systemctl unmask strongswan.service
        fi
        # Check if stunnel is installed
        if command -v stunnel >/dev/null 2>&1; then
            echo "STUNNEL is installed. Please run './install_stunnel.sh uninstall' to uninstall it..."
        fi
        exit_ok "UnInstall completed ok"
    fi
    _install_apps "$@"
}

get_current_python_version () {
  echo "$(python3 --version 2>&1 | awk '{print $2}')"
}

wait_till_true () {
    action="$1"
    secs=$2
    echo "Wait: $1"
    for i in `seq 1 10`; do
        eval "$action" &>/dev/null
        if [ "$?" == "0" ]; then
            return
        fi
        sleep $secs
    done
}

check_python3_installed () {
    if ! reject_ipsec
    then
    	if command_exist cloud-init; then
        	log "Wait for cloud-init to complete."
        	cloud-init status --wait --long
    	fi
    fi

    if is_linux LINUX_RED_HAT; then
        PYTHON3_PACKAGE=packages/rhel/$VERSION/python*.rpm
    elif ( is_linux LINUX_UBUNTU || is_linux LINUX_DEBIAN ); then
        PYTHON3_PACKAGE=packages/ubuntu/$VERSION/python*.deb
    else
        PYTHON3_PACKAGE=$1
    fi
    if command_not_exist python3; then
        if [ "$PYTHON3_PACKAGE" == "" ]; then
            exit_err "Python3 not installed"
        fi;
        _install_apps "$PYTHON3_PACKAGE"
    fi;
    PYTHON3_VERSION="$(get_current_python_version)"
    if version_less_than $PYTHON3_VERSION $MIN_PYTHON3_VERSION; then
        exit_err  "Can only install with Python3 version $MIN_PYTHON3_VERSION or greater. Current version:$PYTHON3_VERSION"
    fi;
    log "Python $PYTHON3_VERSION installed"
}

disable_metadata () {

    log "Disabling metadata service"
    sed -i 's/USE_METADATA_SERVICE = True/USE_METADATA_SERVICE = False/' $SBIN_SCRIPT
}

install_tls_certificates() {

    CERT_PATH="$1"
    if is_linux LINUX_UBUNTU &&  [[ "$VERSION" == 24.04 ]]; then
        TLS_CERT_PATH="/usr/local/share/ca-certificates"
        cp "$CERT_PATH"/* "$TLS_CERT_PATH/"
        if [ $? -eq 0 ]; then
            echo "CA certificates for TLS copied successfully to usr/local/share/ca-certificates."
        else
            exit_err "Error: Failed to copy ca-certificates for TLS copied ."
        fi
        echo "Updating CA certificates..."
        sudo update-ca-certificates
        if [ $? -eq 0 ]; then
            echo "CA certificates updated successfully."
        else
            exit_err "Error: Failed to update CA certificates."
        fi
    fi
    if { is_linux LINUX_RED_HAT && [[ "$VERSION" == 9.4 ]]; } || { is_linux LINUX_ROCKY && [[ "$VERSION" == 9.4 ]]; }; then
       TLS_CERT_PATH="/etc/pki/ca-trust/source/anchors"
       for CERT in "$CERT_PATH"/*.crt; do
            if [ -f "$CERT" ]; then
                CERT_NAME=$(basename "$CERT" .crt)
                sudo cp "$CERT" "$TLS_CERT_PATH/$CERT_NAME.pem"
            fi
        done
        if [ $? -eq 0 ]; then
            echo "CA certificates for TLS copied and renamed successfully to $TLS_CERT_PATH."
        else
             exit_err "Error: Failed to copy CA certificates."
        fi
        echo "Updating CA certificates..."
        sudo update-ca-trust anchors
        if [ $? -eq 0 ]; then
            echo "CA certificates updated successfully."
        else
            exit_err "Error: Failed to update CA certificates."
        fi
    fi
}

touch_conf_file() {
    sudo touch  "$CONF_FILE"
    sudo chmod 744  "$CONF_FILE"
}

setup_share_config() {
    DIR_NAME="/etc/ibmcloud"

    sudo mkdir -p $DIR_NAME
    sudo chmod 744 $DIR_NAME
    touch_conf_file
}

init_mount_helper () {
    if [[ "$INSTALL_ARG" == "region="* ]]; then
        region_code="${INSTALL_ARG#region=}"
        mapped_region="${region_map[$region_code]}"
        if [ -n "$mapped_region" ]; then
            log "Updating config file: $CONF_FILE"
            sed -i "s/region=.*/region=$mapped_region/" $CONF_FILE
        else
            exit_err "Error: Invalid region code '$region_code'"
        fi
        INSTALL_ARG=""
    fi

    if [[ "$INSTALL_MOUNT_OPTION_ARG" == "stage" ]]; then
        exit_err "incorrect command, pass stage as first arg."
    fi
    if [[ "$INSTALL_ARG" == "--tls" || "$INSTALL_MOUNT_OPTION_ARG" == "--tls" ]]; then
        check_tls_supported_linux_verion
    fi
    if [[ "$INSTALL_ARG" == "stage" || "$INSTALL_ARG" == "--update-stage" ]]; then
        CERT_PATH="./dev_certs/metadata"
        log "Installing certs for stage environment..."
        $SBIN_SCRIPT -INSTALL_ROOT_CERT $CERT_PATH
        check_result "Problem installing ssl certs"
        if [[ "$INSTALL_MOUNT_OPTION_ARG" == "--tls" ]]; then
            install_tls_certificates $CERT_PATH
        fi
        exit_ok "Install completed ok"
    fi


    if [[ "$INSTALL_ARG" == "" || "$INSTALL_ARG" == "--update" || "$INSTALL_ARG" == "--tls" || "$INSTALL_ARG" == "--stunnel" ]]; then
        if [[ "$INSTALL_ARG" == "--tls" ]]; then
            INSTALL_MOUNT_OPTION_ARG="--tls"
        fi
        INSTALL_ARG="metadata"
    fi

   	log "Installing certs for: $INSTALL_ARG"
    CERT_PATH="./certs/$INSTALL_ARG"
    if [ ! -d $CERT_PATH ]; then
        exit_err "$CERT_PATH cert folder does not exist"
    fi
    if [ "$INSTALL_ARG" != "metadata" ]; then
        disable_metadata
    fi
    $SBIN_SCRIPT -INSTALL_ROOT_CERT $CERT_PATH
    check_result "Problem installing ssl certs"
    if [[ "$INSTALL_MOUNT_OPTION_ARG" == "--tls" ]]; then
      	install_tls_certificates $CERT_PATH
    fi
    # Check if STUNNEL_ENABLED is set to true
    if [ "$STUNNEL_ENABLED" == "true" ]; then
        echo "STUNNEL is enabled. Installing stunnel..."

        # Make sure the script exists
        if [ -x "./install_stunnel.sh" ]; then
            ./install_stunnel.sh install
        else
            echo "Error: install_stunnel.sh not found or not executable in current directory."
            exit 1
        fi
    fi
    exit_ok "Install completed ok"
}

# main starts here.
#
if [[ "$INSTALL_ARG" == "--stunnel" ]]; then
        STUNNEL_INSTALL_CMD="./install_stunnel.sh install"
        STUNNEL_ENABLED=true
else
        STUNNEL_INSTALL_CMD="echo skipping stunnel..."

fi


reject_ipsec && setup_share_config

if ( is_linux LINUX_UBUNTU || is_linux LINUX_DEBIAN ); then
    export DEBIAN_FRONTEND=noninteractive
    check_python3_installed

    if reject_ipsec
    then
        install_apps mount.ibmshare*.deb && $STUNNEL_INSTALL_CMD
        exit $?
    fi

    apt-get -y remove needrestart

    # Define the path to the package list file based on the Ubuntu version or debian
    if is_linux  LINUX_DEBIAN ; then
        #debian by default does not have /etc/hosts defined
        if [ ! -f /etc/hosts ]; then
            HOSTNAME=$(hostname)
            echo "127.0.0.1   $HOSTNAME localhost" > /etc/hosts
            echo "::1         localhost ip6-localhost ip6-loopback" >> /etc/hosts
            echo "127.0.1.1   $HOSTNAME" >> /etc/hosts
            echo "/etc/hosts created with hostname: $HOSTNAME"
        fi
        PACKAGE_LIST_PATH="packages/debian/package_list"
    else
        PACKAGE_LIST_PATH="packages/ubuntu/$VERSION/package_list"
    fi

    # Check if the package list file exists
    if [ ! -f "$PACKAGE_LIST_PATH" ]; then
        exit_err "Package list file '$PACKAGE_LIST_PATH' does not exist"
    fi

    # Read the package list from the file
    packages=()
    while IFS= read -r line; do
         packages+=("$line")
    done < "$PACKAGE_LIST_PATH"

    # Install the packages in the defined order
    install_apps "${packages[@]}" mount.ibmshare*.deb
    setup_strongswan_restart_service
    init_mount_helper
fi;

if is_linux LINUX_RED_HAT; then
    check_python3_installed python3

    if reject_ipsec
    then
        install_apps mount.ibmshare*.rpm && $STUNNEL_INSTALL_CMD
        exit $?
    fi

    if [ -d "$DOWNLOADED_RHEL_PACKAGE_PATH" ]; then
        # Define the path to the package list file based on the RHEL version
        PACKAGE_LIST_PATH="packages/rhel/$VERSION/package_list"

        # Check if the package list file exists
        if [ ! -f "$PACKAGE_LIST_PATH" ]; then
            exit_err "Package list file '$PACKAGE_LIST_PATH' does not exist"
        fi

        # Read the package list from the file
        packages=()
       	while IFS= read -r line; do
            packages+=("$line")
        done < "$PACKAGE_LIST_PATH"

        # Install the packages in the defined order
        install_apps "${packages[@]}" mount.ibmshare*.rpm
        setup_strongswan_restart_service
        init_mount_helper
    else
        if [ "$INSTALL_ARG" != "--uninstall" ]; then
            yum install -y --nogpgcheck "https://dl.fedoraproject.org/pub/epel/epel-release-latest-$MAJOR_VERSION.noarch.rpm"
        fi
        install_apps strongswan  nfs-utils iptables mount.ibmshare*.rpm
        setup_strongswan_restart_service
        init_mount_helper
    fi
fi;

if is_linux LINUX_CENTOS; then
    check_python3_installed python3
    if reject_ipsec
    then
        install_apps mount.ibmshare*.rpm && $STUNNEL_INSTALL_CMD
        exit $?
    fi
    # Define the path to the package list file for CENTOS_STREAM
    PACKAGE_LIST_PATH="packages/centos_stream/$VERSION/package_list"

    # Check if the package list file exists
    if [ ! -f "$PACKAGE_LIST_PATH" ]; then
        exit_err "Package list file '$PACKAGE_LIST_PATH' does not exist"
    fi

    # Read the package list from the file
    packages=()
    while IFS= read -r line; do
        packages+=("$line")
    done < "$PACKAGE_LIST_PATH"

    if [ "$INSTALL_ARG" != "--uninstall" ]; then
        sudo dnf install -y "https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm"
    fi

    # Install the packages in the defined order
    install_apps "${packages[@]}" mount.ibmshare*.rpm
    setup_strongswan_restart_service
    init_mount_helper
fi;

if is_linux LINUX_ROCKY; then
    check_python3_installed python39
    if reject_ipsec
    then
        install_apps mount.ibmshare*.rpm && $STUNNEL_INSTALL_CMD
        exit $?
    fi

    install_apps epel-release strongswan strongswan-sqlite nfs-utils mount.ibmshare*.rpm
    setup_strongswan_restart_service
    init_mount_helper
fi;

if is_linux LINUX_SUSE; then
    check_python3_installed
    if reject_ipsec
    then
        install_apps mount.ibmshare*.rpm && $STUNNEL_INSTALL_CMD
        exit $?
    fi
    # causing install failures - so disable it
    systemctl disable --now packagekit
    install_apps strongswan nfs-client mount.ibmshare*.rpm
    setup_strongswan_restart_service
    init_mount_helper
fi;

if is_linux LINUX_FEDORA; then
    echo "Locked down distro not supported"
fi;


exit_err "IbmMountHelper Install not supported $NAME $VERSION"
