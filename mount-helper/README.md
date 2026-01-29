```
Copyright (c) IBM Corp. 2023. All Rights Reserved.
Project name: VPC File Storage Mount Helper
This project is licensed under the MIT License, see LICENSE file in the root directory.
```

# Mount Helper
Mount helper is an open source automation tool that helps to establish secure IPsec and stunnel connection between customer virtual server instance (VSI) and storage server. The mount helper ensures that the communication between the customer VSI and the file share is encrypted in transit.

For more information, see the [IBM Cloud File Share Mount Helper utility](https://cloud.ibm.com/docs/vpc?topic=vpc-file-storage-vpc-eit&interface=ui#fs-mount-helper-utility) topic in the IBM Cloud Docs.

## How to build mount helper packages
Mount helper packages can be built from the source code that is available in public GitHub. Follow steps below to build packages for Debian and RedHat instances.
1. Clone mount helper code from github.com
```
git clone git@github.com:IBM/vpc-file-storage-mount-helper.git
```
2. Go to cloned repo directory
```
cd vpc-file-storage-mount-helper
```
3. Run make command to build mount helper .deb/.rpm packages along with installation/uninstallation scripts.
```
make prod
```
4. You can find mount.ibmshare-latest.tar.gz tar file in current directory

5. Untar to have all required files for installation
```
tar -xvzf mount.ibmshare-latest.tar.gz -C test/
```

## How to contribute code
Mount helper code is open sourced and anybody can contribute to the code. Follow steps below to contribute mount helper code.
1. Fork mount helper code from https://github.com/IBM/vpc-file-storage-mount-helper
2. Clone your forked repo
```
git clone git@github.com:<user_name>/vpc-file-storage-mount-helper.git
```
3. Create a new branch
```
git checkout -b <BR_NAME>
```
4. Make code changes and update/add tests in test directory.
5. Run unit tests.
```
cd test
./run_test.sh
Make sure all the tests are passed.
```
6. Commit code and push.
```
git add <files>
git commit
git push
```
7. Create a pull request.
8. If you want to create a new version for the package please change version in following files
   - Update APP_VERSION in Makefile.
   - Update .github/workflows/release.yml to create a new release in GitHub.
9. Before creating pull request make sure your workflow ran successfully.
   - Go to Actions in GitHub on your forked repo.
   - Check the latest workflow run.
   -  Fix if there are any issues.
10. Finally create pull request.

## How to install
1. You can download the packages directly from GitHub releases.
   The latest packages are available at: https://github.com/IBM/vpc-file-storage-mount-helper/releases
```
curl -LO https://github.com/IBM/vpc-file-storage-mount-helper/releases/download/latest/mount.ibmshare-latest.tar.gz
```
3. Then install use script,
```
For dev and staging users, it is necessary to export STUNNEL_ENV variable before running ./install.sh
export STUNNEL_ENV=dev # For development environment users
export STUNNEL_ENV=staging # For staging environenment users.
There is no need for this export for production users.
./install.sh  ( For zonal share to install just Ipsec)
./install.sh --stunnel ( For regional share to install both ipsec and stunnel)
```
4. Few tips to verify installation
    - Check for file /sbin/mount.ibmshare, if the file is not found then installation must have failed. Check the logs and fix/report.
    - Check strongswan status: systemctl status strongswan. This should be in active(running) state.
    - Check for config file: /etc/ibmshare/share.conf

## How to mount a zonal EIT share using ipsec
Use the following command syntax to mount the share. Replace the mountpath with the information that is specific to your file share.
```
mount -t ibmshare -o secure=true <MOUNT_PATH> <MOUNT_POINT>
```

## How to mount a regional EIT share using stunnel
Use the following command syntax to mount the share. Replace the mountpath with the information that is specific to your file share.
```
mount -t ibmshare -o stunnel <MOUNT_PATH> <MOUNT_POINT>
```

## Supported Platform:
1. RedHat versions 8, 9
2. Ubuntu versions 20, 22, 24
3. CentOS versions 9,10
4. Debian versions 10,11,12
5. Rocky linux 8,9

## How to update packages:
1. Uninstall currently installed package
```
./uninstall.sh
```
2. Download the latest packages from GitHub and install.
3. TODO
   - If we are able to host packages on any web server to be able to install directly, then below commands are enough to update the packages. We have to make sure latest packages are uploaded to the repo server.
```
apt update mount.ibmshare
yum update mount.ibmshare
```

## Dependencies of these Packages:
### Ubuntu:
    Python3
    nfs-common
    strongswan-swanctl, charon-systemd
### RedHat:
    python3
    nfs-utils
    epel-release
    strongswan, strongswan-sqlite

## Release/Package versioning process details
   - The packages are versioned as x.x.x
   - Initial version is: 1.0.0
   - The releases are versioned in the same manner: https://github.com/IBM/vpc-file-storage-mount-helper/releases
   - But in the GitHub you can find a release with version tag “latest”, this always points to the latest version.

## Current available packages which anyone can download and install with version
```
https://github.com/IBM/vpc-file-storage-mount-helper/releases
```

## Version metrics for both packages
The currently installed packages and it's details can be verified using below comamnds.
### Ubuntu
```
apt list | grep mount.ibmshare  ---> This shows the currently installed helper package.
apt show mount.ibmshare-<version>   ---> This shows package details.
```
### RedHat
```
yum list | grep mount.ibmshare
yum info mount-.bmshare
```

## Code coverage and unit test cases
   - Unit test cases are located in “test” directory of the mount helper repo.
