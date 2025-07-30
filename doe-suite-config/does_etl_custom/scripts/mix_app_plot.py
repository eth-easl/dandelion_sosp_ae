import re
import glob
import sys
import os
import pandas as pd
import matplotlib.pyplot as plt

# Set output directory
output_dir = "/Users/yazhuo/Workspace/EASL/dandelionExperiments/plots"

# Set larger font sizes
plt.rcParams.update({
    'font.size': 12,
    'axes.labelsize': 14,
    'axes.titlesize': 16,
    'xtick.labelsize': 12,
    'ytick.labelsize': 12,
    'legend.fontsize': 12
})

# Ensure correct usage
assert len(sys.argv) == 2
base_dir = sys.argv[1]

app_colors_dict = {
    "compression-app": "blue",
    "middleware-app": "orange",
}

app_labels_dict = {
    "compression-app": "img compression",
    "middleware-app": "log processing",
}

# Find all subfolders matching 'run_*'
run_folders = sorted(glob.glob(f"{base_dir}/run_*"))

# Prepare a single RPS plot (shared for all runs) and one latency subplot for each run
fig, axs = plt.subplots(len(run_folders) + 1, figsize=(10, 2 + 4 * len(run_folders)))

# Iterate over each run folder
for i, run_folder in enumerate(run_folders):
    # Locate the CSV file in the fixed structure
    csv_files = glob.glob(f"{run_folder}/rep_0/loader/host_0/latencies_*.csv")
    csv_files.sort()
    if not csv_files:
        print(f"No CSV files found in {run_folder}/rep_0/loader/host_0")
        continue

    for csv_file in csv_files:
        # Parse function name and process type from the file name
        parser = re.fullmatch(
            r".*latencies_(.*)_open-loop_(.*)_.*_.*hot_1_rate\.csv", csv_file
        )
        if not parser:
            print(f"Skipping invalid file name: {csv_file}")
            continue
        process_type = parser[1]  # Extract `dandelion-process`
        function_name = parser[2]  # Extract `compression-app`

        # Read and preprocess the CSV file
        df = pd.read_csv(csv_file)
        df = df.sort_values(by="startTime")
        min_start_time = df["startTime"][0]
        df["startTime"] = df["startTime"] - min_start_time
        df = df[1:-1]  # Skip first and last rows

        # Compute requests per second
        start_second = (df["startTime"] / 1e6).astype("int")
        requests_per_second = start_second.groupby(start_second).size()

        if i == 0:
            axs[0].plot(requests_per_second, label=app_labels_dict[function_name], color=app_colors_dict[function_name])
            axs[0].set_ylabel("RPS")
            axs[0].set_ylim(bottom=0, top=520)
            axs[0].legend()

        # Filter only successful requests and plot latency for this run
        df = df[df["statusCode"] == 200]
        # Convert to milliseconds
        latencies_ms = df["responseTime"] / 1000
        print(f"Process: {process_type}, Max latency: {latencies_ms.max():.2f}ms, Min latency: {latencies_ms.min():.2f}ms")
        
        # Split data into normal and high latency points
        normal_latency_mask = latencies_ms <= 60
        high_latency_mask = latencies_ms > 60
        
        # Plot normal latencies
        axs[i + 1].scatter(
            df[normal_latency_mask]["startTime"] / 1e6,
            latencies_ms[normal_latency_mask],
            s=3,
            label=app_labels_dict[function_name],
            color=app_colors_dict[function_name]
        )
        
        # Plot high latencies in red at 60ms
        axs[i + 1].scatter(
            df[high_latency_mask]["startTime"] / 1e6,
            [60] * len(df[high_latency_mask]),
            s=3,
            color='red'
        )
        
        axs[i + 1].set_ylabel("Latency [ms]")
        axs[i + 1].legend()
        axs[i + 1].set_title(f"{process_type}")
        axs[i + 1].set_ylim(0, 65)  # Set y-axis limit for all subplots

# Finalize the plots
plt.xlabel("time [s]")
plt.legend()
plt.tight_layout()

# plt.show()
plt.savefig(os.path.join(output_dir, "latency_plot_over_time.png"))
