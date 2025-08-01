
## Firecracker experiment:
- Locally clone https://github.com/eth-easl/dirigent and checkout to `dandelion_sosp25_firecracker` branch.
- Create a Cloudlab cluster of 4 `d430` nodes with Dirigent profile (https://www.cloudlab.us/p/faas-sched/dirigent).
- On your local machine execute `scripts/remote_install.sh <username>@<node0> <username>@<node1> <username>@<node2> <username>@<node3>`. Replace username and `node[0-3]`.
- On your local machine execute `scripts/remote_start_cluster.sh <username>@<node0> <username>@<node1> <username>@<node2> <username>@<node3>`. Replace username and `node[0-3]`.
- On `node0` checkout `~/invitro` repo to branch `dandelion_sosp25_firecracker` and copy `azure_100` to `node0` to location `~/invitro/data/traces/azure_100`
- Need to warm up the cluster first:
	Run for a few times and make sure you get positive responses from the cluster - `go run cmd/loader.go --config cmd/config_dirigent_rps.json` 
- Run the main experiment in `tmux` by executing `go run cmd/loader.go --config cmd/config_dirigent_trace.json`
- Create folder local folder `firecracker_100_100000` and transfer data from the cluster to it:
	- `node0` -> `~/invitro/data/out/experiment_duration_30.csv`
	- `node1` -> `/data/cold_start_trace.csv`
	- `node2` -> `/data/proxy_trace.csv`

## Dandelion experiment:
- Locally clone `https://github.com/eth-easl/dirigent` and checkout to `dandelion_sosp25_dandelion_new` branch.
- Create a Cloudlab cluster of 4 `d430` nodes with Dirigent profile (https://www.cloudlab.us/p/faas-sched/dirigent).
- On your local machine execute `scripts/remote_install.sh <username>@<node0> <username>@<node1> <username>@<node2> <username>@<node3>`. Replace username and `node[0-3]`.
- On your local machine execute `scripts/remote_start_cluster.sh <username>@<node0> <username>@<node1> <username>@<node2> <username>@<node3>`. Replace username and `node[0-3]`.
- On `node0` checkout `~/invitro` repo to branch `dandelion_sosp25_firecracker` and copy `azure_100` to `node0` to location `~/invitro/data/traces/azure_100`
- Need to warm up the cluster first:
	Run for a few times and make sure you get positive responses from the cluster - `go run cmd/loader.go --config cmd/config_dirigent_dandelion_rps.json `
- Run the main experiment in `tmux` by executing `go run cmd/loader.go --config cmd/config_dirigent_dandelion_trace.json`
- Create folder local folder `dandelion_100_100000` and transfer data from the cluster to it:
	- `node0` -> `~/invitro/data/out/experiment_duration_30.csv`
	- `node1` -> `/data/cold_start_trace.csv`
	- `node2` -> `/data/proxy_trace.csv`

## Plotting	

Having run both experiments, execute `python3 committed_memory.py` to generate plot for Figure 10.
