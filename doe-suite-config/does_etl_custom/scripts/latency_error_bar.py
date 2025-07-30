import re
import os
import json
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter

dirs_to_compare = {
    "ctrl_await": "/home/bgoranov/workplace/dandelionExperiments/doe-suite-results/middleware_controller_1732983998/middleware_controller",
    "noctrl_await": "/home/bgoranov/workplace/dandelionExperiments/doe-suite-results/middleware_controller_1733006066/middleware_controller",
    "noctrl_noawait": "/home/bgoranov/workplace/dandelionExperiments/doe-suite-results/middleware_controller_1733052342/middleware_controller",
}

output_path = "/home/bgoranov/workplace/dandelionExperiments/figures/middleware_bars_print"

def compare_experiments(dirs_to_compare, output_path):
    
    results = {}
    for key in dirs_to_compare:
        results[key] = group_runs_by_rps(dirs_to_compare[key])
    
    plot_comparison(results, output_path)
    
    return results

def plot_comparison(results, output_path):
    exp_names = list(results.keys())
    rps_values = sorted(list(results[exp_names[0]].keys()))
    metrics = list(results[exp_names[0]][rps_values[0]].keys())

    # plot a bar chart for each of the metrics where the x-axis is the RPS value and group the bars by RPS
    for metric in metrics:
        plt.figure(figsize=(10, 6))
        x_indexes = range(len(rps_values))
        width = 0.2

        for i, exp_name in enumerate(exp_names):
            y_values = [results[exp_name][rps][metric] for rps in rps_values]
            plt.bar([x + width * i for x in x_indexes], y_values, width=width, label=exp_name)
        
        plt.title(f"{metric} comparison")
        plt.xlabel("RPS")
        plt.ylabel(metric)
        plt.xticks(ticks=[i + width for i in x_indexes], labels=rps_values)
        plt.legend()

        ax = plt.gca()
        ax.yaxis.set_major_formatter(ScalarFormatter(useMathText=True))
        ax.ticklabel_format(axis='y', style='sci', scilimits=(1,4))

        if not os.path.exists(output_path):
            os.makedirs(output_path)

        plt.tight_layout()
        plt.savefig(os.path.join(output_path, f"{metric}.png"))


def group_runs_by_rps(worker_dir):

    run_dirs = [os.path.join(worker_dir, subdir) for subdir in os.listdir(worker_dir) if subdir.startswith("run")]
    rps_map = {}

    for run_dir in run_dirs:
        rps = extract_config_rps(run_dir)
        rps_map[rps] = process_worker_run(run_dir)
    
    return rps_map

def extract_config_rps(worker_dir):

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
        return config["rps"]

def process_worker_run(worker_dir):

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
        avg_metrics["error_percentage"] += metrics["error_percentage"]
        avg_metrics["p50_latency_us"] += metrics["p50_latency_us"]
        avg_metrics["p90_latency_us"] += metrics["p90_latency_us"]
        avg_metrics["p99_latency_us"] += metrics["p99_latency_us"]
    
    for key in avg_metrics:
        avg_metrics[key] /= len(metrics_list)
    
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

if __name__ == "__main__":
    results = compare_experiments(dirs_to_compare, output_path)
    print("Processed results:\n")
    print(json.dumps(results, indent=4))