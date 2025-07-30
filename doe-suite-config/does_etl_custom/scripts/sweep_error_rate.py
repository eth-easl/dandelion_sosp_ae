import os
import json
import re
import numpy as np
import matplotlib.pyplot as plt

sweep_dir = "/home/bgoranov/workplace/dandelionExperiments/doe-suite-results/middleware_controller_1733302081/middleware_controller"
output_dir = "/home/bgoranov/workplace/dandelionExperiments/figures/controller_sweep_stats"

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

def process_worker_run(worker_dir: str):

    metrics_list = []
    for dir, _, files in os.walk(worker_dir):
        for file in files:
            if file == "stdout.log" and "loader" in dir:
                metrics = extract_latency_errors(os.path.join(dir, file))
                metrics_list.append(metrics)

    if not metrics_list:
        return None
    
    avg_metrics = {
        "error_percentage": 0,
        "p50_latency_us": 0,
        "p90_latency_us": 0,
        "p99_latency_us": 0
    }

    for metrics in metrics_list:
        print("Error percentage: ", metrics["error_percentage"])
        avg_metrics["error_percentage"] += metrics["error_percentage"]
        avg_metrics["p50_latency_us"] += metrics["p50_latency_us"]
        avg_metrics["p90_latency_us"] += metrics["p90_latency_us"]
        avg_metrics["p99_latency_us"] += metrics["p99_latency_us"]
    
    for key in avg_metrics:
        avg_metrics[key] /= len(metrics_list)
    
    print("Average error percentage: ", avg_metrics["error_percentage"])
    
    return avg_metrics

def extract_latency_errors(file_path):

    metrics = {
        "error_percentage": None,
        "p50_latency_us": None,
        "p90_latency_us": None,
        "p99_latency_us": None
    }

    with open(file_path, 'r') as file:
        for line in file:
            # Extract Errors percentage
            if line.startswith("Total:"):
                match = re.search(r"Errors: (\d+)", line)
                if match:
                    total_match = re.search(r"Total: (\d+)", line)
                    total_requests = int(total_match.group(1))
                    errors = int(match.group(1))
                    metrics["error_percentage"] = (errors / total_requests) * 100 if total_requests > 0 else 0

            # Extract latency percentiles
            if line.startswith("   50%"):
                metrics["p50_latency_us"] = int(re.search(r"50% -- (\d+)", line).group(1))
            elif line.startswith("   90%"):
                metrics["p90_latency_us"] = int(re.search(r"90% -- (\d+)", line).group(1))
            elif line.startswith("   99%"):
                metrics["p99_latency_us"] = int(re.search(r"99% -- (\d+)", line).group(1))

    return metrics

def compare_experiments(sweep_dir: str):

    run_dirs = [os.path.join(sweep_dir, subdir) for subdir in os.listdir(sweep_dir) if subdir.startswith("run")]
    sweep_results = {}

    for run_dir in run_dirs:
        io_cores = extract_config_io_cores(run_dir)
        if io_cores is None:
            print(f"Could not extract io_cores from {run_dir}")
            continue

        metrics = process_worker_run(run_dir)
        if metrics is None:
            print(f"Could not extract metrics from {run_dir}")
            continue

        sweep_results[io_cores] = metrics

    plot_sweep_results(sweep_results)

    return sweep_results

def plot_sweep_results(sweep_results: dict):
    io_cores = sorted(list(sweep_results.keys()))
    metrics = ["error_percentage"]

    values = {metric: [sweep_results[core][metric] for core in io_cores] for metric in metrics}

    bar_width = 0.2
    x = np.arange(len(io_cores))  # X positions for groups
    fig, ax = plt.subplots(figsize=(10, 6))

    for i, metric in enumerate(metrics):
        ax.bar(x + i * bar_width, values[metric], bar_width, label=metric)

    ax.set_xticks(x + bar_width * (len(metrics) - 1) / 2)
    ax.set_xticklabels(io_cores)
    ax.set_xlabel("IO cores (out of 13)")
    ax.set_ylabel("Errors (%)")
    ax.set_title("Errors per core split")
    ax.legend(title="Metrics")

    plt.tight_layout()

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    plt.savefig(output_dir + '/core_sweep_stats.png')

if __name__ == "__main__":
    res = compare_experiments(sweep_dir)
    print(res)