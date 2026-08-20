# Ecommerce Lambda Function

This is a serverless application built with Rust and AWS Lambda that provides a backend for an e-commerce platform. 
It interacts with an AWS DynamoDB table to handle various operations related to products, categories, collections, 
and carts.

## Architecture 

This architecture defines the current state of the application.

![sls-shopping-cart.svg](./assets/imgs/sls-shopping-cart.svg)

## Services

### Product Service

- `POST /products`: Search endpoint across all products.
- `GET /product/<product_id>`: Retrieves details of a specific product.

### Cart Service

- `POST /cart/create_cart`: Creates a new cart.
- `POST /cart/add_to_cart/<cart_id>`: Adds a product to the cart.
- `GET /cart/get_cart/<cart_id>`: Retrieves the contents of a cart.
- `POST /cart/remove_from_cart/<cart_id>`: Removes a product from the cart.
- `POST /cart/update_cart/<cart_id>`: Updates the quantity of a given product in the carts 

### UI Service

- `GET /menu/<menu_id>`: Retrieves the menu structure (categories and collections).
- `GET /pages`: Retrieves a list of all pages -- **UNUSED**.
- `GET /page/<_page_handle>`: Retrieves details of a specific page -- **UNUSED**.
- `GET /category/<category_handle>`: Retrieves details of the category
- `GET /category/<category_handle>/products`: Retrieves the products in that category
- `GET /categories`: Retrieves a list of all the categories
- `GET /collection/<collection_handle>`: Reserved for special collections for events/front_page

### Product Images

Product images live in `static/images/`, checked into git as WebP (smaller than the PNG originals
for cheaper transmission), and are served directly by this service using Rocket's built-in
`FileServer` -- no external bucket or CDN involved. Add real photos there, named to match the
`file` column in `src/api/res/products.csv` (e.g. `sticker.webp`, `bag-black.webp`), and they'll be
served as-is, both when running locally with `cargo run` and inside the container
(`Dockerfile`/`Dockerfile.arm` copy `static/` into the image). Anything you haven't added yet gets
a small generated placeholder instead at startup, so a missing file never breaks the catalog.

The pod itself only ever knows about the unprefixed route, `/product-images/<file>`. The `url`
value returned in API responses is prefixed with `APP_BASE_PATH` (empty by default, matching direct
access), so that consumers going through this app's ingress get a correctly-routable URL. In this
workshop's deployment, `APP_BASE_PATH` is set to `/rust-app` to match the ingress path in
`deployment/templates/kubevela/application.yaml` and `deployment/templates/kro/application.yaml` --
nginx's `rewrite-target` strips that prefix before the request reaches this service, exactly like
every other route here (see `platform-meta/templates/traits/path-based-ingress.yaml`).

### To Do for Workshop
Wishlist service: Write a wishlist service that maintains wishlists for each individual user with name, Products, and
all other things normal to a wishlist.

We expect it to have the following routes:
- `POST /wishlist/new`: Creates a new wishlist
- `POST /wishlist/<wishlist_id>/add`: Adds a product to the wishlist
- `GET /wishlist/<wishlist_id>`: Retrieves the contents of the wishlist
- `POST /wishlist/<wishlist_id>/remove/<product_id>`: Removes a product from the wishlist

Sample prompt you can use to generate a skeleton for the wishlist service:
```
Implement the following routes:

- POST /wishlist/new: Creates a new wishlist, returns wishlist ID.
- POST /wishlist/<wishlist_id>/add: Adds a product to the specified wishlist.
- GET /wishlist/<wishlist_id>: Retrieves the contents of the specified wishlist.
- POST /wishlist/<wishlist_id>/remove/<product_id>: Removes a product from the wishlist.

Use AWS dynamodb to persist wishlist data (database or in-memory). Design for concurrent requests, scalability, and performance.

Requirements:

- Proper error handling and HTTP status codes.
- Unit tests for correctness.
- Code documentation and Rust best practices.
- Authentication and authorization for accessing/modifying wishlists.
- Consider caching mechanisms for performance.

Generate the Rust code for the wishlist service, including data structures, routes, handlers. 
Explain your implementation and design decisions briefly.
```

## Deployment Guide

The Rust application is setup for automated deployment through ArgoCD. All you need to do is commit your changes through
Git and the build/deploy pipeline will take care of the rest.

Fundamentally, the application is composed through Kubevela templates to abstract infrastructure building blocks away
for the engineering team so they can request something like a: `WebServer` instead of having to request a `Deployment`.

Kubevela also allows you to abstract away Kubernetes and Cloud-Native concepts behind a simple YAML or composition. This
then breaks down your application into the necessary components to be deployed across the platform teams compute provider
and the underlying cloud provider.

How the system deploys behind the scenes is that:
* Kubevela builds downstream templates for your application based on what you want
* The compute and containers is deployed through ArgoCD
* Necessary Cloud components are parsed through Crossplane and deployed
