use crate::types::{Cart, CartProduct, Product, UIResponder};
use crate::utils::{query_ddb, reconstruct_result};
use aws_sdk_dynamodb as ddb;
use aws_sdk_dynamodb::operation::put_item::PutItemOutput;
use opentelemetry::global;
use rocket::serde::json::Json;
use rocket::{error, get, post, State};
use serde_dynamo::to_item;
use uuid::Uuid;

#[instrument]
#[post("/cart/create_cart", format = "json", data = "<cart_id>")]
pub async fn create_cart(
    cart_id: Json<&str>,
    db: &State<ddb::Client>,
    table_name: &State<String>,
) -> UIResponder<Cart> {
    let cart_id = cart_id.into_inner().to_string();
    let new_cart = Cart {
        partition_key: "CART".to_string(),
        sort_key: cart_id.clone(),
        id: cart_id,
        products: vec![],
        total_quantity: 0,
        cost: "0".to_string(),
        checkout_url: "".to_string(),
    };

    let item = to_item(new_cart.clone()).expect("Failed to turn cart into item");

    let results = db
        .put_item()
        .table_name(table_name.to_string())
        .set_item(Some(item))
        .send()
        .await;

    match results {
        Ok(res) => UIResponder::Ok(Json::from(new_cart)),
        Err(e) => UIResponder::Err(error!("Failed to create a new cart")),
    }
}

#[instrument]
#[get("/cart/get_cart/<cart_id>")]
pub async fn get_cart(
    cart_id: &str,
    db: &State<ddb::Client>,
    table_name: &State<String>,
) -> UIResponder<Cart> {
    let results = query_ddb(table_name.to_string(), db, "CART", Some(cart_id));

    match results.await {
        Ok(res) => match reconstruct_result::<Cart>(res) {
            Ok(cart) => UIResponder::Ok(Json::from(cart)),
            Err(err) => UIResponder::Err(error!("Failed to transform cart: {}", err)),
        },
        Err(err) => UIResponder::Err(error!("Failed to get retrieve cart: {}", err)),
    }
}

#[instrument]
#[post(
    "/cart/add_to_cart/<cart_id>",
    format = "json",
    data = "<product_to_add>"
)]
pub async fn add_to_cart(
    cart_id: &str,
    product_to_add: Json<CartProduct>,
    db: &State<ddb::Client>,
    table_name: &State<String>,
) -> UIResponder<Cart> {
    let results = query_ddb(table_name.to_string(), db, "CART", Some(cart_id));

    match results.await {
        Ok(res) => match reconstruct_result::<Cart>(res) {
            Ok(mut cart) => {
                cart.products.push(product_to_add.0.clone());
                cart.total_quantity += 1;
                let item = to_item(cart.clone()).expect("Failed to turn cart into item");

                let results = db
                    .put_item()
                    .table_name(table_name.to_string())
                    .set_item(Some(item))
                    .send()
                    .await;

                match results {
                    Ok(res) => UIResponder::Ok(Json::from(cart)),
                    Err(e) => UIResponder::Err(error!("Failed to add to cart")),
                }
            }
            Err(err) => UIResponder::Err(error!("Failed to transform cart: {}", err)),
        },
        Err(err) => UIResponder::Err(error!("Failed to put in fetch from cart: {}", err)),
    }
}

#[instrument]
#[post(
    "/cart/remove_from_cart/<cart_id>",
    format = "json",
    data = "<delete_from_cart>"
)]
pub async fn remove_from_cart(
    cart_id: &str,
    delete_from_cart: String,
    db: &State<ddb::Client>,
    table_name: &State<String>,
) -> UIResponder<Cart> {
    let results = query_ddb(table_name.to_string(), db, "CART", Some(cart_id));

    match results.await {
        Ok(res) => match reconstruct_result::<Cart>(res) {
            Ok(mut cart) => {
                cart.products = cart
                    .products
                    .into_iter()
                    .filter(|p| p.product.id != delete_from_cart)
                    .collect();

                let item = to_item(cart.clone()).expect("Failed to turn cart into item");

                let results = db
                    .put_item()
                    .table_name(table_name.to_string())
                    .set_item(Some(item))
                    .send()
                    .await;

                match results {
                    Ok(res) => UIResponder::Ok(Json::from(cart)),
                    Err(e) => UIResponder::Err(error!("Failed to remove from cart")),
                }
            }
            Err(err) => UIResponder::Err(error!("Failed to transform cart: {}", err)),
        },
        Err(err) => UIResponder::Err(error!("Failed to put in fetch from cart: {}", err)),
    }
}

#[instrument]
#[post("/cart/update_cart/<cart_id>", format = "json", data = "<cart_update>")]
pub async fn update_cart(
    cart_id: &str,
    cart_update: Json<CartProduct>,
    db: &State<ddb::Client>,
    table_name: &State<String>,
) -> UIResponder<Cart> {
    let results = query_ddb(table_name.to_string(), db, "CART", Some(cart_id));

    match results.await {
        Ok(res) => match reconstruct_result::<Cart>(res) {
            Ok(mut cart) => {
                let product_index = cart
                    .products
                    .iter()
                    .position(|p| p.product.id == cart_update.product.id);

                if let Some(index) = product_index {
                    cart.products[index].quantity = cart_update.quantity;
                }

                let item = to_item(cart.clone()).expect("Failed to turn cart into item");

                let results = db
                    .put_item()
                    .table_name(table_name.to_string())
                    .set_item(Some(item))
                    .send()
                    .await;

                match results {
                    Ok(res) => UIResponder::Ok(Json::from(cart)),
                    Err(e) => UIResponder::Err(error!("Failed to update cart")),
                }
            }
            Err(err) => UIResponder::Err(error!("Failed to transform cart: {}", err)),
        },
        Err(err) => UIResponder::Err(error!("Failed to put in fetch from cart: {}", err)),
    }
}