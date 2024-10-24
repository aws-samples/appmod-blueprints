use crate::types::{Product, UIResponder};
use crate::utils::{reconstruct_result, reconstruct_results, TracingSpan};
use aws_sdk_dynamodb as ddb;
use aws_sdk_dynamodb::types::AttributeValue;
use rocket::serde::json::Json;
use rocket::{error, get, post, State};
use tracing::instrument;

#[instrument(skip(db))]
#[get("/product/<id>")]
pub async fn get_product(
    id: &str,
    db: &State<ddb::Client>,
    table_name: &State<String>,
) -> UIResponder<Product> {
    let results = db
        .query()
        .table_name(table_name.to_string())
        .key_condition_expression("partition_key = :pk_val")
        .expression_attribute_values(":pk_val", AttributeValue::S("PRODUCT".to_string()))
        .filter_expression("id = :id")
        .expression_attribute_values(":id", AttributeValue::S(id.to_string()))
        .send()
        .await;

    match results {
        Ok(res) => match reconstruct_result::<Product>(res) {
            Ok(res) => UIResponder::Ok(Json::from(res)),
            Err(err) => UIResponder::Err(error!("{:?}", err)),
        },
        Err(err) => {
            println!("{:?}", err);
            UIResponder::Err(error!("Something went wrong"))
        }
    }
}

#[instrument(skip(db))]
#[post("/products", format = "json", data = "<search_val>")]
pub async fn get_products(
    search_val: Json<String>,
    db: &State<ddb::Client>,
    table_name: &State<String>,
) -> UIResponder<Vec<Product>> {
    println!("{}", search_val.clone().into_inner());
    let results = db
        .query()
        .table_name(table_name.to_string())
        .key_condition_expression("partition_key = :pk_val")
        .expression_attribute_values(":pk_val", AttributeValue::S("PRODUCT".to_string()))
        .filter_expression("contains(description, :name)")
        .expression_attribute_values(
            ":name",
            AttributeValue::S(search_val.into_inner().to_string()),
        )
        .send()
        .await;

    match results {
        Ok(res) => match reconstruct_results::<Product>(res) {
            Ok(res) => {
                println!("{:?}", res);
                UIResponder::Ok(Json::from(res))
            }
            Err(err) => UIResponder::Err(error!("{:?}", err)),
        },
        Err(err) => {
            println!("{:?}", err);
            UIResponder::Err(error!("Something went wrong"))
        }
    }
}
