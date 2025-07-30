import os
from os.path import expanduser
from threading import Thread

import psutil
import time

# CPU and MEM collection logic
SLEEP_TIME = 0.1  # 100ms
DUMP_TIME = 10    # 10s
DUMP_FREQ = int(DUMP_TIME / SLEEP_TIME)


def cpu_mem_measure(output_path):
    # Accumulate the measurements: [[time, cpu, mem], ...]
    measurements = []

    # Create the file
    with open(output_path, "w+") as f:
        f.write(
            "timestamp,cpu,cpu_first,cpu_last,mem,net_bytes_sent,net_bytes_recv,disk_read_bytes,disk_write_bytes,disk_busy_time\n"
        )

    # Define function which dumps metrics
    def dump():
        with open(output_path, "a") as f:
            for el in measurements:
                f.write(",".join(map(str, el)) + "\n")
        measurements.clear()

    # ref_time = time.time()
    next_time = time.time()
    while True:
        # timestamp = time.time() - ref_time
        cpu = psutil.cpu_percent(percpu=True)
        mem = psutil.virtual_memory().percent
        net_io = psutil.net_io_counters()
        disk_io = psutil.disk_io_counters()
        assert disk_io is not None

        measurements.append(
            [
                time.time_ns(),
                sum(cpu) / len(cpu),
                cpu[0],
                cpu[-1],
                mem,
                net_io.bytes_sent,
                net_io.bytes_recv,
                disk_io.read_bytes,
                disk_io.write_bytes,
                disk_io.busy_time,  # !! Platform specific field - time spent doing disk I/O in milliseconds
            ]
        )

        if len(measurements) >= DUMP_FREQ:
            dump()

        next_time += SLEEP_TIME
        time.sleep(next_time - time.time())


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-o",
        "--output",
        help="Output file path to write report to",
        metavar="OUTPUT",
        required=True,
    )
    args = parser.parse_args()
    output_file = args.output

    # Create a logging dir
    directory = os.path.dirname(os.path.abspath(output_file))
    os.makedirs(directory, exist_ok=True)

    # Start measurement
    measure_thread = Thread(target=cpu_mem_measure, args=(output_file,))
    measure_thread.start()

    measure_thread.join()
