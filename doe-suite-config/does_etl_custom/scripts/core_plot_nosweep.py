import os
import json
import re
import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.size": 28,
    "font.family": "serif"
})

discard_error = True
exp_dir = "/home/bgoranov/workplace/dandelionExperiments/doe-suite-results/middleware_controller_1741194140/middleware_controller"
output_dir = "/home/bgoranov/workplace/dandelionExperiments/figures/delta_core_allocation"
engine_types = { "Process": "compute", "Reqwest": "communication" }
colours = { "Process": "blue", "Reqwest": "orange" }
y_limit = 300

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

def plot_core_tasks(core_map, task_map, queue_map, output_dir, ctrl_delta, ctrl_interval, rps):
    
    fig, axs = plt.subplots(2, figsize=(12, 10))
    cores_yticks = list(range(0, 14, 2))
    x_ticks = list(range(0, len(core_map["Process"])))
    x_ticks = [x * 600 / len(core_map["Process"]) for x in x_ticks]

    for engine_type in core_map:
        axs[0].plot(x_ticks, core_map[engine_type], label=engine_types[engine_type], color=colours[engine_type], linewidth=2)
        axs[1].plot(x_ticks, task_map[engine_type], label=engine_types[engine_type], color=colours[engine_type], linewidth=2)
    
    axs[0].set_title(f"delta={ctrl_delta}")
    axs[0].set_ylabel("Cores")
    axs[0].set_yticks(cores_yticks)
    axs[0].legend()
    axs[0].set_xticks([i for i in range(0, 601, 60)])
    axs[0].set_xticklabels([f"{i // 60}" for i in range(0, 601, 60)])

    axs[1].set_ylabel("Tasks")
    axs[1].set_xlabel("Time (s)")
    axs[1].set_xticks([i for i in range(0, 601, 60)])
    axs[1].set_xticklabels([f"{i // 60}" for i in range(0, 601, 60)])

    if y_limit:
        axs[1].set_ylim(0, y_limit)

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
    
    rps = extract_config_rps(run_dir)
    delta = extract_delta(worker_log)
    loop_duration = extract_loop_duration(worker_log)
    core_map = extract_core_nums(worker_log)
    task_map = extract_tasks(worker_log)
    queue_map = extract_queue_lengths(worker_log)

    return rps, delta, loop_duration, core_map, task_map, queue_map

def process_experiment(exp_dir):
    run_dirs = [os.path.join(exp_dir, subdir) for subdir in os.listdir(exp_dir) if subdir.startswith("run")]

    for run_dir in run_dirs:
        run_result = process_run(run_dir)
        if run_result is None:
            print(f"Run {run_dir} failed")
            continue
        rps, delta, loop_duration, core_map, task_map, queue_map = run_result
        plot_core_tasks(
            core_map=core_map,
            task_map=task_map,
            queue_map=queue_map,
            output_dir=output_dir,
            ctrl_delta=delta,
            ctrl_interval=loop_duration,
            rps=rps,
        )
    
    return

if __name__ == "__main__":
    process_experiment(exp_dir)
    print(f"Results available in: {output_dir}")