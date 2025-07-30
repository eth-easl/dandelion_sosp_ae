use clap::ValueEnum;
use core::str;
use serde::{Deserialize, Serialize};
use std::{fmt, fs::read, path::PathBuf, sync::Once};

#[derive(Clone, Copy, ValueEnum)]
pub enum RequestType {
    Matmul,
    MatmulStorage,
    IoScale,
    IoScaleHybrid,
    ChainScaling,
    ChainScalingDedicated,
    PythonApp,
    MiddlewareApp,
    MiddlewareAppHybrid,
    CompressionApp,
}

impl fmt::Display for RequestType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.to_possible_value().unwrap().get_name())
    }
}

impl RequestType {
    // we need this for function and composition name generation
    // as the parser doesn't accept identifier with hyphens
    pub fn to_string_nohyphen(&self) -> String {
        self.to_string().replace("-", "_")
    }
}

#[derive(Serialize)]
struct Request<'data> {
    name: String,
    sets: Vec<InputSet<'data>>,
}

#[derive(Deserialize)]
struct Response<'data> {
    #[serde(borrow)]
    sets: Vec<InputSet<'data>>,
}

#[derive(Serialize, Deserialize)]
struct InputSet<'data> {
    identifier: String,
    #[serde(borrow)]
    items: Vec<InputItem<'data>>,
}

#[derive(Serialize, Deserialize)]
struct InputItem<'data> {
    identifier: String,
    key: u32,
    #[serde(with = "serde_bytes")]
    data: &'data [u8],
}

const DANDELION_PORT: i32 = 8080;

fn read_python_scripts(script_name: String) -> Vec<(String, Vec<u8>)> {
    let mut script_path = PathBuf::from(core::env!("CARGO_MANIFEST_DIR"));
    let _ = script_path.pop();
    script_path.push(format!("servers/dandelion/python_app/{}", script_name));
    debug!("script path: {:?}", script_path.as_mut_os_string());
    let script = std::fs::read(script_path).unwrap();
    return vec![(script_name, script)];
}

fn read_files_from_dir(path: PathBuf, prepath: String) -> Vec<(String, Vec<u8>)> {
    let mut file_vec = Vec::new();
    println!("file path looking for {:?}", path);
    for entry_result in std::fs::read_dir(path).unwrap() {
        let entry = entry_result.unwrap();
        let file_type = entry.file_type().unwrap();
        if file_type.is_dir() {
            file_vec.append(&mut read_files_from_dir(
                entry.path(),
                format!("{}/{}", prepath, entry.file_name().into_string().unwrap()),
            ));
        } else if file_type.is_file() {
            let file_name = entry.file_name().into_string().unwrap();
            if file_name.ends_with(".py") || file_name.ends_with(".pyi") {
                file_vec.push((
                    format!("{}/{}", prepath, file_name),
                    read(entry.path()).unwrap(),
                ));
            }
        };
    }
    return file_vec;
}

fn read_python_lib() -> Vec<(String, Vec<u8>)> {
    let mut dir_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let _ = dir_path.pop();
    dir_path.push("servers/dandelion/python_app/Lib");
    let file_vec = read_files_from_dir(dir_path, String::from("lib"));
    for file in &file_vec {
        println!("file: {}", file.0);
    }
    return file_vec;
}

// Consider implementing this using dynamic dispatch
impl RequestType {
    pub fn input_sets(
        &self,
        script_name: Option<String>,
        storage_ip: &Option<String>,
    ) -> Vec<(String, Option<Vec<(String, Vec<u8>)>>)> {
        match self {
            Self::Matmul | Self::MatmulStorage | Self::CompressionApp => {
                vec![(String::from(""), None)]
            }
            Self::IoScale
            | Self::IoScaleHybrid
            | Self::ChainScaling
            | Self::ChainScalingDedicated => {
                vec![
                    (String::from("data"), None),
                    (String::from("preamble"), None),
                ]
            }
            Self::MiddlewareApp | Self::MiddlewareAppHybrid => {
                let server = vec![(
                    String::from("server.txt"),
                    format!(
                        "{}:8000",
                        storage_ip
                            .as_ref()
                            .expect("Need a storage IP for python application")
                    )
                    .into_bytes(),
                )];
                vec![
                    (String::from("servers"), Some(server)),
                    (String::from("responses"), None),
                ]
            }
            Self::PythonApp => {
                let script = script_name.expect("Python function registration needs a script name");
                let argv = format!("python3\0/scripts/{}\0", script)
                    .as_bytes()
                    .to_vec();
                let environ = "PYTHONHOME=/pylib\0PYTHONPATH=/pylib/lib\0LC_ALL=POSIX\0"
                    .as_bytes()
                    .to_vec();
                let scripts = read_python_scripts(script);
                static PYLIB_ONCE: Once = Once::new();
                static mut PYLIB: Vec<(String, Vec<u8>)> = Vec::<(String, Vec<u8>)>::new();
                PYLIB_ONCE.call_once(|| unsafe { PYLIB = read_python_lib() });
                let pylib = unsafe { PYLIB.clone() };
                let server = vec![(
                    String::from("server.txt"),
                    format!(
                        "{}:8000",
                        storage_ip
                            .as_ref()
                            .expect("Need a storage IP for python application")
                    )
                    .into_bytes(),
                )];
                vec![
                    (String::from("scripts"), Some(scripts)),
                    (
                        String::from("stdio"),
                        Some(vec![
                            (String::from("argv"), argv),
                            (String::from("environ"), environ),
                        ]),
                    ),
                    (String::from("pylib"), Some(pylib)),
                    (
                        String::from("etc"),
                        Some(vec![(
                            String::from("localtime"),
                            std::fs::read("/etc/localtime").unwrap(),
                        )]),
                    ),
                    (String::from("servers"), Some(server)),
                    (String::from("responses"), None),
                ]
            }
        }
    }

    pub fn output_sets(&self) -> Vec<String> {
        match self {
            Self::Matmul | Self::MatmulStorage | Self::CompressionApp => {
                vec![String::from("")]
            }
            Self::IoScale
            | Self::IoScaleHybrid
            | Self::ChainScaling
            | Self::ChainScalingDedicated => {
                vec![String::from("store_request")]
            }
            Self::MiddlewareApp | Self::PythonApp | Self::MiddlewareAppHybrid => {
                vec![String::from("stdio"), String::from("requests")]
            }
        }
    }

    pub fn url(&self, ip: &str, is_hot: bool) -> String {
        format!(
            "http://{}:{}/{}/{}",
            ip,
            DANDELION_PORT,
            if is_hot { "hot" } else { "cold" },
            match self {
                Self::Matmul => "matmul",
                Self::MatmulStorage => "matmulstore",
                Self::IoScale => "io",
                Self::IoScaleHybrid => "io",
                Self::ChainScaling => "chain_scaling",
                Self::ChainScalingDedicated => "chain_scaling_dedicated",
                Self::PythonApp => "python_app",
                Self::MiddlewareApp => "middleware_app",
                Self::MiddlewareAppHybrid => "middleware_app_hybrid",
                Self::CompressionApp => "compression_app",
            }
        )
    }

    pub fn body(
        &self,
        input_size: u64,
        iterations: u64,
        layers: u64,
        function_name: String,
        storage_ip: &Option<String>,
        matrix: &[u8],
    ) -> Vec<u8> {
        match self {
            Self::Matmul | Self::CompressionApp => {
                let request = Request {
                    name: function_name,
                    sets: vec![InputSet {
                        identifier: String::from(""),
                        items: vec![InputItem {
                            identifier: String::from(""),
                            key: 0,
                            data: matrix,
                        }],
                    }],
                };
                bson::to_vec(&request).unwrap()
            }
            Self::MatmulStorage
            | Self::IoScale
            | Self::IoScaleHybrid
            | Self::ChainScaling
            | Self::ChainScalingDedicated => {
                let get_request = match self {
                    Self::MatmulStorage => format!(
                        "GET http://{}:{}/matrix/{} HTTP/1.1",
                        storage_ip
                            .as_ref()
                            .expect("Need to specify storage IP for compute request"),
                        8000,
                        input_size,
                    ),
                    Self::IoScale
                    | Self::IoScaleHybrid
                    | Self::ChainScaling
                    | Self::ChainScalingDedicated => format!(
                        "GET http://{}:{}/io/{}/{} HTTP/1.1",
                        storage_ip
                            .as_ref()
                            .expect("Need to specify storage IP for compute request"),
                        8000,
                        iterations,
                        input_size,
                    ),
                    _ => panic!("Unexpected request type: {}", self),
                };
                let post_request = match self {
                    Self::ChainScaling | Self::ChainScalingDedicated => format!(
                        "POST http://{}:{}/io/{}/{} HTTP/1.1\n\n",
                        storage_ip.as_ref().unwrap(),
                        8000,
                        iterations,
                        input_size,
                    ),
                    Self::MatmulStorage | Self::IoScale | Self::IoScaleHybrid => format!(
                        "POST http://{}:{}/post HTTP/1.1\n\n",
                        storage_ip.as_ref().unwrap(),
                        8000
                    ),
                    _ => panic!("Unexpected request type: {}", self),
                };
                let layer_bytes = layers.to_le_bytes();
                let sets = if let Self::ChainScalingDedicated = self {
                    vec![
                        InputSet {
                            identifier: String::from("get_request"),
                            items: vec![InputItem {
                                identifier: String::from("get_request"),
                                key: 0,
                                data: get_request.as_bytes(),
                            }],
                        },
                        InputSet {
                            identifier: String::from("post_request"),
                            items: vec![InputItem {
                                identifier: String::from("post_request"),
                                key: 0,
                                data: post_request.as_bytes(),
                            }],
                        },
                        InputSet {
                            identifier: String::from("layers"),
                            items: vec![InputItem {
                                identifier: String::from("layers"),
                                key: 0,
                                data: &layer_bytes,
                            }],
                        },
                    ]
                } else {
                    vec![
                        InputSet {
                            identifier: String::from("get_request"),
                            items: vec![InputItem {
                                identifier: String::from("get_request"),
                                key: 0,
                                data: get_request.as_bytes(),
                            }],
                        },
                        InputSet {
                            identifier: String::from("post_request"),
                            items: vec![InputItem {
                                identifier: String::from("post_request"),
                                key: 0,
                                data: post_request.as_bytes(),
                            }],
                        },
                    ]
                };

                let request = Request {
                    name: function_name,
                    sets,
                };

                bson::to_vec(&request).unwrap()
            }
            Self::MiddlewareApp | Self::MiddlewareAppHybrid | Self::PythonApp => {
                let request = Request {
                    name: function_name,
                    sets: vec![InputSet {
                        identifier: String::from("inputs"),
                        items: vec![InputItem {
                            identifier: String::from("Authorization"),
                            key: 0,
                            data: "Bearer fapw84ypf3984viuhsvpoi843ypoghvejkfld".as_bytes(),
                        }],
                    }],
                };
                bson::to_vec(&request).unwrap()
            }
        }
    }

    pub fn check_body(&self, body: bytes::Bytes, expected: (u64, usize)) {
        let (expected_checksum, expected_size) = expected;
        let response: Response = bson::from_slice(&body).unwrap();
        let (checksum, response_size) = match self {
            Self::Matmul => {
                let mut buf = [0u8; 8];
                let data = response.sets[0].items[0].data;
                buf.copy_from_slice(&data[data.len() - 8..]);
                (u64::from_le_bytes(buf), data.len())
            }
            Self::MatmulStorage => {
                let data = response.sets[0].items[0].data;
                let mut buf = vec![0u8; 3];
                buf.copy_from_slice(&data[9..12]);
                let status = String::from_utf8(buf).unwrap();
                (status.parse::<u64>().unwrap(), data.len())
            }
            Self::IoScale => {
                let mut buf = [0u8; 8];
                let data = response.sets[0].items[0].data;
                let offset = data
                    .windows(2)
                    .position(|window| window == b"\n\n")
                    .unwrap();
                buf.copy_from_slice(&data[offset + 2..offset + 10]);
                let sum = i64::from_le_bytes(buf);
                buf.copy_from_slice(&data[offset + 10..offset + 18]);
                let min = i64::from_le_bytes(buf);
                assert_eq!(-120, min);
                buf.copy_from_slice(&data[offset + 18..offset + 26]);
                let max = i64::from_le_bytes(buf);
                assert_eq!(113, max);
                (sum as u64, data[offset + 10..].len())
            }
            Self::IoScaleHybrid => {
                let mut buf = [0u8; 8];
                let data = response.sets[0].items[0].data;
                let offset = data
                    .windows(4)
                    .position(|window| window == b"\r\n\r\n")
                    .unwrap();
                buf.copy_from_slice(&data[offset + 4..offset + 12]);
                let sum = i64::from_le_bytes(buf);
                buf.copy_from_slice(&data[offset + 12..offset + 20]);
                let min = i64::from_le_bytes(buf);
                assert_eq!(-120, min);
                buf.copy_from_slice(&data[offset + 20..offset + 28]);
                let max = i64::from_le_bytes(buf);
                assert_eq!(113, max);
                (sum as u64, data[offset + 12..].len())
            }
            Self::ChainScaling | Self::ChainScalingDedicated | Self::CompressionApp => {
                let mut buf = [0u8; 8];
                let data = response.sets[0].items[0].data;
                buf.copy_from_slice(&data[0..8]);
                (u64::from_le_bytes(buf), data.len())
            }
            Self::MiddlewareApp | Self::PythonApp | Self::MiddlewareAppHybrid => {
                for set in &response.sets {
                    for item in &set.items {
                        debug!(
                            "set name: {} item name: {}, data: {}",
                            &set.identifier,
                            &item.identifier,
                            std::str::from_utf8(item.data).unwrap()
                        );
                    }
                }
                // check they send back the correct number of lines
                let lines = &response
                    .sets
                    .iter()
                    .find(|set| set.identifier == "requests")
                    .and_then(|set| {
                        if set.items.len() != 1 {
                            return None;
                        }
                        Some(
                            u64::try_from(
                                std::str::from_utf8(set.items[0].data)
                                    .unwrap()
                                    .lines()
                                    .count(),
                            )
                            .unwrap(),
                        )
                    })
                    .unwrap_or(0);
                (*lines, 0)
            }
        };
        debug!("Checkusm: {}", checksum);
        assert_eq!(checksum, expected_checksum);
        assert_eq!(response_size, expected_size);
    }

    pub fn checksum(&self, input_size: u64, iterations: u64) -> (u64, usize) {
        match self {
            Self::Matmul => {
                let in_mat: Vec<_> = (1..input_size * input_size + 1).collect();
                let input_size = input_size as usize;
                let mut out_mat = vec![0u64; input_size * input_size];
                for i in 0..input_size {
                    for j in 0..input_size {
                        for k in 0..input_size {
                            out_mat[i * input_size + j] +=
                                in_mat[i * input_size + k] * in_mat[j * input_size + k]
                        }
                    }
                }
                (out_mat[out_mat.len() - 1], (out_mat.len() + 1) * 8)
            }
            Self::MatmulStorage => (200, 15),
            Self::IoScale | Self::IoScaleHybrid => {
                let io_values: [i8; 16] = [
                    -53, 32, 60, -29, 113, 109, -113, 89, -112, 0, -114, -120, 84, -50, 94, 98,
                ];
                let mut sum = 0i64;
                for item in io_values {
                    sum += item as i64;
                }
                (iterations * (sum as u64), 16)
            }
            Self::ChainScaling | Self::ChainScalingDedicated => {
                // subtract size of iterator, add 15 for rounding up
                let mut number_of_chunks = ((input_size as usize) - 8 + 15) / 16;
                if number_of_chunks == 0 {
                    number_of_chunks = 1;
                }
                let expected_size = 8 + number_of_chunks * 16;
                (iterations, expected_size)
            }
            Self::MiddlewareApp | Self::PythonApp | Self::MiddlewareAppHybrid => {
                let preamble = 14;
                let server_logs = 10 * 20 * 6;
                let trailer = 2;
                (preamble + server_logs + trailer, 0)
            }
            Self::CompressionApp => (727905341920923785, 17287),
        }
    }
}
