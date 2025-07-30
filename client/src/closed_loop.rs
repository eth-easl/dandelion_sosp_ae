use crate::{
    file_writing, Arc, Args, BenchLog, Client, ExperimentModel, FunctionId, HotGenerator, Record,
    Result, SystemTime,
};
use std::sync::atomic::AtomicUsize;
use tokio::{
    spawn,
    sync::mpsc::{channel, Sender},
};

struct LoopArc {
    args: Args,
    hot_gen: HotGenerator,
    request_counter: AtomicUsize,
    function_id: FunctionId,
    matrix_data: Vec<u8>,
}

async fn request_loop(
    loop_arc: Arc<LoopArc>,
    measurement_number: usize,
    client: Client,
    expected_response: (u64, usize),
    record_sender: Sender<Record>,
) -> Result<()> {
    while loop_arc
        .request_counter
        .fetch_add(1, std::sync::atomic::Ordering::SeqCst)
        < measurement_number
    {
        let is_hot = loop_arc.hot_gen.next();
        let url = loop_arc.args.request_type.url(&loop_arc.args.ip, is_hot);
        let function_name = loop_arc.function_id.get_name(is_hot);
        let body = loop_arc.args.request_type.body(
            loop_arc.args.input_size,
            loop_arc.args.iterations,
            loop_arc.args.chain_stages as u64,
            function_name,
            &loop_arc.args.storage_ip,
            &loop_arc.matrix_data,
        );
        let request = client.post(&url).body(body);
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
                let body = r.bytes().await.unwrap();
                loop_arc
                    .args
                    .request_type
                    .check_body(body, expected_response);
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
        record_sender.try_send(record)?;
    }
    return Ok(());
}

pub async fn run_closed_loop_n_clients(
    args: &Args,
    function_id: &FunctionId,
    client: &Client,
    matrix_data: &Vec<u8>,
    expected_response: (u64, usize),
    client_number: usize,
) -> Result<(f32, BenchLog)> {
    info!(
        "Starting measurement for {} clients and {} measurements each",
        client_number, args.duration
    );
    let measurement_number = args.duration as usize;
    let (record_tx, mut record_rx) = channel(measurement_number);
    info!("Starting loop with {} clients", client_number);
    let mut join_vec = Vec::new();
    let loop_arc = Arc::new(LoopArc {
        args: args.clone(),
        hot_gen: HotGenerator::new(args.hot_percent),
        request_counter: AtomicUsize::new(0),
        function_id: function_id.fresh_copy(),
        matrix_data: matrix_data.clone(),
    });
    join_vec.reserve(client_number);
    for _ in 0..client_number {
        join_vec.push(spawn(request_loop(
            loop_arc.clone(),
            measurement_number,
            client.clone(),
            expected_response,
            record_tx.clone(),
        )))
    }
    for join_handle in join_vec {
        join_handle.await??;
    }

    let mut record_buffer = Vec::new();
    let mut total_received = 0usize;
    loop {
        let num_received = record_rx
            .recv_many(&mut record_buffer, measurement_number)
            .await;
        if num_received == 0 {
            break;
        }
        total_received += num_received;
        if total_received >= measurement_number {
            break;
        }
    }
    match total_received {
        x if x > measurement_number => warn!(
            "Received {} but only expected {} measurements",
            total_received, measurement_number
        ),
        x if x < measurement_number => error!("Did not reach specified measurement number"),
        _ => (),
    }
    let mut current_records = BenchLog::new(measurement_number);
    for record in record_buffer.into_iter() {
        current_records.add_record(record);
    }
    let throughput = (measurement_number as f32) / current_records.duration() as f32;

    info!("Finished measurement");
    return Ok((throughput, current_records));
}

pub async fn run_closed_loop(
    args: Args,
    client: Client,
    function_id: FunctionId,
    expected_response: (u64, usize),
    matrix_data: Vec<u8>,
) -> Result<()> {
    let (baseline_throughput, baseline_log) = run_closed_loop_n_clients(
        &args,
        &function_id,
        &client,
        &matrix_data,
        expected_response,
        1,
    )
    .await?;

    info!("baseline throughput: {}", baseline_throughput);

    file_writing::write_latencies(&args, baseline_log, 1)?;

    if args.record_stats() {
        file_writing::write_timestamps(&client, &args, 1).await?
    }

    // continue if the peak also needs to be detected
    match args.experiment_model {
        ExperimentModel::ClosedUnloaded => return Ok(()),
        _ => (),
    }
    // find peak
    let mut client_number = std::cmp::max(2, args.rate) as usize;
    let mut last_throughput = baseline_throughput;
    let mut repetition = 0;
    loop {
        let (current_throughput, current_records) = run_closed_loop_n_clients(
            &args,
            &function_id,
            &client,
            &matrix_data,
            expected_response,
            client_number,
        )
        .await?;
        match current_throughput {
            current if current > last_throughput => (),
            current
                if current > last_throughput * (1.0 - args.significant_degradation)
                    && repetition < 2 =>
            {
                repetition += 1;
                continue;
            }
            _ => break,
        }
        repetition = 0;
        let error_rate = (current_records.errors() as f64) / (current_records.total() as f64);
        if error_rate >= 0.01 {
            warn!("Error rate above 1% at: {}", error_rate);
            break;
        }
        last_throughput = current_throughput;

        file_writing::write_latencies(&args, current_records, client_number as u64)?;

        if args.record_stats() {
            file_writing::write_timestamps(&client, &args, client_number as u64).await?;
        }
        client_number += 1;
    }

    Ok(())
}
