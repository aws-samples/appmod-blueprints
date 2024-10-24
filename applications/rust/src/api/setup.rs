use crate::types::{Category, Image, Product, ProductOption, ProductVariant};
use aws_config::default_provider::credentials::DefaultCredentialsChain;
use aws_config::{Region, SdkConfig};
use aws_sdk_dynamodb::Client;
use image::GenericImageView;
use rand::seq::SliceRandom;
use rand::{thread_rng, Rng};
use serde::Deserialize;
use serde_dynamo::to_item;
use std::collections::HashMap;
use std::fs::File;
use uuid::Uuid;

#[derive(Deserialize, Debug, Clone)]
struct CSVProduct {
    category: String,
    product: String,
    name: String,
    image_number: u32,
    file: String,
}

#[derive(Deserialize, Debug, Clone)]
struct CSVOptions {
    category: String,
    product: String,
    name: String,
    variant_name: String,
    option_name: String,
}

pub async fn setup(config: SdkConfig, table_name: String) {
    let client = Client::new(&config);

    let scan_output = client
        .scan()
        .table_name(&table_name)
        .send()
        .await
        .expect("Failed to scan table");
    if !scan_output.items().is_empty() {
        println!("Table already has items, skipping setup");
        return;
    }

    // purge_table(&client, &table_name).await;

    let (products, categories) = csv_to_data();

    for product in &products {
        let product_item = match to_item(&product) {
            Ok(item) => item,
            Err(e) => {
                println!("Error converting product to item: {}", e);
                continue;
            }
        };
        match client
            .put_item()
            .table_name(&table_name)
            .set_item(Some(product_item))
            .send()
            .await
        {
            Ok(_) => {}
            Err(e) => {
                println!("Error putting product: {:?}", e);
            }
        };
    }

    for category in categories.values() {
        let category_item = match to_item(&category) {
            Ok(item) => item,
            Err(e) => {
                println!("Error converting category to item: {}", e);
                continue;
            }
        };
        match client
            .put_item()
            .table_name(&table_name)
            .set_item(Some(category_item))
            .send()
            .await
        {
            Ok(_) => {}
            Err(e) => {
                println!("Error putting category: {:?}", e);
            }
        };
    }

    let front_page_products: Vec<Product> = products
        .choose_multiple(&mut thread_rng(), 3)
        .cloned()
        .collect();

    let front_page_category = Category {
        partition_key: "CATEGORY".to_string(),
        sort_key: "FRONT_PAGE".to_string(),
        path: "front-page".to_string(),
        category_id: Uuid::new_v4().to_string(),
        title: "FRONT Page".to_string(),
        description: "Front Page".to_string(),
        products: front_page_products,
    };

    let front_page_cat_item = match to_item(&front_page_category) {
        Ok(item) => item,
        Err(e) => {
            println!("Error converting front page category to item: {}", e);
            return;
        }
    };
    match client
        .put_item()
        .table_name(&table_name)
        .set_item(Some(front_page_cat_item))
        .send()
        .await
    {
        Ok(_) => {}
        Err(e) => {
            println!("Error putting front page category: {:?}", e);
        }
    };
}

fn csv_to_data() -> (Vec<Product>, HashMap<String, Category>) {
    let mut csv_products: Vec<CSVProduct> = Vec::new();
    let mut csv_options: Vec<CSVOptions> = Vec::new();

    let products_file = match File::open("./src/api/res/products.csv") {
        Ok(file) => file,
        Err(e) => panic!("Required file not found: {}", e),
    };

    let variants_file = match File::open("./src/api/res/variants.csv") {
        Ok(file) => file,
        Err(e) => panic!("Required file not found: {}", e),
    };

    let mut product_rdr = csv::Reader::from_reader(products_file);
    for result in product_rdr.deserialize() {
        let record: CSVProduct = match result {
            Ok(record) => record,
            Err(e) => {
                println!("Error: {}", e);
                continue;
            }
        };

        csv_products.push(record.clone());
    }

    let mut variant_rdr = csv::Reader::from_reader(variants_file);
    for result in variant_rdr.deserialize() {
        let record: CSVOptions = match result {
            Ok(record) => record,
            Err(e) => {
                println!("Error: {}", e);
                continue;
            }
        };

        csv_options.push(record.clone());
    }

    let images: HashMap<String, Vec<String>> = extract_images(&csv_products);
    let variants = build_variants(&csv_options);
    let options = build_options(&csv_options);

    // Build the product type
    let mut products: Vec<Product> = Vec::new();
    let mut categories: HashMap<String, Category> = HashMap::new();

    for csv_product in csv_products {
        let pre_existing_product: Vec<_> = products
            .iter()
            .filter(|p| p.name == csv_product.name)
            .collect();
        if !pre_existing_product.is_empty() {
            continue;
        }

        let variants: Option<Vec<ProductVariant>> = match variants.get(&csv_product.name) {
            Some(vec) => Some(vec.to_vec()),
            None => None,
        };
        let options: Option<Vec<ProductOption>> = match options.get(&csv_product.name) {
            Some(vec) => Some(vec.to_vec()),
            None => None,
        };

        // construct Product from CSVProduct
        let product = Product {
            partition_key: "PRODUCT".to_string(),
            sort_key: csv_product.name.clone(),
            id: Uuid::new_v4().to_string(),
            name: csv_product.name.clone(),
            description: csv_product.name.clone(),
            inventory: rand::thread_rng().gen_range(1..=1000),
            options: options,
            variants: variants,
            images: {
                let prod_imgs = match images.get(&csv_product.name) {
                    Some(imgs) => imgs,
                    None => &Vec::default(),
                };
                prod_imgs
                    .iter()
                    .map(|image| {
                        let (width, height) = get_image_dimensions(image);
                        Image {
                            url: format!(
                                "/images/{}",
                                image.to_string()
                            ),
                            alt_text: format!("{} image", csv_product.name),
                            width,
                            height,
                        }
                    })
                    .collect()
            },
            price: rand::thread_rng().gen_range(1..=100).to_string(),
        };

        match categories.get_mut(&csv_product.category) {
            Some(category) => {
                category.products.push(product.clone());
            }
            None => {
                categories.insert(
                    csv_product.category.clone(),
                    Category {
                        partition_key: "CATEGORY".to_string(),
                        sort_key: csv_product.category.clone(),
                        path: format!("/search/{}", csv_product.category.clone()),
                        category_id: Uuid::new_v4().to_string(),
                        title: csv_product.category.clone(),
                        products: vec![product.clone()],
                        description: csv_product.category.clone(),
                    },
                );
            }
        }

        products.push(product);
    }

    (products, categories)
}

fn get_image_dimensions(file_name: &String) -> (usize, usize) {
    let path = format!("./src/api/res/images/{}", file_name);
    let img = match image::open(path) {
        Ok(img) => img,
        Err(e) => panic!("Error opening image: {}", e),
    };

    let (width, height) = img.dimensions();

    (width as usize, height as usize)
}

fn build_options(csv_options: &Vec<CSVOptions>) -> HashMap<String, Vec<ProductOption>> {
    let mut options: HashMap<String, Vec<ProductOption>> = HashMap::new();

    for csv_option in csv_options {
        match options.get_mut(&csv_option.name) {
            Some(opts) => {
                // we've seen the product before
                // find the option
                let option = opts.iter_mut().find(|o| o.id == csv_option.option_name);

                match option {
                    Some(opt) => {
                        // we've seen the option before
                        // find the variant
                        let variant = opt
                            .values
                            .iter()
                            .find(|v| v.to_string() == csv_option.variant_name);
                        match variant {
                            Some(var) => {
                                // we've seen the variant before
                                continue;
                            }
                            None => {
                                // just add variant to option values list
                                opt.values.push(csv_option.variant_name.clone());
                            }
                        }
                    }
                    None => {
                        opts.push(ProductOption {
                            id: csv_option.option_name.clone(),
                            name: csv_option.option_name.clone(),
                            values: vec![csv_option.variant_name.clone()],
                        });
                    }
                }
            }
            None => {
                options.insert(
                    csv_option.name.clone(),
                    vec![ProductOption {
                        id: csv_option.option_name.clone(),
                        name: csv_option.option_name.clone(),
                        values: vec![csv_option.variant_name.clone()],
                    }],
                );
            }
        }
    }

    options
}

fn build_variants(csv_options: &Vec<CSVOptions>) -> HashMap<String, Vec<ProductVariant>> {
    let mut variants: HashMap<String, Vec<ProductVariant>> = HashMap::new();
    for variant in csv_options {
        match variants.get_mut(&variant.name) {
            Some(var) => {
                if !var.iter().any(|v| v.id == variant.variant_name) {
                    var.push(ProductVariant {
                        id: variant.variant_name.clone(),
                        title: variant.variant_name.clone(),
                        price: rand::thread_rng().gen_range(1..=100).to_string(),
                    });
                }
            }
            None => {
                variants.insert(
                    variant.name.clone(),
                    vec![ProductVariant {
                        id: variant.variant_name.clone(),
                        title: variant.variant_name.clone(),
                        price: rand::thread_rng().gen_range(1..=100).to_string(),
                    }],
                );
            }
        }
    }
    variants
}

fn extract_images(products: &Vec<CSVProduct>) -> HashMap<String, Vec<String>> {
    let mut images: HashMap<String, Vec<String>> = HashMap::new();
    for product in products {
        match images.get_mut(&product.name) {
            Some(image) => {
                if !image.contains(&product.file) {
                    image.push(product.file.clone());
                }
            }
            None => {
                images.insert(product.name.clone(), vec![product.file.clone()]);
            }
        }
    }
    images
}
