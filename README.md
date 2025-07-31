# Setup
Originally we ran our experiments on internal servers, but have ported them to cloudlab, so evaluators can rerun them more easily.
Consequently you will need a cloudlab account to get access to the resources.

Clone the [experiment repository](https://github.com/eth-easl/dandelion_sosp_ae).
If you clone the base repository, make sure to check out the branch `sosp25`.
Also make sure you clone recursively, as we depend on the doe-suite for running our experiments.

```
git clone --recurse-submodules https://github.com/eth-easl/dandelion_sosp_ae
cd dandelion_sosp_ae
```

The `doe-suite` relies on a few environment variables to be set, that need to be set before any experiment can be started.
For this run the following commands in the repositories root directory:
```
export DOES_PROJECT_DIR=$(pwd)
export DOES_PROJECT_ID_SUFFIX="eval"
export DOES_SSH_KEY_NAME=<path to your ssh key for cloudlab>
```
You should also make sure your ssh agent is running and has access to your ssh keys.
For that you can run:
```
eval "$(ssh-agent -s)"
```
To start it and to add your key:
```
ssh-add ~/.ssh/<your git/cloudlabl key>
```

To run the `doe-suite` you need python3, poetry, cookiecutter, and make installed as well as ssh set up. 
We recommend getting python3, make and pip through the package manager and then installing poetry and cookiecutter via:
```
pipx install poetry
pipx install cookiecutter
```
For additional information on the suite, documentation and setup instructions can be found [here](https://nicolas-kuechler.github.io/doe-suite/installation.html)

# Running experiments for figures 6 & 8

On cloudlab, create an experiment with the `multi_node_profile`, `UBUNTU22-64-STD` image and 2 hardware nodes of type `d430` available in `Emulab`.

In `doe-suite-config/inventory/cloudlab.yml` you need to replace the two placeholders with the URIs of the servers.
Make sure to use the uri of node 0 is the loader and node 1 is the worker, so the IPs they use to address each other are correct.

Additionally in the `doe-suite/ansible.cfg` add a additional line at the bottom (under `ssh_connection`):
```
retries = 10
```

To rerun the experiments for figure 6 in the paper, run the following command in the `does-suite` folder:
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

## Creating the plots

Once all the data is collected, there should be a folder called `doe-suite-results`.
In that folder the results will be in folders will be named `<experiment name>_<ID>`.
The IDs need to be filled in `doe-suite-config/super_etl/SOSP_plots.yml`.
Replace the `<ID>` placeholders under `$SUITE_ID$` with the IDs of the results folders.
Once that is done, execute the following command in the `doe-suite` folder:

```
make etl-super config=SOSP_plots
```