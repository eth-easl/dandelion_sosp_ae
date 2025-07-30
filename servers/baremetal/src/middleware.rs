use crate::*;

lazy_static! {
    pub static ref AUTH_SERVER: String = {
        std::env::var("STORAGE_HOST")
            .expect("Storage host must be provided with environment variable STORAGE_HOST")
    };
}

const LOG_SERVER_COUNT: usize = 10;

const LOGS_TEMPLATE_HEAD: &str =
r#"<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Logs</title>
</head>
<body>
    <table>
        <tr>
            <th>Timestamp</th>
            <th>Server ID</th>
            <th>Event Type</th>
            <th>Details</th>
        </tr>"#;

const LOGS_TEMPLATE_TAIL: &str =
r#"
    </table>
</body>"#;

// run, then make http requests as follows:
// curl --header "Authorization: Bearer fapw84ypf3984viuhsvpoi843ypoghvejkfld" --request GET localhost:8080/middleware
pub async fn handle(
    req: Request<Incoming>,
    client: reqwest::Client,
) -> Result<Response<Full<Bytes>>, Infallible> {
    #[derive(Debug, Deserialize)]
    struct MiddlewareAuthResponse {
        authorized: String,
        token: String,
    }

    #[derive(Debug, Deserialize)]
    struct MiddlewareLogsEvent {
        details: String,
        event_type: String,
        server_id: String,
        timestamp: String,
    }

    fn render_page(events: &[MiddlewareLogsEvent]) -> String {
        let mut page = LOGS_TEMPLATE_HEAD.to_string();
        for event in events {
            page.push_str(&format!(
            r#"
        <tr>
            <th>{}</th>
            <th>{}</th>
            <th>{}</th>
            <th>{}</th>
        <\tr>"#, 
                event.timestamp, event.server_id, event.event_type, event.details
            ));
        }
        page.push_str(LOGS_TEMPLATE_TAIL);
        return page;
    }

    let request_buf = req
        .collect()
        .await
        .expect("Could not read request body")
        .to_bytes();
    let LoaderRequest {
        name: _,
        sets, // get_uri,
              // post_uri,
    } = bson::from_slice(&request_buf).expect("Should be able to deserialize compute request");

    let auth_token = {
        assert!(sets[0].items[0].identifier == "Authorization");
        let auth_header =
            std::str::from_utf8(sets[0].items[0].data).expect("invalid Authorization token");
        let mut auth_header = auth_header.split(" ");
        assert!(auth_header.next().unwrap() == "Bearer");
        let auth_token = auth_header.next().unwrap().to_string();
        auth_token
    };
    let auth_req_body = serde_json::json!({
        "token": auth_token,
    });
    let body = serde_json::to_string(&auth_req_body).unwrap();
    let url_string = format!("http://{}/authorize", *AUTH_SERVER);
    let auth_resp_bytes = client
        .post(url_string)
        .body(body)
        .header("Content-Type", "application/json")
        .send()
        .await
        .unwrap()
        .bytes()
        .await
        .unwrap();
    let auth_resp: MiddlewareAuthResponse =
        serde_json::from_slice(&auth_resp_bytes).expect("invalid auth response");

    let log_servers = (0..LOG_SERVER_COUNT)
        .map(|e| format!("http://{}/logs/{}", *AUTH_SERVER, e))
        .collect::<Vec<_>>();
    let _ = &auth_resp.authorized;
    let auth_header_value = format!("Bearer {}", auth_resp.token);
    let log_requests: Vec<_> = log_servers
        .into_iter()
        .map(|log_server| {
            let client = &client;
            let auth_header_value = &auth_header_value;
            async move {
                client
                    .get(log_server)
                    .header("Authorization", auth_header_value)
                    .send()
                    .await
                    .unwrap()
                    .bytes()
                    .await
                    .unwrap()
            }
        })
        .collect::<Vec<_>>();
    let mut logs = futures::future::join_all(log_requests)
        .await
        .into_iter()
        .flat_map(|bytes| {
            let log_json: serde_json::Value =
                serde_json::from_slice(&bytes).expect("invalid log response");
            let events = log_json.get("events").expect("invalid log response");
            let events = events.as_array().expect("invalid log response");
            events
                .into_iter()
                .map(|event| {
                    let event: MiddlewareLogsEvent =
                        serde_json::from_value(event.clone()).expect("invalid log response");
                    event
                })
                .collect::<Vec<MiddlewareLogsEvent>>()
        })
        .collect::<Vec<MiddlewareLogsEvent>>();
    logs.sort_by(|a, b| a.timestamp.cmp(&b.timestamp));

    let rendered = render_page(&logs);

    let response_struct = LoaderResponse {
        sets: vec![DataSet {
            identifier: String::from("requests"),
            items: vec![DataItem {
                identifier: String::from("body"),
                key: 0,
                data: &rendered.as_bytes(),
            }],
        }],
    };

    let response = Response::builder()
        .status(StatusCode::OK.as_u16())
        .body(bson::to_vec(&response_struct).unwrap().into())
        .unwrap();
    Ok::<_, Infallible>(response)
}
