#! /bin/bash

set -ex

cd /root

apt update
apt install -y \
  python3.10 \
  ssh \
  ssh-agent \
  build-essential \
  git \
  python3-pip \
  python3-venv

python3 -m pip install --user pipx
~/.local/bin/pipx ensurepath
pipx install poetry
pipx install cookiecutter

cd dandelion_sosp_ae
export DOES_PROJECT_DIR=$(pwd)
export DOES_PROJECT_ID_SUFFIX="eval"
export DOES_SSH_KEY_NAME=/root/keys/<path to private key>
echo >> doe-suite/ansible.cfg
echo "retries = 10" >> doe-suite/ansible.cfg
