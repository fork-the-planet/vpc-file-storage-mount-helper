#!/usr/bin/env python3
#
# Copyright (c) IBM Corp. 2023. All Rights Reserved.
# Project name: VPC File Storage Mount Helper
# This project is licensed under the MIT License, see LICENSE file in the root directory.

import argparse
from enum import Enum
from common import *

ESSENTIAL_OPTIONS = "sec=sys"
MOUNT = "mount"
NFS_VERSION = "nfs4"
MOUNT_T_OPTION = "-t"
MOUNT_O_OPTION = "-o"
MOUNT_VERBOSE_FLAG = "-v"
RENEW_CERTIFICATE_FLAG = "-RENEW_CERTIFICATE_NOW"
INSTALL_ROOT_CERT = "-INSTALL_ROOT_CERT"
SECURE_OPTION = "secure"
SECURE_ARG = "true"
MOUNT_OPTION_TLS = "tls"
TLS_OPTION = "xprtsec=tls"
MOUNT_OPTION_IPSEC = "ipsec"
MOUNT_OPTION_STUNNEL = "stunnel"
SBIN_SCRIPT = "/sbin/mount.ibmshare"
TEARDOWN_APP = "-TEARDOWN_APP"
TLS_ENABLED_OS = ["Ubuntu 24.04", "Red Hat Enterprise Linux 9.4", "Rocky Linux 9.4"]


class AppRunType(object):
    SETUP = "SUP"
    TEARDOWN = "TDN"
    RENEW = "REN"
    MOUNT = "MNT"

    def __init__(self, value):
        self.value = value

    def is_setup(self):
        return self.value == self.SETUP

    def is_teardown(self):
        return self.value == self.TEARDOWN

    def is_renew(self):
        return self.value == self.RENEW

    def is_mount(self):
        return self.value == self.MOUNT


class ArgsHandler(MountHelperBase):
    """Class to process nfs mount command arguments."""

    mount_args = None

    def __init__(self):
        self.ip_address = None
        self.mount_point = None
        self.mount_path = None
        self.mount_source = None
        self.options = None
        self.is_secure = False
        self.is_tls = False
        self.is_stunnel = False

    def parse(self):
        is_error = False

        def parse_error(errmsg):
            nonlocal is_error
            is_error = True
            self.LogError(errmsg)

        parser = argparse.ArgumentParser()
        parser.error = parse_error
        parser.add_argument("Source", default="")  # nfs_host:path
        parser.add_argument("Destination", default="")  # mount point
        parser.add_argument("-t", default="")
        parser.add_argument("-o", default="")
        args, _ = parser.parse_known_args()
        if is_error:
            return False
        self.mount_source = args.Source
        self.mount_point = args.Destination
        self.ip_address, self.mount_path = NfsMount.extract_source(self.mount_source)
        if not self.ip_address or not self.mount_path:
            return self.LogError(
                "Provide the mount source as <ip address or resolvable nfs_host>:<path>("
                + self.mount_source
                + ")."
            )
        if len(self.mount_point) <= 0:
            return self.LogError("Provide the mount point to mount on local host.")
        self.options, self.is_secure, self.is_tls, self.is_stunnel = (
            self.get_mount_options(args.o)
        )
        return True

    @staticmethod
    def get_mount_args():
        args = ArgsHandler()
        return args if args.parse() else None

    @staticmethod
    def is_renew_certificate():
        return SysApp.has_arg(RENEW_CERTIFICATE_FLAG)

    @staticmethod
    def is_app_setup():
        return SysApp.has_arg(INSTALL_ROOT_CERT)

    @staticmethod
    def is_app_teardown():
        return SysApp.has_arg(TEARDOWN_APP)

    def get_renew_certificate_cmd_line(self):
        return SBIN_SCRIPT + " " + RENEW_CERTIFICATE_FLAG

    @staticmethod
    def is_debug_enabled():
        args = str(SysApp.argv())
        return MOUNT_VERBOSE_FLAG in args

    @staticmethod
    def get_app_run_type():
        run_type = AppRunType.MOUNT
        if ArgsHandler.is_app_setup():
            run_type = AppRunType.SETUP
        elif ArgsHandler.is_app_teardown():
            run_type = AppRunType.TEARDOWN
        elif ArgsHandler.is_renew_certificate():
            run_type = AppRunType.RENEW
        return AppRunType(run_type)

    @staticmethod
    def is_request_stunnel():
        parser = argparse.ArgumentParser()
        parser.add_argument("-o", default="")
        args, _ = parser.parse_known_args()

        return MOUNT_OPTION_STUNNEL in args.o

    @staticmethod
    def set_logging_level():
        rt = ArgsHandler.get_app_run_type()
        if ArgsHandler.is_debug_enabled() or rt.is_setup() or rt.is_teardown():
            MountHelperLogger().SetDebugEnabled()
        MountHelperLogger().SetLogToFileEnabled()
        MountHelperLogger.log_prefix = rt.value

    # Method to return all -o option list of mount command.
    def get_mount_options(self, opts_in):
        is_secure = False
        is_tls = False
        is_stunnel = False
        eit_counter = 0
        options = opts_in.split(",")
        error_selection = ""
        o_options = []
        for option in options:
            if not SECURE_OPTION in option.lower():
                if MOUNT_OPTION_TLS == option.lower():
                    if self.tls_on_version() == True:
                        is_tls = True
                        eit_counter += 1
                        error_selection += str(eit_counter) + ") " + MOUNT_OPTION_TLS
                    else:
                        sys.exit(0)
                elif MOUNT_OPTION_IPSEC == option.lower():
                    is_secure = True
                    eit_counter += 1
                    error_selection += (
                        " " + str(eit_counter) + ") " + MOUNT_OPTION_IPSEC
                    )
                elif MOUNT_OPTION_STUNNEL == option.lower():
                    is_stunnel = True
                    is_secure = True
                    eit_counter += 1
                    error_selection += (
                        " " + str(eit_counter) + ") " + MOUNT_OPTION_STUNNEL
                    )
                else:
                    o_options.append(option)
            elif SECURE_ARG in option.lower().split("="):
                is_secure = True
        if eit_counter > 1:
            self.LogError("Choose only one of the folowing " + error_selection)
            sys.exit(0)
        elif is_tls:
            if is_tls:
                o_options.append(TLS_OPTION)
            if is_secure:
                # dont generate certs
                print("non eit mount")
        return ",".join(o_options), is_secure, is_tls, is_stunnel

    def get_stunnel_mount_cmd_line(self, port, source):
        cmd = [
            MOUNT,
            MOUNT_T_OPTION,
            NFS_VERSION,
            MOUNT_O_OPTION,
            ",".join([ESSENTIAL_OPTIONS, self.options, "port=" + str(port)]),
            source,
            self.mount_point,
        ]
        if self.is_debug_enabled():
            cmd.append(MOUNT_VERBOSE_FLAG)

        return cmd

    # Method to contruct mount command to run finally.
    def get_mount_cmd_line(self):
        assert len(self.mount_source) > 0
        if self.is_tls:
            tls_mount_source = self.get_tls_mount_source()
            if tls_mount_source != "":
                self.mount_source = tls_mount_source
        cmd = [
            MOUNT,
            MOUNT_T_OPTION,
            NFS_VERSION,
            MOUNT_O_OPTION,
            ",".join([ESSENTIAL_OPTIONS, self.options]),
            self.mount_source,
            self.mount_point,
        ]

        # pass on the verbose flag
        if self.is_debug_enabled():
            cmd.append(MOUNT_VERBOSE_FLAG)

        return cmd

    def tls_on_version(self):
        system_ctl = SystemCtl(self)
        required_packages_for_tls = ["ktls-utils", "ca-certificates"]
        if (
            system_ctl.check_tls_enabled_os(TLS_ENABLED_OS)
            and system_ctl.is_kernel_version_6_or_higher()
        ):
            for package in required_packages_for_tls:
                if system_ctl.tls_package_installed(package):
                    self.LogDebug(package + " package is installed on the system")
                else:
                    self.LogError(
                        "TLS is not supported , package is not installed on the system: "
                        + package
                    )
                    return False
            return True
        else:
            self.LogError(
                "TLS is not supported on current version, make sure kernel version is 6.x "
            )
            return False

    def get_tls_mount_source(self):
        self.ip_address, self.mount_path = NfsMount.extract_source(self.mount_source)
        file_path = "/etc/hosts"
        self.check_and_add_ip_to_hosts()
        if self.FileExists(file_path):
            with open(file_path, "r") as content:
                for line in content:
                    tls_mount_source = line.split()
                    if len(tls_mount_source) >= 2:
                        ip_address = tls_mount_source[0]
                        value = tls_mount_source[1]
                        if ip_address == self.ip_address:
                            self.LogInfo(
                                "Using corresponding mount address to honour tls connection "
                                + value
                            )
                            self.mount_source = value + ":" + self.mount_path
                            return self.mount_source

    def check_and_add_ip_to_hosts(self):
        file_path = "/etc/hosts"
        with open(file_path, "r") as content:
            lines = content.readlines()
            ip_exists = any(line.startswith(self.ip_address) for line in lines)
            if not ip_exists:
                try:
                    subprocess.run(["./tls.sh", self.ip_address], check=True)
                    self.LogInfo("Added ip address in /etc/hosts.")
                except subprocess.CalledProcessError as e:
                    sys.exit(0)
