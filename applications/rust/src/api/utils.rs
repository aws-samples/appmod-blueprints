use aws_sdk_dynamodb as ddb;
use aws_sdk_dynamodb::operation::query::QueryOutput;
use aws_sdk_dynamodb::types::AttributeValue;
use serde::{Deserialize, Serialize};
use serde_dynamo::{from_item, from_items};
use std::fmt::Debug;
use std::time::Duration;
use futures::SinkExt;
use opentelemetry::{global, KeyValue};
use opentelemetry::trace::{TracerProvider};
use opentelemetry_appender_tracing::layer;
use opentelemetry_otlp::WithExportConfig;
use opentelemetry_sdk::{trace, Resource};
use opentelemetry_sdk::metrics::SdkMeterProvider;
use tracing_opentelemetry::{MetricsLayer, OpenTelemetryLayer};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};
use opentelemetry_sdk::trace::{RandomIdGenerator, Sampler, Tracer};
use rocket::fairing::{Fairing, Info, Kind};
use rocket::{async_trait, Build, Data, Orbit, Request, Response, Rocket};
use tracing::{info_span, Level, Span};

pub fn reconstruct_results<'a, T>(results: QueryOutput) -> Result<Vec<T>, String>
where
    T: Debug + Deserialize<'a> + Serialize + Clone,
{
    match from_items(results.items().to_vec()) {
        Ok(inner_res) => Ok(inner_res),
        Err(err) => {
            println!("Error deserializing data: {:?}", err);
            Err("Error deserializing data".to_string())
        }
    }
}

pub fn reconstruct_result<'a, T>(results: QueryOutput) -> Result<T, String>
where
    T: Debug + Deserialize<'a> + Serialize + Clone,
{
    let items: Vec<T> = match from_items(results.items().to_vec()) {
        Ok(inner_res) => inner_res,
        Err(err) => {
            println!("Error deserializing data: {:?}", err);
            return Err("Error deserializing data".to_string());
        }
    };

    if items.len() > 1 {
        return Err("More than one item returned".to_string());
    } else if items.is_empty() {
        return Err("No items returned".to_string());
    }

    // Return the first (and only) item
    Ok(items[0].clone())
}

#[instrument]
pub async fn query_ddb(
    table_name: String,
    db: &ddb::Client,
    pk: &str,
    sk: Option<&str>,
) -> Result<QueryOutput, String> {
    let res = match sk {
        Some(sk) => {
            db.query()
                .table_name(table_name)
                .key_condition_expression("partition_key = :pk AND sort_key = :sk")
                .expression_attribute_values(":pk", AttributeValue::S(pk.into()))
                .expression_attribute_values(":sk", AttributeValue::S(sk.into()))
                .send()
                .await
        }
        None => {
            db.query()
                .table_name(table_name)
                .key_condition_expression("partition_key = :pk")
                .expression_attribute_values(":pk", AttributeValue::S(pk.into()))
                .send()
                .await
        }
    };

    match res {
        Ok(res) => Ok(res),
        Err(err) => {
            println!("Error querying DDB: {:?}", err);
            Err(format!(
                "Error querying DDB, {}, {}",
                pk,
                sk.unwrap_or("no sk")
            ))
        }
    }
}

pub fn init_tracer() -> Tracer {
    let provider = opentelemetry_otlp::new_pipeline()
        .tracing()
        .with_exporter(
            opentelemetry_otlp::new_exporter()
                .tonic()
                .with_endpoint("http://localhost:4317")
                .with_timeout(Duration::from_secs(3))
        )
        .with_trace_config(
            trace::Config::default()
                .with_sampler(Sampler::AlwaysOn)
                .with_id_generator(RandomIdGenerator::default())
                .with_max_events_per_span(64)
                .with_max_attributes_per_span(16)
                .with_max_events_per_span(16)
                .with_resource(Resource::new(vec![KeyValue::new("service.name", "RustMicroservice")])),
        )
        .install_batch(opentelemetry_sdk::runtime::Tokio)
        .unwrap(); // This will just explode if it's a bad config

    global::set_tracer_provider(provider.clone());
    provider.tracer("rust-webserver-tracer")
}

pub struct OtelGuard {}

// Initialize tracing-subscriber and return OtelGuard for opentelemetry-related termination processing
pub fn init_tracing_subscriber() -> OtelGuard {
    let tracer = init_tracer();

    tracing_subscriber::registry()
        .with(tracing_subscriber::filter::LevelFilter::from_level(
            Level::INFO,
        ))
        .with(tracing_subscriber::fmt::layer())
        .with(OpenTelemetryLayer::new(tracer))
        .init();

    OtelGuard{}
}

impl Drop for OtelGuard {
    fn drop(&mut self) {
        global::shutdown_tracer_provider();
    }
}


#[derive(Clone)]
pub struct TracingSpan<T = Span>(T);

#[derive(Debug)]
pub(crate) struct TracingFairing;

#[async_trait]
impl Fairing for TracingFairing {
    fn info(&self) -> Info {
        Info {
            name: "Tracing Fairing",
            kind: Kind::Request | Kind::Response
        }
    }

    async fn on_request(&self, request: &mut Request<'_>, data: &mut Data<'_>) {
        let span = info_span!(
            "request",
            otel.name=%format!("{} {}", request.method(), request.uri().path()),
            http.method = %request.method(),
            http.uri = %request.uri().path(),
            http.status_code = tracing::field::Empty,
        );

        request.local_cache(|| TracingSpan::<Option<Span>>(Some(span)));
    }

    async fn on_response<'r>(&self, request: &'r Request<'_>, response: &mut Response<'r>) {
        if let Some(span) = request.local_cache(|| TracingSpan::<Option<Span>>(None)).0.to_owned() {
            let current_span = span.entered();
            current_span.record("http.status_code", response.status().code);
        }
    }
}

