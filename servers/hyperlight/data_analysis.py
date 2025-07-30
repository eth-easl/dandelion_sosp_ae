import pandas as pd
import json
import matplotlib.pyplot as plt
from pathlib import Path
import re

# Read the logs
log_file = Path('latency_logs_128.json')
if not log_file.exists():
    print(f"Error: {log_file} does not exist")
    exit(1)

print(f"Reading logs from {log_file}")
latency_data = []

# Regular expression to extract JSON from latency_metrics log entries
metrics_pattern = re.compile(r'latency_metrics=(\{.*\})')

with open(log_file, 'r') as f:
    for line in f:
        try:
            # Try to parse the line as JSON first
            try:
                log = json.loads(line.strip())
                if 'fields' in log and 'message' in log['fields']:
                    message = log['fields']['message']
                    if 'latency_metrics=' in message:
                        # Extract the JSON part from the message
                        match = metrics_pattern.search(message)
                        if match:
                            metrics_json = match.group(1)
                            metrics = json.loads(metrics_json)
                            metrics['timestamp'] = log['timestamp']  # Use the log timestamp
                            latency_data.append(metrics)
            except json.JSONDecodeError:
                # If not JSON, try to find latency_metrics directly
                if 'latency_metrics=' in line:
                    match = metrics_pattern.search(line)
                    if match:
                        metrics_json = match.group(1)
                        metrics = json.loads(metrics_json)
                        metrics['timestamp'] = pd.Timestamp.now().isoformat()  # Use current time
                        latency_data.append(metrics)
        except Exception as e:
            print(f"Warning: Error processing log line: {e}")
            continue

print(f"Extracted latency metrics entries: {len(latency_data)}")

if not latency_data:
    print("Error: No latency metrics found in the logs")
    print("Make sure the server is logging latency metrics in the correct format")
    exit(1)

# Convert to DataFrame
df = pd.DataFrame(latency_data)
print(f"DataFrame columns: {list(df.columns)}")

# Calculate RPS (requests per second)
df['timestamp'] = pd.to_datetime(df['timestamp'])
df['rps'] = df.groupby(pd.Grouper(key='timestamp', freq='1s'))['request_id'].transform('count')

# Create stacked histogram
plt.figure(figsize=(12, 8))
plt.hist([
    df['sandbox_creation'],
    df['runtime_loading'],
    df['module_loading'],
    df['function_execution']
], 
bins=50, 
stacked=True,
label=['Sandbox Creation', 'Runtime Loading', 'Module Loading', 'Function Execution'])

plt.xlabel('Latency (µs)')
plt.ylabel('Frequency')
plt.title('Latency Distribution by Component')
plt.legend()
plt.savefig('latency_histogram.png')
print("Saved latency histogram to latency_histogram.png")

# Create RPS vs Latency scatter plot
plt.figure(figsize=(12, 8))
plt.scatter(df['rps'], df['total_time'], alpha=0.5)
plt.xlabel('Requests Per Second')
plt.ylabel('Total Latency (µs)')
plt.title('RPS vs Total Latency')
plt.savefig('rps_vs_latency.png')
print("Saved RPS vs latency plot to rps_vs_latency.png")

# Print summary statistics
print("\nLatency Summary Statistics (microseconds):")
print("Component               Mean     Min      Max      Std")
print("-" * 55)
for component in ['sandbox_creation', 'runtime_loading', 'module_loading', 'function_execution', 'total_time']:
    stats = df[component].describe()
    print(f"{component:20} {stats['mean']:8.2f} {stats['min']:8.2f} {stats['max']:8.2f} {stats['std']:8.2f}")

# Calculate average RPS
print(f"\nAverage RPS: {df['rps'].mean():.2f}")
print(f"Max RPS: {df['rps'].max():.2f}")
print(f"Total requests processed: {len(df)}")