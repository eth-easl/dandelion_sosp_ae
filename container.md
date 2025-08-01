To follow these steps, you need a container runtime like docker.

Start a container and bind-mount (i) the directory with you GitHub (deploy) key and CloudLab key (see the note in [README.md](README.md) on how to set up a key) and (ii) bind-mount a new directory to extract the plots:

(note: replace `<path to key directory on host>` to the directory created during [key set-up](key.md))
(note: replace `<path to plot directory on host>` to the new directory created to collect the plots)

```
docker run -it --rm --mount type=bind,src=<path to key directory on host>,dst=/root/keys,ro --mount type=bind,src=<path to plot directory on host>,dst=/root/plots ubuntu:22.04 bash
```

Once the experiments are complete inside the container, copy them to `/root/plots` so you have access to them at `<pat to plot directory on host>` on the host.

Then in the container, run (note: replace `<path to private key>` with the name of the private key):

```
cd /root
apt update
apt install -y git
eval "$(ssh-agent -s)"
ssh-add /root/keys/<path to private key>
git clone --recurse-submodules https://github.com/eth-easl/dandelion_sosp_ae
# confirm you trust the GitHub host by typing `yes`
cd dandelion_sosp_ae
bash run-in-container.sh
```

then, check you are in the repository's root (`dandelion_sosp_ae`) and export the necessary environment variables (note: replace `<path to private key>` with the name of the private key):

```
source ~/.bashrc
export DOES_PROJECT_DIR=$(pwd)
export DOES_PROJECT_ID_SUFFIX="eval"
export DOES_SSH_KEY_NAME=/root/keys/<path to private key>
```

You can now continue by following the steps for "Setting up for experiments" in the [README](README.md).

