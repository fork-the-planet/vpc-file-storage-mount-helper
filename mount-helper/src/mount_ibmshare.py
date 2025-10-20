#!/usr/bin/env python3
#
# Copyright (c) IBM Corp. 2023. All Rights Reserved.
# Project name: VPC File Storage Mount Helper
# This project is licensed under the MIT License, see LICENSE file in the root directory.

from args_handler import ArgsHandler
from common import *
import file_lock
import os
import stat
import signal
import timer_handler
import traceback
from renew_certs import RenewCerts
from config import LocalInstall, StrongSwanConfig
import stunnel_config_create, find_free_stunnel_port
from stunnel_config_get import StunnelConfigGet

LOOPBACK_ADDRESS = "127.0.0.1"
MOUNT_PORT = 20049
STUNNEL_COMMAND = "stunnel"


class MountIbmshare(MountHelperBase):

    DESIRED_DEFAULT_UMASK = 0o22

    def __init__(self):
        self.mounts = []
        self.lockhandler = file_lock.LockHandler.mount_share_lock()

    def set_installed_stunnel(self):
        stunnel_dirs = ["/etc/stunnel", "/var/log/stunnel/"]
        errored = False
        for directory in stunnel_dirs:
            if not os.path.isdir(directory):
                self.LogError(f"The directory '{directory}' does not exist.")
                errored = True

        if errored:
            self.LogError(
                f"The Stunnel setup required for encryption in transit is missing."
            )
            self.LogError(
                f"Please download mount helper and run  './install.sh --stunnel' to complete installation"
            )

        return not errored

    def set_installed_ipsec(self):
        ss_obj = StrongSwanConfig()
        if ss_obj.set_version():
            LocalInstall.set_ipsec_mgr(ss_obj)
            return True
        self.LogError("IPsec installation failed, check the charon logs.")
        return False

    def get_ipsec_mgr(self):
        return LocalInstall.get_ipsec_mgr()

    def app_setup(self):
        if LocalInstall.setup():
            ipsec = self.get_ipsec_mgr()
            if ipsec:
                ipsec.remove_all_configs(unused=True)
                if ipsec.setup():
                    cert_path = SysApp.argv(2)
                    return RenewCerts().install_root_cert(cert_path)
        self.LogError("Installation failed.", code=SysApp.ERR_APP_INSTALL)
        return False

    def is_ppc(self):
        try:
            answer = subprocess.run(
                ["uname", "-m"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                check=True,
            ).stdout.strip()
            return answer.startswith("ppc")
        except subprocess.CalledProcessError as e:
            self.LogError(f"Cannot fetch architecture due to exception {e}")
            return False

    def app_teardown(self):
        self.LogDebug("TearDown starting")
        ipsec = self.get_ipsec_mgr()
        if ipsec:
            ipsec.remove_all_certs()
            ipsec.remove_all_configs()
        LocalInstall.teardown()
        timer_handler.TimerHandler().teardown()
        self.LogDebug("TearDown complete")
        return True

    def renew_certs(self):
        return RenewCerts().renew_cert_cmd_line()

    def lock(self):
        return self.lockhandler.grab_blocking_lock()

    def unlock(self):
        return self.lockhandler.release_lock()

    # Method to check whether nfs share is already mounted.
    def is_share_mounted(self, ip_address, mount_path, port=""):
        self.mounts = NfsMount().load_nfs_mounts()
        for mount in self.mounts:
            if mount.ip == ip_address and mount.mount_path == mount_path:
                if port == "" or port == mount.mount_port:
                    return True
        return False

    def configure_default_umask(self):
        # Need to call os.umask twice as the call returns previous seting of umask.
        desired_default_umask = self.DESIRED_DEFAULT_UMASK
        os.umask(desired_default_umask)
        current_umask = os.umask(desired_default_umask)

        return current_umask == desired_default_umask

    def process_stunnel_mount(self, args):
        ip_address = args.ip_address
        mount_path = args.mount_path
        config_file_found = False

        if not self.configure_default_umask():
            self.LogError(
                f"Could not set umask to 0{self.DESIRED_DEFAULT_UMASK:o}. Aborting"
            )
            return False

        # Identify a port for stunnel.
        port = find_free_stunnel_port.FindFreeSTunnelPort(
            LOOPBACK_ADDRESS
        ).get_free_port()

        if port == -1:
            self.LogError("No Free ports found for use by Stunnel.")
            return False

        self.LogDebug(f"Local port {port} will be used for setting up the next stunnel")

        pid_file_dir = StunnelConfigGet.get_pid_file_dir()
        if not os.path.isdir(pid_file_dir):
            try:
                os.makedirs(pid_file_dir, exist_ok=True)
            except OSError as ex:
                self.LogError(
                    f'Attempt to create directory "{pid_file_dir}" resulted in an exception {ex}. Please fix and retry'
                )
                return False

        if not os.access(pid_file_dir, os.W_OK):
            self.LogError(
                f'The directory "{pid_file_dir}" is not writable. Make it writable and retry'
            )
            return False

        st = StunnelConfigGet()
        st.open_with_remote_path(mount_path, ip_address)
        config_file_found = st.is_found() and st.connect_ip == ip_address

        mount_port = port
        if config_file_found:
            mount_port = st.accept_port

        if not config_file_found:
            if not self.start_stunnel(port, ip_address, mount_path):
                return False
        return self.run_stunnel_mount_command(mount_port, mount_path, ip_address, False)

    # Cleans up unused conf files. Should not throw exception .
    def cleanup_stale_conf(self, dirname=StunnelConfigGet.STUNNEL_DIR_NAME):
        # os.listdir always listed only one file in unit tests!!!
        for entity in os.scandir(dirname):
            filename = entity.name
            if (
                entity.is_file()
                and filename.endswith(StunnelConfigGet.STUNNEL_CONF_EXT)
                and StunnelConfigGet.IBM_SHARE_SIG in filename
            ):
                full_file_name = entity.path
                st = StunnelConfigGet()
                st.parse_with_full_path(full_file_name)
                if st.is_found():
                    mount_path = st.get_full_mount_path()
                    # Do not send in the third arg to is_share_mounted so that accessor share conf is not deleted.
                    mounted = mount_path and self.is_share_mounted(
                        LOOPBACK_ADDRESS, mount_path
                    )
                    # mounted == true and pid_alive == false can happen due to accessor shares.
                    # When NFS mounts two paths to the same share, it can prefer one of the two network paths.
                    # when that happens on sunnel, mount forces itself on one of the two stunnel accept ports.
                    if not mounted:

                        self.LogInfo(
                            f"{full_file_name} has no mounts associated with it. Killing stunnel process"
                        )
                        self.kill_stunnel_pid(st)
                        try:
                            self.RemoveFile(full_file_name)
                            self.LogInfo(f"{full_file_name} removed")
                        except Exception as e:
                            self.LogError(f"Removefile returned an exception:{e}")

    def pid_from_file(self, pid_file):
        try:
            with open(pid_file, "r") as file:
                pid = int(file.readline().strip())
                if pid > 0:
                    return pid
        except Exception as e:
            self.LogWarn(
                f"Could not get PID from file {pid_file} due to exception {e} . Continuing."
            )
            pass
        return None

    def kill_stunnel_pid(self, st):
        if not st.is_found():
            return False
        else:
            pid_file = st.get_pid_file()
            if pid_file:
                pid = self.pid_from_file(pid_file)
                try:
                    if pid:  # 0 targets process group. Must avoid.
                        os.kill(pid, signal.SIGKILL)
                except Exception as e:
                    self.LogWarn(
                        f"Method kill_stunnel_pid failed with exception {e}. Continuing."
                    )
                    return False
                finally:
                    try:
                        os.remove(pid_file)
                    except:
                        pass
            return True

    # Create conf file and start stunnel.
    def start_stunnel(self, port, ip_address, mount_path):
        self.LogDebug(f"Starting stunnel for mounting {mount_path}")
        st = stunnel_config_create.StunnelConfigCreate(
            accept_ip=LOOPBACK_ADDRESS,
            accept_port=port,
            connect_ip=ip_address,
            connect_port=MOUNT_PORT,
            remote_path=mount_path,
        )
        st.write_file()
        if not st.is_valid():
            self.LogError(st.get_error())
            return False
        else:
            conf_file = st.get_config_file()
            self.LogDebug(f"Stunnel conf file created {conf_file}")
            try:
                current_path = os.environ.get("PATH", " ")
                # Dirs where stunnel command is found on various OS versions
                additional_path = "/usr/bin:/usr/sbin"
                new_path = f"{additional_path}:{current_path}"
                env_copy = os.environ.copy()
                env_copy["PATH"] = new_path
                self.LogDebug(f"Attempting to start stunnel using {conf_file}")
                result = subprocess.run(
                    [STUNNEL_COMMAND, conf_file],
                    check=False,
                    env=env_copy,
                    stderr=subprocess.PIPE,
                )
                if result.returncode != 0:
                    self.LogError(
                        f'''Stunnel start returned error "{result.stderr.decode('utf-8')}"'''
                    )
                    return False
            except subprocess.CalledProcessError as cpe:
                self.LogError(f"Stunnel start returned exception {cpe}")
                return False
        return True

    def run_stunnel_mount_command(
        self, port, mount_path, ip_address, cleanup_config=False
    ):
        ah = ArgsHandler()
        ah.parse()

        cmd = ah.get_stunnel_mount_cmd_line(
            port, str(LOOPBACK_ADDRESS) + ":" + mount_path
        )
        self.LogDebug(f"Attempting mount of {mount_path} on local host")
        out = self.RunCmd(cmd, "Mount using stunnel ", ret_out=True)
        if not out or out.is_error():
            # Removes conf file as well.
            st = StunnelConfigGet()
            st.open_with_remote_path(mount_path, ip_address)
            if st.is_found() and cleanup_config:
                self.kill_stunnel_pid(st)
                os.remove(st.get_config_file())

            if (
                out
                and isinstance(out.stderr, str)
                and "timed out" in out.stderr.lower()
            ):
                self.LogError(
                    f"Mount command timed out. Kill stunnel process and retry mount",
                    code=SysApp.ERR_MOUNT + out.returncode,
                )
            # we pass back the mount command exit code
            exit_code = SysApp.ERR_MOUNT + out.returncode if out else SysApp.ERR_MOUNT
            self.LogError("mount command on localhost returned error", code=exit_code)
            return False
        return True

    def mount(self, args):
        if not self.is_share_mounted(args.ip_address, args.mount_path):
            if not args.is_secure or args.is_tls:
                self.LogUser("Non-IPsec mount requested.")
                ipsec = self.get_ipsec_mgr()
                if ipsec:
                    ipsec.remove_config(args.ip_address)
                    ipsec.reload_config()
            else:
                if self.is_ppc():
                    self.LogError("Ipsec mounts are not suported on PPC")
                    self.LogError("Use the -o stunnel option. Remove secure=true")
                    return False

                cert = RenewCerts()
                if not cert.root_cert_installed():
                    self.LogError("Root Certificate must be installed.")
                    return False

                if not cert.load_certificate():
                    if not cert.get_initial_certs():
                        return False

                if cert.is_certificate_eligible_for_renewal():
                    if not cert.renew_cert_now():
                        if cert.is_certificate_expired():
                            return False
                        self.LogWarn("Cert has not expired, so will continue.")

                ipsec = cert.get_ipsec_mgr()
                if not ipsec.is_running():
                    return False
                if not ipsec.create_config(args.ip_address):
                    return False
                ipsec.cleanup_unused_configs(self.mounts)
                ipsec.is_reload = True
                if not ipsec.reload_config():
                    return False

        self.unlock()
        out = self.RunCmd(args.get_mount_cmd_line(), "MountCmd", ret_out=True)
        # When the -v option is used, stdout and stderr may contain additional output.
        if not out or out.is_error():
            if (
                out
                and isinstance(out.stderr, str)
                and "timed out" in out.stderr.lower()
            ):
                self.LogError(
                    "Mount command timed out. Try to restart StrongSwan service.",
                    code=SysApp.ERR_MOUNT + out.returncode,
                )
            # we pass back the mount command exit code
            exit_code = SysApp.ERR_MOUNT + out.returncode if out else SysApp.ERR_MOUNT
            return self.LogError("Share mount failed.", code=exit_code)

        self.ca_certs_alert()
        self.LogUser("Share successfully mounted:" + out.stdout)
        return True

    # Check int and root CA certs validity.
    def ca_certs_alert(self):
        cert = RenewCerts()
        if not cert.load_int_ca_certificate():
            return False
        cert.check_ca_certs_validity("Int")
        if not cert.load_root_ca_certificate():
            return False
        cert.check_ca_certs_validity("Root")
        return True

    def run(self):
        if not SysApp.is_root():
            return self.LogError(
                "Run the mount as super user.", code=SysApp.ERR_NOT_SUPER_USER
            )

        ret = False
        try:
            ArgsHandler.set_logging_level()
            stunnel_requested = ArgsHandler.is_request_stunnel()

            if stunnel_requested:
                self.lock()
                ret = self.set_installed_stunnel()
                self.unlock()
                if not ret:
                    return False
            else:
                self.set_installed_ipsec()

            rt = ArgsHandler.get_app_run_type()
            if rt.is_setup():
                ret = self.app_setup()
            elif rt.is_teardown():
                ret = self.app_teardown()
            elif rt.is_renew():
                ret = self.renew_certs()
                self.ca_certs_alert()
            elif rt.is_mount():
                args = ArgsHandler.get_mount_args()
                if args:
                    self.lock()
                    if stunnel_requested:
                        self.cleanup_stale_conf()
                        ret = self.process_stunnel_mount(args)
                        if not ret:
                            self.LogError("Stunnel mount failed")
                        else:
                            self.LogDebug("Stunnel mount was successful")
                    else:
                        ret = self.mount(args)
                    self.unlock()
        except Exception as ex:
            self.LogException("AppRun", ex)
            traceback.print_exc()
            self.unlock()
        return ret


# Entry method for mount helper processing.
def main():
    ret = MountIbmshare().run()
    SysApp.exit(ret)


if __name__ == "__main__":
    main()
