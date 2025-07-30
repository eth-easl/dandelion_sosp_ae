use crate::{
    log::{error, info},
    Client, EngineType, PathBuf, RequestType,
};
use serde::Serialize;
use std::{
    sync::atomic::{AtomicU32, Ordering},
    time::{Duration, Instant},
};

pub async fn check_service_ready(client: &Client, ip: &String, port: u32, timeout_seconds: u32) {
    let service_url = format!("http://{}:{}", ip, port);
    let start = Instant::now();
    let timeout_duration = Duration::from_secs(timeout_seconds.into());
    while Instant::now().duration_since(start) < timeout_duration {
        if client
            .post(service_url.clone())
            .send()
            .await
            .is_ok_and(|response| response.status().is_success())
        {
            return;
        }
    }
    panic!("Service at {} not ready", service_url);
}

pub struct FunctionId {
    base_name: String,
    cold_counter: AtomicU32,
    cold_max: u32,
}

fn format_name(name: &String, cold_index: Option<u32>) -> String {
    return cold_index
        .and_then(|index| Some(format!("{}_{}", name, index)))
        .unwrap_or(name.clone());
}

impl FunctionId {
    pub fn new(name: String, cold_instances: u32) -> Self {
        return FunctionId {
            base_name: name,
            cold_counter: AtomicU32::new(0),
            cold_max: cold_instances,
        };
    }
    pub fn fresh_copy(&self) -> Self {
        return FunctionId {
            base_name: self.base_name.clone(),
            cold_counter: AtomicU32::new(0),
            cold_max: self.cold_max,
        };
    }
    pub fn get_name(&self, is_hot: bool) -> String {
        if is_hot {
            return self.base_name.clone();
        } else {
            return self.get_cold_name();
        }
    }
    fn get_cold_name(&self) -> String {
        let cold_count = self.cold_counter.fetch_add(1u32, Ordering::SeqCst);
        let cold_index = cold_count % self.cold_max;
        return format_name(&self.base_name, Some(cold_index));
    }
}

#[derive(Serialize)]
struct RegisterFunction {
    name: String,
    context_size: u64,
    engine_type: String,
    binary: Vec<u8>,
    input_sets: Vec<(String, Option<Vec<(String, Vec<u8>)>>)>,
    output_sets: Vec<String>,
}

// TODO set to 0x800_0000 once the wasm update goes through
const DEFAULT_COMPUTE_CONTEXT_SIZE: u64 = 0x80_0000;
const PYTHON_COMPUTE_CONTEXT_SIZE: u64 = 0xA00_0000;
const HANDLE_FUNCTION_NAME: &str = "handle";
const FAN_OUT_FUNCTION_NAME: &str = "fan_out";
const TEMPLATE_FUNCTION_NAME: &str = "render";

async fn register_function(
    client: &Client,
    ip: &String,
    workload_path: &PathBuf,
    function_id: &FunctionId,
    engine_type: EngineType,
    request_type: &RequestType,
    script_name: Option<String>,
    context_size: Option<u64>,
    storage_ip: &Option<String>,
) {
    info!("Starting to register functions");

    let mut hot_function = RegisterFunction {
        name: function_id.base_name.clone(),
        context_size: context_size.unwrap_or(DEFAULT_COMPUTE_CONTEXT_SIZE),
        engine_type: engine_type.to_string(),
        binary: std::fs::read(workload_path).unwrap(),
        input_sets: request_type.input_sets(script_name, storage_ip),
        output_sets: request_type.output_sets(),
    };
    if !client
        .post(format!("http://{}:{}/register/function", ip, 8080))
        .body(bson::to_vec(&hot_function).unwrap())
        .send()
        .await
        .unwrap()
        .status()
        .is_success()
    {
        error!("Failed to register hot function");
    }

    info!("Registered hot function, starting to register cold functions");

    for cold_index in 0..function_id.cold_max {
        hot_function.name = format_name(&function_id.base_name, Some(cold_index));
        if !client
            .post(format!("http://{}:{}/register/function", ip, 8080))
            .body(bson::to_vec(&hot_function).unwrap())
            .send()
            .await
            .unwrap()
            .status()
            .is_success()
        {
            error!("Failed to register cold function");
        }
    }

    info!("Registered cold functions");
}

#[derive(Serialize)]
struct RegisterComposition {
    composition: String,
}

fn create_compositon(
    request_type: &RequestType,
    composition_name: &str,
    cold_id: Option<u32>,
    chain_depth: usize,
) -> RegisterComposition {
    // TODO be more flexible in function_name rather than just using request_type
    let composition = match request_type {
        RequestType::Matmul | RequestType::CompressionApp => format!(
            r#"
            function {function} (in_data) => (out_data);
            composition {composition} (comp_in) => (comp_out) {{
                {function} (in_data = all comp_in) => (comp_out = out_data);
            }}"#,
            function = format_name(&request_type.to_string_nohyphen(), cold_id),
            composition = composition_name
        ),
        RequestType::MatmulStorage => format!(
            r#"
            function {function} (in_data) => (out_data);
            function HTTP (request, headers, body) => (status, headers, body);
            composition {composition} (fetch_request, store_request) => (store_status) {{
                HTTP (request = all fetch_request) => (fetch_body = body);
                {function} (in_data = all fetch_body) => (store_body = out_data);
                HTTP (request = all store_request, body = all store_body) => (store_status = status);
            }}"#,
            function = format_name(&request_type.to_string_nohyphen(), cold_id),
            composition = composition_name
        ),
        RequestType::IoScale => format!(
            r#"
            function {function} (in_data, preamble) => (out_data);
            function HTTP (request) => (response, body);
            composition {composition} (fetch_request, store_preamble) => (store_response) {{
                HTTP (request = all fetch_request) => (fetch_body = body);
                {function} (in_data = all fetch_body, preamble = all store_preamble) => (store_request = out_data);
                HTTP (request = all store_request) => (store_response = response);
            }}"#,
            function = format_name(&request_type.to_string_nohyphen(), cold_id),
            composition = composition_name
        ),
        RequestType::IoScaleHybrid => format!(
            r#"
            function {function} (in_data, preamble) => (out_data);
            composition {composition} (fetch_request, store_preamble) => (store_response) {{
                {function} (in_data = all fetch_request, preamble = all store_preamble) => (store_response = out_data);
            }}"#,
            function = format_name(&request_type.to_string_nohyphen(), cold_id),
            composition = composition_name
        ),
        RequestType::ChainScaling | RequestType::ChainScalingDedicated => {
            let function_name = format_name(&request_type.to_string_nohyphen(), cold_id);
            let mut composition = format!(
                r#"
            function {function} (in_data, preamble) => (out_data);
            function HTTP (request) => (response body);
            composition {composition} (fetch_request, store_preamble) => (store_response_{chain_depth}) {{
                HTTP (request = all fetch_request) => (store_response_0 = body);"#,
                function = function_name,
                composition = composition_name,
                chain_depth = chain_depth,
            );
            for depth in 0..chain_depth {
                let layer = format!(
                    r#"
                    {function} (in_data = all store_response_{depth}, preamble = all store_preamble) 
                        => (store_request_{depth} = out_data);
                    HTTP (request = all store_request_{depth}) => (store_response_{depth_after} = body);"#,
                    function = function_name,
                    depth_after = depth + 1
                );
                composition.push_str(&layer);
            }
            composition.push_str("\n}}");
            composition
        }
        RequestType::MiddlewareApp => format!(
            r#"
            function {handle_func} (servers, responses) => (stdio, requests);
            function {fan_out_func} (servers, responses) => (stdio, requests);
            function {render_func} (servers, responses) => (stdio, requests);
            function HTTP (request) => (response, body);
            composition {composition} (comp_inputs) => (comp_outputs, out_1, out_2, out_3) {{
                {handle_func} (responses = all comp_inputs) => (auth_requests = requests, out_1 = stdio);
                HTTP (request = each auth_requests) => (auth_response_body = body);
                {fan_out_func} (responses = all auth_response_body) => (log_requests = requests, out_2 = stdio);
                HTTP (request = each log_requests) => (log_response_body = body);
                {render_func} (responses = all log_response_body) => (comp_outputs = requests, out_3 = stdio);
            }}"#,
            handle_func = format_name(&HANDLE_FUNCTION_NAME.to_string(), cold_id),
            fan_out_func = format_name(&FAN_OUT_FUNCTION_NAME.to_string(), cold_id),
            render_func = format_name(&TEMPLATE_FUNCTION_NAME.to_string(), cold_id),
            composition = composition_name
        ),
        RequestType::MiddlewareAppHybrid => format!(
            r#"
            function {function} (servers, responses) => (stdio, requests);
            composition {composition} (comp_in) => (comp_outputs, stdio) {{
                {function} (responses = comp_in) => (stdio = stdio, comp_outputs = requests);
            }}"#,
            function = format_name(&request_type.to_string_nohyphen(), cold_id),
            composition = composition_name
        ),
        RequestType::PythonApp => format!(
            r#"
            function {handle_func} (scripts, stdio, pylib, etc, servers, responses) => (stdout, requests);
            function {fan_out_func} (scripts, stdio, pylib, etc, servers, responses) => (stdout, requests);
            function {render_func} (scripts, stdio, pylib, etc, servers, responses) => (stdout, requests);
            function HTTP (request) => (response, body);
            composition {composition} (comp_inputs) => (comp_outputs) {{
                {handle_func} (responses = all comp_inputs) => (auth_requests = requests);
                HTTP (request = each auth_requests) => (auth_response_body = body);
                {fan_out_func} (responses = all auth_response_body) => (log_requests = requests);
                HTTP (request = each log_requests) => (log_response_body = body);
                {render_func} (responses = all log_response_body) => (comp_outputs = requests);
            }}"#,
            handle_func = format_name(&HANDLE_FUNCTION_NAME.to_string(), cold_id),
            fan_out_func = format_name(&FAN_OUT_FUNCTION_NAME.to_string(), cold_id),
            render_func = format_name(&TEMPLATE_FUNCTION_NAME.to_string(), cold_id),
            composition = composition_name
        ),
    };
    return RegisterComposition { composition };
}

pub async fn register_composition(
    client: &Client,
    ip: &String,
    request_type: &RequestType,
    engine_type: EngineType,
    workload_path: &PathBuf,
    compositon_id: &FunctionId,
    chain_depth: usize,
    storage_ip: &Option<String>,
    context_size: Option<u64>,
) {
    info!("Starting to register function(s)");
    match request_type {
        RequestType::Matmul
        | RequestType::MatmulStorage
        | RequestType::IoScale
        | RequestType::IoScaleHybrid
        | RequestType::ChainScalingDedicated
        | RequestType::ChainScaling
        | RequestType::MiddlewareAppHybrid
        | RequestType::CompressionApp => {
            let function_id =
                FunctionId::new(request_type.to_string_nohyphen(), compositon_id.cold_max);
            register_function(
                client,
                ip,
                workload_path,
                &function_id,
                engine_type,
                request_type,
                None,
                context_size,
                storage_ip,
            )
            .await
        }
        RequestType::MiddlewareApp => {
            let engine_name = match engine_type {
                EngineType::Process => "mmu",
                EngineType::Kvm => "kvm",
                _ => panic!("unsuported engine type for middleware app"),
            };
            let handle_id =
                FunctionId::new(String::from(HANDLE_FUNCTION_NAME), compositon_id.cold_max);
            let mut handle_path = workload_path.clone();
            handle_path.push(format!("handle_{}_x86_64", engine_name));
            register_function(
                client,
                ip,
                &handle_path,
                &handle_id,
                engine_type,
                request_type,
                None,
                context_size,
                storage_ip,
            )
            .await;
            let fan_out_id =
                FunctionId::new(String::from(FAN_OUT_FUNCTION_NAME), compositon_id.cold_max);
            let mut fan_out_path = workload_path.clone();
            fan_out_path.push(format!("fan_out_{}_x86_64", engine_name));
            register_function(
                client,
                ip,
                &fan_out_path,
                &fan_out_id,
                engine_type,
                request_type,
                None,
                context_size,
                storage_ip,
            )
            .await;
            let render_id =
                FunctionId::new(String::from(TEMPLATE_FUNCTION_NAME), compositon_id.cold_max);
            let mut render_path = workload_path.clone();
            render_path.push(format!("template_{}_x86_64", engine_name));
            register_function(
                client,
                ip,
                &render_path,
                &render_id,
                engine_type,
                request_type,
                None,
                context_size,
                storage_ip,
            )
            .await;
        }
        RequestType::PythonApp => {
            let handle_id =
                FunctionId::new(String::from(HANDLE_FUNCTION_NAME), compositon_id.cold_max);
            register_function(
                client,
                ip,
                workload_path,
                &handle_id,
                engine_type,
                request_type,
                Some(String::from("logs_0_handle.py")),
                context_size.or(Some(PYTHON_COMPUTE_CONTEXT_SIZE)),
                storage_ip,
            )
            .await;
            let fan_out_id =
                FunctionId::new(String::from(FAN_OUT_FUNCTION_NAME), compositon_id.cold_max);
            register_function(
                client,
                ip,
                workload_path,
                &fan_out_id,
                engine_type,
                request_type,
                Some(String::from("logs_1_fanout.py")),
                context_size.or(Some(PYTHON_COMPUTE_CONTEXT_SIZE)),
                storage_ip,
            )
            .await;
            let render_id =
                FunctionId::new(String::from(TEMPLATE_FUNCTION_NAME), compositon_id.cold_max);
            register_function(
                client,
                ip,
                workload_path,
                &render_id,
                engine_type,
                request_type,
                Some(String::from("logs_2_render.py")),
                context_size.or(Some(PYTHON_COMPUTE_CONTEXT_SIZE)),
                storage_ip,
            )
            .await;
        }
    }

    info!("Starting to register compositions");

    if !client
        .post(format!("http://{}:{}/register/composition", ip, 8080))
        .body(
            bson::to_vec(&create_compositon(
                request_type,
                &compositon_id.base_name,
                None,
                chain_depth,
            ))
            .unwrap(),
        )
        .send()
        .await
        .unwrap()
        .status()
        .is_success()
    {
        error!("Failed to register hot composition");
    }

    info!("Finished registering hot composition, starting to register cold compositons");

    for cold_index in 0..compositon_id.cold_max {
        if !client
            .post(format!("http://{}:{}/register/composition", ip, 8080))
            .body(
                bson::to_vec(&create_compositon(
                    request_type,
                    &format_name(&compositon_id.base_name, Some(cold_index)),
                    Some(cold_index),
                    chain_depth,
                ))
                .unwrap(),
            )
            .send()
            .await
            .unwrap()
            .status()
            .is_success()
        {
            error!("Failed to register cold composition");
        }
    }

    info!("Finished registering cold compositions");
}
