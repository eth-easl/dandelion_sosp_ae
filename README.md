# Setup
Originally we ran our experiments on internal servers, but have ported them to cloudlab, so evaluators can rerun them more easily.
Consequently you will need a [cloudlab](https://www.cloudlab.us/) account to get access to the resources.

Our setup requires that the ssh key for GitHub and Cloudlab are the same.
You only need a readonly key for public GitHub repositories: to add one, you can add it as a deploy key to a temporary repository, it will also allow pulling from public GitHub repositories. Detailed instructions are available [here](key.md).
Make sure your ssh agent is running and has access to this ssh key (as described in the following step).

We recommend Ubuntu 22.04: its apt repos still have python3.10 available, which is required by one of the dependencies.
If you are not on Ubuntu 22.04, you can use a [container](container.md): if you do so, follow the instructions there, then continue from "Setting up for experiments".

Start it:
```
eval "$(ssh-agent -s)"
```
and add your key:
```
ssh-add <your github and cloudlab private key>
```

Then clone the [experiment repository](https://github.com/eth-easl/dandelion_sosp_ae).
`--recurse-submodules` clones git submodules recursively; this is needed because we depend on the [doe-suite](https://nicolas-kuechler.github.io/doe-suite) for running our experiments.
```
git clone --recurse-submodules https://github.com/eth-easl/dandelion_sosp_ae
cd dandelion_sosp_ae
```

The `doe-suite` relies on a few environment variables to be set before any experiment can be started.
For this run the following commands in the repository's root directory:
```
export DOES_PROJECT_DIR=$(pwd)
export DOES_PROJECT_ID_SUFFIX="eval"
export DOES_SSH_KEY_NAME=<path to your private key>
```

To run the `doe-suite` you need python3.9 or python3.10, poetry, cookiecutter, ssh client and make installed.

We recommend getting python3, make and pip through the package manager and then installing poetry and cookiecutter via:
```
python3 -m pip install --user pipx
~/.local/bin/pipx ensurepath
pipx install poetry
pipx install cookiecutter
```

This guide includes all the necessary steps, but should you need to refer to additional information, documentation and setup instructions for the doe-suite, you can find them at [https://nicolas-kuechler.github.io/doe-suite/installation.html](https://nicolas-kuechler.github.io/doe-suite/installation.html).

## Notes:

The original measurements were taken on machines with the following spec:

Ubuntu 22.04.5 LTS with the 5.15.0-136-generic Kernel
CPU: Intel(R) Xeon(R) CPU E5-2630 v3 @ 2.40GHz, Hyperthreading disabled
NIC: Mellanox ConnectX-3 (MT27500)

# Setting up for experiments

On cloudlab, create an experiment with the `multi_node_profile`, `UBUNTU22-64-STD` image and 2 hardware nodes of type `d430` available in `Emulab`.

In `doe-suite-config/inventory/cloudlab.yml` you need to replace the two placeholders with the URIs of the servers:
you can find these in the cloudlab experiment UI, by selecting "List View" and copying the two URIs after the `@` from the ssh commands;
for example if you see `ssh user@pc778.emulab.net` and `ssh user@pc770.emulab.net` you will need to replace the two `<server url here>` placeholders with
`pc778.emulab.net` and `pc770.emulab.net` respectively.
Make sure to use the URI of node 0 as the loader and the URI of node 1 as the worker, so that the IPs they use to address each other are correct.
(If you are in the container you can use `vim` or `nano`, or you can install a different editor with `apt`.)

Additionally in the `doe-suite/ansible.cfg` add a additional line at the bottom (under `ssh_connection`):
(this step has already been performed if you used the container set-up)
```
retries = 10
```

Finally you need to add an ssh config: add the following to `~/.ssh/config` (create the file if necessary):
(note: replace `<cloudlab username>` with your cloudlab username; if you are using the container, this ssh
config goes inside the container, in `/root/.ssh/config`)
```
Host *.emulab.net
  ForwardAgent yes
  User <cloudlab username>
```

# Running experiments for figures 6 & 8

To rerun the experiments for figure 6 in the paper, run the following command in the `doe-suite` folder:
```
make run suite=load_latency_matmul id=new cloud=cloudlab
```
Note: this experiment takes a long time to run (>4h).
Also the very first time any experiment is run on the servers, the scripts automatically set up everything (installing libraraies, builing binaries etc.).
During the setup process 2 failures are expected, the first one that cargo is missing and the second one is about setting up some networking configurations.
Neither of these should stop the process, as the next commands should fix the issues and it should continue running.

The experiment will arrive at a block started by: 

```
# experiment-job: output progress information of experiments ***
```
This is indicating the experiment is running.
Once it is finished a block started by: 

```
# STATS ***
```

For the experiment in figure 8 run the command:
```
make run suite=mixed_workload_sosp id=new cloud=cloudlab
```

The progress bars should look the same as for the experiment above, but it does finish much faster.

## Creating the plots

Once all the data is collected, there should be a folder called `doe-suite-results`.
In that folder the results will be in folders will be named `<experiment name>_<ID>`.
The IDs need to be filled in `doe-suite-config/super_etl/SOSP_plots.yml`.
Replace the `<ID>` placeholders under `$SUITE_ID$` with the IDs of the results folders.
Once that is done, execute the following command in the `doe-suite` folder:

```
make etl-super config=SOSP_plots
```

To only produce one of the plots, you can comment out the parts relating to the other plot.
(This includes the line with suite id as well as the block containing the experiemnts, extractors, transformers and loaders)
