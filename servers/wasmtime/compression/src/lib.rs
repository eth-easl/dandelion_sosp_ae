use spin_sdk::http::{IntoResponse, Request, Response};
use spin_sdk::http_component;
use serde::{Deserialize, Serialize};


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

#[link(name = "compress")]
extern "C" {
    fn compress(
       in_qoi: *const u8,
       qoi_size: i32,
       out_png: *mut *const u8, 
    ) -> i32;
}

/// A simple Spin HTTP component.
#[http_component]
fn handle_compression(req: Request) -> anyhow::Result<impl IntoResponse> {
    
    let request_buf = req.body().to_vec().into_boxed_slice();

    let LoaderRequest { name: _, sets } =
        bson::from_slice(&request_buf).expect("Should be able to deserialize compression request");

    let qoi_picture = sets[0].items[0].data;

    let qoi_size = i32::try_from(qoi_picture.len()).unwrap();
    let mut png_pointer: *const u8 = std::ptr::null_mut();
    let png_size = unsafe {compress(qoi_picture.as_ptr(), qoi_size, &mut png_pointer)};
    assert!(png_size > 0);
    assert!(!png_pointer.is_null());
    let usize_png_size = usize::try_from(png_size).unwrap();
    let png_picture = unsafe {std::slice::from_raw_parts(png_pointer, usize_png_size)};
    
    let response_struct = LoaderResponse {
        sets: vec![DataSet {
            identifier: String::from("store_body"),
            items: vec![DataItem {
                identifier: String::from("body"),
                key: 0,
                data: png_picture,
            }],
        }],
    };

    let response = Response::builder()
        .status(200)
        .body(bson::to_vec(&response_struct).unwrap())
        .build();
    
    return Ok(response);
}
