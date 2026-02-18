#!/usr/bin/env python3
#
# Copyright (c) IBM Corp. 2025. All Rights Reserved.
# Project name: VPC File Storage Mount Helper
# This project is licensed under the MIT License, see LICENSE file in the root directory.

import re
import os


class StunnelConfigGet:
    IBM_SHARE_SIG = "ibmshare"
    STUNNEL_DIR_NAME = "/etc/stunnel"
    STUNNEL_PID_FILE_DIR = "/var/run/stunnel4"
    STUNNEL_LOG_DIR = "/var/log/stunnel"
    STUNNEL_CONF_EXT = ".conf"
    STUNNEL_IDENTIFIER = "stunnel_identifier"
    SHARE_CONFIG_FILE = "/etc/ibmshare/share.conf"
    CA_FILE_KEY = "TRUSTED_ROOT_CACERT"
    STUNNEL_ENV_KEY = "STUNNEL_ENV"

    STUNNEL_ENV_DEV = "dev"
    STUNNEL_ENV_STAGE = "staging"
    STUNNEL_ENV_PROD = "production"

    STUNNEL_ACCEPT = "accept"
    STUNNEL_CONNECT = "connect"
    FILE_NOT_FOUND_ERR = "StunnelConfigGet could not find the config_file"
    FILE_OPEN_GENERIC_ERR = "StunnelConfigGet received an error on file open"
    TLS_CA_NAME = os.path.join(STUNNEL_DIR_NAME, "allca.pem")

    def __init__(self):
        self.accept_ip = None
        self.accept_port = None
        self.connect_ip = None
        self.connect_port = None
        self.pid_file = None
        self.found = False
        self.error = None
        self.remote_path = None

    @staticmethod
    def get_pid_file_dir():
        return StunnelConfigGet.STUNNEL_PID_FILE_DIR

    @staticmethod
    def get_sanitized_remote_path(remote_path, connect_ip_str=""):
        path = StunnelConfigGet.IBM_SHARE_SIG + remote_path.replace("/", "_")
        if len(connect_ip_str) > 0:
            path = path + "_" + connect_ip_str.replace(".", "-")
        return path

    # Versions v1 and v2 only refer to the file name fomat.
    # v2 name format has the ip address of the mount path embedded
    @staticmethod
    def get_v2_config_file_from_remote_path(remote_path, connect_ip):
        if len(connect_ip) > 0:
            connect_ip_str = str(connect_ip)
        else:
            connect_ip_str = ""

        clean_name = StunnelConfigGet.get_sanitized_remote_path(
            remote_path, connect_ip_str
        )
        return os.path.join(
            StunnelConfigGet.STUNNEL_DIR_NAME,
            clean_name + StunnelConfigGet.STUNNEL_CONF_EXT,
        )

    @staticmethod
    def get_v1_config_file_from_remote_path(remote_path):
        clean_name = StunnelConfigGet.get_sanitized_remote_path(remote_path)
        return os.path.join(
            StunnelConfigGet.STUNNEL_DIR_NAME,
            clean_name + StunnelConfigGet.STUNNEL_CONF_EXT,
        )

    def open_with_remote_path(self, remote_path, connect_ip):
        v1_format = StunnelConfigGet.get_v1_config_file_from_remote_path(remote_path)
        v2_format = StunnelConfigGet.get_v2_config_file_from_remote_path(
            remote_path, connect_ip
        )
        self.parse_with_full_path(v2_format)
        if not self.found:
            self.parse_with_full_path(v1_format)

    def parse_with_full_path(self, config_file):
        self.config_file = config_file
        try:
            with open(config_file, "r") as file:
                for line in file:
                    line = line.strip()
                    self.parse_lines(line)
            self.found = True
        except FileNotFoundError as fne:
            self.error = f"{StunnelConfigGet.FILE_NOT_FOUND_ERR} : {fne}"
            self.found = False

        except Exception as e:
            self.error = f"{StunnelConfigGet.FILE_OPEN_GENERIC_ERR}: {e}"
            self.found = False

    def parse_lines(self, line):
        match = re.match(r"pid\s*=\s*(.+)", line)
        if match:
            self.pid_file = match.group(1)
        else:
            match = re.match(
                rf"#\s*{StunnelConfigGet.STUNNEL_IDENTIFIER}\s*=\s*(.+)", line
            )
            if match:
                self.remote_path = match.group(1)

            else:
                pattern = r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d{1,5})"
                match = re.search(pattern, line)
                if match:
                    ip = match.group(1)
                    port = match.group(2)
                    if f"{StunnelConfigGet.STUNNEL_CONNECT}" in line:
                        self.connect_ip = ip
                        self.connect_port = port
                    elif f"{StunnelConfigGet.STUNNEL_ACCEPT}" in line:
                        self.accept_ip = ip
                        self.accept_port = port

    def get_pid_file(self):
        return self.pid_file

    def is_found(self):
        return self.found

    def get_config_file(self):
        return self.config_file

    def get_full_mount_path(self):
        return self.remote_path

    def get_error(self):
        return self.error
