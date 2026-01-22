use crate::types::{Category, Menu, Page, Product, UIResponder};
use crate::utils::{query_ddb, reconstruct_result, reconstruct_results};
use aws_sdk_dynamodb as ddb;
use tracing::{info, instrument};
use rocket::serde::json::Json;
use rocket::{error, get, State};
use tokio::time::{sleep, Duration};


#[get("/menu/<menu_id>")]
pub async fn get_menu(menu_id: &str) -> UIResponder<Vec<Menu>> {
    match menu_id {
        "navbar" => UIResponder::Ok(
            vec![
                Menu {
                    title: "AWS Store".to_string(),
                    path: "/".to_string(),
                },
                Menu {
                    title: "All".to_string(),
                    path: "/search".to_string(),
                },
                Menu {
                    title: "Clothing".to_string(),
                    path: "/search/clothing".to_string(),
                },
                Menu {
                    title: "Other".to_string(),
                    path: "/search/other".to_string(),
                },
            ]
            .into(),
        ),
        "footer" => UIResponder::Ok(
            vec![
                Menu {
                    title: "Home".to_string(),
                    path: "/".to_string(),
                },
                Menu {
                    title: "About".to_string(),
                    path: "/about".to_string(),
                },
                Menu {
                    title: "Terms & Conditions".to_string(),
                    path: "/terms-conditions".to_string(),
                },
                Menu {
                    title: "Privacy Policy".to_string(),
                    path: "/privacy-policy".to_string(),
                },
                Menu {
                    title: "FAQ".to_string(),
                    path: "/faq".to_string(),
                },
            ]
            .into(),
        ),
        _ => UIResponder::Err(error!("Menu not found")),
    }
}

#[get("/page/<_page_handle>")]
pub async fn get_page(_page_handle: String) -> UIResponder<Page> {
    UIResponder::Ok(Page::default().into())
}


#[get("/pages")]
pub async fn get_pages() -> UIResponder<Vec<Page>> {
    UIResponder::Ok(vec![Page::default()].into())
}


#[instrument(skip(db))]
#[get("/category/<category_handle>")]
pub async fn get_category(
    category_handle: &str,
    db: &State<ddb::Client>,
    table_name: &State<String>,
) -> UIResponder<Category> {
    let table_name = table_name.inner();
    let results = query_ddb(
        table_name.to_string(),
        db,
        "CATEGORY",
        Some(category_handle),
    );

    return match results.await {
        Ok(res) => match reconstruct_result::<Category>(res) {
            Ok(res) => UIResponder::Ok(Json::from(res)),
            Err(err) => UIResponder::Err(error!("{:?}", err)),
        },
        Err(err) => {
            println!("{:?}", err);
            UIResponder::Err(error!("Something went wrong"))
        }
    };
}


#[instrument(skip(db))]
#[get("/category/<category_handle>/products")]
pub async fn get_category_products(
    category_handle: &str,
    db: &State<ddb::Client>,
    table_name: &State<String>,
) -> UIResponder<Vec<Product>> {
    let table_name = table_name.inner();

    let results = query_ddb(
        table_name.to_string(),
        db,
        "CATEGORY",
        Some(category_handle),
    );
    return match results.await {
        Ok(res) => match reconstruct_result::<Category>(res) {
            Ok(res) => UIResponder::Ok(Json::from(res.products)),
            Err(err) => UIResponder::Err(error!("{:?}", err)),
        },
        Err(err) => {
            println!("{:?}", err);
            UIResponder::Err(error!("Something went wrong"))
        }
    };
}

#[instrument(skip(db))]
#[get("/categories")]
pub async fn get_categories(
    db: &State<ddb::Client>,
    table_name: &State<String>,
) -> UIResponder<Vec<Category>> {
    let table_name = table_name.inner();

    let results = query_ddb(table_name.to_string(), db, "CATEGORY", None);

    return match results.await {
        Ok(res) => match reconstruct_results::<Category>(res) {
            Ok(res) => {
                let categories = res
                    .into_iter()
                    .filter(|category: &Category| category.visible)
                    .collect::<Vec<Category>>();
                UIResponder::Ok(Json::from(categories))
            },
            Err(err) => UIResponder::Err(error!("{:?}", err)),
        },
        Err(err) => {
            println!("{:?}", err);
            UIResponder::Err(error!("Something went wrong"))
        }
    };
}

#[instrument(skip(db))]
#[get("/collection/<collection_handle>")]
pub async fn get_collection(
    collection_handle: &str,
    db: &State<ddb::Client>,
    table_name: &State<String>,
) -> UIResponder<Vec<Product>> {
    // Uncomment to demo metrics-driven rollback
    // sleep(Duration::from_secs(3)).await;
    
    let results = query_ddb(
        table_name.to_string(),
        db,
        "CATEGORY",
        Some(collection_handle),
    );

    return match results.await {
        Ok(res) => match reconstruct_result::<Category>(res) {
            Ok(res) => {
                let products = res.products;
                UIResponder::Ok(Json::from(products))
            }
            Err(err) => UIResponder::Err(error!("{:?}", err)),
        },
        Err(err) => {
            println!("{:?}", err);
            UIResponder::Err(error!("Something went wrong"))
        }
    };
}
