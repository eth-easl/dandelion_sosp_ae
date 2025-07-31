To follow these steps, you need a container runtime like docker.

Start a container and bind-mount the directory with you GitHub (deploy) key and CloudLab key (see the note in [README.md](README.md) on how to set up a key):

```
docker run -it --rm --mount type=bind,src=<path to key directory on host>,dst=/root/keys,ro ubuntu:22.04 bash
```

Then in the container, run:

```
apt update
apt install -y git
eval "$(ssh-agent -s)"
ssh-add /root/keys/<path to private key>
git clone --recurse-submodules https://github.com/eth-easl/dandelion_sosp_ae
cd dandelion_sosp_ae
bash run-in-container.sh
```

then

```
export DOES_PROJECT_DIR=$(pwd)
export DOES_PROJECT_ID_SUFFIX="eval"
export DOES_SSH_KEY_NAME=/root/keys/<path to private key>
```
