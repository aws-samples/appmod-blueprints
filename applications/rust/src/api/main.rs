#![allow(warnings)]
mod services;
mod types;
mod utils;
mod setup;

#[macro_use]
extern crate tracing;

use aws_config::default_provider::credentials::DefaultCredentialsChain;
use aws_config::default_provider::region::DefaultRegionChain;
use aws_sdk_dynamodb as ddb;
use rocket_prometheus::{PrometheusMetrics};
use rocket::{self, routes};
use services::product::*;
use aws_config::Region;
use services::cart::*;
use services::ui::*;

#[rocket::main]
async fn main() -> Result<(), rocket::Error> {
    let mut config;

    let region = DefaultRegionChain::builder()
        .build()
        .region()
        .await
        .unwrap_or(Region::from_static("us-east-1"));

    let creds = DefaultCredentialsChain::builder()
        .region(region.clone())
        .build()
        .await;

    config = aws_config::from_env()
        .credentials_provider(creds)
        .region(region)
        .load()
        .await;

    let rocket_address = std::env::var("ROCKET_ADDRESS").unwrap_or(String::from("0.0.0.0"));
    let rocket_port = std::env::var("ROCKET_PORT").unwrap_or(String::from("8080"));
    let table_name = std::env::var("TABLE_NAME").unwrap_or(String::from("rust-service-table"));

    let rocket_config = rocket::Config::figment()
        .merge(("address", rocket_address))
        .merge(("port", rocket_port.parse::<u16>().unwrap()))
        .merge(("workers", 4));

    let prometheus = PrometheusMetrics::new();

    // let tracing = init_tracing_subscriber();

    setup::setup(config.clone(), table_name.clone()).await;

    let rocket = rocket::custom(rocket_config)
        .manage(ddb::Client::new(&config))
        .manage(table_name)
        .attach(prometheus.clone())
        .mount(
            "/",
            routes![
                create_cart,
                add_to_cart,
                get_cart,
                remove_from_cart,
                get_product,
                get_products,
                get_menu,
                get_page,
                get_pages,
                get_category,
                get_category_products,
                get_categories,
                get_collection
            ],
        )
        .mount("/metrics", prometheus);

    let _rocket = rocket.launch().await?;

    Ok(())
}
