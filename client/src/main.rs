mod closed_loop;
mod file_writing;
mod generator;
mod open_loop;
mod rate_change;
mod registration;
mod request_type;

#[macro_use]
extern crate log;

use crate::{
    generator::ConstGen,
    registration::{check_service_ready, register_composition, FunctionId},
    request_type::RequestType,
};
use clap::{Parser, ValueEnum};
use reqwest::{Client, StatusCode};
use std::{
    fmt,
    io::Read,
    path::PathBuf,
    sync::{atomic::AtomicU32, Arc},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::runtime::Builder;

type Result<T> = core::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;

#[derive(Clone, Copy, ValueEnum, PartialEq)]
enum TargetType {
    Dedicated,
    DandelionProcess,
    DandelionRwasm,
    DandelionCheri,
    DandelionKvm,
    Firecracker,
    Wasmtime,
    Hyperlight,
}

impl fmt::Display for TargetType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let string_repr = match self {
            TargetType::Dedicated => "dedicated",
            TargetType::DandelionProcess => "dandelion-process",
            TargetType::DandelionRwasm => "dandelion-rwasm",
            TargetType::DandelionCheri => "dandelion-cheri",
            TargetType::DandelionKvm => "dandelion-kvm",
            TargetType::Firecracker => "firecracker",
            TargetType::Wasmtime => "wasmtime",
            TargetType::Hyperlight => "hyperlight",
        };
        write!(f, "{}", string_repr)
    }
}

// Dandelion specific
#[derive(Clone, Copy, ValueEnum)]
enum EngineType {
    Process,
    RWasm,
    Cheri,
    Kvm,
}

impl fmt::Display for EngineType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let string_repr = match self {
            EngineType::Process => "Process",
            EngineType::RWasm => "RWasm",
            EngineType::Cheri => "Cheri",
            EngineType::Kvm => "Kvm",
        };
        write!(f, "{}", string_repr)
    }
}

#[derive(Clone, Copy, ValueEnum, Parser, PartialEq)]
enum ExperimentModel {
    OpenLoop,
    OpenSweep,
    OpenAdaptive,
    ClosedUnloaded,
    ClosedPeak,
}

impl fmt::Display for ExperimentModel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.to_possible_value().unwrap().get_name())
    }
}

#[derive(Parser, Clone)]
struct Args {
    /// IP address to issue requests to
    #[arg(long, default_value_t = String::from("localhost"))]
    ip: String,

    /// For open loop: number of seconds to run
    /// For closed loop: number of measurements to collect per run
    #[arg(short, long = "duration", default_value_t = 1)]
    duration: u64,

    /// For open loop: number of requests per second to issue
    /// For closed loop: initial number of clients for peak finding
    #[arg(short, long = "rps", default_value_t = 1)]
    rate: u64,

    /// RPS increase step for sweep experiment.
    #[arg(long = "step-coarse", default_value_t = 50)]
    step_coarse: u64,

    /// RPS increase step for the fine-grained sweep
    #[arg(long = "step-fine", default_value_t = 10)]
    step_fine: u64,

    /// Request timeout in milliseconds
    #[arg(long, default_value_t = 10000)]
    request_timeout: u64,

    /// Service initialization timeout in seconds
    #[arg(long, default_value_t = 60)]
    service_timeout: u32,

    /// Disable warmup phase before measurement
    #[arg(long, default_value_t = true)]
    no_warmup: bool,

    /// Path to output results
    #[arg(long = "outputdir", default_value_t = String::from("."))]
    output_dir: String,

    /// Target platform to run
    #[arg(long = "target", default_value_t = TargetType::Dedicated)]
    target: TargetType,

    /// What kind of requests to send
    #[arg(long = "requestformat", default_value_t = RequestType::Matmul)]
    request_type: RequestType,

    /// The model of the experiment
    #[arg(long = "model", default_value_t = ExperimentModel::OpenLoop)]
    experiment_model: ExperimentModel,

    /// Path to binary that is to be registered as workload function
    #[arg(long)]
    workload_path: Option<PathBuf>,

    /// Size (N) of the NxN matrix to multiply / number of iterations to compute
    #[arg(long = "size", default_value_t = 128)]
    input_size: u64,

    /// Number of iterations to run the I/O busy loop for
    #[arg(long = "iterations", default_value_t = 2000000)]
    iterations: u64,

    #[arg(long = "chain-stages", default_value_t = 2)]
    chain_stages: usize,

    /// The IP of the HTTP storage server (used only for the composition experiment)
    #[arg(long = "storageip")]
    storage_ip: Option<String>,

    /// The average percentage of hot requests to issue
    #[arg(long = "hotpercent", default_value_t = 1.0)]
    hot_percent: f64,

    /// Number of cold copies of the worklaod function to register
    #[arg(long, default_value_t = 0)]
    cold_instances: u32,

    /// The amount of throughput degradation between steps that causes stopping the experiment
    #[arg(long = "degradation", default_value_t = 0.025)]
    significant_degradation: f32,

    /// Flag to enable the retrieval of the stats
    #[arg(long = "enable-server-stats", default_value_t = false)]
    get_server_stats: bool,

    /// Overwrite the size of context for Dandelion functions
    #[arg(long)]
    context_size: Option<u64>,

    /// Path to CSV file that specifies changes in RPS over time (only in OpenLoop model)
    #[arg(long)]
    trace_path: Option<PathBuf>,
}

impl Args {
    fn record_stats(&self) -> bool {
        return self.get_server_stats
            && (self.target == TargetType::DandelionProcess
                || self.target == TargetType::DandelionRwasm
                || self.target == TargetType::DandelionCheri
                || self.target == TargetType::DandelionKvm
                || self.target == TargetType::Wasmtime
                || self.target == TargetType::Hyperlight
                || self.target == TargetType::Dedicated);
    }
}

struct HotGenerator {
    hot_rate: u32,
    request_counter: AtomicU32,
}

impl HotGenerator {
    fn new(hot_percent: f64) -> Self {
        assert!(hot_percent >= 0.0);
        assert!(hot_percent <= 1.0);
        let hot_rate = match hot_percent {
            x if x >= 1.0 => u32::MAX,
            x if x <= 0.0 => u32::MIN,
            x => (f64::from(u32::MAX) * x) as u32,
        };
        Self {
            hot_rate,
            request_counter: AtomicU32::new(rand::random()),
        }
    }

    fn next(&self) -> bool {
        let old_request_counter = self
            .request_counter
            .fetch_add(self.hot_rate, std::sync::atomic::Ordering::SeqCst);
        let (_, hot) = old_request_counter.overflowing_add(self.hot_rate);
        return hot;
    }
}

#[derive(Debug)]
struct Record {
    start: SystemTime,
    end: SystemTime,
    url: String,
    timeout: bool,
    error: bool,
    status: Option<StatusCode>,
}

impl Record {
    fn start_time(&self) -> Duration {
        self.start.duration_since(UNIX_EPOCH).unwrap()
    }

    fn duration(&self) -> Duration {
        self.end.duration_since(self.start).unwrap()
    }
}

struct BenchLog {
    records: Vec<Record>,
    timeouts: usize,
    errors: usize,
    earliest_start: Duration,
    last_finish: Duration,
}

impl BenchLog {
    fn new(num_records: usize) -> Self {
        Self {
            records: Vec::with_capacity(num_records),
            timeouts: 0,
            errors: 0,
            earliest_start: Duration::from_secs(u64::MAX),
            last_finish: Duration::from_secs(u64::MIN),
        }
    }

    fn add_record(&mut self, record: Record) {
        if record.timeout {
            self.timeouts += 1;
        }
        if record.error {
            self.errors += 1;
        }
        let start_time = record.start_time();
        let end_time = start_time + record.duration();
        if start_time < self.earliest_start {
            self.earliest_start = start_time;
        }
        if end_time > self.last_finish {
            self.last_finish = end_time;
        }
        self.records.push(record);
    }

    fn total(&self) -> usize {
        self.records.len()
    }

    fn errors(&self) -> usize {
        self.timeouts + self.errors
    }

    /// Calculate the latency percentiles.
    /// The input arugments should be in the range of (0.0, 100.0)
    fn latencies(&self, percentages: &[f64]) -> Vec<Duration> {
        let mut latency: Vec<_> = self.records.iter().map(|t| t.duration()).collect();
        latency.sort();
        percentages
            .iter()
            .map(|p| {
                latency
                    .get(((latency.len() as f64 * p - 1.0) / 100.0) as usize)
                    .cloned()
                    .unwrap_or_default()
            })
            .collect()
    }

    fn duration(&self) -> f64 {
        return (self.last_finish - self.earliest_start).as_secs_f64();
    }
}

fn main() -> Result<()> {
    env_logger::init();
    let args = Args::parse();
    let rt = Builder::new_multi_thread().enable_all().build()?;
    rt.block_on(tokio_main(args))
}

// #[tokio::main]
async fn tokio_main(args: Args) -> Result<()> {
    let matrix_data = match args.request_type {
        RequestType::Matmul => {
            let mut matrix_data = Vec::new();
            matrix_data.extend_from_slice(&i64::to_le_bytes(args.input_size as i64));
            for i in 0..(args.input_size * args.input_size) {
                matrix_data.extend_from_slice(&i64::to_le_bytes(i as i64 + 1));
            }
            matrix_data
        }
        RequestType::CompressionApp => {
            let mut path = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
            path.push("data/dnd8won.qoi");
            let mut picture_file = std::fs::File::open(path).unwrap();
            let mut picture_buf = Vec::new();
            let _ = picture_file.read_to_end(&mut picture_buf).unwrap();
            picture_buf
        }
        _ => Vec::new(),
    };

    let expected_checksum = args.request_type.checksum(args.input_size, args.iterations);

    let client = Client::builder()
        .timeout(Duration::from_millis(args.request_timeout))
        .build()
        .unwrap();

    if args.cold_instances == 0 && args.hot_percent < 1.0 {
        panic!("Registering 0 cold instances for non pure hot experiment");
    }

    // ensure the server is ready
    check_service_ready(&client, &args.ip, 8080, args.service_timeout).await;
    // ensure the storage is ready
    if let Some(ref storage_ip) = args.storage_ip {
        check_service_ready(&client, &storage_ip, 8000, args.service_timeout).await;
    }

    let compositon_id = FunctionId::new(
        format!("composition_{}", &args.request_type.to_string_nohyphen()),
        args.cold_instances,
    );

    // Dandelion specific setup
    if matches!(
        args.target,
        TargetType::DandelionCheri
            | TargetType::DandelionProcess
            | TargetType::DandelionRwasm
            | TargetType::DandelionKvm
    ) {
        let engine_type = match args.target {
            TargetType::DandelionProcess => EngineType::Process,
            TargetType::DandelionRwasm => EngineType::RWasm,
            TargetType::DandelionCheri => EngineType::Cheri,
            TargetType::DandelionKvm => EngineType::Kvm,
            _ => unreachable!(),
        };

        if let Some(ref workload_path) = args.workload_path {
            let context_size = if let RequestType::IoScale
            | RequestType::IoScaleHybrid
            | RequestType::ChainScaling
            | RequestType::ChainScalingDedicated = args.request_type
            {
                // context size needs to be bigger than input + some margin
                Some(args.input_size + 0x10_0000)
            } else {
                args.context_size
            };
            register_composition(
                &client,
                &args.ip,
                &args.request_type,
                engine_type,
                workload_path,
                &compositon_id,
                args.chain_stages,
                &args.storage_ip,
                context_size,
            )
            .await;
        } else {
            log::info!("No workload path, skipping function registration");
        }
    }

    let mut pretest_args = args.clone();
    pretest_args.duration = 1000;
    let experiment_timeout = if args.experiment_model == ExperimentModel::OpenAdaptive {
        match closed_loop::run_closed_loop_n_clients(
            &pretest_args,
            &compositon_id.fresh_copy(),
            &client,
            &matrix_data,
            expected_checksum,
            1,
        )
        .await
        {
            Ok((_, log)) => log.latencies(&[100.0])[0] * 10,
            Err(e) => panic!("basline measuremt failed with {}", e),
        }
    } else {
        Duration::from_millis(args.request_timeout)
    };

    let experiment_client = Client::builder()
        .timeout(experiment_timeout)
        .build()
        .unwrap();

    match args.experiment_model {
        ExperimentModel::OpenLoop => {
            let rps = args.rate;
            match open_loop::run_open_loop(
                args,
                rps,
                experiment_client,
                Arc::new(compositon_id.fresh_copy()),
                expected_checksum,
                matrix_data.clone(),
            )
            .await
            {
                Ok(_) => Ok(()),
                Err(e) => {
                    error!("Error: {}", e);
                    Err(e)
                }
            }
        }
        ExperimentModel::OpenSweep => {
            let mut last_good_rps: u64 = 0;
            let max_failed_percentage = 0.01;
            let rates = (args.step_coarse..).step_by(args.step_coarse as usize);
            let mut median_latency = 0;
            // Step coarse
            for rps in rates {
                let (total, errors, median) = open_loop::run_open_loop(
                    args.clone(),
                    rps,
                    experiment_client.clone(),
                    Arc::new(compositon_id.fresh_copy()),
                    expected_checksum,
                    matrix_data.clone(),
                )
                .await?;
                info!("Sleeping for {}s", args.request_timeout / 1000);
                tokio::time::sleep(Duration::from_millis(args.request_timeout)).await;

                // set 50% latency check to stop when queuing starts
                if rps == args.step_coarse {
                    median_latency = median;
                } else if median_latency * 10 < median {
                    println!(
                        "Median latency {}, exceeds order of magnitude more than unloaded {}",
                        median, median_latency
                    );
                    break;
                }

                // Check if more than X% of requests failed
                if errors as f64 / total as f64 > max_failed_percentage {
                    println!(
                        "Out of {} requests, {} failed, stopping sweep at {} rps",
                        total, errors, rps
                    );
                    break;
                }
                last_good_rps = rps
            }

            // Step fine
            let start_rps_fine: u64 = last_good_rps + args.step_fine;
            let end_rps_fine: u64 = last_good_rps + args.step_coarse;
            println!(
                "Starting fine-grained sweep from {} to {} rps",
                start_rps_fine, end_rps_fine
            );

            let fine_rates = (start_rps_fine..end_rps_fine).step_by(args.step_fine as usize);
            for rps in fine_rates {
                let (total, errors, median) = open_loop::run_open_loop(
                    args.clone(),
                    rps,
                    experiment_client.clone(),
                    Arc::new(compositon_id.fresh_copy()),
                    expected_checksum,
                    matrix_data.clone(),
                )
                .await?;
                info!("Sleeping for {}s", args.request_timeout / 1000);
                tokio::time::sleep(Duration::from_millis(args.request_timeout)).await;

                // set 50% latency check to stop when queuing starts
                if rps == args.step_fine {
                    median_latency = median;
                } else if median_latency * 10 < median {
                    println!(
                        "Median latency {}, exceeds order of magnitude more than unloaded {}",
                        median, median_latency
                    );
                    break;
                }

                // Check if more than X% of requests failed
                if errors as f64 / total as f64 > max_failed_percentage {
                    println!(
                        "Out of {} requests, {} failed, stopping sweep at {} rps",
                        total, errors, rps
                    );
                    break;
                }
            }

            Ok(())
        }

        ExperimentModel::OpenAdaptive => {
            let mut last_good_rps = args.step_fine;
            let mut last_bad_rps;
            let mut rps = args.step_fine;
            let max_failed_percentage = 0.01;
            // find last bad with exponential increasing steps
            loop {
                let (total, errors, _) = open_loop::run_open_loop(
                    args.clone(),
                    rps,
                    experiment_client.clone(),
                    Arc::new(compositon_id.fresh_copy()),
                    expected_checksum,
                    matrix_data.clone(),
                )
                .await?;
                info!("Sleeping for {}s", args.request_timeout / 100);
                tokio::time::sleep(Duration::from_millis(args.request_timeout * 10)).await;

                // Check if more than X% of requests failed
                if errors as f64 / total as f64 > max_failed_percentage {
                    println!(
                        "Out of {} requests, {} failed, stopping sweep at {} rps",
                        total, errors, rps
                    );
                    last_bad_rps = rps;
                    break;
                }
                last_good_rps = rps;
                rps = 2 * rps;
            }
            while last_good_rps + args.step_fine < last_bad_rps {
                let rps = last_good_rps
                    + std::cmp::max(args.step_fine, (last_bad_rps - last_good_rps) / 2);
                if let Ok((total, errors, _)) = open_loop::run_open_loop(
                    args.clone(),
                    rps,
                    experiment_client.clone(),
                    Arc::new(compositon_id.fresh_copy()),
                    expected_checksum,
                    matrix_data.clone(),
                )
                .await
                {
                    // Check if more than X% of requests failed
                    if errors as f64 / total as f64 > max_failed_percentage {
                        println!(
                            "Out of {} requests, {} failed, stopping sweep at {} rps",
                            total, errors, rps
                        );
                        last_bad_rps = rps;
                    } else {
                        last_good_rps = rps;
                    }
                } else {
                    last_bad_rps = rps;
                }
            }
            // make sure all requests on the server had time to get flushed out
            info!("Sleeping for {}s", args.request_timeout / 100);
            tokio::time::sleep(Duration::from_millis(args.request_timeout * 10)).await;

            Ok(())
        }

        ExperimentModel::ClosedPeak | ExperimentModel::ClosedUnloaded => {
            match closed_loop::run_closed_loop(
                args,
                experiment_client,
                compositon_id.fresh_copy(),
                expected_checksum,
                matrix_data,
            )
            .await
            {
                Ok(_) => Ok(()),
                Err(e) => {
                    error!("Error: {}", e);
                    Err(e)
                }
            }
        }
    }
}
