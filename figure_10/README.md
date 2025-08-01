# Figure 10 experiments

NOTE: The setup scripts assume that SSH keys for accessing any node in the Cloudlab cluster are present on the machine, i.e., that commands such as `ssh user@node` work. 
You can ignore the prompt in `scripts/remote_install.sh` to add your SSH keys to your GitHub account, i.e., just press ENTER. 
All repositories needed for running the following experiments are public.

## Firecracker experiment:
- Locally clone https://github.com/eth-easl/dirigent and checkout to `dandelion_sosp25_firecracker` branch.
- Create a Cloudlab cluster of 4 `d430` nodes with Dirigent profile (https://www.cloudlab.us/p/faas-sched/dirigent).
- On your local machine execute `scripts/remote_install.sh <username>@<node0> <username>@<node1> <username>@<node2> <username>@<node3>`. Replace username and `node[0-3]`.
- On your local machine execute `scripts/remote_start_cluster.sh <username>@<node0> <username>@<node1> <username>@<node2> <username>@<node3>`. Replace username and `node[0-3]`.
- On `node0` checkout `~/invitro` repo to branch `dandelion_sosp25_firecracker` and copy `azure_100` to `node0` to location `~/invitro/data/traces/azure_100`, you can use the following command from your local machine in this folder:
`scp -r azure_100 <username>@<node0>:invitro/data/traces/`
- Back on node 0 in the invitro folder, you need to warm up the cluster first:
	Run for a few times and make sure you get positive responses from the cluster - `go run cmd/loader.go --config cmd/config_dirigent_rps.json` 
- Run the main experiment in `tmux` by executing `go run cmd/loader.go --config cmd/config_dirigent_trace.json`
- Create folder local folder `firecracker_100_100000` and transfer data from the cluster to it:
	- `node0` -> `~/invitro/data/out/experiment_duration_30.csv`
	- `node1` -> `/data/cold_start_trace.csv`
	- `node2` -> `/data/proxy_trace.csv`

## Dandelion experiment:
- Locally clone `https://github.com/eth-easl/dirigent` and checkout to `dandelion_sosp25_dandelion_new` branch.
- Create a Cloudlab cluster of 4 `d430` nodes with Dirigent profile (https://www.cloudlab.us/p/faas-sched/dirigent).
- On your local machine clone `https://github.com/eth-easl/dandelion` and checkout to `archive/sosp2025` and edit the path in the dirigent folder in `scripts/setup.cfg` where `export DANDELION_DIR=<your path here>`
- On your local machine execute `scripts/remote_install.sh <username>@<node0> <username>@<node1> <username>@<node2> <username>@<node3>`. Replace username and `node[0-3]`.
- On your local machine execute `scripts/remote_start_cluster.sh <username>@<node0> <username>@<node1> <username>@<node2> <username>@<node3>`. Replace username and `node[0-3]`.
- On `node0` checkout `~/invitro` repo to branch `dandelion_sosp25_firecracker` and copy `azure_100` to `node0` to location `~/invitro/data/traces/azure_100`. You can use the following command in from this folder: `scp -r azure_100 <username>@<node0>:invitro/data/traces/`
- Back on node0 in the `~/invitro` folder, you need to warm up the cluster first:
	Run for a few times and make sure you get positive responses from the cluster - `go run cmd/loader.go --config cmd/config_dirigent_dandelion_rps.json `
- Run the main experiment in `tmux` by executing `go run cmd/loader.go --config cmd/config_dirigent_dandelion_trace.json`
- Create folder local folder `dandelion_100_100000` and transfer data from the cluster to it:
	- `node0` -> `~/invitro/data/out/experiment_duration_30.csv`
	- `node1` -> `/data/cold_start_trace.csv`
	- `node2` -> `/data/proxy_trace.csv`

## Plotting	

Having run both experiments, execute `python3 committed_memory.py` to generate plot for Figure 10.
