import datetime
import re
import os
import sys
import pandas as pd
import matplotlib.pyplot as plt

plt.rcParams.update({'font.size': 16, 'font.family': 'serif'})

output_path = "/home/bgoranov/workplace/dandelionExperiments/figures/pid_mixed_apps"
static_path = "/home/bgoranov/workplace/dandelionExperiments/doe-suite-results/mixed_workload_1742757090/load_latency"
dynamic_path = "/home/bgoranov/workplace/dandelionExperiments/doe-suite-results/mixed_workload_1742804219/load_latency"

colors = { 'compression-app': 'blue', 'middleware-app': 'orange' }

def plot_latency_over_time(static_path, dynamic_path, output_path):
    # Read two csv files in static_path and two csv files in dynamic_path
    dfs_dynamic = {}
    dfs_static = {}
    for dir, _, files in os.walk(static_path):
        for file in files:
            if file.endswith(".csv"):
                app_name = file.split("_")[-5]
                dfs_static[app_name] = pd.read_csv(os.path.join(dir, file))

    for dir, _, files in os.walk(dynamic_path):
        for file in files:
            if file.endswith(".csv"):
                app_name = file.split("_")[-5]
                dfs_dynamic[app_name] = pd.read_csv(os.path.join(dir, file))

    # Plot three figures one on top of the other.

    # set start time to zero
    for app_name in dfs_static:
        min_start_time = dfs_static[app_name]['startTime'][0]
        dfs_static[app_name]['startTime'] = dfs_static[app_name]['startTime'] - min_start_time
        dfs_static[app_name] = dfs_static[app_name][1:-1]
    
    requests_per_second = {}
    for app_name in dfs_dynamic:
        min_start_time = dfs_dynamic[app_name]['startTime'][0]
        dfs_dynamic[app_name]['startTime'] = dfs_dynamic[app_name]['startTime'] - min_start_time
        dfs_dynamic[app_name] = dfs_dynamic[app_name][1:-1]

        start_second = (dfs_dynamic[app_name]['startTime'] / 1e6).astype('int')
        requests_per_second[app_name] = start_second.groupby(start_second).size()
    
    fig, ax = plt.subplots(3, figsize=(14, 10))

    for app_name in dfs_dynamic:
        ax[0].plot(requests_per_second[app_name], label=app_name, color=colors[app_name])
    ax[0].set_ylabel('RPS (sent)')
    ax[0].legend()

    y_limit = 100000

    for app_name in dfs_static:
        latencies = dfs_static[app_name]['responseTime']
        times = dfs_static[app_name]['startTime'] / 1e6
        ax[1].scatter(times, latencies, s=3, label=f"{app_name} io_cores=6", color=colors[app_name])
        ax[1].scatter(times[latencies > y_limit], [y_limit] * sum(latencies > y_limit), s=3, color='red')
    ax[1].set_ylabel('Latency [us]')
    ax[1].legend()
    ax[1].set_ylim(0, y_limit)

    for app_name in dfs_dynamic:
        latencies = dfs_dynamic[app_name]['responseTime']
        times = dfs_dynamic[app_name]['startTime'] / 1e6
        ax[2].scatter(times, latencies, s=3, label=f"{app_name} controller", color=colors[app_name])
        ax[2].scatter(times[latencies > y_limit], [y_limit] * sum(latencies > y_limit), s=3, color='red')
    ax[2].set_ylabel('Latency [us]')
    ax[2].legend()
    ax[2].set_ylim(0, y_limit)

    if not os.path.exists(output_path):
        os.makedirs(output_path)
    
    plt.savefig(output_path + '/mixed_apps_latency.png')

if __name__ == "__main__":
    static_path = sys.argv[1] if len(sys.argv) > 1 else static_path
    dynamic_path = sys.argv[2] if len(sys.argv) > 2 else dynamic_path
    output_path = sys.argv[3] if len(sys.argv) > 3 else output_path
    plot_latency_over_time(static_path, dynamic_path, output_path)
    print(f"Results saved in {output_path}")
