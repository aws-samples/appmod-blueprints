use std::collections::HashMap;
use crate::types::{Menu, Page, Category, Product, UIResponder};
use rocket::{error, get, post, Responder, State};
use aws_sdk_dynamodb as ddb;
use aws_sdk_dynamodb::types::AttributeValue;
use rand::Rng;
use rocket::serde::json::Json;

#[get("/menu")]
pub async fn get_menu(db: &State<ddb::Client>) -> UIResponder<Vec<Menu>> {
    UIResponder::Ok(vec![Menu::default()].into())
}

#[get("/page/<page_handle>")]
pub async fn get_page(page_handle: String, db: &State<ddb::Client>) -> UIResponder<Page> {
    UIResponder::Ok(Page::default().into())
}

#[get("/pages")]
pub async fn get_pages(db: &State<ddb::Client>) -> UIResponder<Vec<Page>> {
    UIResponder::Ok(vec![Page::default()].into())
}

#[get("/category/<category_handle>")]
pub async fn get_category(
    category_handle: String,
    db: &State<ddb::Client>,
    table_name: &State<String>
) -> UIResponder<Category> {
    let table_name = table_name.inner();
    let results = db
        .query()
        .table_name(table_name)
        .key_condition_expression("partition_key = :pk_val AND begins_with(sort_key, :sk_val)")
        .expression_attribute_values(":pk_val", AttributeValue::S("CATEGORY".to_string()))
        .expression_attribute_values(":sk_val", AttributeValue::S(category_handle.clone()))
        .send()
        .await;

    let results = results.unwrap().items;

    println!("{:?}", results);

    match results {
        Some(items) => {
            // ensure that items only has one item in it
            if items.len() > 1 {
                UIResponder::Err(error!("More than one item found for this category"))
            } else {
                let item = items.get(0).unwrap();
                println!("{:?}", item);

                let category = Category {
                    path: category_handle,
                    category_id: item.get("id").unwrap().as_s().unwrap().to_string(),
                    title: item.get("name").unwrap().as_s().unwrap().to_string(),
                    description : item.get("name").unwrap().as_s().unwrap().to_string(),
                };

                UIResponder::Ok(category.into())
            }

        },
        None => UIResponder::Err(error!("Looks like this category doesn't exist"))
    }
}

#[get("/category/<category_handle>/products")]
pub async fn get_category_products(
    category_handle: String,
    db: &State<ddb::Client>,
    table_name: &State<String>
) -> UIResponder<Vec<Product>> {
    let table_name = table_name.inner();

    let results = db
        .query()
        .table_name(table_name)
        .key_condition_expression("partition_key = :prod")
        .expression_attribute_values(":prod", AttributeValue::S("PRODUCT".to_string()))
        .filter_expression("category = :category_name")
        .expression_attribute_values(":category_name", AttributeValue::S(category_handle.clone()))
        .send()
        .await;

    let results = results.unwrap().items;

    let mut products: Vec<Product> = Vec::new();

    for item in results.unwrap() {
        let product = Product {
            id: item.get("id").unwrap().as_s().unwrap().to_string(),
            name: item.get("name").unwrap().as_s().unwrap().to_string(),
            description: item.get("name").unwrap().as_s().unwrap().to_string(),
            // random number
            inventory: rand::thread_rng().gen_range(0..100),
            options: vec![],
            variants: vec![],
            price: rand::thread_rng().gen_range(0..300).to_string(),
            images: vec![],
        };

        products.push(product.into());
        println!("{:?}", item);
    }

    UIResponder::Ok(products.into())
}

#[get("/categories")]
pub async fn get_categories(db: &State<ddb::Client>) -> UIResponder<Vec<Category>> {
    UIResponder::Ok(vec![Category::default()].into())
}