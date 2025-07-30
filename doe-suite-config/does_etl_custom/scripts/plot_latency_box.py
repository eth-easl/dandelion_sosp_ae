import os
import json
import re
import matplotlib.pyplot as plt

static_path = "/home/bgoranov/workplace/dandelionExperiments/doe-suite-results/middleware_coresweep_1733262927/middleware_controller"
dynamic_path = "/home/bgoranov/workplace/dandelionExperiments/doe-suite-results/middleware_controller_1733302081/middleware_controller"
output_path = "/home/bgoranov/workplace/dandelionExperiments/figures/controller_sweep_box"

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
    
    return metrics_list

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

def plot_latency_boxes(metrics, metrics_dict_static, metrics_dict_dynamic):
    io_cores_static = sorted(metrics_dict_static.keys())
    io_cores_dynamic = sorted(metrics_dict_dynamic.keys())

    for metric in metrics:
        data = []

        for io_cores in io_cores_dynamic:
            data.append([stat[metric] for stat in metrics_dict_dynamic[io_cores]])

        for io_cores in io_cores_static:
            data.append([stat[metric] for stat in metrics_dict_static[io_cores]])
        
        x_labels = [f"ctrl {io_cores}" for io_cores in io_cores_dynamic] + [f"noctrl {io_cores}" for io_cores in io_cores_static]
        fig, ax = plt.subplots(figsize=(12, 10))
        bp = ax.boxplot(data, tick_labels=x_labels, patch_artist=True, showfliers=False)

        for _, median in enumerate(bp['medians']):
            x = (median.get_xdata()[0] + median.get_xdata()[1]) / 2
            y = median.get_ydata()[0]
            ax.text(x, y, f'{y:.2e}', ha='center', va='bottom', color='black')
        
        ax.set_xlabel('IO cores')
        ax.set_ylabel(metric)
        ax.set_title(f'{metric} comparison')
        fig.tight_layout()

        if not os.path.exists(output_path):
            os.makedirs(output_path)
        plt.savefig(f'{output_path}/{metric}_comparison.png')

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

    return sweep_results

if __name__ == "__main__":
    metrics = ["error_percentage", "p50_latency_us", "p90_latency_us", "p99_latency_us"]
    metrics_dict_static = compare_experiments(static_path)
    metrics_dict_dynamic = compare_experiments(dynamic_path)
    plot_latency_boxes(metrics, metrics_dict_static, metrics_dict_dynamic)
    print(metrics_dict_dynamic)
    print("Done!")