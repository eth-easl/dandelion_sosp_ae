use hyperlight_wasm::{SandboxBuilder, ReturnType, ParameterValue, ReturnValue};
use hyperlight_host::Result;
use std::path::Path;
use axum::{
    routing::post,
    Router,
    response::IntoResponse,
    http::StatusCode,
    body::Bytes,
    serve,
};
use tokio::net::TcpListener;
use tokio::runtime::Handle;
use tokio::time;
use tracing::{info, error};
use std::time::Instant;
use serde::{Deserialize, Serialize};
use bson::{from_slice, to_vec};
use std::mem::size_of;
use uuid::Uuid;
use chrono;
use serde_json;
use clap::Parser;

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    /// Path to the workload WASM file
    #[arg(short, long, default_value = "matmul.wasm")]
    workload_path: String,
}

#[derive(Deserialize)]
#[allow(dead_code)]
struct LoaderRequest<'data> {
    name: String,
    #[serde(borrow)]
    sets: Vec<DataSet<'data>>,
}

#[derive(Serialize)]
#[allow(dead_code)]
struct LoaderResponse<'data> {
    #[serde(borrow)]
    sets: Vec<DataSet<'data>>,
}

#[derive(Deserialize, Serialize)]
#[allow(dead_code)]
struct DataSet<'data> {
    identifier: String,
    #[serde(borrow)]
    items: Vec<DataItem<'data>>,
}

#[derive(Deserialize, Serialize)]
#[allow(dead_code)]
struct DataItem<'data> {
    identifier: String,
    key: u32,
    #[serde(with = "serde_bytes")]
    data: &'data [u8],
}

#[derive(Serialize)]
struct LatencyMetrics {
    request_id: String,
    sandbox_creation: f64,  // microseconds
    runtime_loading: f64,   // microseconds
    module_loading: f64,    // microseconds
    function_execution: f64,// microseconds
    total_time: f64,        // microseconds
    timestamp: String,      // ISO 8601 timestamp
}

async fn handle_matmul_request(body: Bytes) -> impl IntoResponse {
    // println!("Received request with body length: {}", body.len());
    let request_start = Instant::now();
    match handle_request(body.to_vec()).await {
        Ok(response_data) => {
            let total_time = request_start.elapsed();
            info!(
                "Request completed successfully. Total time: {:.2}µs",
                total_time.as_secs_f64() * 1_000_000.0
            );
            (StatusCode::OK, response_data)
        },
        Err(e) => {
            error!("Error processing request: {}", e);
            (StatusCode::INTERNAL_SERVER_ERROR, format!("Error: {}", e).into_bytes())
        },
    }
}

async fn handle_request(body: Vec<u8>) -> Result<Vec<u8>> {
    let total_start = Instant::now();
    let request_id = Uuid::new_v4().to_string();

    // Log the request body length
    
    // Parse the BSON request
    let LoaderRequest { name: _, sets } = from_slice::<LoaderRequest>(&body)
        .map_err(|e| anyhow::anyhow!("Failed to parse request: {}", e))?;
    
    // 1. Sandbox Creation
    let sandbox_start = Instant::now();
    // let sandbox = SandboxBuilder::new().build()?;
    let sandbox = SandboxBuilder::new()
        .with_guest_error_buffer_size(0x1000)        // 4KB
        .with_guest_input_buffer_size(0x100000)      // 1MB (increased from 32KB/0x8000)
        .with_guest_output_buffer_size(0x100000)     // 1MB (increased from 32KB/0x8000)
        .with_host_function_buffer_size(0x1000)      // 4KB
        .with_host_exception_buffer_size(0x1000)     // 4KB
        .with_guest_stack_size(0x100000)             // 1MB (increased from 8KB/0x2000)
        .with_guest_heap_size(0x200000)              // 2MB (increased from 1MB/0x100000)
        .with_guest_panic_context_buffer_size(0x800) // 2KB
        .with_guest_function_call_max_execution_time_millis(0) // No timeout
        .build()?;
    
    let sandbox_time = sandbox_start.elapsed();
    
    // 2. Runtime Loading
    let runtime_start = Instant::now();
    let wasm_sandbox = sandbox.load_runtime()?;
    let runtime_time = runtime_start.elapsed();
    
    // 3. Module Loading
    let module_start = Instant::now();
    let args = Args::parse();
    let wasm_path = Path::new(&args.workload_path).to_str().unwrap().to_string();
    let mut loaded_wasm_sandbox = wasm_sandbox.load_module(wasm_path)?;
    let module_time = module_start.elapsed();

    // 4. Function Execution
    let exec_start = Instant::now();
    let input_data = sets[0].items[0].data;
    
    
    // Calculate matrix dimensions
    assert_eq!(0, input_data.len() % size_of::<i64>());
    let rows = i64::from_le_bytes(input_data[0..8].try_into().unwrap()) as i32;
    let cols = ((input_data.len() - 8) / size_of::<i64>() / (rows as usize)) as i32;
    
    info!("Matrix dimensions: {}x{}", rows, cols);
    info!("Total data size: {}", input_data.len());
    info!("Data after header: {}", input_data[8..].len());

    // Print input matrix values for debugging
    let input_matrix = &input_data[8..];
    info!("Input matrix values:");
    for i in 0..rows as usize {
        for j in 0..cols as usize {
            let idx = i * cols as usize + j;
            if idx * size_of::<i64>() + size_of::<i64>() <= input_matrix.len() {
                let value = i64::from_le_bytes(
                    input_matrix[idx * size_of::<i64>()..(idx + 1) * size_of::<i64>()]
                        .try_into()
                        .unwrap()
                );
                info!("input[{}][{}] = {}", i, j, value);
            }
        }
    }

    // Prepare output buffer
    let out_mat: Vec<u8> = vec![0; (rows as usize * rows as usize) * size_of::<i64>()];
    info!("Output matrix values:");
    for i in 0..rows as usize {
        for j in 0..cols as usize {
            let idx = i * cols as usize + j;
            if idx * size_of::<i64>() + size_of::<i64>() <= input_data[8..].len() {
                let value = i64::from_le_bytes(
                    input_data[8..][idx * size_of::<i64>()..(idx + 1) * size_of::<i64>()]
                        .try_into()
                        .unwrap()
                );
                info!("Output[{}][{}] = {}", i, j, value);
            }
        }
    }

   info!("Expected output buffer size: {} bytes", out_mat.len());


    // Call matmul with input and output buffers
    let ReturnValue::VecBytes(result) = loaded_wasm_sandbox
        .call_guest_function(
            "matmul",
            Some(vec![
                ParameterValue::VecBytes(input_data[8..].to_vec()), // Input matrix data
                ParameterValue::Int(rows),
                ParameterValue::Int(cols),
            ]),
            ReturnType::VecBytes,  // Expect the modified buffer to be returned
        )
        .unwrap()
    else {
        panic!("Unexpected return type from matmul");
    };

    // print the results in bytes
    info!("Result: {:?}", result);

    
    let out_mat = result;

    let exec_time = exec_start.elapsed();
    let total_time = total_start.elapsed();

    // Collect latency metrics
    let metrics = LatencyMetrics {
        request_id,
        sandbox_creation: sandbox_time.as_secs_f64() * 1_000_000.0,
        runtime_loading: runtime_time.as_secs_f64() * 1_000_000.0,
        module_loading: module_time.as_secs_f64() * 1_000_000.0,
        function_execution: exec_time.as_secs_f64() * 1_000_000.0,
        total_time: total_time.as_secs_f64() * 1_000_000.0,
        timestamp: chrono::Utc::now().to_rfc3339(),
    };


    info!("Output matrix values (after removing prefix):");
    for i in 0..rows as usize {
        for j in 0..rows as usize {
            let idx = i * rows as usize + j;
            // Adjust offset to read non-zero byte at position 4, 12, 20, 28
            let byte_offset = idx * size_of::<i64>() + 4; // Start at offset 4
            if byte_offset + 1 <= out_mat.len() {
                // Read single byte and extend to i64
                let value = out_mat[byte_offset] as i64;
                info!("output[{}][{}] = {}", i, j, value);
            }
        }
    }

    let mut full_out_mat: Vec<u8> = vec![0; rows as usize * rows as usize * size_of::<i64>() + 8];
    let length = (rows as usize * rows as usize * size_of::<i64>()) as i64;
    full_out_mat[0..8].copy_from_slice(&length.to_le_bytes());
    full_out_mat[8..8 + out_mat.len()].copy_from_slice(&out_mat);
    info!("\nOutput matrix:");
    for i in 0..rows as usize {
        for j in 0..rows as usize {
            let idx = i * rows as usize + j;
            if idx * size_of::<i64>() + size_of::<i64>() <= full_out_mat[8..].len() {
                let value = i64::from_le_bytes(
                    full_out_mat[8 + idx * size_of::<i64>()..8 + (idx + 1) * size_of::<i64>()]
                        .try_into()
                        .unwrap()
                );
                info!("output[{}][{}] = {}", i, j, value);
            }
        }
    }

    // Construct the response structure
    let response_struct = LoaderResponse {
        sets: vec![DataSet {
            identifier: String::from("outmatrix"),
            items: vec![DataItem {
                identifier: String::from(""),
                key: 0,
                data: &full_out_mat,
            }],
        }],
    };

    // Serialize the response structure back to BSON
    let response_bson = to_vec(&response_struct)
        .map_err(|e| anyhow::anyhow!("Failed to serialize response: {}", e))?;

    // Total time breakdown
    info!(
        "Total request breakdown (µs):\n\
        \tSandbox creation: {:.2}\n\
        \tRuntime loading:  {:.2}\n\
        \tModule loading:   {:.2}\n\
        \tFunction exec:    {:.2}\n\
        \tOther overhead:   {:.2}\n\
        \tTotal:           {:.2}",
        sandbox_time.as_secs_f64() * 1_000_000.0,
        runtime_time.as_secs_f64() * 1_000_000.0,
        module_time.as_secs_f64() * 1_000_000.0,
        exec_time.as_secs_f64() * 1_000_000.0,
        (total_time - sandbox_time - runtime_time - module_time - exec_time).as_secs_f64() * 1_000_000.0,
        total_time.as_secs_f64() * 1_000_000.0
    );

    // print latency break in a row
    println!("latency_metrics={}", serde_json::to_string(&metrics).unwrap());

    Ok(response_bson)
}


#[tokio::main]
async fn main() -> Result<()> {
    // Parse command line arguments
    let args = Args::parse();
    info!("Using workload path: {}", args.workload_path);

    // Initialize tracing with JSON output
    tracing_subscriber::fmt()
        .with_env_filter(tracing_subscriber::EnvFilter::new(
            std::env::var("RUST_LOG").unwrap_or_else(|_| "error".into()),
        ))
        .with_target(true)
        .with_thread_ids(true)
        .with_thread_names(true)
        .with_file(true)
        .with_line_number(true)
        .json()
        .init();

    // Get the runtime handle
    let handle = Handle::current();

    // Spawn a background task to log metrics every second
    tokio::spawn(async move {
        loop {
            let metrics = handle.metrics();
            let _num_workers = metrics.num_workers();
            let _num_alive_tasks = metrics.num_alive_tasks();
            let _global_queue_depth = metrics.global_queue_depth();
            // println!("runtime_metrics: {} workers, {} alive tasks, {} tasks in global queue", _num_workers, _num_alive_tasks, _global_queue_depth);
            time::sleep(time::Duration::from_millis(10)).await;
        }
    });
    
    // Build our application with a route
    let app = Router::new()
        .route("/", post(|| async { StatusCode::OK }))  // Add root route for service readiness check
        .route("/cold/matmul", post(handle_matmul_request))
        .route("/hot/matmul", post(handle_matmul_request));


    // Run it with hyper on 0.0.0.0:8080 to accept connections from any IP
    let addr = std::net::SocketAddr::from(([0, 0, 0, 0], 8080));
    let listener = TcpListener::bind(addr).await?;
    info!("Server listening on {}:8080", std::net::Ipv4Addr::from([0, 0, 0, 0]));
    
    // Add a health check endpoint
    info!("Server is ready and accepting connections");
    
    serve(listener, app.into_make_service()).await?;

    Ok(())
}
