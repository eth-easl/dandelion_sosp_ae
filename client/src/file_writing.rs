use crate::{Args, BenchLog, Result};
use reqwest::Client;
use std::{io::Write, time::Duration};

pub fn write_latencies(args: &Args, log: BenchLog, rate: u64) -> Result<()> {
    // write all log recrods to file
    let file_name = format!(
        "{}/latencies_{}_{}_{}_{}_{:03.0}%hot_{}_rate.csv",
        args.output_dir,
        args.target,
        args.experiment_model,
        args.request_type,
        args.input_size,
        args.hot_percent * 100.0,
        rate,
    );
    std::fs::create_dir_all(args.output_dir.clone())?;
    let mut file = std::fs::File::create(file_name)?;
    writeln!(
        file,
        "instance,startTime,responseTime,connectionTimeout,functionTimeout,statusCode",
    )?;
    for record in &log.records {
        writeln!(
            file,
            "{},{},{},{},{},{}",
            record.url,
            record.start_time().as_micros(),
            record.duration().as_micros(),
            record.timeout,
            record.error,
            record.status.map_or(0, |s| s.as_u16()),
        )?;
    }

    // log to rought results to console for sanity checking
    let num_total = log.total();
    let num_errors = log.errors();
    println!("Total: {}, Errors: {}", num_total, num_errors);
    let percentages = [50.0, 90.0, 95.0, 99.0, 99.9, 100.0];
    let latencies = log.latencies(&percentages);
    println!("Latency percentiles (in us):");
    for (p, l) in percentages.into_iter().zip(latencies) {
        println!("{:5}% -- {}\t", p, l.as_micros());
    }
    // required by the experiment script
    println!(
        "error%=\"{}\" goodput=\"{}\"",
        num_errors as f64 / num_total as f64,
        (num_total - num_errors) as f64 / log.duration(),
    );
    return Ok(());
}

pub async fn write_timestamps(client: &Client, args: &Args, rate: u64) -> Result<()> {
    let stat_url = format!("http://{}:{}/{}", args.ip, 8080, "stats");
    let file_name = format!(
        "{}/timestamps_{}_{}_{}_{}_{:03.0}%hot_{}_rate.csv",
        args.output_dir,
        args.target,
        args.experiment_model,
        args.request_type,
        args.input_size,
        args.hot_percent * 100.0,
        rate,
    );
    // Get stats and save them to file
    let stats_request = client.get(stat_url).timeout(Duration::from_secs(60));
    std::fs::create_dir_all(args.output_dir.clone())?;
    let mut stats_file = std::fs::OpenOptions::new()
        .append(true)
        .create(true)
        .open(file_name)?;
    let mut stats_response = stats_request.send().await?;
    while let Some(chunk) = stats_response.chunk().await? {
        stats_file.write_all(&chunk)?;
    }
    return Ok(());
}
