import json
from doespy.etl.steps.extractors import Extractor
from doespy.etl.steps.transformers import Transformer
from doespy.etl.steps.loaders import Loader, PlotLoader

import seaborn as sns
import pandas as pd
from typing import Dict, List, Tuple, Match
import matplotlib.pyplot as plt
import matplotlib.ticker
from matplotlib.lines import Line2D
import itertools 
import re 
from numpy import int64,ndarray
from pathlib import PurePath 
import pickle
from .helpers import *
import math
from .general import create_fig 
import os

# https://stackoverflow.com/questions/31147893/logarithmic-plot-of-a-cumulative-distribution-function-in-matplotlib

import numpy as np
from numpy import ma
from matplotlib import scale as mscale
from matplotlib import transforms as mtransforms
from matplotlib.ticker import FixedFormatter, FixedLocator

class CloseToOne(mscale.ScaleBase):
    name = 'close_to_one'

    def __init__(self, axis, **kwargs):
        mscale.ScaleBase.__init__(self, axis)
        self.nines = kwargs.get('nines', 5)

    def get_transform(self):
        return self.Transform(self.nines)

    def set_default_locators_and_formatters(self, axis):
        axis.set_major_locator(
            FixedLocator(np.array([1 - 10 ** (-k) for k in range(1 + self.nines)]))
        )
        axis.set_major_formatter(
            FixedFormatter([str(1 - 10 ** (-k)) for k in range(1 + self.nines)])
        )

    def limit_range_for_scale(self, vmin, vmax, minpos):
        return vmin, min(1 - 10 ** (-self.nines), vmax)

    class Transform(mtransforms.Transform):
        input_dims = 1
        output_dims = 1
        is_separable = True

        def __init__(self, nines):
            mtransforms.Transform.__init__(self)
            self.nines = nines

        def transform_non_affine(self, a):
            masked = ma.masked_where(a > 1 - 10 ** (-1 - self.nines), a)
            if masked.mask.any():
                return -ma.log10(1 - a)
            else:
                return -np.log10(1 - a)

        def inverted(self):
            return CloseToOne.InvertedTransform(self.nines)

    class InvertedTransform(mtransforms.Transform):
        input_dims = 1
        output_dims = 1
        is_separable = True

        def __init__(self, nines):
            mtransforms.Transform.__init__(self)
            self.nines = nines

        def transform_non_affine(self, a):
            return 1.0 - 10 ** (-a)

        def inverted(self):
            return CloseToOne.Transform(self.nines)

mscale.register_scale(CloseToOne)


class ControllerLatencyHeatmapLoader(PlotLoader):

    quantile = 0.5

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        print("loading middleware controller latency")
        if df.empty:
            print("empty dataframe")
            return
        
        iterations_values = df['iterations'].unique()
        for iterations in iterations_values:
            options['iterations'] = iterations
            output_dir = self.get_output_dir(etl_info)
            fig = self.create_fig(df[df['iterations'] == iterations], options)
            file_name = f"dynamic_allocator_latency_heatmap_iterations={iterations},p={int(self.quantile * 100)}"
            self.save_plot(fig, filename=file_name, output_dir=output_dir)

    def create_fig(self, df: pd.DataFrame, options: Dict):
        print("creating middleware controller latency plot")
        set_fonts()

        p_latency = df.groupby(['control_low_thre', 'control_high_thre'])['latency'].quantile(self.quantile).reset_index()
        p_latency = p_latency.pivot('control_low_thre', 'control_high_thre', 'latency')
        p_latency = p_latency.sort_index(ascending=False)
        p_latency = p_latency.sort_index(axis=1)
        
        fig, axis = plt.subplots(figsize=(12, 10))
        sns.heatmap(p_latency, annot=True, fmt=".2f", ax=axis, cmap="flare", annot_kws={"size": 16})
        axis.set_xlabel("high threshold")
        axis.set_ylabel("low threshold")
        axis.set_title(f"p{int(self.quantile * 100)} latency [ms] for iterations={options['iterations']}, rps=600")
        fig.tight_layout()
        return fig

class ControllerLatencyBarLoader(PlotLoader):
    quantile: float = 0.5
    val_key: str = "iterations"

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        print(etl_info, options)
        print("loading controller latency")
        if df.empty:
            print("empty dataframe")
            return
        
        unique_vals = df[self.val_key].unique()
        for val in unique_vals:
            options[self.val_key] = val
            output_dir = self.get_output_dir(etl_info)
            fig = self.create_fig(df[df[self.val_key] == val], options)
            file_name = f"dynamic_allocator_latency_{self.val_key}={val},p={int(self.quantile * 100)}"
            self.save_plot(fig, filename=file_name, output_dir=output_dir)
    
    def create_fig(self, df: pd.DataFrame, options: Dict):
        print("creating controller latency plot")
        set_fonts()

        p_latency = df.groupby(['control_delta'])['latency'].quantile(self.quantile).reset_index()
        p_latency = p_latency.sort_values(by='control_delta')
        delta_positions = range(len(p_latency['control_delta']))

        fig, axis = plt.subplots(figsize=(12, 10))
        axis.bar(delta_positions, p_latency['latency'])
        axis.set_xticks(delta_positions)
        axis.set_xticklabels(p_latency['control_delta'])
        axis.set_xlabel("control delta")
        axis.set_ylabel(f"p{int(self.quantile * 100)} latency [ms]")
        axis.set_title(f"p{int(self.quantile * 100)} latency [ms] for {self.val_key}={format(options[self.val_key], '.1e')}")
        fig.tight_layout()
        return fig

class ControllerCoresExtractor(Extractor):
        
        val_key: str = "none"
    
        def default_file_regex():
            return [r"stdout.*\.log$"]
        
        def parse_config(self, input_file: str):
            while not os.path.exists(f"{input_file}/config.json"):
                input_file = os.path.dirname(input_file)
            with open(f"{input_file}/config.json", 'r') as file:
                config = json.load(file)
            return config
        
        def parse_log_file(self, input_file: str):
            with open(input_file, 'r') as file:
                lines = file.readlines()
            
            delta_line = [line for line in lines if line.startswith("delta")][0]
            control_delta = int(delta_line.split(",")[0].split(" ")[-1])
            
            lines = [line for line in lines if line.startswith("Engine type") and not "Buffer" in line]
            lines = [lines[i:i+2] for i in range(0, len(lines), 2)]

            cpu_core_map = { "control_delta": control_delta }
            queue_length_map = { "control_delta": control_delta }

            if self.val_key != "none":
                config = self.parse_config(input_file)
                cpu_core_map[self.val_key] = config[self.val_key]
                queue_length_map[self.val_key] = config[self.val_key]

            for line_pair in lines:
                core_no_lines = line_pair[0].split("; ")
                queue_length_lines = line_pair[1].split("; ")
                self.parse_type_number_map(cpu_core_map, core_no_lines)
                self.parse_type_number_map(queue_length_map, queue_length_lines)
            
            return cpu_core_map, queue_length_map
        
        def parse_type_number_map(self, engine_type_map: Dict, lines: List[str]):
            for line in lines:
                if not line.startswith("Engine type"):
                    continue

                engine_type, n = self.parse_type_number(line)

                if engine_type not in engine_type_map:
                    engine_type_map[engine_type] = []
                engine_type_map[engine_type].append(n)
            return engine_type_map
        
        def parse_type_number(self, line: str):
            engine_type, n = line.split(", ")
            n = int(n.split(": ")[1])
            engine_type = engine_type.split(": ")[1]
            return engine_type, n
    
        def extract(self, path: str, options: Dict) -> List[Dict]:
            if "loader" in path:
                return []
            
            cpu_core_map, queue_length_map = self.parse_log_file(path)
            return [{ "cpu_cores": json.dumps(cpu_core_map), "queue_length": json.dumps(queue_length_map) }]

class ControllerCoresPlotLoader(PlotLoader):
        
        val_key: str = "none"
        time_ticks: List[int] = [0, 10]
        
        def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
            if df.empty:
                return
            
            output_dir = self.get_output_dir(etl_info)

            cpu_cores_maps = df['cpu_cores']
            cpu_cores_maps = [m for m in cpu_cores_maps[~cpu_cores_maps.isnull()]]
            queue_length_maps = df['queue_length']
            queue_length_maps = [m for m in queue_length_maps[~queue_length_maps.isnull()]]
            map_pairs = list(zip(cpu_cores_maps, queue_length_maps))

            for cpu_cores_map, queue_length_map in map_pairs:
                cpu_cores_map = json.loads(cpu_cores_map)
                queue_length_map = json.loads(queue_length_map)
                options['cpu_cores'] = cpu_cores_map
                options['queue_length'] = queue_length_map
                fig = self.create_fig(df, options)
                file_name = self.get_file_name(cpu_cores_map, queue_length_map)
                self.save_plot(fig, filename=file_name, output_dir=output_dir)
        
        def get_file_name(self, cpu_cores_map: Dict, queue_length_map: Dict) -> str:
            if cpu_cores_map['control_delta'] != queue_length_map['control_delta']:
                raise ValueError("control deltas do not match")
            
            control_delta = cpu_cores_map['control_delta']
            if self.val_key != "none":
                if cpu_cores_map[self.val_key] != queue_length_map[self.val_key]:
                    raise ValueError("changing values do not match")
                return f"controller_cores_{self.val_key}={cpu_cores_map[self.val_key]},control_delta={control_delta}"
            else:
                return f"controller_cores_control_delta={control_delta}"
        
        def distribute_points_equally(self, cores, time_ticks):
            num_intervals = len(time_ticks) - 1
            num_points = len(cores)

            # Generate indices of cores divided into equal groups for each interval
            interval_indices = np.linspace(0, num_points, num_intervals + 1, dtype=int)

            # New timestamps
            new_timestamps = np.zeros(num_points)
            for i in range(num_intervals):
                start_idx, end_idx = interval_indices[i], interval_indices[i + 1]
                if end_idx > start_idx:
                    new_timestamps[start_idx:end_idx] = np.linspace(time_ticks[i], time_ticks[i + 1], end_idx - start_idx)

            return new_timestamps.tolist()
        
        def create_fig(self, df: pd.DataFrame, options: Dict):
            set_fonts()
            
            fig, axs = plt.subplots(2, figsize=(12, 10))
            cores_yticks = list(range(0, 14, 2))

            cpu_core_map = options['cpu_cores']
            queue_length_map = options['queue_length']
            control_delta = cpu_core_map['control_delta']
            if self.val_key != "none":
                changing_value = cpu_core_map[self.val_key]

            cpu_core_map = { k: v for k, v in cpu_core_map.items() if k != 'control_delta' and k != self.val_key }
            queue_length_map = { k: v for k, v in queue_length_map.items() if k != 'control_delta' and k != self.val_key }

            df = df[df['control_delta'] == control_delta]
            if self.val_key != "none":
                df = df[df[self.val_key] == changing_value]

            # plot cores over time
            for engine_type, cores in cpu_core_map.items():
                timestamps = self.distribute_points_equally(cores, self.time_ticks)
                axs[0].plot(timestamps, cores, label=engine_type)

            # plot queue lengths over time
            for engine_type, queue_length in queue_length_map.items():
                timestamps = self.distribute_points_equally(queue_length, self.time_ticks)
                axs[1].plot(timestamps, queue_length, label=engine_type)

            rps_vals = df['rps'].unique()
            rps_vals = rps_vals[~np.isnan(rps_vals)]
            rps_vals = np.sort(rps_vals)
            line_spacing = len(queue_length) / 5 / len(rps_vals)
            for i in range(len(rps_vals)):
                axs[0].axvline(x=i * line_spacing, color='red', linestyle='--')
                axs[1].axvline(x=i * line_spacing, color='red', linestyle='--')
            
            if self.val_key != "none":
                axs[0].set_title(f"{self.val_key}={changing_value}; rps=[{rps_vals[0]}, {rps_vals[-1]}]")
            else:
                axs[0].set_title(f"rps=[{rps_vals[0]}, {rps_vals[-1]}]")
            
            axs[0].set_yticks(cores_yticks)
            axs[0].set_ylabel("Cores")
            axs[0].legend()

            axs[1].set_xlabel("Time (s)")
            axs[1].set_ylabel("Queue length")
            axs[1].legend()

            return fig

class ControllerLatencyBoxLoader(PlotLoader):

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        print(etl_info, options)
        print("loading controller latency")
        if df.empty:
            print("empty dataframe")
            return
        
        output_dir = self.get_output_dir(etl_info)
        options['output_dir'] = output_dir
        self.generate_boxplots(df, options)
    
    def generate_boxplots(self, df: pd.DataFrame, options: Dict):
        print("creating controller latency box plots")
        set_fonts()

        io_cores_unique = df['io_cores'].unique()
        io_cores_unique = io_cores_unique[~np.isnan(io_cores_unique)]
        io_cores_unique = np.sort(io_cores_unique)

        quantiles = [0.5, 0.9, 0.95, 0.99, 1.0]
        for quantile in quantiles:
            data = []

            for io_cores in io_cores_unique:
                key = 'latency_p' + str(int(quantile * 100))
                latencies = df[df['io_cores'] == io_cores][key][~np.isnan(df[key])]
                data.append(latencies)
            
            fig = self.create_fig(data, io_cores_unique, quantile)
            file_name = f"dynamic_allocator_box_latency_p{int(quantile * 100)}"
            self.save_plot(fig, filename=file_name, output_dir=options['output_dir'])
    
    def create_fig(self, data, io_cores_unique, quantile):
        print(f"creating controller latency box plot for p{int(quantile * 100)}")

        fig, axis = plt.subplots(figsize=(12, 10))
        x_labels = [f"{int(io_cores) if io_cores > 0 else 'dynamic'}" for io_cores in io_cores_unique]
        bp = axis.boxplot(data, labels=x_labels, showfliers=False)

        for _, median in enumerate(bp['medians']):
            x = (median.get_xdata()[0] + median.get_xdata()[1]) / 2
            y = median.get_ydata()[0]
            axis.text(x, y, f"{y:.2f}", ha='center', va='bottom', fontsize=12)

        axis.set_xlabel("IO cores")
        axis.set_ylabel("Latency [ms]")
        axis.set_title(f"Latency distribution middleware (p{int(quantile * 100)})")
        fig.tight_layout()
        return fig

class ControllerRpsExtractor(Extractor):

    rps_regex = re.compile("(.*)hot_([0-9]+)_rate\.csv")

    def default_file_regex():
        return [r".*\.csv$"]

    def extract_rps(self, path: str) -> int:
        rps_match = re.fullmatch(self.rps_regex, path)
        return int(rps_match[2])
    
    def extract(self, path: str, options: Dict) -> List[Dict]:
        return [{ "rps": self.extract_rps(path) }]

class ControllerLatencyCoreSweepExtractor(Extractor):

    latency_line_regex = re.compile("http://[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}:8080/(\w+)/(\w+),([0-9]+),([0-9]+),(\w+),(\w+),([0-9]{1,3})\n")

    def default_file_regex():
        return [r"latencies.*\.csv$"]
    
    def extract_latency(self, latency_line: str) -> int | None:
        current_latency = re.fullmatch(self.latency_line_regex, latency_line)
        if current_latency is not None:
            response_time = int(current_latency[4]) / 1000
            response_code = int(current_latency[7])
            return response_time if response_code == 200 else None
        else:
            return None
        
    def parse_config(self, input_file: str):
        while not os.path.exists(f"{input_file}/config.json"):
            input_file = os.path.dirname(input_file)
        with open(f"{input_file}/config.json", 'r') as file:
            config = json.load(file)
        return config
    
    def extract(self, path: str, options: Dict) -> List[Dict]:
        config = self.parse_config(path)
        io_cores = config['io_cores'] if not 'control_delta' in config else 0

        print(f"extracting {path}...")
        result = []
        with open(path) as latency_log:
            latencies = [self.extract_latency(latency_line) for latency_line in latency_log.readlines()[1:]]
            latencies = [lat for lat in latencies if lat is not None]
            lat_p50 = np.percentile(latencies, 50)
            lat_p90 = np.percentile(latencies, 90)
            lat_p95 = np.percentile(latencies, 95)
            lat_p99 = np.percentile(latencies, 99)
            lat_p100 = np.percentile(latencies, 100)
            latency_dict = {
                'latency_p50': lat_p50,
                'latency_p90': lat_p90,
                'latency_p95': lat_p95,
                'latency_p99': lat_p99,
                'latency_p100': lat_p100,
                'io_cores': io_cores,
            }
            result = [latency_dict]
        return result

        
class ControllerLatencyExtractor(Extractor):

    latency_line_regex = re.compile("http://[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}:8080/(\w+)/(\w+),([0-9]+),([0-9]+),(\w+),(\w+),([0-9]{1,3})\n")

    def default_file_regex():
        return [r"latencies.*\.csv$"]

    def extract_latency(self, latency_line: str) -> int | None:
        current_latency = re.fullmatch(self.latency_line_regex, latency_line)
        if current_latency is not None:
            return int(current_latency[4]) / 1000
        else:
            return None

    def extract(self, path: str, options: Dict) -> List[Dict]:
        print(f"extracting {path}...")
        result = []
        with open(path) as latency_log:
            result = [{ 'latency': self.extract_latency(latency_line) } for latency_line in latency_log.readlines()[1:]]
        return result

class MiddlewareLatencyExtractor(Extractor):

    rps: int
    
    def default_file_regex():
        return [r"latencies.*\.csv$"]

    def extract(self, path: str, options: Dict) -> List[Dict]:
        latency_log = open(path)
        path_parser = re.fullmatch("(.*)hot_([0-9]+)_rate\.csv", path)
        rps = int(path_parser[2])
        if rps != self.rps:
            return []
        end2end_list = []
        for index, latency_line in enumerate(latency_log.readlines()[1:]):
            current_latency = re.fullmatch("http://[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}:8080/(\w+)/(\w+),([0-9]+),([0-9]+),(\w+),(\w+),([0-9]{1,3})\n", latency_line)
            if current_latency is not None:
                # # check if timeout or other failure
                # if current_latency[5] == "true" or current_latency[6] == "true":
                end2end_list.append({'latency': int(current_latency[4]) / 1000})
            else:
                print(f"could not parse latency line for {path} at line {index + 1}")
        return end2end_list 

class MiddlewareLatencyPlotLoader(PlotLoader):

    rps: int

    def load(self, df: pd.DataFrame, options: Dict, etl_info: Dict) -> None:
        if not df.empty:
            figurename = f'middleware cdf {self.rps}rps'
            plt.rcParams.update({'font.size': 22})
            fig = self.create_fig(df, options)
            output_dir = self.get_output_dir(etl_info)
            file_name = figurename.replace(' ', '_').replace(":","_")
            self.save_plot(fig, filename=file_name, output_dir=output_dir)

    def create_fig(self, df, options):
        set_fonts()
        fig, axis = plt.subplots(figsize=(7, 6))

        grouped = df.groupby(['server'])
        for (group_name, group) in grouped:
            latency = group['latency']
            axis.ecdf(
                latency,
                label=LINE_DICT[group_name].name,
                color=LINE_DICT[group_name].color, 
                linestyle=LINE_DICT[group_name].linestyle,
            )

        axis.grid(True)
        axis.set_xscale('log')
        axis.set_yscale('close_to_one')
        axis.set_ylim((0, 0.999))

        axis.set_xlabel('latency [ms]')
        axis.set_ylabel('CDF')
    
        handles,labels = axis.get_legend_handles_labels()
        fig.legend(handles, labels, loc="upper left", bbox_to_anchor=(0.96, 0.9))
        fig.tight_layout()
        return fig