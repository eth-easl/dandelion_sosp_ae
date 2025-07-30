import re
import os
import json
import matplotlib.pyplot as plt
import numpy as np

exp_dir = "/home/bgoranov/workplace/dandelionExperiments/doe-suite-results/middleware_controller_1733492023/middleware_controller"
output_dir = "/home/bgoranov/workplace/dandelionExperiments/figures/middleware_controller_latency_sweep8_30"
y_limit = 5_000
discard_errors = True

def extract_metrics(file_path):
    metrics = []
    with open(file_path, 'r') as f:
        content = f.read()

    runs = content.split("Total:")[1:]

    for run in runs:
        total_match = re.search(r'(\d+), Errors: (\d+)', run)
        if not total_match:
            continue
        total = int(total_match.group(1))
        errors = int(total_match.group(2))

        latency_matches = {
            "p50": re.search(r'50% -- (\d+)', run),
            "p90": re.search(r'90% -- (\d+)', run),
            "p99": re.search(r'99% -- (\d+)', run)
        }
        latencies = {key: int(match.group(1)) for key, match in latency_matches.items() if match}

        rps = total / 60
        error_percentage = (errors / total) if total > 0 else 0

        metrics.append({
            "rps": rps,
            "p50": latencies.get("p50", None),
            "p90": latencies.get("p90", None),
            "p99": latencies.get("p99", None),
            "error_percentage": error_percentage
        })

    return metrics

def extract_config_controller(file_path):
    
    with open(file_path, 'r') as file:
        for line in file:
            if "controller" in line:
                return True
    return False

def extract_config_io_cores(worker_dir):

    config_file = None
    for dir, _, files in os.walk(worker_dir):
        for file in files:
            if file == "config.json":
                config_file = os.path.join(dir, file)
                break
        if config_file:
            break
    
    if not config_file:
        return None
    
    with open(config_file, 'r') as file:
        config = json.load(file)
        return config["io_cores"]
    
def process_worker_run(run_dir: str):

    loader_log = None
    worker_log = None

    for dir, _, files in os.walk(run_dir):
        for file in files:
            if file == "stdout.log" and "loader" in dir:
                loader_log = os.path.join(dir, file)
            if file == "stdout.log" and "worker" in dir:
                worker_log = os.path.join(dir, file)
    
    if not loader_log or not worker_log:
        return None
    
    metrics = extract_metrics(loader_log)
    controller = extract_config_controller(worker_log)
    io_cores = extract_config_io_cores(run_dir)

    return metrics, controller, io_cores

def plot_latency_sweep(data, output_dir):

    # plot p50, p90, and p99 against RPS in three separate plots and save each figure

    p50_fig, p50_ax = plt.subplots()
    p90_fig, p90_ax = plt.subplots()
    p99_fig, p99_ax = plt.subplots()

    for metrics, controller, io_cores in data:
        if not metrics:
            continue

        if discard_errors:
            metrics = [metric for metric in metrics if metric["error_percentage"] == 0]
        
        metrics = sorted(metrics, key=lambda x: x["rps"])

        rps_values = [metric["rps"] for metric in metrics]
        p50_values = [metric["p50"] for metric in metrics]
        p90_values = [metric["p90"] for metric in metrics]
        p99_values = [metric["p99"] for metric in metrics]

        label = "controller" if controller else f"io_cores={io_cores}"

        p50_ax.plot(rps_values, p50_values, 'o--', label=label)
        p90_ax.plot(rps_values, p90_values, 'o--', label=label)
        p99_ax.plot(rps_values, p99_values, 'o--', label=label)
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    if y_limit:
        min_p50 = min([metric["p50"] for metrics, _, _ in data for metric in metrics if metric["p50"]])
        min_p90 = min([metric["p90"] for metrics, _, _ in data for metric in metrics if metric["p90"]])
        min_p99 = min([metric["p99"] for metrics, _, _ in data for metric in metrics if metric["p99"]])
        
        p50_ax.set_ylim(max(min_p50 - 100, 0), y_limit)
        p90_ax.set_ylim(max(min_p90 - 100, 0), y_limit)
        p99_ax.set_ylim(max(min_p99 - 100, 0), y_limit)

    p50_ax.set_title("P50 Latency vs RPS")
    p50_ax.set_xlabel("RPS")
    p50_ax.set_ylabel("P50 Latency (us)")
    p50_ax.legend()
    p50_fig.savefig(os.path.join(output_dir, "p50_latency.png"))

    p90_ax.set_title("P90 Latency vs RPS")
    p90_ax.set_xlabel("RPS")
    p90_ax.set_ylabel("P90 Latency (us)")
    p90_ax.legend()
    p90_fig.savefig(os.path.join(output_dir, "p90_latency.png"))

    p99_ax.set_title("P99 Latency vs RPS")
    p99_ax.set_xlabel("RPS")
    p99_ax.set_ylabel("P99 Latency (us)")
    p99_ax.legend()
    p99_fig.savefig(os.path.join(output_dir, "p99_latency.png"))

    return

def process_experiment(exp_dir):

    run_dirs = [os.path.join(exp_dir, subdir) for subdir in os.listdir(exp_dir) if subdir.startswith("run")]

    data = []
    for run_dir in run_dirs:
        run_result = process_worker_run(run_dir)
        if run_result:
            data.append(run_result)

    return data

if __name__ == "__main__":
    data = process_experiment(exp_dir)
    plot_latency_sweep(data, output_dir)
    print("Done!")