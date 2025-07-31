#! /bin/bash

set -ex

cd /root

apt update
apt install -y \
  python3.10 \
  openssh-client \
  build-essential \
  git \
  python3-pip \
  python3-venv \
  vim-nox \
  nano

python3 -m pip install --user pipx
~/.local/bin/pipx ensurepath
export PATH="$PATH:/root/.local/bin"
pipx install poetry
pipx install cookiecutter

cd dandelion_sosp_ae
echo >> doe-suite/ansible.cfg
echo "retries = 10" >> doe-suite/ansible.cfg
