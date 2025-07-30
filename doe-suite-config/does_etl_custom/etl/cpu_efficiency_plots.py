from doespy.etl.steps.extractors import Extractor
from doespy.etl.steps.transformers import Transformer
from doespy.etl.steps.loaders import Loader, PlotLoader

import pandas as pd
from typing import Dict, List, Tuple
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

class LineStyle:
    def __init__(self, name, marker, color, linestyle='solid'):
        self.name = name
        self.marker = marker
        self.color = color
        self.linestyle = linestyle

LINE_DICT = {
    'middleware-app-hybrid (pin=false,tpc=1)': LineStyle('HB-hybrid (tpc=1)', '^', 'tab:blue', 'dashed'),
    'middleware-app-hybrid (pin=false,tpc=2)': LineStyle('HB-hybrid (tpc=2)', 'D', 'tab:orange', 'dashed'),
    'middleware-app-hybrid (pin=false,tpc=3)': LineStyle('HB-hybrid (tpc=3)', 'v', 'darkkhaki', 'dashed'),
    'middleware-app-hybrid (pin=false,tpc=4)': LineStyle('HB-hybrid (tpc=4)', '<', 'gold', 'dashed'),
    'middleware-app-hybrid (pin=false,tpc=5)': LineStyle('HB-hybrid (tpc=5)', '>', 'darkorange', 'dashdot'),
    'middleware-app-hybrid (pin=false,tpc=6)': LineStyle('HB-hybrid (tpc=6)', 's', 'tab:brown', 'dashed'),
    'middleware-app-hybrid (pin=false,tpc=7)': LineStyle('HB-hybrid (tpc=7)', 'o', 'tab:pink', 'dashed'),
    'middleware-app-hybrid (pin=false,tpc=8)': LineStyle('HB-hybrid (tpc=8)', '*', 'tab:gray', 'dashed'),
    'middleware-app-hybrid (pin=true,tpc=1)': LineStyle('HB-hybrid (tpc=1,pin)', '*', 'blue', 'dotted'),
    'middleware-app-hybrid (pin=true,tpc=2)': LineStyle('HB-hybrid (tpc=2,pin)', '>', 'tab:orange', 'dotted'),
    'middleware-app-hybrid (pin=true,tpc=3)': LineStyle('HB-hybrid (tpc=3,pin)', 'v', 'tab:green', 'dotted'),
    'middleware-app-hybrid (pin=true,tpc=4)': LineStyle('HB-hybrid (tpc=4,pin)', '<', 'tab:red', 'dotted'),
    'middleware-app-hybrid (pin=true,tpc=5)': LineStyle('HB-hybrid (tpc=5,pin)', 'D', 'tab:purple', 'dotted'),
    'middleware-app-hybrid (pin=true,tpc=6)': LineStyle('HB-hybrid (tpc=6,pin)', 's', 'tab:brown', 'dotted'),
    'middleware-app-hybrid (pin=true,tpc=7)': LineStyle('HB-hybrid (tpc=7,pin)', 'o', 'tab:pink', 'dotted'),
    'middleware-app-hybrid (pin=true,tpc=8)': LineStyle('HB-hybrid (tpc=8,pin)', '*', 'tab:gray', 'dotted'),
    'middleware-app (io_cores=2)': LineStyle('split (io cores=2)', 'v', 'darkgreen'),
    'middleware-app (io_cores=3)': LineStyle('split (io cores=3)', '>', 'forestgreen'),
    'middleware-app (io_cores=4)': LineStyle('split (io cores=4)', '>', 'darkgreen', 'dotted'),
    'middleware-app (io_cores=5)': LineStyle('split (io cores=5)', 'D', 'cornflowerblue', 'dotted'),
    'middleware-app (io_cores=6)': LineStyle('split (io cores=6)', 's', 'darkblue', 'dashed'),
    'middleware-app (controller)': LineStyle('HB', 'P', 'forestgreen'),
    }

CPU_LINE_DICT = {
    'enable_cpu_pinning: true': LineStyle('with CPU Pinning', '^', 'darkorange'),
    'enable_cpu_pinning: false': LineStyle('without CPU Pinning', 'v', 'darkgreen'),
    }

def set_fonts():
    SMALL_SIZE = 16
    MEDIUM_SIZE = 28
    BIGGER_SIZE = 28

    plt.rc('font', size=MEDIUM_SIZE)          # controls default text sizes
    plt.rc('axes', titlesize=MEDIUM_SIZE)     # fontsize of the axes title
    plt.rc('axes', labelsize=MEDIUM_SIZE)    # fontsize of the x and y labels
    plt.rc('xtick', labelsize=MEDIUM_SIZE)    # fontsize of the tick labels
    plt.rc('ytick', labelsize=MEDIUM_SIZE)    # fontsize of the tick labels
    plt.rc('legend', fontsize=MEDIUM_SIZE)    # legend fontsize
    plt.rc('figure', titlesize=BIGGER_SIZE)  # fontsize of the figure title


class HybridLatencyPlotLoader(PlotLoader):
    
    def load(self, df: pd.DataFrame, options: Dict,  etl_info: Dict) -> None:
        percentiles = [50, 90, 95, 99]
        if not df.empty:
            for percentile in percentiles:
                # figurename = f"hybrid (multi-thread, no cpu pinning) latency P{percentile}"
                figurename = f"hybrid (w/wo CPU Pinning) (P{percentile})"
                plt.rcParams.update({'font.size': True})
                fig = self.create_fig(df, options, percentile, figurename)
                output_dir = self.get_output_dir(etl_info)
                file_name = figurename.replace(' ', '_').replace("/","_")
                self.save_plot(fig, filename=file_name, output_dir=output_dir)

    def create_fig(self, df, options, percentile, figure_name):
        set_fonts()
        fig,axis = plt.subplots(figsize=(9,6))
        df=df[ df['total_failures'] / df['total_requests'] < 0.005]
        # df=df[ df['enable_cpu_pinning'] == 'true']

        x_col_name = 'rps'
        y_col_name = f'latency_p{percentile:3d}'
        grouped = df.groupby('enable_cpu_pinning')
        for (group_name, group) in grouped:
            group.sort_values(x_col_name, ignore_index=True, inplace=True)
            x_data = group[x_col_name]
            y_data = group[y_col_name]
            label = f"enable_cpu_pinning: {group_name}"
            axis.plot(x_data,
                      y_data, 
                      # yerr=[y_err_low, y_err_high],
                      label=CPU_LINE_DICT[label].name,
                      marker=CPU_LINE_DICT[label].marker,
                      color=CPU_LINE_DICT[label].color,
                      linestyle=CPU_LINE_DICT[label].linestyle,
                      )
        axis.grid(True)
        axis.set_xlabel('RPS')
        axis.set_ylabel(f"Latency P{percentile} (ms)")
        axis.set_xlim(left=0)
        axis.legend(loc='upper left')
        axis.set_title(figure_name)

        fig.tight_layout()
        return fig

class HybridvsSplitLatencyPlotLoader(PlotLoader):
    
    def load(self, df: pd.DataFrame, options: Dict,  etl_info: Dict) -> None:
        percentiles = [50, 90, 95, 99]
        if not df.empty:
            for percentile in percentiles:
                for(delay, delay_group) in df.groupby('delay'):
                    if delay == 0:
                        continue
                    figurename = f"hybrid vs. split (P{percentile}) delay={delay/1000}"
                    # figurename = f"matmul P{percentile}"
                    # figurename = f"ioscale P{percentile} delay={delay/1000}"
                    plt.rcParams.update({'font.size': True})
                    fig = self.create_fig(delay_group, options, percentile, figurename)
                    output_dir = self.get_output_dir(etl_info)
                    file_name = figurename.replace(' ', '_').replace(":","_")
                    self.save_plot(fig, filename=file_name, output_dir=output_dir)

    def create_fig(self, df, options, percentile, figure_name):
        set_fonts()
        fig,axis = plt.subplots(figsize=(12,8))
        df=df[ df['total_failures'] / df['total_requests'] < 0.005]
        # df=df[ df['rps'] < 3000]
        # df=df[ df['enable_cpu_pinning'] == 'true']
        # drop hybrid that has more I/O cores
        # df=df[((df['function'] == 'middleware-app-hybrid') & (df['io_cores'] == 2)) | (df['function'] == 'middleware-app')]

        x_col_name = 'rps'
        y_col_name = f'latency_p{percentile:3.1f}'
        max_y = 100
        # add lines for split
        # split_df = df[df['exp_name'] == 'cpu_efficiency_split']
        # cores_grouped = split_df.groupby('io_cores')
        # for (core_group_name, core_group) in cores_grouped:
        #     core_group.sort_values(x_col_name, ignore_index=True, inplace=True)
        #     x_data = core_group[x_col_name]
        #     y_data = core_group[y_col_name]
        #     # y_err_low = subgroup['latency_p 50'] - subgroup['latency_p  5']
        #     # y_err_high = subgroup['latency_p 95'] - subgroup['latency_p 50']
        #     label = f"middleware-app (io_cores={int(core_group_name)})"
        #     axis.plot(x_data, 
        #                 y_data, 
        #                 # yerr=[y_err_low, y_err_high],
        #                 label=LINE_DICT[label].name,
        #                 marker=LINE_DICT[label].marker,
        #                 markersize=10,
        #                 color=LINE_DICT[label].color,
        #                 linestyle=LINE_DICT[label].linestyle,
        #                 linewidth=3
        #                 )
        # add lines for controller
        controller_df = df[df['exp_name'] == 'middleware_controller'].copy()
        # controller_df = df[df['exp_name'] == 'schedule_split'].copy()
        controller_df.sort_values(x_col_name, ignore_index=True, inplace=True)
        x_data = controller_df[x_col_name]
        new_x_series = pd.Series(data={x_data.size: x_data.iat[x_data.size-1]+1})
        x_data = pd.concat([x_data, new_x_series])
        # y_data = controller_df[y_col_name]
        y_data = pd.concat([controller_df[y_col_name], pd.Series(data={x_data.size: 2*max_y})])

        # y_err_low = subgroup['latency_p 50'] - subgroup['latency_p  5']
        # y_err_high = subgroup['latency_p 95'] - subgroup['latency_p 50']
        label = f"middleware-app (controller)"
        axis.plot(x_data, 
                    y_data, 
                    # yerr=[y_err_low, y_err_high],
                    label=LINE_DICT[label].name,
                    marker=LINE_DICT[label].marker,
                    markersize=10,
                    color=LINE_DICT[label].color,
                    linestyle=LINE_DICT[label].linestyle,
                    linewidth=3,
                    markevery=2,
                    )
        
        # add lines for hybrid
        hybrid_df = df[(df['exp_name'] == 'cpu_efficiency_hybrid') | (df['exp_name'] == 'cpu_efficiency_hybrid_multithread')]
        # hybrid_df = df[df['exp_name'] == 'schedule_hybrid']
        hybrid_grouped = hybrid_df.groupby(['enable_cpu_pinning', 'threads_per_core'])
        for (hybrid_group_name, hybrid_group) in hybrid_grouped:
            hybrid_group.sort_values(x_col_name, ignore_index=True, inplace=True)
            x_data = hybrid_group[x_col_name]
            new_x_series = pd.Series(data={x_data.size: x_data.iat[x_data.size-1]+1})
            x_data = pd.concat([x_data, new_x_series])
            # y_data = hybrid_group[y_col_name]
            y_data = pd.concat([hybrid_group[y_col_name], pd.Series(data={x_data.size: 2*max_y})])

            if hybrid_group_name[0] == 'true':
                continue
            # y_err_low = subgroup['latency_p 50'] - subgroup['latency_p  5']
            # y_err_high = subgroup['latency_p 95'] - subgroup['latency_p 50']
            label = f"middleware-app-hybrid (pin={hybrid_group_name[0]},tpc={int(hybrid_group_name[1])})"
            axis.plot(x_data, 
                        y_data, 
                        # yerr=[y_err_low, y_err_high],
                        label=LINE_DICT[label].name,
                        marker=LINE_DICT[label].marker,
                        markersize=10,
                        color=LINE_DICT[label].color,
                        linestyle=LINE_DICT[label].linestyle,
                        linewidth=3,
                        markevery=2,
                        )       
        axis.grid(True)
        axis.set_xlabel('RPS')
        axis.set_ylabel(f"Latency P{percentile} (ms)")
        axis.set_xlim(left=0)
        axis.set_ylim(bottom=0,top=max_y)
        # axis.set_yscale('log')
        axis.legend(loc='lower center', ncols=2, bbox_to_anchor=(0.5, 1.02))
        # axis.set_title(figure_name)

        fig.tight_layout()
        return fig

class HybridvsSplitLatencyUnifiedPlotLoader(PlotLoader):
    
    def load(self, df: pd.DataFrame, options: Dict,  etl_info: Dict) -> None:
        percentiles = [99]
        if not df.empty:
            for percentile in percentiles:
                for(delay, delay_group) in df.groupby('delay'):
                    if delay == 0:
                        continue
                    figurename = f"hybrid vs. split (P{percentile}) delay={delay/1000}"
                    plt.rcParams.update({'font.size': True})
                    fig = self.create_fig(delay_group, options, percentile, figurename)
                    output_dir = self.get_output_dir(etl_info)
                    file_name = figurename.replace(' ', '_').replace(":","_")
                    self.save_plot(fig, filename=file_name, output_dir=output_dir)

    def create_fig(self, df, options, percentile, figure_name):
        set_fonts()
        fig,axes = plt.subplots(nrows=2, figsize=(12,12))
        df=df[ df['total_failures'] / df['total_requests'] < 0.005]

        x_col_name = 'rps'
        y_col_name = f'latency_p{percentile:3.1f}'


        max_y = 15
        # add lines for controller
        controller_df = df[(df['exp_name'] == 'schedule_split') & (df['function'] == 'matmul')].copy()
        controller_df.sort_values(x_col_name, ignore_index=True, inplace=True)
        x_data = controller_df[x_col_name]
        new_x_series = pd.Series(data={x_data.size: x_data.iat[x_data.size-1]+1})
        x_data = pd.concat([x_data, new_x_series])
        y_data = pd.concat([controller_df[y_col_name], pd.Series(data={x_data.size: 2*max_y})])

        label = f"middleware-app (controller)"
        axes[0].plot(x_data, 
                    y_data, 
                    label=LINE_DICT[label].name,
                    marker=LINE_DICT[label].marker,
                    markersize=10,
                    color=LINE_DICT[label].color,
                    linestyle=LINE_DICT[label].linestyle,
                    linewidth=3,
                    # markevery=2,
                    )
        
        # add lines for hybrid
        hybrid_df = df[(df['exp_name'] == 'schedule_hybrid') & (df['function'] == 'matmul')]
        hybrid_grouped = hybrid_df.groupby(['enable_cpu_pinning', 'threads_per_core'])
        for (hybrid_group_name, hybrid_group) in hybrid_grouped:
            if hybrid_group_name[0] == 'true' and hybrid_group_name[1] != 1:
                continue
            if hybrid_group_name[0] == 'false' and hybrid_group_name[1] not in [3,4,5]:
                continue

            hybrid_group.sort_values(x_col_name, ignore_index=True, inplace=True)
            x_data = hybrid_group[x_col_name]
            new_x_series = pd.Series(data={x_data.size: x_data.iat[x_data.size-1]+1})
            x_data = pd.concat([x_data, new_x_series])
            y_data = pd.concat([hybrid_group[y_col_name], pd.Series(data={x_data.size: 2*max_y})])

            label = f"middleware-app-hybrid (pin={hybrid_group_name[0]},tpc={int(hybrid_group_name[1])})"
            axes[0].plot(x_data, 
                        y_data, 
                        label=LINE_DICT[label].name,
                        marker=LINE_DICT[label].marker,
                        markersize=10,
                        color=LINE_DICT[label].color,
                        linestyle=LINE_DICT[label].linestyle,
                        linewidth=3,
                        # markevery=2,
                        )       
        axes[0].grid(True)
        # axes[0].set_xlabel('RPS')
        axes[0].set_ylabel(f"p{percentile} latency [ms]")
        axes[0].set_xlim(left=0)
        axes[0].set_ylim(bottom=0,top=max_y)
        axes[0].set_title('matrix multiplication', y=0.85)


        max_y = 80
        # add lines for controller
        controller_df = df[(df['exp_name'] == 'schedule_split') & (df['function'] == 'io-scale')].copy()
        controller_df.sort_values(x_col_name, ignore_index=True, inplace=True)
        x_data = controller_df[x_col_name]
        new_x_series = pd.Series(data={x_data.size: x_data.iat[x_data.size-1]+1})
        x_data = pd.concat([x_data, new_x_series])
        y_data = pd.concat([controller_df[y_col_name], pd.Series(data={x_data.size: 2*max_y})])

        label = f"middleware-app (controller)"
        axes[1].plot(x_data, 
                    y_data, 
                    label=LINE_DICT[label].name,
                    marker=LINE_DICT[label].marker,
                    markersize=10,
                    color=LINE_DICT[label].color,
                    linestyle=LINE_DICT[label].linestyle,
                    linewidth=3,
                    # markevery=2,
                    )
        
        # add lines for hybrid
        hybrid_df = df[(df['exp_name'] == 'schedule_hybrid') & (df['function'] == 'io-scale-hybrid')]
        hybrid_grouped = hybrid_df.groupby(['enable_cpu_pinning', 'threads_per_core'])
        for (hybrid_group_name, hybrid_group) in hybrid_grouped:
            if hybrid_group_name[0] == 'true' and hybrid_group_name[1] != 1:
                continue
            if hybrid_group_name[0] == 'false' and hybrid_group_name[1] not in [3,4,5]:
                continue

            hybrid_group.sort_values(x_col_name, ignore_index=True, inplace=True)
            x_data = hybrid_group[x_col_name]
            new_x_series = pd.Series(data={x_data.size: x_data.iat[x_data.size-1]+1})
            x_data = pd.concat([x_data, new_x_series])
            y_data = pd.concat([hybrid_group[y_col_name], pd.Series(data={x_data.size: 2*max_y})])

            label = f"middleware-app-hybrid (pin={hybrid_group_name[0]},tpc={int(hybrid_group_name[1])})"
            axes[1].plot(x_data, 
                        y_data, 
                        label=LINE_DICT[label].name,
                        marker=LINE_DICT[label].marker,
                        markersize=10,
                        color=LINE_DICT[label].color,
                        linestyle=LINE_DICT[label].linestyle,
                        linewidth=3,
                        # markevery=2,
                        )       
        axes[1].grid(True)
        axes[1].set_xlabel('RPS')
        axes[1].set_ylabel(f"p{percentile} latency [ms]")
        axes[1].set_xlim(left=0)
        axes[1].set_ylim(bottom=0,top=max_y)
        axes[1].set_title('fetch and compute', y=0.85)


        axes[0].legend(loc='lower center', ncols=2, bbox_to_anchor=(0.45, 1.02))
        # axes[1].legend(loc='lower center', ncols=2, bbox_to_anchor=(0.5, -1.02))
        # handles,labels = axes.get_legend_handles_labels()
        # fig.legend(handles, labels, loc="lower center", ncols=2, bbox_to_anchor=(0.5, -0.2))
        # axis.set_title(figure_name)

        fig.tight_layout()
        return fig


class WorkerQueueLatencyComparisonPlotLoader(PlotLoader):

    def load(self, df: pd.DataFrame, options: Dict,  etl_info: Dict) -> None:
        percentiles = [5, 50, 90, 95, 99]
        if not df.empty:
            df=df[ df['total_failures'] / df['total_requests'] < 0.005]
            df=df[ df['rps'] < 3000]
            for percentile in percentiles:
                figurename = f"Worker Priority Results(P{percentile}, matmul 128*128)"
                plt.rcParams.update({'font.size': True})
                fig = self.create_fig(df, options, percentile, figurename)
                output_dir = self.get_output_dir(etl_info)
                file_name = figurename.replace(' ', '_').replace(":","_")
                self.save_plot(fig, filename=file_name, output_dir=output_dir)
    
    def create_fig(self, df, options, percentile, figure_name):
        set_fonts()
        fig,axis = plt.subplots(figsize=(9,6))
        # Define color palette for different suites
        colors = plt.cm.Paired(range(len(df['suite_name'].unique())))
        rps_categories = sorted(df['rps'].unique())
        n_suites = len(df['suite_name'].unique())
        offset = 0.2

        x_col_name = 'rps'
        y_col_name = f'latency_p{percentile:3d}'
        for idx, (suite_name, group) in enumerate(df.groupby('suite_name')):
            # x_values = sorted(group[x_col_name].unique())
            y_data = [group[group[x_col_name] == x][y_col_name].dropna() for x in rps_categories]

            positions = [i + (idx - n_suites/2) * offset for i in range(len(rps_categories))]
            axis.boxplot(y_data, 
                         positions=positions, 
                         widths=0.15, 
                         patch_artist=True,
                         boxprops=dict(facecolor=colors[idx], alpha=0.7),
                         medianprops=dict(color="black"),
                         flierprops=dict(marker='o', color='red', alpha=0.5),
                        #  labels=[str(x) for x in x_values] if idx == 0 else None
                         )

        axis.set_xticks(range(len(rps_categories)))
        axis.set_xticklabels(rps_categories, rotation=45)
        axis.set_xlabel("RPS")
        axis.set_ylabel(f"Latency P{percentile} (ms)")
        axis.grid(True, linestyle="--", alpha=0.6)
        axis.set_title(figure_name)

        legend_elements = [
        Line2D([0], [0], color=colors[i], marker='s', markersize=10, linestyle='None', label=suite_name)
            for i, suite_name in enumerate(df['suite_name'].unique())
        ]
        axis.legend(handles=legend_elements, loc="upper left")

        fig.tight_layout()
        return fig