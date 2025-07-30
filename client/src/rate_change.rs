use crate::Result;
use csv::ReaderBuilder;
use std::fs::File;
use std::io::BufReader;
use std::path::PathBuf;

#[derive(Debug)]
struct RateChange {
    /// timestamp in second, starting from zero
    time: u64,
    /// request per second during [time, time+1)
    rate: u64,
}

fn load_rate_changes_from_csv(path: &PathBuf) -> Result<Vec<RateChange>> {
    let file = File::open(path)?;
    let mut rdr = ReaderBuilder::new()
        .has_headers(true)
        .from_reader(BufReader::new(file));

    // Validate headers
    {
        let headers = rdr.headers()?;
        if headers.len() != 2 {
            return Err("CSV must have exactly two columns: time_sec and requests_per_sec".into());
        }

        if headers.get(0) != Some("time_sec") || headers.get(1) != Some("requests_per_sec") {
            return Err("CSV headers must be: time_sec,requests_per_sec".into());
        }
    }

    let mut changes = Vec::new();

    for result in rdr.records() {
        let record = result?;
        let time_sec = record[0].parse()?;
        let requests_per_sec = record[1].parse()?;
        changes.push(RateChange {
            time: time_sec,
            rate: requests_per_sec,
        });
    }

    if changes.is_empty() {
        return Err("No data found in CSV".into());
    }

    // Ensure first entry starts at second 0
    if changes[0].time != 0 {
        return Err("Config must start from second 0".into());
    }

    // Check that time_sec is strictly increasing
    for i in 1..changes.len() {
        if changes[i].time <= changes[i - 1].time {
            return Err(format!(
                "time_sec values must be strictly increasing, found {} followed by {}",
                changes[i - 1].time,
                changes[i].time
            )
            .into());
        }
    }

    Ok(changes)
}

fn generate_rate_per_sec(changes: &[RateChange], duration: u64) -> Vec<u64> {
    let mut rate_per_sec = vec![0; duration as usize];

    for i in 0..changes.len() {
        let current_start = changes[i].time;
        let current_rate = changes[i].rate;
        let next_start = if i + 1 < changes.len() {
            changes[i + 1].time
        } else {
            duration // If no next entry, fill until the end of duration
        };

        let end = next_start.min(duration);
        for t in current_start..end {
            rate_per_sec[t as usize] = current_rate;
        }
    }

    rate_per_sec
}

/// load rate changes from CSV file and generate rates per second up to desired duration
pub fn load_rps(path: &PathBuf, duration: u64) -> Result<Vec<u64>> {
    let changes = load_rate_changes_from_csv(path)?;
    let rate_per_sec = generate_rate_per_sec(&changes, duration);
    Ok(rate_per_sec)
}
