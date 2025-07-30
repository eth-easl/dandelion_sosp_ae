use crate::{
    file_writing, rate_change, Args, BenchLog, Client, ConstGen, FunctionId, HotGenerator, Record,
    Result,
};
use std::{
    sync::Arc,
    time::{Instant, SystemTime},
};
use tokio::sync::mpsc::{self, error::TrySendError};

const RATE_INC_PER_SEC: u64 = 1000;
const REQ_ISSUE_SLACK_S: f64 = 0.100;

pub async fn run_open_loop(
    args: Args,
    rps: u64,
    client: Client,
    function_id: Arc<FunctionId>,
    expected_response: (u64, usize),
    matrix_data: Vec<u8>,
) -> Result<(usize, usize, u128)> {
    let hot_gen = HotGenerator::new(args.hot_percent);
    let mut rate_per_sec = if args.no_warmup {
        vec![]
    } else {
        (RATE_INC_PER_SEC..rps)
            .step_by(RATE_INC_PER_SEC as usize)
            .collect()
    };
    let num_warmup = rate_per_sec.iter().sum::<u64>() as usize;
    if let Some(trace_path) = &args.trace_path {
        rate_per_sec.extend_from_slice(&rate_change::load_rps(trace_path, args.duration).unwrap());
    } else {
        rate_per_sec.extend(std::iter::repeat(rps).take(args.duration as usize));
    }

    let starts = ConstGen::new(rate_per_sec);
    let mut bench_log = BenchLog::new(starts.expected_len() + 1);
    let (tx, mut rx) = mpsc::channel(100);
    let (timer_tx, mut timer_rx) = mpsc::channel(1000);
    let mut late_counter = 0;

    // prepare to spawn requests
    let args_for_stats = args.clone();
    let matrix_arc = Arc::new(matrix_data);
    tokio::spawn(async move {
        while let Some(_) = timer_rx.recv().await {
            let is_hot = hot_gen.next();
            let url = args_for_stats.request_type.url(&args_for_stats.ip, is_hot);
            let function_name = function_id.get_name(is_hot);
            let request_type = args_for_stats.request_type;
            let storage_ip = args_for_stats.storage_ip.clone();
            let input_size = args_for_stats.input_size;
            let iterations = args_for_stats.iterations;
            let stages = args_for_stats.chain_stages;
            let local_clinet = client.clone();
            let local_matrix = matrix_arc.clone();
            let tx = tx.clone();
            tokio::spawn(async move {
                let body = request_type.body(
                    input_size,
                    iterations,
                    stages as u64,
                    function_name,
                    &storage_ip,
                    &local_matrix,
                );
                let request = local_clinet.post(&url).body(body);
                let start = SystemTime::now();
                let result = request.send().await;
                let end = SystemTime::now();

                let mut record = Record {
                    start,
                    end,
                    url,
                    timeout: false,
                    error: false,
                    status: None,
                };
                match result.and_then(|r| r.error_for_status()) {
                    Ok(r) => {
                        record.status = Some(r.status());
                        if let Ok(body) = r.bytes().await {
                            request_type.check_body(body, expected_response);
                        } else {
                            record.timeout = true;
                            debug!("Request timed out on body");
                        }
                    }
                    Err(e) => {
                        if e.is_timeout() {
                            record.timeout = true;
                            debug!("Request timed out");
                        } else {
                            record.error = true;
                            record.status = e.status();
                            warn!("Request error: {}", e);
                        }
                    }
                }
                tx.send(record).await.unwrap();
            });
        }

        if args_for_stats.record_stats() {
            file_writing::write_timestamps(&client, &args_for_stats, rps)
                .await
                .unwrap();
        }
    });

    // task timer for pacing
    let task_timer = tokio::task::spawn_blocking(move || {
        let base = Instant::now();
        for start in starts {
            let next = base + start;
            let sleep_time = Instant::now();
            let sleep_duration = next.checked_duration_since(sleep_time);
            // early enough so need to wait
            let is_late = if let Some(sleep_dur) = sleep_duration {
                // higher precision than tokio::time::sleep
                std::thread::sleep(sleep_dur);
                if let Some(late_time) = sleep_time.checked_duration_since(next) {
                    if late_time.as_secs_f64() > REQ_ISSUE_SLACK_S {
                        warn!("late after sleeping by: {:?}", late_time);
                        true
                    } else {
                        false
                    }
                } else {
                    false
                }
            } else {
                // late by some time
                let late_time = sleep_time.duration_since(next);
                warn!("late on iteraton start by: {:?}", late_time);
                late_time.as_secs_f64() > REQ_ISSUE_SLACK_S
            };
            if is_late {
                late_counter += 1;
                if late_counter >= 10 {
                    let msg: Box<dyn std::error::Error + Send + Sync> =
                        "Timer task late more than 10 times".into();
                    return Err(msg);
                }
            } else {
                late_counter = 0;
            }

            match timer_tx.try_send(()) {
                Ok(()) => (),
                Err(TrySendError::Full(_)) => {
                    let msg: Box<dyn std::error::Error + Send + Sync> =
                        "Timer task queue full".into();
                    return Err(msg);
                }
                Err(TrySendError::Closed(_)) => {
                    let msg: Box<dyn std::error::Error + Send + Sync> =
                        "Timer task queue closed".into();
                    return Err(msg);
                }
            };
        }
        info!("Started all requests in {:?}", base.elapsed());
        Ok(())
    });

    let mut num_received = 0;
    while let Some(record) = rx.recv().await {
        num_received += 1;
        if num_received > num_warmup {
            bench_log.add_record(record);
        }
    }

    task_timer.await??;

    let total = bench_log.total();
    let errors = bench_log.errors();
    let median_latency = bench_log.latencies(&[50.0])[0].as_micros();
    file_writing::write_latencies(&args, bench_log, rps)?;

    Ok((total, errors, median_latency))
}
