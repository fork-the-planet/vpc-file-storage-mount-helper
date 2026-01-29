#!/usr/bin/env python3
#
# Copyright (c) IBM Corp. 2023. All Rights Reserved.
# Project name: VPC File Storage Mount Helper
# This project is licensed under the MIT License, see LICENSE file in the root directory.


import copy
import glob
import os
import re
import sys
import socket
import subprocess
import shutil
import tempfile
import time
import logging
import logging.handlers
from datetime import datetime, timezone, timedelta


def sleep_msg(secs, msg):
    print("Wait (" + str(secs) + " secs): " + msg)
    time.sleep(secs)


def decode(val):
    _val = val.decode(encoding="UTF-8", errors="replace") if val else ""
    return _val.strip()


def clone_obj(obj):
    return copy.deepcopy(obj)


def make_dirs(fpath, is_file=False):
    path = fpath
    if is_file:
        path, _ = os.path.split(path)
    if not os.path.exists(path):
        os.makedirs(path)
        MountHelperLogger().LogDebug("Folder created:" + path)
        return path
    return None


def to_utc(dt):
    return datetime(
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, tzinfo=timezone.utc
    )


def utc_format(dt, show_tz=True):
    if not dt:
        dt = get_utc_now()
    fmt = "%Y-%m-%d %H:%M:%S"
    if show_tz:
        fmt += " UTC"
    return dt.strftime(fmt)


def get_utc_now(seconds=None, minutes=None):
    return get_utc_date(datetime.now(timezone.utc), seconds=seconds, minutes=minutes)


def get_utc_date(dt, seconds=None, minutes=None, days=None):
    assert dt is not None
    if seconds:
        dt += timedelta(seconds=seconds)
    if minutes:
        dt += timedelta(minutes=minutes)
    if days:
        dt += timedelta(days=days)
    return to_utc(dt)


def trim(val):
    if val:
        return val.strip()
    return ""


def is_empty(val):
    return len(trim(val)) == 0


def to_int(val):
    val = trim(val)
    if val.isdigit():
        return int(val)
    return 0


def get_files_in_folder(src, filter="*"):
    src = make_filename(src, filter)
    nfiles = []
    for file in glob.glob(src):
        if os.path.isfile(file):
            nfiles.append(file)
    return nfiles


def make_filename(adir, name):
    if not adir.endswith("/"):
        adir += "/"
    return os.path.join(adir, name)


def get_filename(name):
    _, name = os.path.split(name)
    return name


def get_val_from_text(txt, what, all, comments=None):
    txt = txt.strip()
    for line in txt.split("\n"):
        if comments and line.lstrip().startswith(comments):
            continue
        pos = line.lower().find(what.lower())
        if pos >= 0:
            pos += len(what)
            txt = line[pos:]
            return trim(txt) if all else txt.split()[0]
    return None


class TempFile(object):
    def __init__(self, data=None, delete=True):
        self.tf = tempfile.NamedTemporaryFile(delete=delete, dir=LocalInstall.path())
        self.filename = self.tf.name
        self.data = data

    def __enter__(self):
        if self.data:
            with open(self.filename, "w") as fd:
                fd.write(self.data)
        return self

    def read(self):
        with open(self.filename, "r") as fd:
            return fd.read()

    def __exit__(self, exception_type, exception_value, traceback):
        pass


class LocalInstall:
    ipsec_mgr_obj = None

    @staticmethod
    def set_ipsec_mgr(obj):
        LocalInstall.ipsec_mgr_obj = obj

    @staticmethod
    def get_ipsec_mgr():
        return LocalInstall.ipsec_mgr_obj

    @staticmethod
    def path():
        return "/opt/ibm/mount-ibmshare"

    @staticmethod
    def exists():
        return os.path.exists(LocalInstall.path())

    @staticmethod
    def teardown():
        shutil.rmtree(LocalInstall.path(), ignore_errors=True)

    @staticmethod
    def setup():
        make_dirs(LocalInstall.cert_path())
        return True

    @staticmethod
    def cert_path():
        return LocalInstall.make_filename("certs")

    @staticmethod
    def make_filename(name):
        return LocalInstall.path() + "/" + name


class SysApp:
    ERR_METADATA_UNAVAILABLE = 1  # check to see if metadata port is open
    ERR_METADATA_TOKEN = 2  # call to metadata service get token
    ERR_METADATA_CERT_RENEW = 3  # call to metadata service fails
    ERR_IPSEC_CFG = 4  # ipsec/swanctl call failure
    ERR_APP_INSTALL = 5  # install/setup fails
    ERR_APP_GENERIC = 6  # generic error
    ERR_NOT_SUPER_USER = 7  # user must be super user
    ERR_PYTHON_EXCEPTION = 50  # a python exception
    ERR_MOUNT = 100  # call to mount nfs4 share fails - mount exit value added
    last_error_code = None

    @staticmethod
    def set_code(code):
        SysApp.last_error_code = code
        return False

    @staticmethod
    def is_none():
        return SysApp.last_error_code == None

    @staticmethod
    def is_code(code):
        return SysApp.last_error_code == code

    @staticmethod
    def exit(ok):
        if ok:
            sys.exit(0)
        else:
            code = SysApp.last_error_code
            sys.exit(code if code else SysApp.ERR_APP_GENERIC)

    @staticmethod
    def argv(pos=None):
        if pos:
            if len(sys.argv) < (pos + 1):
                return None
            return sys.argv[pos]
        return sys.argv

    @staticmethod
    def has_arg(arg):
        args = str(SysApp.argv())
        return arg in args

    @staticmethod
    def is_root():
        return os.geteuid() == 0


class MountHelperLogger:
    LOG_FILE = LocalInstall.make_filename("mount-ibmshare.log")
    MAX_SIZE = 1024 * 64
    MAX_FILES = 2
    debug_enabled = False
    use_log_file = False
    log_store = None
    log_file = None
    log_prefix = None

    def init_log_file(self):
        if not LocalInstall.exists():
            return None
        handler = logging.handlers.RotatingFileHandler(
            self.LOG_FILE, maxBytes=self.MAX_SIZE, backupCount=self.MAX_FILES
        )
        log_file = logging.getLogger()
        log_file.setLevel(logging.INFO)
        log_file.addHandler(handler)
        return log_file

    def EnableLogStore(self):
        MountHelperLogger.log_store = "*\n"

    def HasLogMessage(self, msg):
        assert MountHelperLogger.log_store
        return MountHelperLogger.log_store.find(msg) >= 0

    def SetLogToFileEnabled(self):
        MountHelperLogger.use_log_file = True

    def SetDebugEnabled(self):
        MountHelperLogger.debug_enabled = True

    def IsDebugEnabled(self):
        return MountHelperLogger.debug_enabled

    def log_to_file(self, level, msg):
        if not MountHelperLogger.use_log_file:
            return
        if level not in [logging.ERROR, logging.INFO, logging.WARN]:
            return
        if not MountHelperLogger.log_file:
            MountHelperLogger.log_file = self.init_log_file()

        if MountHelperLogger.log_file:
            fmt_msg = "%s %s %s" % (self.log_prefix, utc_format(None, False), msg)
            self.log_file.log(level, fmt_msg)

    def _log(self, level, msg):
        if level == logging.NOTSET:
            print(msg)
        else:
            _level = logging.getLevelName(level).capitalize()
            fmt_msg = "%-5s - %s" % (_level, msg)
            print(fmt_msg)

        if MountHelperLogger.log_store:
            MountHelperLogger.log_store += msg + "\n"

        self.log_to_file(level, msg)

    def LogUser(self, msg):
        self._log(logging.NOTSET, msg)

    def LogDebug(self, msg):
        if self.IsDebugEnabled():
            self._log(logging.DEBUG, msg)

    def LogInfo(self, msg):
        self._log(logging.INFO, msg)

    def LogError(self, msg, code=None):
        self._log(logging.ERROR, msg)
        if code:
            SysApp.set_code(code)
        return False

    def LogWarn(self, msg):
        self._log(logging.WARN, msg)

    def LogException(self, action, ex, extra=None):
        err = str(ex)
        if extra:
            msg = "Exception: (%s) %s - %s" % (err, action, extra)
        else:
            msg = "Exception: (%s) %s" % (err, action)

        self.LogError(msg, code=SysApp.ERR_PYTHON_EXCEPTION)


class SubProcess(MountHelperLogger):
    def __init__(self, cmd):
        if isinstance(cmd, str):
            cmd = cmd.split()
        assert isinstance(cmd, list)
        self.cmd = cmd
        self.set_output(-1, None, None)

    def set_output(self, ret, stdout, stderr):
        self.returncode = ret
        self.stderr = decode(stderr)
        self.stdout = decode(stdout)
        return self

    def show_output(self):
        msg = "Cmd: %s\nRetCode: %d\nStdError: %s\nStdOut: %s\n" % (
            self.cmd,
            self.returncode,
            self.stderr,
            self.stdout,
        )
        print(msg)

    def get_error(self):
        if self.is_error():
            msg = "RunCmd Failed: ExitCode(%d) StdError(%s) Cmd(%s)" % (
                self.returncode,
                self.stderr,
                self.cmd_to_str(),
            )
            return msg.replace("StdError() ", "")
        return None

    def is_error(self):
        return self.returncode != 0

    def cmd_to_str(self):
        return " ".join(self.cmd)

    def get_stdout_val(self, what, all=False):
        return get_val_from_text(self.stdout, what, all)

    def get_stderr_val(self, what, all=False):
        return get_val_from_text(self.stderr, what, all)

    def stream(self):
        try:
            self.LogDebug("Stream: " + self.cmd_to_str())
            with subprocess.Popen(
                # self.cmd_to_str(),
                self.cmd,
                # shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ) as proc:
                self.LogDebug("Waiting for ouput......")

                for line in iter(proc.stdout.readline, b""):
                    if line:
                        txt = line.decode().strip("\r\n") + "\n"
                        sys.stdout.write(txt)
                proc.wait()
                return self.set_output(proc.returncode, "", "")
        except Exception as ex:
            self.LogException(ex, "Stream")
        return None

    def run(self):
        if sys.version_info[:2] < (3, 5):
            proc = subprocess.Popen(
                self.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            (stdout, stderr) = proc.communicate()
            return self.set_output(proc.returncode, stdout, stderr)

        out = subprocess.run(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return self.set_output(out.returncode, out.stdout, out.stderr)


class MountHelperBase(MountHelperLogger):

    def __init__(self):
        pass

    def wait(self, secs, msg):
        self.LogInfo("Wait (" + str(secs) + " secs): " + msg)
        time.sleep(secs)

    def FileExists(self, fpath, log=False):
        ret = os.path.exists(fpath)
        if not ret and log:
            self.LogDebug("FileNotExist:" + fpath)
        return ret

    def MakeDirForFile(self, dst):
        make_dirs(dst, is_file=True)

    def CopyFile(self, src, dst, mkdir=False):
        if self.FileExists(src):
            try:
                if mkdir:
                    self.MakeDirForFile(dst)
                shutil.copyfile(src, dst)
                return True
            except Exception as ex:
                self.LogException("CopyFile:", ex)

        return False

    def CleanupDir(self, dpath, filter="*", remove_empty=True):
        if os.path.exists(dpath):
            files = get_files_in_folder(dpath, filter)
            if len(files) > 0:
                self.LogDebug("Cleanup folder:" + dpath)
                for file in files:
                    os.remove(file)
            if remove_empty and not os.listdir(dpath):
                os.rmdir(dpath)

    def RemoveFile(self, fpath):
        if self.FileExists(fpath):
            os.remove(fpath)

    def ReadFile(self, fpath, log=True):
        if not self.FileExists(fpath, log=True):
            return None

        if log:
            self.LogDebug("ReadFile:" + fpath)
        try:
            with open(fpath, "r") as fp:
                return fp.read()
        except Exception as ex:
            self.LogException("ReadFile:", ex, fpath)
        return None

    def WriteFile(self, fpath, data, mkdir=False, chmod=None):
        self.LogDebug("WriteFile:" + fpath)
        try:
            if mkdir:
                self.MakeDirForFile(fpath)

            with open(fpath, "w") as fp:
                fp.write(data)
            if chmod:
                os.chmod(fpath, chmod)

        except Exception as ex:
            self.LogException("WriteFile:", ex, fpath)
            return False

        return True

    def FileNoChange(self, fpath, data):
        if self.FileExists(fpath):
            old_data = self.ReadFile(fpath, log=False)
            return old_data == data
        return False

    def RunSilent(self, cmd):
        out = SubProcess(cmd).run()
        return out

    def RunCmd(self, cmd, descr, ret_out=False):
        proc = SubProcess(cmd)

        try:
            msg = proc.cmd_to_str()
            if not is_empty(descr):
                msg = "%s (%s)" % (descr, msg)
            self.LogDebug("RunCmd: " + msg)
            output = proc.run()
            if output.is_error():
                self.LogError(output.get_error())
                if ret_out:
                    return output
            else:
                # self.LogDebug("Successfully executed:"+descr)
                return output

        except KeyboardInterrupt:
            self.LogError("Keyboard Interrupt caught")
        except Exception as ex:
            self.LogException("RunCmd:", ex, descr)
            
        return None

class SystemCtl(MountHelperBase):
    EXE_PATH = "/bin/systemctl"
    OS_PATH = "/etc/os-release"
    SYSTEMD_VERSION_SUPPORTS_UTC = 228

    def __init__(self, name):
        self.name = name
        self.SetDebugEnabled()

    def restart(self):
        self.action("enable")
        return self.action("restart")

    def enable(self):
        # --now does not work on older systems
        self.action("enable")
        return self.start()

    def disable(self):
        # --now does not work on older systems
        self.stop()
        return self.action("disable")

    def stop(self):
        return self.action("stop")

    def start(self):
        return self.action("start")

    def status(self):
        return self.action("status")

    def show_status(self):
        out = self.status()
        if out:
            out.show_output()

    def is_active(self):
        out = self.action("is-active", silent=True)
        return out.stdout == "active" if out else False

    def systemd_supports_utc(self):
        return self.systemd_version() >= self.SYSTEMD_VERSION_SUPPORTS_UTC

    def systemd_version(self):
        version = get_app_version(self.EXE_PATH, "systemd")
        return to_int(version) if version else 0

    def get_os_version(self):
        if self.FileExists(self.OS_PATH):
            content = self.ReadFile(self.OS_PATH, log=False)
            match = re.search(r'^VERSION_ID="([^"]+)"', content, re.MULTILINE)
            return match.group(1)

    def get_os_name(self):
        if self.FileExists(self.OS_PATH):
            content = self.ReadFile(self.OS_PATH, log=False)
            match = re.search(r'^NAME="([^"]*)"', content, re.MULTILINE)
            return match.group(1)

    def is_kernel_version_6_or_higher(self):
        result = subprocess.run(
            ["uname", "-r"], capture_output=True, text=True, check=True
        )
        version = result.stdout.strip()
        major_version = int(version.split(".")[0])
        return major_version >= 6

    def check_tls_enabled_os(self, os_list):
        os_name = self.get_os_name()
        os_version = self.get_os_version()
        enabled = f"{os_name} {os_version}"

        return enabled in os_list

    def tls_package_installed(self, package_name):
        os_name = self.get_os_name()
        if os_name == "Ubuntu":
            # For Ubuntu and Debian-based systems
            command = ["dpkg", "-l"]
            output = subprocess.check_output(command).decode()
            return package_name in output
        elif os_name in ["Red Hat Enterprise Linux", "Rocky Linux"]:
            # For RHEL, CentOS, and Rocky Linux
            command = ["rpm", "-qa"]
            output = subprocess.check_output(command).decode().strip()
            return package_name in output
        return "not installed" not in output

    def action(self, action, arg=None, silent=False):
        cmd = [self.EXE_PATH, action]
        if arg:
            cmd.append(arg)
        cmd.append(self.name)
        if silent:
            return self.RunSilent(cmd)
        return self.RunCmd(cmd, "")


class NfsMount(MountHelperBase):
    MOUNT_OUTPUT_FIELDS_SIZE = 5
    MOUNT_TYPE_NFS = "nfs"
    MOUNT_TYPE_NFS4 = "nfs4"
    NFS_PATH_INDEX = 0
    MOUNTED_AT = 2
    HOST_INDEX = 0
    PATH_INDEX = 1
    SOURCE_ARGS_LENGTH = 2
    MOUNT_LIST_NFS_CMD = ["mount", "-t nfs,nfs4"]

    def __init__(self, ip=None, mount_path=None, mounted_at=None, mount_port=None):
        self.ip = ip
        self.mount_path = mount_path
        self.mounted_at = mounted_at
        self.mount_port = mount_port

    def load_nfs_mounts(self):
        result = self.RunCmd(NfsMount.MOUNT_LIST_NFS_CMD, "ListNfsMounts")
        if not result:
            return []

        lines = result.stdout.splitlines()
        mounts = []
        # Parse mount command output line by line and search for ip address and mount path.
        for line in lines:
            mount = self.get_nfs_mount(line)
            if mount:
                mounts.append(mount)

        self.LogDebug("Existing nfs/nfs4 mounts found:" + str(len(mounts)))
        return mounts

    def get_nfs_mount(self, line):
        mount_fields = line.split(" ")
        if len(mount_fields) >= NfsMount.MOUNT_OUTPUT_FIELDS_SIZE:
            if (
                NfsMount.MOUNT_TYPE_NFS in mount_fields
                or NfsMount.MOUNT_TYPE_NFS4 in mount_fields
            ):
                ip, mount_path = NfsMount.extract_source(
                    mount_fields[NfsMount.NFS_PATH_INDEX]
                )
                port = self.get_mount_port(line)
                if ip and mount_path:
                    return NfsMount(
                        ip, mount_path, mount_fields[NfsMount.MOUNTED_AT], port
                    )
        return None

    def get_mount_port(self, line):
        match = re.search(r"port=(\d+)", line)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def extract_source(src):
        if len(src) > 0:
            host_path = src.split(":")
            if len(host_path) >= NfsMount.SOURCE_ARGS_LENGTH:
                mount_path = host_path[NfsMount.PATH_INDEX]
                try:
                    ip = socket.gethostbyname(host_path[NfsMount.HOST_INDEX])
                    return ip, mount_path
                except:
                    pass
        return None, None


def extract_version(ver):
    str = ""
    for a in trim(ver):
        if a.isdigit() or a == ".":
            str += a
        elif len(str) > 0:
            break
    str = str.strip(".")
    return None if is_empty(str) else str


def get_app_version(app, tag, vcmd="--version"):
    if os.path.exists(app):
        cmd = SubProcess([app, vcmd])
        if cmd.run():
            if not cmd.is_error():
                return extract_version(cmd.get_stdout_val(tag))
    return None


def version_compare(version1, version2):
    assert not is_empty(version1)
    assert not is_empty(version2)

    def cmp(a, b):
        return (a > b) - (a < b)

    def fix(v):
        return [int(x) for x in re.sub(r"(\.0+)*$", "", v).split(".")]

    return cmp(fix(version1), fix(version2))


class ConfigEditor(MountHelperBase):
    def __init__(self, fname):
        self.name = fname
        self.data = None

    def exists(self):
        return self.FileExists(self.name)

    def read(self):
        self.data = self.ReadFile(self.name)
        return not is_empty(self.data)

    def write(self):
        return self.WriteFile(self.name, self.data)

    def comment(self, data):
        self.data = "%s\n# %s" % (self.data, data)

    def append(self, data):
        self.data = "%s\n%s" % (self.data, data)

    def add_val(self, name, value):
        if self.get_val(name):
            return False

        self.append("%s = %s" % (name, value))
        return self.write()

    def get_val(self, name, all=True):
        data = self.data.replace(" ", "")
        return get_val_from_text(data, name + "=", all, "#")


class RootCert(object):
    def __init__(self, region, fname):
        self.region = region
        self.fname = fname

    @staticmethod
    def find(files, region):
        for file in files:
            if region == file.region:
                return file
        return None

    @staticmethod
    def sort(files):
        def get_key(o):
            return o.region

        files.sort(key=get_key)


class ShareConfig(ConfigEditor):
    conf_path = "/etc/ibmshare"

    def __init__(self, path, cert_path=".", show_error=True):
        self.name = make_filename(path if path else self.conf_path, "share.conf")
        self.data = ""
        self.cert_path = cert_path
        self.show_error = show_error

    def load_files(self):
        pfx = "type_ibmshare_root_"
        files = get_files_in_folder(self.cert_path, pfx + "*.*")
        if len(files) == 0:
            return self.LogError(
                "Ensure root CA certs are present in: " + self.cert_path
            )

        regions = []
        for file in files:
            start = file.find(pfx)
            start += len(pfx)
            stop = file.rfind(".")
            assert start > 0 and stop > start
            region = file[start:stop]
            region = RootCert(region.lower(), file)
            if not RootCert.find(regions, region):
                regions.append(region)
        return regions

    def create(self):
        self.LogInfo("Generate config file: " + self.name)
        files = self.load_files()
        if not files:
            return False
        RootCert.sort(files)
        self.comment("all - install all certificates")
        self.comment("region list - use any combination")

        for file in files:
            self.comment(file.region)

        self.append("\nregion=\n")
        return self.write()

    def error(self, msg):
        msg = "%s (%s)" % (msg, self.name)
        self.LogError(msg)
        return None

    def get_region(self):
        if self.read():
            return self.get_val("region")
        return None

    def get_certificate_duration(self):
        if self.read():
            return self.get_val("certificate_duration_seconds", False)
        return None

    def get_metadata_retry_count(self):
        if self.read():
            return self.get_val("metadata_retry_count", False)
        return None

    def get_metadata_retry_interval(self):
        if self.read():
            return self.get_val("metadata_retry_interval", False)
        return None

    def load_regions(self):
        regions = self.get_region()
        if regions:
            regions = regions.lower().split(",")
        if not regions or len(regions) == 0:
            return self.error("No regions found in:")

        if (len(regions) > 1) and ("all" in regions):
            return self.error(
                "Only one region entry allowed if using 'all': " + str(regions)
            )
        return regions

    def get_files_for_regions(self, regions):
        if not os.path.exists(self.cert_path):
            return self.LogError("Root certs directory is missing: " + self.cert_path)

        install_cas = []
        files = self.load_files()
        if files:
            for region in regions:
                if region in ["all"]:
                    if len(files) == 0:
                        return self.error("No regions found for selector: " + region)
                    return files
                else:
                    file = RootCert.find(files, region)
                    if not file:
                        return self.error("No root CA cert found for region: " + region)
                    install_cas.append(file)

        return install_cas if len(install_cas) > 0 else None
