import os
import json
import re
import matplotlib.pyplot as plt
import numpy as np

discard_error = True
exp_dir = "/home/bgoranov/workplace/dandelionExperiments/doe-suite-results/middleware_controller_1733501503/middleware_controller"
output_dir = "/home/bgoranov/workplace/dandelionExperiments/figures/middleware_controller_cores_open_sweep_8_30"

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
    
def extract_error_percentage(file_path):

    with open(file_path, 'r') as file:
        for line in file:
            # Extract Errors percentage
            if line.startswith("Total:"):
                match = re.search(r"Errors: (\d+)", line)
                total_match = re.search(r"Total: (\d+)", line)
                total_requests = int(total_match.group(1))
                errors = int(match.group(1))
                return (errors / total_requests) * 100 if total_requests > 0 else 0
    return None

def extract_rps_values(file_path):

    rps_values = []

    with open(file_path, 'r') as file:
        for line in file:
            # Extract Errors percentage
            if line.startswith("Total:"):
                total_match = re.search(r"Total: (\d+)", line)
                total_requests = int(total_match.group(1))
                rps = total_requests / 60
                rps_values.append(rps)
    return sorted(rps_values)

def extract_delta(file_path):

    with open(file_path, 'r') as file:
        for line in file:
            if line.startswith("delta"):
                return int(re.search(r"delta (\d+)", line).group(1))
    return None

def extract_loop_duration(file_path):

    with open(file_path, 'r') as file:
        for line in file:
            if line.startswith("delta"):
                return int(re.search(r"loop duration: (\d+)", line).group(1))
    return None

def extract_core_nums(file_path):

    core_map = {}
    with open(file_path, 'r') as file:
        core_lines = [line for line in file if line.startswith("[CTRL]") and "Cores" in line]
        for line in core_lines:
            match = re.findall(r"Engine type: (\w+), Cores: (\d+)", line)
            for engine_type, cores in match:
                if engine_type not in core_map:
                    core_map[engine_type] = []
                core_map[engine_type].append(int(cores))
    return core_map

def extract_tasks(file_path):

    task_map = {}
    with open(file_path, 'r') as file:
        task_lines = [line for line in file if line.startswith("[CTRL]") and "Tasks" in line]
        for line in task_lines:
            match = re.findall(r"Engine type: (\w+), Tasks: (\d+)", line)
            for engine_type, tasks in match:
                if engine_type not in task_map:
                    task_map[engine_type] = []
                task_map[engine_type].append(int(tasks))
    return task_map

def extract_queue_lengths(file_path):

    queue_map = {}
    with open(file_path, 'r') as file:
        queue_lines = [line for line in file if line.startswith("[CTRL]") and "Queue length" in line]
        for line in queue_lines:
            match = re.findall(r"Engine type: (\w+), Queue length: (\d+)", line)
            for engine_type, queue_length in match:
                if engine_type not in queue_map:
                    queue_map[engine_type] = []
                queue_map[engine_type].append(int(queue_length))
    return queue_map

def plot_core_tasks(core_map, task_map, queue_map, output_dir, ctrl_delta, ctrl_interval, rps_values):
    
    fig, axs = plt.subplots(3, figsize=(12, 10))
    cores_yticks = list(range(0, 14, 2))

    for engine_type in core_map:
        y_len = len(core_map[engine_type])
        x_interp = np.interp(
            np.linspace(0, y_len - 1, y_len),  # Target indices for interpolation
            np.linspace(0, y_len - 1, len(rps_values)),  # Original indices
            rps_values
        )
        axs[0].plot(x_interp, core_map[engine_type], label=engine_type)
        axs[1].plot(x_interp, task_map[engine_type], label=engine_type)
        axs[2].plot(x_interp, queue_map[engine_type], label=engine_type)
    
    axs[0].set_title(f"delta={ctrl_delta}, interval={ctrl_interval}")
    axs[0].set_ylabel("Cores")
    axs[0].set_yticks(cores_yticks)
    axs[0].legend()

    axs[1].set_ylabel("Tasks")
    axs[1].legend()

    axs[2].set_ylabel("Queue Length")
    axs[2].set_xlabel("RPS")
    axs[2].legend()

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, f"core_tasks_delta={ctrl_delta}_interval={ctrl_interval}.png"))

def process_run(run_dir):
    
    loader_log = None
    worker_log = None

    for dir, _, files in os.walk(run_dir):
        for file in files:
            if file == "stdout.log" and "loader" in dir:
                loader_log = os.path.join(dir, file)
            if file == "stdout.log" and "worker" in dir:
                worker_log = os.path.join(dir, file)

    error_percentage = extract_error_percentage(loader_log)

    if error_percentage > 0 and discard_error:
        return None
    
    delta = extract_delta(worker_log)
    loop_duration = extract_loop_duration(worker_log)
    core_map = extract_core_nums(worker_log)
    task_map = extract_tasks(worker_log)
    queue_map = extract_queue_lengths(worker_log)
    rps_values = extract_rps_values(loader_log)

    return rps_values, delta, loop_duration, core_map, task_map, queue_map

def process_experiment(exp_dir):
    run_dirs = [os.path.join(exp_dir, subdir) for subdir in os.listdir(exp_dir) if subdir.startswith("run")]

    for run_dir in run_dirs:
        run_result = process_run(run_dir)
        if run_result is None:
            print(f"Run {run_dir} failed")
            continue
        rps_values, delta, loop_duration, core_map, task_map, queue_map = run_result
        plot_core_tasks(
            core_map=core_map,
            task_map=task_map,
            queue_map=queue_map,
            output_dir=output_dir,
            ctrl_delta=delta,
            ctrl_interval=loop_duration,
            rps_values=rps_values
        )
    
    return

if __name__ == "__main__":
    process_experiment(exp_dir)
    print(f"Results available in: {output_dir}")